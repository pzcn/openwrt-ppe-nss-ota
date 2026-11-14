#!/usr/bin/env bash
# Hybrid Builder: compile only the PPE/NSS kernel, its kmods, base-files and
# the custom packages; take every other APK from the official ImmortalWrt
# snapshot; then package a standalone ImageBuilder + matching SDK.
#
#   kernel tree   ImmortalWrt master + PPE/NSS port (same as the full Builder)
#   feeds         pinned to the commits of the official arch package repos
#   toolchain     official snapshot toolchain (same libc/libgcc as userland)
#   userland      official APKs, signed index + SHA256 verified, mirrored
#                 into the ImageBuilder so it never depends on a moving URL
#
# Inputs (environment):
#   SNAPSHOT_LOCK        output of resolve-immortalwrt-snapshot.py (required)
#   EXPECTED_*_SHA       optional pins from the resolve job
set -Eeuo pipefail
trap 'echo "::error::Hybrid Builder failed at line $LINENO: $BASH_COMMAND" >&2' ERR

ROOT="${GITHUB_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
WORK="${RUNNER_TEMP:-/tmp}/immortal-hybrid"
OUT="${HYBRID_OUT_DIR:-$ROOT/out-hybrid}"
IMM="$WORK/immortalwrt"
PPE="$WORK/ppe-nss"
BUILDER="$WORK/ppe-builder"
PPE_LUCI="$WORK/ppe-luci"
LOCK="$(realpath "${SNAPSHOT_LOCK:?Set SNAPSHOT_LOCK to snapshot-lock.json}")"
CACHE_ROOT="${IMMORTAL_CACHE_ROOT:-$ROOT/.build-cache}"
CACHE_DL="$CACHE_ROOT/dl"
CACHE_CCACHE="$CACHE_ROOT/ccache"
HB=(python3 "$ROOT/scripts/hybrid_builder.py")
JOBS="$(nproc)"
mkdir -p "$WORK" "$OUT" "$CACHE_DL" "$CACHE_CCACHE"
: > "$OUT/timings.tsv"

