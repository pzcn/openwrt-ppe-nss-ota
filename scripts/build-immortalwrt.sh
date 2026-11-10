#!/usr/bin/env bash
# Full-source build: ImmortalWrt + OpenWrt PPE/NSS Wi-Fi port + RE-SS-01 customizations.
set -Eeuo pipefail
trap 'echo "::error::ImmortalWrt build failed at line $LINENO: $BASH_COMMAND" >&2' ERR

ROOT="${GITHUB_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
WORK="${RUNNER_TEMP:-/tmp}/immortal-ppe-nss"
OUT="$ROOT/out-immortal"
IMM="$WORK/immortalwrt"
PPE="$WORK/ppe-nss"
BUILDER="$WORK/ppe-builder"
PUBLISH_RELEASE="${PUBLISH_RELEASE:-false}"
IMMORTAL_REF="${IMMORTAL_REF:-master}"
PPE_REF="${PPE_REF:-ppe-nss}"
RUN_NUMBER="${GITHUB_RUN_NUMBER:-1}"
ATTEMPT="${GITHUB_RUN_ATTEMPT:-1}"
mkdir -p "$WORK" "$OUT"
# Persist only source archives and compiler objects between ephemeral Actions runners.
# Leave kernel build directories fresh so stale patches and ABI objects cannot leak in.
CACHE_ROOT="${IMMORTAL_CACHE_ROOT:-$ROOT/.build-cache}"
CACHE_DL="$CACHE_ROOT/dl"
CACHE_CCACHE="$CACHE_ROOT/ccache"
CACHE_GO="$CACHE_ROOT/go-build"
mkdir -p "$CACHE_DL" "$CACHE_CCACHE" "$CACHE_GO"
BUILD_START_SECONDS="$(date +%s)"

for n in "$RUN_NUMBER" "$ATTEMPT"; do
  [[ "$n" =~ ^[0-9]+$ ]] || { echo "Invalid run number" >&2; exit 1; }
done
(( ATTEMPT < 10 )) || { echo "Unexpected run attempt" >&2; exit 1; }
BUILD_NUMBER="$(date -u +%s)"
SOURCE_REV="$(git -C "$ROOT" rev-parse --short=8 HEAD)"

clone() {
  local url="$1" ref="$2" dest="$3"
  git clone --quiet --depth 1 --single-branch --branch "$ref" "$url" "$dest"
}
clone https://github.com/immortalwrt/immortalwrt.git "$IMMORTAL_REF" "$IMM"
clone https://github.com/JuliusBairaktaris/openwrt-ppe-nss.git "$PPE_REF" "$PPE"
clone https://github.com/JuliusBairaktaris/Qualcommax_NSS_Builder.git main "$BUILDER"
# Both paths must be missing in a clean clone. Link them into the Actions cache.
for name in dl .ccache; do
  if [[ -e "$IMM/$name" || -L "$IMM/$name" ]]; then
    echo "::error::Unexpected cache path already exists in ImmortalWrt clone: $name" >&2
    exit 1
  fi
done
ln -s "$CACHE_DL" "$IMM/dl"
ln -s "$CACHE_CCACHE" "$IMM/.ccache"
CCACHE_DIR="$CACHE_CCACHE" ccache --max-size 1600M
CCACHE_DIR="$CACHE_CCACHE" ccache --zero-stats
IMM_SHA="$(git -C "$IMM" rev-parse HEAD)"
PPE_SHA="$(git -C "$PPE" rev-parse HEAD)"
BASE_SHA="$(git -C "$BUILDER" rev-parse HEAD)"
# Fail before compiling if remote branch heads changed since workflow resolution.
for pair in "IMM_SHA:EXPECTED_IMM_SHA" "PPE_SHA:EXPECTED_PPE_SHA" "BASE_SHA:EXPECTED_BASE_SHA"; do
  actual_var="${pair%%:*}"
  expected_var="${pair#*:}"
  expected="${!expected_var:-}"
  actual="${!actual_var}"
  if [[ -n "$expected" && "$actual" != "$expected" ]]; then
    echo "::error::Upstream moved during Builder resolution: $actual_var $actual != $expected" >&2
    exit 1
  fi
