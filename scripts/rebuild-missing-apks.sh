#!/usr/bin/env bash
# Compile only missing APKs with the SDK published beside this ImageBuilder.
set -Eeuo pipefail
ROOT="${GITHUB_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
IB="${1:?Expected extracted ImageBuilder directory}"
BUILDER_META="${2:?Expected Builder metadata}"
[[ -d "$IB/packages" && -s "$BUILDER_META" ]] || exit 1

APKS="$ROOT/scripts/immortalwrt_sdk_apks.py"
SDK_CHECK="$ROOT/scripts/immortalwrt_sdk.py"
ADD="$ROOT/config/add.txt"
REMOVE="$ROOT/config/remove.txt"
MISSING_RAW="$(python3 "$APKS" plan --imagebuilder "$IB" --add "$ADD")"
if [[ -z "$MISSING_RAW" ]]; then
  echo "All requested packages already exist in this Builder; SDK is not needed."
  exit 0
fi
mapfile -t MISSING <<< "$MISSING_RAW"
BUILDER_TAG="$(jq -er '.tag' "$BUILDER_META")"
[[ "$BUILDER_TAG" =~ ^imm-builder-[a-z0-9._-]+$ ]] || exit 1
printf 'Missing %s APK(s): %s\n' "${#MISSING[@]}" "${MISSING[*]}"
if [[ -z "${GH_TOKEN:-}" ]]; then
  echo "::error::Missing packages need the matching SDK; GitHub release token is absent." >&2
  exit 1
fi

WORK="${RUNNER_TEMP:-/tmp}/immortal-sdk-extra"
CACHE="${SDK_APK_CACHE_DIR:-$ROOT/.build-cache/sdk-apks}"
mkdir -p "$WORK/assets" "$CACHE"
REPO="${GITHUB_REPOSITORY:-pzcn/openwrt-ppe-nss-ota}"
[[ "$REPO" == "pzcn/openwrt-ppe-nss-ota" ]] || exit 1
download_asset() {
  gh release download "$BUILDER_TAG" -R "$REPO" \
    -D "$WORK/assets" -p "$1" --clobber
}
for file in sdk-metadata.json sdk-feeds.lock.json; do
  download_asset "$file" || {
    echo "::error::Builder $BUILDER_TAG has no matching SDK. Run one full Builder." >&2
    exit 1
  }
done
SDK_META="$WORK/assets/sdk-metadata.json"
LOCK="$WORK/assets/sdk-feeds.lock.json"
SDK_NAME="$(jq -er '.archive' "$SDK_META")"
[[ "$SDK_NAME" =~ ^immortalwrt-sdk-qualcommax-ipq60xx[a-zA-Z0-9._+-]*\.tar\.zst$ ]] || exit 1
SDK_ARCHIVE="$CACHE/$SDK_NAME"
if [[ ! -s "$SDK_ARCHIVE" ]] ||
   [[ "$(sha256sum "$SDK_ARCHIVE" | cut -d' ' -f1)" != "$(jq -er '.archive_sha256' "$SDK_META")" ]]; then
  rm -f "$SDK_ARCHIVE"
  download_asset "$SDK_NAME" || exit 1
  mv "$WORK/assets/$SDK_NAME" "$SDK_ARCHIVE"
fi
python3 "$SDK_CHECK" verify \
  --metadata "$SDK_META" --builder-metadata "$BUILDER_META" \
  --archive "$SDK_ARCHIVE" --feed-lock "$LOCK"

common=(
  --imagebuilder "$IB" --add "$ADD" --remove "$REMOVE"
  --builder-metadata "$BUILDER_META" --sdk-metadata "$SDK_META"
  --sdk-archive "$SDK_ARCHIVE" --feed-lock "$LOCK" --cache "$CACHE"
)
if python3 "$APKS" verify-cache "${common[@]}"; then
  echo "Reusing matching SDK-built APK cache for $BUILDER_TAG"