jq -e '.schema == 2 and .target == "qualcommax/ipq60xx" and
       .architecture == "aarch64_cortex-a53"' "$LOCK" >/dev/null || {
  echo "::error::Not an ipq60xx snapshot lock: $LOCK" >&2; exit 1;
}
TARGET_URL="$(jq -er '.target_url' "$LOCK")"
ARCH_URL="$(jq -er '.architecture_url' "$LOCK")"
[[ "$TARGET_URL" == https://downloads.immortalwrt.org/snapshots/targets/qualcommax/ipq60xx &&
   "$ARCH_URL" == https://downloads.immortalwrt.org/snapshots/packages/aarch64_cortex-a53 ]] || {
  echo "::error::Unexpected snapshot URLs in lock" >&2; exit 1;
}

# Run one buildroot phase, record its duration, and on failure re-run only
# that phase serially and verbosely so the first real error is visible.
phase() {
  local name="$1"; shift
  local begin; begin="$(date +%s)"
  echo "::group::$name"
  if ! (cd "$IMM" && make -j"$JOBS" "$@"); then
    echo "::endgroup::"
    echo "::error::Phase '$name' failed; re-running serially with V=s" >&2
    (cd "$IMM" && make -j1 V=s "$@") 2>&1 | tail -n 200 || true
    exit 1
  fi
  echo "::endgroup::"
  printf '%s\t%s\n' "$name" "$(( $(date +%s) - begin ))" >> "$OUT/timings.tsv"
}
# `! cmd` never trips `set -e`; fail explicitly when a forbidden match exists.
refuse() {
  local why="$1"; shift
  if "$@"; then echo "::error::$why" >&2; exit 1; fi
}
mark() { printf '%s\t%s\n' "$1" "$(( $(date +%s) - $2 ))" >> "$OUT/timings.tsv"; }

# Clone a branch, or exactly the commit the resolve job saw.
checkout() {
  local url="$1" branch="$2" sha="$3" dest="$4"
  if [[ -n "$sha" ]]; then
    [[ "$sha" =~ ^[0-9a-f]{40}$ ]] || { echo "::error::Bad pin for $url" >&2; exit 1; }
    git init -q "$dest"
    git -C "$dest" remote add origin "$url"
    git -C "$dest" fetch -q --depth 1 origin "$sha"
    git -C "$dest" -c advice.detachedHead=false checkout -q --detach FETCH_HEAD
  else
    git clone -q --depth 1 --single-branch --branch "$branch" "$url" "$dest"
  fi
  git -C "$dest" rev-parse HEAD
}
head_of() {
  local sha
  sha="$(git ls-remote "$1" "refs/heads/$2" | awk '{print $1}')"
  [[ "$sha" =~ ^[0-9a-f]{40}$ ]] || { echo "::error::Cannot resolve $1 $2" >&2; exit 1; }
  printf '%s\n' "$sha"
}
fetch_verified() {  # url dest sha256
  curl -fsSL --retry 3 --connect-timeout 20 --max-time 300 "$1" -o "$2"
  printf '%s  %s\n' "$3" "$2" | sha256sum -c --status || {
    echo "::error::SHA256 mismatch for $1 (snapshot rotated? retry later)" >&2; exit 1;
  }
}

T0="$(date +%s)"
# ---------------------------------------------------------------------------
# 1. Sources
# ---------------------------------------------------------------------------
IMM_SHA="$(checkout https://github.com/immortalwrt/immortalwrt.git master "${EXPECTED_IMM_SHA:-}" "$IMM")"
PPE_SHA="$(checkout https://github.com/JuliusBairaktaris/openwrt-ppe-nss.git ppe-nss "${EXPECTED_PPE_SHA:-}" "$PPE")"
BASE_SHA="$(checkout https://github.com/JuliusBairaktaris/Qualcommax_NSS_Builder.git main "${EXPECTED_BASE_SHA:-}" "$BUILDER")"
PPE_LUCI_SHA="${EXPECTED_PPE_LUCI_SHA:-$(head_of https://github.com/JuliusBairaktaris/luci.git luci-app-ppe-qos)}"
NSS_SHA="${EXPECTED_NSS_SHA:-$(head_of https://github.com/JuliusBairaktaris/nss-packages.git ppe-nss)}"
SNAPSHOT="$(jq -er '.snapshot_version' "$LOCK")"
printf 'ImmortalWrt=%s\nPPE/NSS=%s\nPPE builder=%s\nNSS feed=%s\nPPE QoS LuCI=%s\nOfficial snapshot=%s\nCustom=%s\n' \
  "$IMM_SHA" "$PPE_SHA" "$BASE_SHA" "$NSS_SHA" "$PPE_LUCI_SHA" "$SNAPSHOT" \
  "$(git -C "$ROOT" rev-parse --short=8 HEAD)" | tee "$OUT/source-commits.txt"

for name in dl .ccache; do
  [[ ! -e "$IMM/$name" ]] || { echo "::error::Unexpected $name in clone" >&2; exit 1; }
done
ln -s "$CACHE_DL" "$IMM/dl"
ln -s "$CACHE_CCACHE" "$IMM/.ccache"
export CCACHE_DIR="$CACHE_CCACHE"
ccache --max-size 3G >/dev/null
ccache --zero-stats >/dev/null

export IMM_SOURCE_DIR="$IMM" PPE_SOURCE_DIR="$PPE"
bash "$ROOT/scripts/port-ppe-nss-to-immortalwrt.sh"

# ---------------------------------------------------------------------------
# 2. Feeds pinned to the official arch repositories (+ NSS, PPE LuCI)
# ---------------------------------------------------------------------------
cd "$IMM"
"${HB[@]}" feeds-conf --lock "$LOCK" --nss "$NSS_SHA" > feeds.conf
cat feeds.conf
./scripts/feeds update -a
# Same exclusions as the full-source Builder (Kconfig cycles, HomeProxy).
rm -rf feeds/packages/net/fwknop feeds/packages/sound/squeezelite \
       feeds/luci/applications/luci-app-fwknopd \
       feeds/luci/applications/luci-app-homeproxy
patch -p1 -d "$IMM/feeds/packages" < \
  "$BUILDER/patches/feeds/ppe-nss/packages/0001-sqm-scripts-pin-the-fork-that-carries-hw_ppe.patch"
git init -q "$PPE_LUCI"
git -C "$PPE_LUCI" remote add origin https://github.com/JuliusBairaktaris/luci.git
git -C "$PPE_LUCI" fetch -q --depth 1 --filter=blob:none origin "$PPE_LUCI_SHA"
git -C "$PPE_LUCI" sparse-checkout set applications/luci-app-qca-ppe-qos
git -C "$PPE_LUCI" -c advice.detachedHead=false checkout -q --detach FETCH_HEAD
rm -rf feeds/luci/applications/luci-app-qca-ppe-qos
cp -a "$PPE_LUCI/applications/luci-app-qca-ppe-qos" feeds/luci/applications/
./scripts/feeds update -i packages
./scripts/feeds update -i luci
grep -Fq 'Package: luci-app-qca-ppe-qos' feeds/luci.index
refuse 'HomeProxy is still indexed in the LuCI feed' grep -Fq 'Package: luci-app-homeproxy' feeds/luci.index
./scripts/feeds install -a
git clone -q --depth 1 --branch v1.4.0 https://github.com/eamonxg/luci-theme-aurora.git package/luci-theme-aurora
bash "$ROOT/scripts/prepare-sing-box-luci.sh" "$IMM/package/luci-app-sing-box"

FEEDS_FINGERPRINT="$(
  for feed in packages luci routing telephony nss; do git -C "feeds/$feed" rev-parse HEAD; done
  git -C "$PPE_LUCI" rev-parse HEAD
)"
FEEDS_FINGERPRINT="$(printf '%s\n' "$FEEDS_FINGERPRINT" | sha256sum | cut -d' ' -f1)"
EXPECTED_FEEDS="$("${HB[@]}" fingerprint feeds --lock "$LOCK" --nss "$NSS_SHA" --ppe-luci "$PPE_LUCI_SHA")"
[[ "$FEEDS_FINGERPRINT" == "$EXPECTED_FEEDS" ]] || {
  echo "::error::Feed checkouts differ from the official snapshot pins" >&2; exit 1;
}
printf 'Feeds=%s\n' "$FEEDS_FINGERPRINT" >> "$OUT/source-commits.txt"