done
TAG="imm-ppe-nss-${IMM_SHA:0:8}-${PPE_SHA:0:8}-g$SOURCE_REV-b$BUILD_NUMBER"
printf 'ImmortalWrt=%s\nPPE/NSS=%s\nPPE builder=%s\nCustom=%s\n' "$IMM_SHA" "$PPE_SHA" "$BASE_SHA" "$SOURCE_REV" | tee "$OUT/source-commits.txt"

export IMM_SOURCE_DIR="$IMM" PPE_SOURCE_DIR="$PPE"
bash "$ROOT/scripts/port-ppe-nss-to-immortalwrt.sh"

# Keep official ImmortalWrt packages/LuCI, adding only the PPE/NSS firmware
# feed and Julius' QoS LuCI application.
cd "$IMM"
cp feeds.conf.default feeds.conf
# The upstream video feed is unnecessary for this router image and currently
# introduces unrelated Qt5 Kconfig recursive dependency errors.
sed -i '/^src-git video /d' feeds.conf
printf '\nsrc-git nss https://github.com/JuliusBairaktaris/nss-packages.git;ppe-nss\n' >> feeds.conf
./scripts/feeds update -a
# Upstream currently includes unrelated packages with circular Kconfig chains.
# Neither is used by this router; exclude only these optional package definitions
# before re-indexing feeds, retaining official sources for all required packages.
# fwknopd <-> luci-app-fwknopd / FWKNOPD_GPG
# squeezelite-custom <-> SQUEEZELITE_WMA_ALAC
# HomeProxy must be absent from the compiled package repository AND the
# published SDK's LuCI source tree, not merely deselected in config/remove.txt.
# Retain the official git commit/feeds lock; change only its working tree.
rm -rf "$IMM/feeds/packages/net/fwknop" \
       "$IMM/feeds/packages/sound/squeezelite" \
       "$IMM/feeds/luci/applications/luci-app-fwknopd" \
       "$IMM/feeds/luci/applications/luci-app-homeproxy"
./scripts/feeds update -i packages

# Use the same pinned hardware SQM backend as the existing PPE release.
patch -p1 -d "$IMM/feeds/packages" < \
  "$BUILDER/patches/feeds/ppe-nss/packages/0001-sqm-scripts-pin-the-fork-that-carries-hw_ppe.patch"

git clone --quiet --depth 1 --filter=blob:none --sparse --branch luci-app-ppe-qos \
  https://github.com/JuliusBairaktaris/luci.git "$WORK/ppe-luci"
git -C "$WORK/ppe-luci" sparse-checkout set applications/luci-app-qca-ppe-qos
# Track the actual feed commits, not only ImmortalWrt's main branch.
# The resolver computes the same digest from the remote feed HEADs.
FEEDS_FINGERPRINT="$(
  {
    for feed in packages luci routing telephony nss; do
      git -C "$IMM/feeds/$feed" rev-parse HEAD
    done
    git -C "$WORK/ppe-luci" rev-parse HEAD
  } | sha256sum | cut -d' ' -f1
)"
if [[ -n "${EXPECTED_FEEDS_FINGERPRINT:-}" &&
      "$EXPECTED_FEEDS_FINGERPRINT" != "$FEEDS_FINGERPRINT" ]]; then
  echo "::error::Upstream feed HEADs changed since Builder version resolution" >&2
  exit 1
fi
printf 'Feeds=%s\n' "$FEEDS_FINGERPRINT" >> "$OUT/source-commits.txt"
rm -rf "$IMM/feeds/luci/applications/luci-app-qca-ppe-qos"
cp -a "$WORK/ppe-luci/applications/luci-app-qca-ppe-qos" "$IMM/feeds/luci/applications/"
# The first feeds update indexed LuCI before this extra application existed.
# Rebuild its local index, otherwise feeds install -a silently skips QoS LuCI.
./scripts/feeds update -i luci
grep -Fq 'luci-app-qca-ppe-qos' "$IMM/feeds/luci.index" || {
  echo "::error::PPE QoS LuCI application missing from feed index" >&2
  exit 1
}
if grep -Fq 'Package: luci-app-homeproxy' "$IMM/feeds/luci.index"; then
  echo "::error::HomeProxy is still indexed in the Builder LuCI feed" >&2
  exit 1