else
  echo "Compiling only missing APKs against $BUILDER_TAG"
  # The standard fast ImageBuilder path does not install SDK build dependencies.
  # Install them here only if a real package compilation is necessary.
  if [[ -n "${GITHUB_ACTIONS:-}" ]]; then
    sudo apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends       build-essential autoconf automake binutils bison clang cmake file flex gawk       gettext git libelf-dev libncurses-dev libssl-dev libtool ninja-build       patch pkgconf python3 python3-pyelftools python3-ply rsync swig       unzip wget zlib1g-dev zstd
  fi
  mkdir -p "$WORK/sdk" "$WORK/git"
  tar -I zstd -xf "$SDK_ARCHIVE" -C "$WORK/sdk"
  mapfile -t sdks < <(find "$WORK/sdk" -mindepth 1 -maxdepth 1 -type d -name '*sdk*')
  [[ "${#sdks[@]}" -eq 1 ]] || exit 1
  SDK="${sdks[0]}"
  test -f "$SDK/Makefile" && test -f "$SDK/scripts/feeds"
  fetch_locked() {
    local label="$1" url="$2" sha="$3" dest="$WORK/git/$1"
    [[ "$sha" =~ ^[a-f0-9]{40}$ ]] || exit 1
    git init -q "$dest"
    git -C "$dest" remote add origin "$url"
    git -C "$dest" fetch -q --depth=1 origin "$sha"
    git -C "$dest" -c advice.detachedHead=false checkout -q --detach FETCH_HEAD
    [[ "$(git -C "$dest" rev-parse HEAD)" == "$sha" ]] || {
      echo "::error::Locked source does not match the Builder: $label" >&2
      exit 1
    }
  }
  SRC_SHA="$(jq -er '.immortalwrt_commit' "$LOCK")"
  fetch_locked base https://github.com/immortalwrt/immortalwrt.git "$SRC_SHA"
  for feed in packages luci routing telephony nss ppe_qos_luci; do
    case "$feed" in
      packages) url=https://github.com/immortalwrt/packages.git ;;
      luci) url=https://github.com/immortalwrt/luci.git ;;
      routing) url=https://github.com/openwrt/routing.git ;;
      telephony) url=https://github.com/openwrt/telephony.git ;;
      nss) url=https://github.com/JuliusBairaktaris/nss-packages.git ;;
      ppe_qos_luci) url=https://github.com/JuliusBairaktaris/luci.git ;;
    esac
    sha="$(jq -er --arg k "$feed" '.feeds[$k]' "$LOCK")"
    fetch_locked "$feed" "$url" "$sha"
  done
  # Mirror the full Builder's known unrelated circular-Kconfig exclusions.
  rm -rf "$WORK/git/packages/net/fwknop" \
         "$WORK/git/packages/sound/squeezelite" \
         "$WORK/git/luci/applications/luci-app-fwknopd"
  {
    echo "src-link --root=package base $WORK/git/base"
    for feed in packages luci routing telephony nss ppe_qos_luci; do
      echo "src-link $feed $WORK/git/$feed"
    done
  } > "$SDK/feeds.conf"
  (
    cd "$SDK"
    ./scripts/feeds update -a
    ./scripts/feeds install -a
    for pkg in "${MISSING[@]}"; do
      printf 'CONFIG_PACKAGE_%s=y\n' "$pkg" >> .config
    done
    make defconfig
    for pkg in "${MISSING[@]}"; do
      if ! grep -Fxq "CONFIG_PACKAGE_${pkg}=y" .config; then
        echo "::error::SDK cannot select $pkg at locked feed revisions" >&2
        exit 1
      fi
    done
    # The SDK makefile compiles packages and dependencies, not the kernel.
    make -j"$(nproc)" package/compile V=s
  )
  python3 "$APKS" collect "${common[@]}" --sdk-bin "$SDK/bin"
fi
python3 "$APKS" install "${common[@]}"
echo "Installed verified SDK-built packages into the matching ImageBuilder."