# F2FS device packages + matching eMMC sysupgrade hook (platform.sh).
COMPAT_FILES="$WORK/compat-files"
bash "$ROOT/scripts/apply-immortalwrt-compat.sh" "$IMM" "$COMPAT_FILES"

# ---------------------------------------------------------------------------
# 3. Configuration: device + official kernel features + full package wish list
# ---------------------------------------------------------------------------
fetch_verified "$TARGET_URL/config.buildinfo" "$WORK/official-config.buildinfo" \
  "$(jq -er '.target_sources["config.buildinfo"].sha256' "$LOCK")"
cp "$ROOT/config/immortalwrt-re-ss-01.config" .config
"${HB[@]}" kernel-config --buildinfo "$WORK/official-config.buildinfo" >> .config
append_packages() {
  local file="$1" value="$2" name line
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    for name in $line; do
      [[ "$name" =~ ^[a-z0-9][a-z0-9+._-]*$ ]] || { echo "Bad package: $name" >&2; exit 1; }
      printf 'CONFIG_PACKAGE_%s=%s\n' "$name" "$value" >> .config
      if [[ "$value" == y && "$name" =~ ^luci-i18n-([a-z0-9_-]+)-zh-cn$ && "${BASH_REMATCH[1]}" != base ]]; then
        printf 'CONFIG_PACKAGE_luci-app-%s=y\n' "${BASH_REMATCH[1]}" >> .config
      fi
    done
  done < "$file"
}
# The complete selection lets Kconfig pull in every kmod the userland needs;
# only the kernel side of it is compiled here.
append_packages "$ROOT/config/add.txt" y
append_packages "$ROOT/config/remove.txt" n

# Official toolchain of THIS snapshot: libc/libgcc match the official APKs.
IMM_OFFICIAL_SNAPSHOT_LOCK="$LOCK" IMM_USE_OFFICIAL_TOOLCHAIN=required \
  bash "$ROOT/scripts/reuse-official-toolchain.sh" "$IMM" "$CACHE_DL" \
  "$OUT/official-toolchain-status.txt"
grep -Fqx 'toolchain=official-immortalwrt' "$OUT/official-toolchain-status.txt"

make defconfig 2>&1 | tee "$WORK/defconfig.log"
refuse 'Kconfig dependency cycle in feeds' grep -Fq 'error: recursive dependency detected!' "$WORK/defconfig.log"
for required in CONFIG_IB=y CONFIG_IB_STANDALONE=y CONFIG_SDK=y CONFIG_CCACHE=y \
  CONFIG_EXTERNAL_TOOLCHAIN=y CONFIG_EXTERNAL_TOOLCHAIN_IB=y CONFIG_EXTERNAL_TOOLCHAIN_SDK=y \
  CONFIG_ATH11K_NSS_WIFI=y CONFIG_TARGET_DEVICE_qualcommax_ipq60xx_DEVICE_jdcloud_re-ss-01=y; do
  grep -Fqx "$required" .config || { echo "::error::defconfig dropped $required" >&2; exit 1; }