fi
./scripts/feeds install -a
test -e "$IMM/package/feeds/luci/luci-app-qca-ppe-qos" || {
  echo "::error::PPE QoS LuCI application was not installed from its feed" >&2
  exit 1
}
if [[ -e "$IMM/package/feeds/luci/luci-app-homeproxy" ||
      -e "$IMM/feeds/luci/applications/luci-app-homeproxy" ]]; then
  echo "::error::HomeProxy source remains in the Builder/SDK package tree" >&2
  exit 1
fi

# Build pinned sources, not foreign-ABI release APKs.
clone https://github.com/eamonxg/luci-theme-aurora.git v1.4.0 "$IMM/package/luci-theme-aurora"
bash "$ROOT/scripts/prepare-sing-box-luci.sh" "$IMM/package/luci-app-sing-box"

# BEGIN firmware-only overlay (excluded from Builder fingerprint)
# Preserve PPE/NSS defaults and apply firmware-only LuCI and app selection.
mkdir -p "$IMM/files"
rsync -a "$BUILDER/devices/common/files.ppe-nss/" "$IMM/files/"
rsync -a "$ROOT/files/" "$IMM/files/"
rm -f "$IMM/files/www/luci-static/resources/view/system/ppe-update.js" \
      "$IMM/files/usr/share/luci/menu.d/luci-app-ppe-update.json" \
      "$IMM/files/etc/uci-defaults/94-custom-world" \
      "$IMM/files/etc/ppe-release" \
      "$IMM/files/etc/config/fstab" \
      "$IMM/files/etc/uci-defaults/96-migrate-legacy-extroot"
# App inclusion/exclusion is applied at image packaging time, not in Builder.
sh "$ROOT/scripts/stage-firmware-overlay.sh" "$IMM/files"

# Temporary F2FS and eMMC sysupgrade fixes, bundled in full and repacked images.
bash "$ROOT/scripts/apply-immortalwrt-compat.sh" "$IMM" "$IMM/files"
test -s "$IMM/files/lib/upgrade/platform.sh"

# Translate the exact existing custom catalogs as native LuCI .lmo files.
I18N_DIR="$IMM/files/usr/lib/lua/luci/i18n"
mkdir -p "$I18N_DIR"
python3 "$ROOT/scripts/build_luci_i18n.py" \
  --input "$ROOT/config/translations/qca-ppe-qos.zh-cn.json" \
  --output "$I18N_DIR/qca-ppe-qos.zh-cn.lmo" --min-entries 61
python3 "$ROOT/scripts/build_luci_i18n.py" \
  --input "$ROOT/config/translations/ppe-update.zh-cn.json" \
  --output "$I18N_DIR/ppe-update.zh-cn.lmo" --min-entries 2
python3 "$ROOT/scripts/immortalwrt_ota.py" prepare \
  --overlay "$IMM/files" --tag "$TAG" --build "$BUILD_NUMBER"
for s in "$IMM/files/usr/sbin/ppe-update" \
         "$IMM/files/etc/init.d/ppe-update"; do
  sh -n "$s"
done
node --check "$IMM/files/www/luci-static/resources/view/system/flash.js"
# END firmware-only overlay

# All user-requested packages are taken from ImmortalWrt's own source feeds.
# Kernel packages are compiled with this exact kernel; no OpenWrt snapshot APKs.
cp "$ROOT/config/immortalwrt-re-ss-01.config" "$IMM/.config"
append_packages() {
  local file="$1" value="$2" name line
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    for name in $line; do
      [[ "$name" =~ ^[a-z0-9][a-z0-9+._-]*$ ]] || { echo "Bad package: $name" >&2; exit 1; }
      printf 'CONFIG_PACKAGE_%s=%s\n' "$name" "$value" >> "$IMM/.config"
    done
  done < "$file"
}
append_packages "$ROOT/config/add.txt" y
append_packages "$ROOT/config/remove.txt" n

# LuCI translation packages do not automatically enable their application
# parents under Kconfig. Request the corresponding LuCI apps before
# defconfig, otherwise existing translations like bcp38-zh-cn are silently
# dropped even though the apps and their Chinese catalogs exist.
# 'base' is special: it belongs to luci-base rather than luci-app-base.
while IFS= read -r line || [[ -n "$line" ]]; do
  line="${line%%#*}"
  for p in $line; do
    if [[ "$p" =~ ^luci-i18n-([a-z0-9_-]+)-zh-cn$ ]]; then
      app="${BASH_REMATCH[1]}"
      if [[ "$app" != base ]]; then
        printf 'CONFIG_PACKAGE_luci-app-%s=y\n' "$app" >> "$IMM/.config"
      fi
    fi
  done
done < "$ROOT/config/add.txt"

# Prefer matching official compiled GCC/musl when available. This does not
# import official kernel modules, DTB or NSS packages.
bash "$ROOT/scripts/reuse-official-toolchain.sh" "$IMM" "$CACHE_DL" \
  "$OUT/official-toolchain-status.txt"

# The upstream Go feed normally builds multiple Go bootstrap generations and
# stores its build cache under transient tmp/go-build. Use the official binary
# Go 1.26 as a supported host bootstrap and persist content-addressed Go work.
GO_BOOTSTRAP_ROOT="$(go env GOROOT)"
GO_BOOTSTRAP_VERSION="$(go env GOVERSION)"
[[ "$GO_BOOTSTRAP_VERSION" == go1.26.* || "$GO_BOOTSTRAP_VERSION" == go1.27.* ]] || {
  echo "::error::Unsupported host Go bootstrap: $GO_BOOTSTRAP_VERSION" >&2
  exit 1
}
test -x "$GO_BOOTSTRAP_ROOT/bin/go"
printf 'CONFIG_GOLANG_EXTERNAL_BOOTSTRAP_ROOT="%s"\n' "$GO_BOOTSTRAP_ROOT" >> "$IMM/.config"
printf '# CONFIG_GOLANG_BUILD_BOOTSTRAP is not set\n' >> "$IMM/.config"
printf 'CONFIG_GOLANG_BUILD_CACHE_DIR="%s"\n' "$CACHE_GO" >> "$IMM/.config"

# Kconfig can report recursive-dependency errors yet return status 0.
# Keep the diagnostic and fail instead of continuing with partial .config.
make defconfig 2>&1 | tee "$WORK/defconfig.log"
if grep -Fq 'error: recursive dependency detected!' "$WORK/defconfig.log"; then
  echo "::error::ImmortalWrt upstream feeds contain a Kconfig dependency cycle" >&2
  exit 1
fi
# Fail instead of silently producing a firmware without its reusable builder.
grep -Fqx 'CONFIG_IB=y' "$IMM/.config"
grep -Fqx 'CONFIG_IB_STANDALONE=y' "$IMM/.config"
grep -Fqx 'CONFIG_SDK=y' "$IMM/.config" || {
  echo "::error::Matching OpenWrt SDK was disabled by defconfig" >&2
  exit 1
}
grep -Fqx 'CONFIG_CCACHE=y' "$IMM/.config"
# Keep firmware buildable if upstream moves its Go Kconfig options.
# Report missing performance settings, without skipping any required APK.
if grep -Fxq '# CONFIG_GOLANG_BUILD_BOOTSTRAP is not set' "$IMM/.config" &&
   grep -Fxq "CONFIG_GOLANG_EXTERNAL_BOOTSTRAP_ROOT=\"$GO_BOOTSTRAP_ROOT\"" "$IMM/.config"; then
  echo "Using official $GO_BOOTSTRAP_VERSION as OpenWrt Go bootstrap."
else
  echo "::warning::External Go bootstrap Kconfig was not retained; using upstream Go bootstrap." >&2
fi
if ! grep -Fxq "CONFIG_GOLANG_BUILD_CACHE_DIR=\"$CACHE_GO\"" "$IMM/.config"; then
  echo "::warning::Persistent Go cache Kconfig was not retained; using upstream Go cache." >&2