done
missing=()
while IFS= read -r line || [[ -n "$line" ]]; do
  line="${line%%#*}"
  for p in $line; do grep -Fqx "CONFIG_PACKAGE_$p=y" .config || missing+=("$p"); done
done < "$ROOT/config/add.txt"
for p in kmod-nss-wifi-drv luci-theme-aurora luci-app-sing-box qca-ppe-qos \
  luci-app-qca-ppe-qos kmod-fs-f2fs; do
  grep -Fqx "CONFIG_PACKAGE_$p=y" .config || missing+=("$p")
done
(( ${#missing[@]} == 0 )) || { echo "::error::Unavailable packages: ${missing[*]}" >&2; exit 1; }
TOOLCHAIN_ROOT="$(sed -n 's/^CONFIG_TOOLCHAIN_ROOT="\([^"]*\)"$/\1/p' .config)"
bash scripts/ext-toolchain.sh --toolchain "$TOOLCHAIN_ROOT" --test c
mark prepare "$T0"

# ---------------------------------------------------------------------------
# 4. Host tools, toolchain wrapper and host apk (needed to read official indexes)
# ---------------------------------------------------------------------------
phase tools tools/install
phase toolchain toolchain/install
phase apk-host package/system/apk/host/compile
APK="$IMM/staging_dir/host/bin/apk"
test -x "$APK"

# ---------------------------------------------------------------------------
# 5. Official indexes (signature + SHA256) and the userland closure
# ---------------------------------------------------------------------------
T1="$(date +%s)"
IDX="$WORK/official-indexes"
KEYS="$WORK/official-keys"
mkdir -p "$IDX" "$KEYS"
KEYRING_SHA="$(sed -n 's/^PKG_SOURCE_VERSION:=\([0-9a-f]\{40\}\)$/\1/p' package/system/openwrt-keyring/Makefile)"
[[ -n "$KEYRING_SHA" ]]
git init -q "$WORK/keyring"
git -C "$WORK/keyring" remote add origin https://github.com/immortalwrt/keyring.git
git -C "$WORK/keyring" fetch -q --depth 1 origin "$KEYRING_SHA"
git -C "$WORK/keyring" -c advice.detachedHead=false checkout -q --detach FETCH_HEAD
cp "$WORK/keyring/apk/"*.pem "$KEYS/"
test -s "$KEYS/immortalwrt-snapshots.pem"

fetch_verified "$TARGET_URL/sha256sums" "$IDX/target.sha256sums" "$(jq -er '.target_checksums_sha256' "$LOCK")"
fetch_verified "$ARCH_URL/sha256sums" "$IDX/arch.sha256sums" "$(jq -er '.arch_checksums_sha256' "$LOCK")"
index_args=()
for repo in target base packages luci routing telephony; do
  if [[ "$repo" == target ]]; then
    rel="$(jq -er '.package_indexes.target.filename' "$LOCK")"
    sha="$(jq -er '.package_indexes.target.sha256' "$LOCK")"
    url="$TARGET_URL/$rel"
  else
    rel="$(jq -er --arg r "$repo" '.package_indexes.architecture[$r].filename' "$LOCK")"
    sha="$(jq -er --arg r "$repo" '.package_indexes.architecture[$r].sha256' "$LOCK")"
    url="$ARCH_URL/$rel"
  fi
  fetch_verified "$url" "$IDX/$repo.adb" "$sha"
  # Trust root: the ImmortalWrt snapshot key from the pinned keyring commit.
  "$APK" --keys-dir "$KEYS" verify "$IDX/$repo.adb" || {
    echo "::error::Official $repo index is not signed by the ImmortalWrt keyring" >&2; exit 1;
  }
  "$APK" adbdump --format json "$IDX/$repo.adb" > "$IDX/$repo.json"
  index_args+=(--index "$repo=$IDX/$repo.json")
done

: > "$WORK/extra-local.txt"
for attempt in 1 2; do
  "${HB[@]}" plan --packageinfo tmp/.packageinfo --config .config \
    --extra-local "$WORK/extra-local.txt" --output "$OUT/local-plan.json"
  "${HB[@]}" closure --plan "$OUT/local-plan.json" --lock "$LOCK" "${index_args[@]}" \
    --target-sums "$IDX/target.sha256sums" --arch-sums "$IDX/arch.sha256sums" \
    --output "$OUT/official-apks.json"
  fallback="$(jq -r '.local_fallback[]' "$OUT/official-apks.json")"
  [[ -n "$fallback" ]] || break
  (( attempt == 1 )) || { echo "::error::Unresolved after local fallback: $fallback" >&2; exit 1; }
  printf '%s\n' $fallback >> "$WORK/extra-local.txt"
done
mark official-closure "$T1"

# ---------------------------------------------------------------------------
# 6. Local compilation: kernel + kmods (with deps), custom userland (NO_DEPS)
# ---------------------------------------------------------------------------
mapfile -t KERNEL_TARGETS < <(jq -r '.kernel_compile_targets[]' "$OUT/local-plan.json")
mapfile -t HOST_TARGETS < <(jq -r '.host_compile_targets[]' "$OUT/local-plan.json")
mapfile -t USER_TARGETS < <(jq -r '.userland_compile_targets[]' "$OUT/local-plan.json")
phase kernel target/compile
phase kmods "${KERNEL_TARGETS[@]}"
(( ${#HOST_TARGETS[@]} == 0 )) || phase host-packages "${HOST_TARGETS[@]}"
# NO_DEPS: these are scripts/LuCI/base files; their userland dependencies
# come from the official repositories and must not be rebuilt here.
phase local-userland NO_DEPS=1 "${USER_TARGETS[@]}"

PKG_DIR="$(make -s val.PACKAGE_DIR | tail -n1)"
[[ "$PKG_DIR" == "$IMM/bin/targets/qualcommax/ipq60xx/packages" ]]
local_apk() { find "$IMM/bin" -type f -name "$1-[0-9]*.apk" -print -quit; }
not_built=()
while IFS= read -r name; do
  [[ -n "$(local_apk "$name")" ]] || not_built+=("$name")
done < <(jq -r '.local_packages[].apk_name' "$OUT/local-plan.json")
(( ${#not_built[@]} == 0 )) || { echo "::error::Not built locally: ${not_built[*]}" >&2; exit 1; }
find "$IMM/bin" -type f -name '*.apk' -printf '%f\n' | sort > "$OUT/local-apks.txt"

# ---------------------------------------------------------------------------
# 7. Mirror the official userland into the standalone ImageBuilder repository
# ---------------------------------------------------------------------------
T2="$(date +%s)"
mkdir -p "$PKG_DIR"
: > "$WORK/mirror.tsv"
skipped=0
while IFS=$'\t' read -r name file url sha; do
  # A local build of the same package always wins.
  if [[ -n "$(local_apk "$name")" ]]; then skipped=$((skipped + 1)); continue; fi
  printf '%s\t%s\t%s\n' "$file" "$url" "$sha" >> "$WORK/mirror.tsv"
done < <(jq -r '.mirror[] | [.name, .filename, .url, .sha256] | @tsv' "$OUT/official-apks.json")
export PKG_DIR
while IFS=$'\t' read -r file url sha; do
  printf '%s\0%s\0%s\0' "$file" "$url" "$sha"
done < "$WORK/mirror.tsv" | xargs -0 -n3 -P8 sh -c '
  curl -fsSL --retry 3 --connect-timeout 20 --max-time 300 "$1" -o "$PKG_DIR/$0" &&
  printf "%s  %s\n" "$2" "$PKG_DIR/$0" | sha256sum -c --status ||
  { echo "::error::Official APK failed SHA256: $0" >&2; exit 255; }'
MIRRORED="$(wc -l < "$WORK/mirror.tsv")"
# Official snapshots set SIGN_EACH_PACKAGE: every mirrored APK must carry a
# valid ImmortalWrt signature, not only match sha256sums.
mapfile -t MIRROR_FILES < <(cut -f1 "$WORK/mirror.tsv" | sed "s|^|$PKG_DIR/|")
(( ${#MIRROR_FILES[@]} == 0 )) || "$APK" --keys-dir "$KEYS" verify "${MIRROR_FILES[@]}" || {
  echo "::error::Mirrored official APKs failed signature verification" >&2; exit 1;
}
echo "Mirrored $MIRRORED official APKs ($skipped replaced by local builds)."
mark official-mirror "$T2"

# ImageBuilder ships the staging rootfs keyring; no package/install ran here.
STAGING_ROOT="$(make -s val.STAGING_DIR_ROOT | tail -n1)"
[[ "$STAGING_ROOT" == "$IMM"/staging_dir/* ]]
mkdir -p "$STAGING_ROOT/etc/apk/keys"
cp "$IMM/public-key.pem" "$KEYS/"*.pem "$STAGING_ROOT/etc/apk/keys/"

# ---------------------------------------------------------------------------
# 8. Standalone ImageBuilder + SDK from this exact tree
# ---------------------------------------------------------------------------
phase imagebuilder NO_DEPS=1 target/imagebuilder/install
phase sdk NO_DEPS=1 target/sdk/install
TARGET_BIN="$IMM/bin/targets/qualcommax/ipq60xx"
IB_ARCHIVE="$(find "$TARGET_BIN" -maxdepth 1 -type f -name '*imagebuilder*.tar.zst' -print -quit)"
SDK_ARCHIVE="$(find "$TARGET_BIN" -maxdepth 1 -type f -name 'immortalwrt-sdk-*.tar.zst' -print -quit)"
test -s "$IB_ARCHIVE" && test -s "$SDK_ARCHIVE"
cp "$IB_ARCHIVE" "$SDK_ARCHIVE" "$OUT/"
IB_ARCHIVE="$OUT/$(basename "$IB_ARCHIVE")"
SDK_ARCHIVE="$OUT/$(basename "$SDK_ARCHIVE")"
(( $(stat -c '%s' "$SDK_ARCHIVE") < 2147483648 ))
tar -I zstd -tf "$SDK_ARCHIVE" > "$WORK/sdk-contents.txt"
for required in '^[^/]+/rules[.]mk$' '^[^/]+/include/kernel[.]mk$' \
  '^[^/]+/staging_dir/toolchain-[^/]+/bin/' \
  '^[^/]+/build_dir/target-[^/]+/linux-[^/]+/linux-[^/]+/Module[.]symvers$'; do
  grep -Eq "$required" "$WORK/sdk-contents.txt" || {
    echo "::error::SDK lacks $required" >&2; exit 1;
  }
done
refuse 'SDK still contains HomeProxy' grep -Eiq '(^|/)(luci-app-homeproxy|luci-i18n-homeproxy-zh-cn)(/|$)' "$WORK/sdk-contents.txt"

# The package list a firmware starts from: exactly what this IB resolves.
T3="$(date +%s)"
IB_TEST="$WORK/ib-manifest"
mkdir -p "$IB_TEST"
tar -I zstd -xf "$IB_ARCHIVE" -C "$IB_TEST"
IB_DIR="$(find "$IB_TEST" -mindepth 1 -maxdepth 1 -type d -name '*imagebuilder*' -print -quit)"
REQUEST=""
while IFS= read -r line || [[ -n "$line" ]]; do line="${line%%#*}"; REQUEST+=" $line"; done < "$ROOT/config/add.txt"
while IFS= read -r line || [[ -n "$line" ]]; do
  line="${line%%#*}"; for p in $line; do REQUEST+=" -$p"; done
done < "$ROOT/config/remove.txt"
make -C "$IB_DIR" -s manifest PROFILE=jdcloud_re-ss-01 STRIP_ABI=1 PACKAGES="$REQUEST" \
  > "$WORK/ib.manifest"
awk 'NF >= 3 && $2 == "-" && $1 ~ /^[a-z0-9][a-z0-9+._-]*$/ &&
     $1 != "kernel" && $1 != "libc" && $1 != "base-files" { print $1 }' \
  "$WORK/ib.manifest" | sort -u > "$OUT/imagebuilder-packages.txt"
for required in kmod-nss-wifi-drv luci-app-sing-box sing-box luci-app-autoreboot \
  luci-app-cpufreq default-settings-chn autocore luci-app-ddns-go kmod-fs-f2fs \
  qca-ppe-qos luci-app-qca-ppe-qos luci-theme-aurora sqm-scripts; do
  grep -Fxq "$required" "$OUT/imagebuilder-packages.txt" || {
    echo "::error::ImageBuilder manifest missing $required" >&2; exit 1;
  }
done
for excluded in luci-app-homeproxy luci-app-diskman luci-app-statistics; do
  refuse "Image still includes $excluded" grep -Fxq "$excluded" "$OUT/imagebuilder-packages.txt"
done
# Every kmod in the image must be one we compiled for this kernel.
awk '$1 ~ /^kmod-/ { print $1 "-" $3 ".apk" }' "$WORK/ib.manifest" | while read -r apk; do
  grep -Fxq "$apk" "$OUT/local-apks.txt" || { echo "::error::Foreign kmod in image: $apk" >&2; exit 1; }
done
cp "$WORK/ib.manifest" "$OUT/imagebuilder.manifest"
mark ib-manifest "$T3"

# ---------------------------------------------------------------------------
# 9. Release metadata + SDK/ImageBuilder smoke tests
# ---------------------------------------------------------------------------
BASE_STAGE="$WORK/base-overlay"
mkdir -p "$BASE_STAGE"
rsync -a "$BUILDER/devices/common/files.ppe-nss/" "$BASE_STAGE/"
install -D -m 0644 "$COMPAT_FILES/lib/upgrade/platform.sh" "$BASE_STAGE/lib/upgrade/platform.sh"
tar -czf "$OUT/base-overlay.tar.gz" -C "$BASE_STAGE" .
cd "$ROOT"
python3 scripts/immortalwrt_builder.py metadata --mode hybrid --snapshot-lock "$LOCK" \
  --immortal "$IMM_SHA" --ppe "$PPE_SHA" --base "$BASE_SHA" --feeds "$FEEDS_FINGERPRINT" \
  --archive "$IB_ARCHIVE" --overlay "$OUT/base-overlay.tar.gz" \
  --packages "$OUT/imagebuilder-packages.txt" --output "$OUT/builder-metadata.json"
python3 scripts/immortalwrt_builder.py verify --metadata "$OUT/builder-metadata.json" \
  --archive "$IB_ARCHIVE" --overlay "$OUT/base-overlay.tar.gz" \
  --packages "$OUT/imagebuilder-packages.txt"
python3 scripts/immortalwrt_sdk.py metadata --source "$IMM" --ppe-luci "$PPE_LUCI" \
  --builder-metadata "$OUT/builder-metadata.json" \
  --toolchain-status "$OUT/official-toolchain-status.txt" \
  --archive "$SDK_ARCHIVE" --feed-lock "$OUT/sdk-feeds.lock.json" \
  --output "$OUT/sdk-metadata.json"
T4="$(date +%s)"
bash scripts/test-sdk-smoke.sh "$SDK_ARCHIVE" "$WORK/sdk-smoke"
BUILDER_META="$OUT/builder-metadata.json" BUILDER_ARCHIVE="$IB_ARCHIVE" \
BASE_OVERLAY="$OUT/base-overlay.tar.gz" BUILDER_PACKAGES="$OUT/imagebuilder-packages.txt" \
IMMORTAL_OUT_DIR="$OUT/ib-smoke" PUBLISH_RELEASE=false \
  bash scripts/repack-immortalwrt.sh
test -s "$OUT/ib-smoke/immortalwrt-qualcommax-ipq60xx-jdcloud_re-ss-01-squashfs-sysupgrade.bin"
mark smoke-tests "$T4"

cp "$LOCK" "$OUT/snapshot-lock.json"
cp "$IMM/.config" "$OUT/immortalwrt.config"
CCACHE_DIR="$CACHE_CCACHE" ccache --show-stats > "$OUT/ccache-stats.txt" || true
mark total "$T0"
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    echo "## Hybrid Builder $(jq -r .tag "$OUT/builder-metadata.json")"
    echo "- Official snapshot: \`$SNAPSHOT\`"
    echo "- Local packages: $(jq '.local_packages | length' "$OUT/local-plan.json") ($(jq '.local_kmods | length' "$OUT/local-plan.json") kmods)"
    echo "- Official APKs mirrored: $MIRRORED"
    echo "- Image packages: $(wc -l < "$OUT/imagebuilder-packages.txt")"
    echo ""
    echo "| Phase | Seconds |"
    echo "|---|---:|"
    awk -F'\t' '{ printf "| %s | %s |\n", $1, $2 }' "$OUT/timings.tsv"
  } >> "$GITHUB_STEP_SUMMARY"
fi
echo "Hybrid Builder ready: $(jq -r .tag "$OUT/builder-metadata.json")"