fi
if grep -Fqx 'toolchain=official-immortalwrt' "$OUT/official-toolchain-status.txt"; then
  grep -Fqx 'CONFIG_EXTERNAL_TOOLCHAIN=y' "$IMM/.config"
  grep -Fqx 'CONFIG_EXTERNAL_TOOLCHAIN_IB=y' "$IMM/.config"
  grep -Fqx 'CONFIG_EXTERNAL_TOOLCHAIN_SDK=y' "$IMM/.config"
  # Fail before the expensive compilation when Kconfig silently ignores the
  # external toolchain path (previously this failed 20 min later at wrapper).
  TOOLCHAIN_ROOT="$(sed -n 's/^CONFIG_TOOLCHAIN_ROOT="\([^"]*\)"$/\1/p' "$IMM/.config")"
  if [[ -z "$TOOLCHAIN_ROOT" || ! -d "$TOOLCHAIN_ROOT" ]]; then
    echo "::error::External toolchain root missing after make defconfig: ${TOOLCHAIN_ROOT:-unset}" >&2
    exit 1
  fi
  bash "$IMM/scripts/ext-toolchain.sh" --toolchain "$TOOLCHAIN_ROOT" --test c || {
    echo "::error::External compiler test failed before build" >&2
    exit 1
  }
  echo "Verified official toolchain root: $TOOLCHAIN_ROOT"
fi

# Kconfig silently omits unavailable packages. Refuse a deceptively
# successful image if a user-requested package or NSS option was dropped.
missing=()
verify_package() {
  local p="$1"
  if ! grep -Fqx "CONFIG_PACKAGE_$p=y" "$IMM/.config"; then
    echo "::error::Required package is unavailable: $p" >&2
    missing+=("$p")
  fi
}
while IFS= read -r line || [[ -n "$line" ]]; do
  line="${line%%#*}"
  for p in $line; do verify_package "$p"; done
done < "$ROOT/config/add.txt"
for p in kmod-nss-wifi-drv luci-theme-aurora luci-app-sing-box \
  qca-ppe-qos luci-app-qca-ppe-qos jq kmod-fs-f2fs; do
  verify_package "$p"
done
if (( ${#missing[@]} )); then
  printf 'Missing required packages (%d): %s\n' "${#missing[@]}" "${missing[*]}" >&2
  exit 1
fi
grep -Fqx 'CONFIG_ATH11K_NSS_WIFI=y' "$IMM/.config"
grep -Fqx 'CONFIG_TARGET_DEVICE_qualcommax_ipq60xx_DEVICE_jdcloud_re-ss-01=y' "$IMM/.config"

DOWNLOAD_BEGIN="$(date +%s)"
PREP_SECONDS=$(( DOWNLOAD_BEGIN - BUILD_START_SECONDS ))
make download -j"$(nproc)"
DOWNLOAD_SECONDS=$(( $(date +%s) - DOWNLOAD_BEGIN ))
COMPILE_BEGIN="$(date +%s)"
make -j"$(nproc)" || make -j1 V=s
COMPILE_SECONDS=$(( $(date +%s) - COMPILE_BEGIN ))
printf 'Downloads: %s seconds; compilation: %s seconds\n' "$DOWNLOAD_SECONDS" "$COMPILE_SECONDS"
CCACHE_DIR="$CACHE_CCACHE" ccache --show-stats
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    echo "## ImmortalWrt PPE/NSS full-source build"
    echo "- Source downloads: ${DOWNLOAD_SECONDS}s"
    echo "- Build and ImageBuilder: ${COMPILE_SECONDS}s"
    echo "- Compiler source: $(head -n1 "$OUT/official-toolchain-status.txt")"
    printf -- '- Source cache directory: `%s`\n' "$CACHE_DL"
    printf -- '- Compiler cache directory: `%s`\n' "$CACHE_CCACHE"
  } >> "$GITHUB_STEP_SUMMARY"
fi

# The image's name is part of the independent OTA safety contract.
TARGET="$IMM/bin/targets/qualcommax/ipq60xx"
IMAGE="immortalwrt-qualcommax-ipq60xx-jdcloud_re-ss-01-squashfs-sysupgrade.bin"
MANIFEST="immortalwrt-qualcommax-ipq60xx-jdcloud_re-ss-01.manifest"
test -s "$TARGET/$IMAGE"
IB_ARCHIVE="$(find "$TARGET" -maxdepth 1 -type f -name '*imagebuilder*.tar.zst' -print -quit)"
test -n "$IB_ARCHIVE" && test -s "$IB_ARCHIVE" || {
  echo "::error::Standalone ImageBuilder was not produced" >&2
  exit 1
}
SDK_ARCHIVE="$(find "$TARGET" -maxdepth 1 -type f -name 'immortalwrt-sdk-*.tar.zst' -print -quit)"
test -n "$SDK_ARCHIVE" && test -s "$SDK_ARCHIVE" || {
  echo "::error::Matching OpenWrt SDK was not produced" >&2
  exit 1
}
# An SDK must contain a buildroot, compiler and kernel module symbols.
SDK_CONTENTS="$WORK/sdk-contents.txt"
tar -I zstd -tf "$SDK_ARCHIVE" > "$SDK_CONTENTS"
# SDK export must not reintroduce either HomeProxy's source or its LuCI APK.
# Checking the archive itself also catches upstream SDK packaging changes.
if grep -Eiq '(^|/)(luci-app-homeproxy|luci-i18n-homeproxy-zh-cn)(/|$)' "$SDK_CONTENTS"; then
  echo "::error::Published SDK archive still contains HomeProxy" >&2
  exit 1
fi
for required in \
  '^[^/]+/rules[.]mk$' \
  '^[^/]+/include/kernel[.]mk$' \
  '^[^/]+/staging_dir/toolchain-[^/]+/bin/' \
  '^[^/]+/build_dir/target-[^/]+/linux-[^/]+/linux-[^/]+/Module[.]symvers$'; do
  grep -Eq "$required" "$SDK_CONTENTS" || {
    echo "::error::SDK archive missing a necessary toolchain or kernel ABI file: $required" >&2
    exit 1
  }
done
if (( $(stat -c '%s' "$SDK_ARCHIVE") >= 2147483648 )); then
  echo "::error::SDK is larger than the GitHub Release asset limit" >&2
  exit 1
fi
# Full-source builds may emit a board-wide manifest even for one device.
# Publish the single-device manifest under the stable per-device OTA name.
if [[ -s "$TARGET/$MANIFEST" ]]; then
  SOURCE_MANIFEST="$TARGET/$MANIFEST"
elif [[ -s "$TARGET/immortalwrt-qualcommax-ipq60xx.manifest" ]]; then
  SOURCE_MANIFEST="$TARGET/immortalwrt-qualcommax-ipq60xx.manifest"
else
  echo "::error::No target package manifest was produced" >&2
  exit 1
fi
cp "$IB_ARCHIVE" "$OUT/"
IB_ARCHIVE="$OUT/$(basename "$IB_ARCHIVE")"
cp "$SDK_ARCHIVE" "$OUT/"
SDK_ARCHIVE="$OUT/$(basename "$SDK_ARCHIVE")"
# An image manifest lists real installed APKs; Kconfig also lists virtual symbols.
# ImageBuilder pins kernel/libc/base-files to its own compatible versions.
awk 'NF >= 2 && $1 ~ /^[a-z0-9][a-z0-9+._-]*$/ &&
     $1 != "kernel" && $1 != "libc" && $1 != "base-files" { print $1 }' \
     "$SOURCE_MANIFEST" | sort -u > "$OUT/imagebuilder-packages.txt"
test -s "$OUT/imagebuilder-packages.txt"
for required in kmod-nss-wifi-drv luci-app-sing-box sing-box \
  luci-app-autoreboot luci-app-cpufreq default-settings-chn autocore \
  luci-app-ddns-go kmod-fs-f2fs; do
  grep -Fxq "$required" "$OUT/imagebuilder-packages.txt" || {
    echo "::error::Built firmware manifest missing $required" >&2
    exit 1
  }
done
# These LuCI apps were intentionally removed; fail rather than publishing
# an image with unexpected upstream/default copies.
for excluded in luci-app-homeproxy luci-i18n-homeproxy-zh-cn \
  luci-app-diskman luci-i18n-diskman-zh-cn \
  luci-app-statistics luci-i18n-statistics-zh-cn; do
  if grep -Fxq "$excluded" "$OUT/imagebuilder-packages.txt"; then
    echo "::error::Built firmware manifest still includes excluded package: $excluded" >&2
    exit 1
  fi
done
# The standalone Builder carries the exact platform.sh used in the full image.
BASE_STAGE="$WORK/base-overlay-for-imagebuilder"
mkdir -p "$BASE_STAGE"
rsync -a "$BUILDER/devices/common/files.ppe-nss/" "$BASE_STAGE/"
install -D -m 0644 "$IMM/files/lib/upgrade/platform.sh" "$BASE_STAGE/lib/upgrade/platform.sh"
tar -czf "$OUT/base-overlay.tar.gz" -C "$BASE_STAGE" .
python3 "$ROOT/scripts/immortalwrt_builder.py" metadata \
  --immortal "$IMM_SHA" --ppe "$PPE_SHA" --base "$BASE_SHA" \
  --feeds "$FEEDS_FINGERPRINT" \
  --archive "$IB_ARCHIVE" --overlay "$OUT/base-overlay.tar.gz" \
  --packages "$OUT/imagebuilder-packages.txt" \
  --output "$OUT/builder-metadata.json"
python3 "$ROOT/scripts/immortalwrt_builder.py" verify \
  --metadata "$OUT/builder-metadata.json" --archive "$IB_ARCHIVE" \
  --overlay "$OUT/base-overlay.tar.gz" \
  --packages "$OUT/imagebuilder-packages.txt"
BUILDER_TAG="$(python3 "$ROOT/scripts/immortalwrt_builder.py" tag \
  --immortal "$IMM_SHA" --ppe "$PPE_SHA" --base "$BASE_SHA" \
  --feeds "$FEEDS_FINGERPRINT")"
# SDK and ImageBuilder are built from exactly the same configured source tree.
python3 "$ROOT/scripts/immortalwrt_sdk.py" metadata \
  --source "$IMM" --ppe-luci "$WORK/ppe-luci" \
  --builder-metadata "$OUT/builder-metadata.json" \
  --toolchain-status "$OUT/official-toolchain-status.txt" \
  --archive "$SDK_ARCHIVE" --feed-lock "$OUT/sdk-feeds.lock.json" \
  --output "$OUT/sdk-metadata.json"
python3 "$ROOT/scripts/immortalwrt_sdk.py" verify \
  --metadata "$OUT/sdk-metadata.json" \
  --builder-metadata "$OUT/builder-metadata.json" \
  --archive "$SDK_ARCHIVE" --feed-lock "$OUT/sdk-feeds.lock.json"
# Exercise the packaged SDK's actual AArch64 cross compiler before publishing.
# This is a tiny SDK-only package; it never enters the router firmware.
bash "$ROOT/scripts/test-sdk-smoke.sh" "$SDK_ARCHIVE" "$WORK/sdk-smoke"
cp "$TARGET/$IMAGE" "$OUT/"
cp "$SOURCE_MANIFEST" "$OUT/$MANIFEST"
cp "$IMM/.config" "$OUT/immortalwrt.config"
(
  cd "$OUT"
  sha256sum "$IMAGE" "$MANIFEST" > sha256sums
)
python3 "$ROOT/scripts/immortalwrt_ota.py" metadata \
  --tag "$TAG" --build "$BUILD_NUMBER" --immortal-commit "$IMM_SHA" \
  --ppe-commit "$PPE_SHA" --image "$OUT/$IMAGE" --manifest "$OUT/$MANIFEST" \
  --output "$OUT/ota.json"

# Rebuild a firmware from the bundled repository before publishing the builder.
SMOKE_BEGIN="$(date +%s)"
echo "::group::Standalone ImageBuilder repack smoke test"
BUILDER_META="$OUT/builder-metadata.json" \
BUILDER_ARCHIVE="$IB_ARCHIVE" \
BASE_OVERLAY="$OUT/base-overlay.tar.gz" \
BUILDER_PACKAGES="$OUT/imagebuilder-packages.txt" \
IMMORTAL_OUT_DIR="$OUT/ib-smoke" \
PUBLISH_RELEASE=false bash "$ROOT/scripts/repack-immortalwrt.sh"
test -s "$OUT/ib-smoke/$IMAGE"
test -s "$OUT/ib-smoke/$MANIFEST"
echo "::endgroup::"
SMOKE_SECONDS=$(( $(date +%s) - SMOKE_BEGIN ))
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    echo "### Build phase timings (seconds)"
    echo "- Preparation + feeds + external cross-toolchain: ${PREP_SECONDS}s"
    echo "- Download: ${DOWNLOAD_SECONDS}s"
    echo "- Host tools, kernel, packages and ImageBuilder: ${COMPILE_SECONDS}s"
    echo "- ImageBuilder smoke repack: ${SMOKE_SECONDS}s"
    echo "- Bootstrap: ${GO_BOOTSTRAP_VERSION}"
    du -sh "${CACHE_GO}" | sed 's/^/- Go cache on disk: /'
  } >> "$GITHUB_STEP_SUMMARY"
fi

# Publish only after a successful full compilation, manifest, and OTA metadata.
# Pull requests produce inspectable Actions artifacts but never update releases.
if [[ "$PUBLISH_RELEASE" == true ]]; then
  [[ "${GITHUB_REPOSITORY:-}" == pzcn/openwrt-ppe-nss-ota ]] || {
    echo "This release channel is reserved for the canonical repository" >&2; exit 1;
  }
  if ! gh release view "$BUILDER_TAG" --repo "$GITHUB_REPOSITORY" >/dev/null 2>&1; then
    gh release create "$BUILDER_TAG" --repo "$GITHUB_REPOSITORY" \
      --latest=false --title "ImmortalWrt PPE+NSS Builder and SDK ($BUILDER_TAG)" \
      --notes "Standalone ImageBuilder and matching OpenWrt SDK for jdcloud_re-ss-01. See sdk-metadata.json and sdk-feeds.lock.json for exact source revision and SHA256." \
      "$IB_ARCHIVE" "$OUT/base-overlay.tar.gz" \
      "$OUT/imagebuilder-packages.txt" "$OUT/builder-metadata.json" \
      "$SDK_ARCHIVE" "$OUT/sdk-metadata.json" "$OUT/sdk-feeds.lock.json" \
      "$OUT/source-commits.txt" "$OUT/official-toolchain-status.txt"
  fi
  cat > "$OUT/release-notes.md" <<EOF
# ImmortalWrt + PPE/NSS + RE-SS-01 customizations

- ImmortalWrt master: $IMM_SHA
- PPE/NSS source: $PPE_SHA
- Customized config: $SOURCE_REV
- Board: JDCloud RE-SS-01 (ipq60xx 512 MiB profile; 1 GiB hardware supported)
- Packages: F2FS/ext4 storage, PPE monitor/QoS, OTA, WireGuard,
  Tailscale, sing-box v0.4.7 LuCI, Aurora, official ImmortalWrt utilities, WOL and LuCI applications.
- Uses the independent \`$TAG\` channel and does not replace OpenWrt Releases/latest.

Experimental full-source build: verify wired PPE, Wi-Fi NSS, storage, and
sysupgrade on the device before enabling unattended OTA.
EOF
  gh release create "$TAG" --repo "$GITHUB_REPOSITORY" --latest=false \
    --title "RE-SS-01 ImmortalWrt PPE+NSS ($BUILD_NUMBER)" \
    --notes-file "$OUT/release-notes.md" \
    "$OUT/$IMAGE" "$OUT/$MANIFEST" "$OUT/ota.json" \
    "$OUT/sha256sums" "$OUT/source-commits.txt" "$OUT/immortalwrt.config"
fi
