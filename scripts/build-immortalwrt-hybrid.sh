#!/usr/bin/env bash
# Hybrid Builder, full mode: compile the PPE/NSS kernel side (kernel, kmods,
# base-files, toolchain libs, custom packages); take every other APK from the
# official ImmortalWrt snapshot; package a standalone ImageBuilder + SDK.
#
#   kernel tree   ImmortalWrt master + PPE/NSS port (same as the full Builder)
#   feeds         pinned to the commits of the official arch package repos
#   toolchain     official snapshot toolchain (same libc/libgcc as userland)
#   userland      official APKs, signed index + per-package signature +
#                 SHA256, mirrored into the IB so it never depends on a
#                 moving URL
#
# When only the userland changes, refresh-hybrid-builder.sh reuses this
# build's output instead (no compilation at all).
#
# Environment: SNAPSHOT_LOCK (required), EXPECTED_*_SHA (optional pins).
set -Eeuo pipefail
trap 'echo "::error::Hybrid Builder failed at line $LINENO: $BASH_COMMAND" >&2' ERR

ROOT="${GITHUB_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
# shellcheck source=hybrid-common.sh
source "$ROOT/scripts/hybrid-common.sh"
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
JOBS="$(nproc)"
mkdir -p "$WORK" "$OUT" "$CACHE_DL" "$CACHE_CCACHE"
: > "$OUT/timings.tsv"
hybrid_check_lock "$LOCK"
TARGET_URL="$(jq -er '.target_url' "$LOCK")"

# A parallel tools build may fail transiently (e.g. source download races).
# Keep the FULL serial diagnostic log, and respect the serial retry's exit code.
phase() {
  local name="$1"; shift
  local begin debug
  begin="$(date +%s)"
  debug="$OUT/$name-serial.log"
  echo "::group::$name"
  if (cd "$IMM" && make -j"$JOBS" "$@"); then
    echo "::endgroup::"
  else
    echo "::endgroup::"
    echo "::warning::Phase '$name' failed in parallel; retrying serially with V=sc (log: $debug)" >&2
    if (cd "$IMM" && make -j1 V=sc "$@") > "$debug" 2>&1; then
      echo "::notice::Phase '$name' succeeded on serial retry; continuing." >&2
    else
      echo "::error::Phase '$name' failed again; full serial log saved: $debug" >&2
      echo "::group::First useful errors in $name"
      grep -nEi 'error:|fatal:|failed to|could not|cannot|no such file|curl:|Error [0-9]+' "$debug" | head -n 65 || true
      echo "::endgroup::"
      echo "::group::Last 140 lines from $name"
      tail -n 140 "$debug" || true
      echo "::endgroup::"
      exit 1
    fi
  fi
  printf '%s\t%s\n' "$name" "$(( $(date +%s) - begin ))" >> "$OUT/timings.tsv"
}
mark() { printf '%s\t%s\n' "$1" "$(( $(date +%s) - $2 ))" >> "$OUT/timings.tsv"; }

# Fetch exactly one commit (a pin from the resolve job, else the branch head).
# Works in a directory that already holds restored build caches.
checkout() {  # url branch sha dest
  local url="$1" branch="$2" sha="$3" dest="$4"
  mkdir -p "$dest"
  git init -q "$dest"
  git -C "$dest" remote add origin "$url"
  if [[ -n "$sha" ]]; then
    [[ "$sha" =~ ^[0-9a-f]{40}$ ]] || { echo "::error::Bad pin for $url" >&2; exit 1; }
    git -C "$dest" fetch -q --depth 1 origin "$sha"
  else
    git -C "$dest" fetch -q --depth 1 origin "refs/heads/$branch"
  fi
  git -C "$dest" -c advice.detachedHead=false checkout -q --detach FETCH_HEAD
  git -C "$dest" rev-parse HEAD
}
head_of() {
  local sha
  sha="$(git ls-remote "$1" "refs/heads/$2" | awk '{print $1}')"
  [[ "$sha" =~ ^[0-9a-f]{40}$ ]] || { echo "::error::Cannot resolve $1 $2" >&2; exit 1; }
  printf '%s\n' "$sha"
}

T0="$(date +%s)"
BUILT_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
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

KERNEL_IDENTITY="$("${HB[@]}" kernel-identity --lock "$LOCK" --ppe "$PPE_SHA" --base "$BASE_SHA" \
  --nss "$NSS_SHA" --ppe-luci "$PPE_LUCI_SHA")"
IDENTITY="$("${HB[@]}" identity --lock "$LOCK" --ppe "$PPE_SHA" --base "$BASE_SHA" \
  --nss "$NSS_SHA" --ppe-luci "$PPE_LUCI_SHA" \
  --packages "$(python3 "$ROOT/scripts/immortalwrt_builder.py" package-fingerprint)")"

for name in dl .ccache; do
  [[ ! -e "$IMM/$name" ]] || { echo "::error::Unexpected $name in clone" >&2; exit 1; }
done
ln -s "$CACHE_DL" "$IMM/dl"
ln -s "$CACHE_CCACHE" "$IMM/.ccache"
export CCACHE_DIR="$CACHE_CCACHE"
ccache --max-size 3G >/dev/null
ccache --zero-stats >/dev/null

# Cached host tools (restored by the workflow into staging_dir/build_dir):
# make tools/ mtimes content-derived so their stamps stay valid, and drop the
# top-level stamps so make re-checks every tool against its own stamp.
"${HB[@]}" normalize-mtimes --repo "$IMM" --path tools
rm -f "$IMM"/staging_dir/host/stamp/.tools_* 2>/dev/null || true
if [[ -d "$IMM/staging_dir/host/bin" ]]; then
  echo "Reusing cached host tools: $(du -sh "$IMM/staging_dir/host" "$IMM/build_dir/host" 2>/dev/null | awk '{print $1}' | paste -sd/)"
fi

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
[[ "$FEEDS_FINGERPRINT" == "$("${HB[@]}" fingerprint feeds --lock "$LOCK" --nss "$NSS_SHA" --ppe-luci "$PPE_LUCI_SHA")" ]] || {
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
# The original LZO download host previously stalled this build. Preseed the
# pinned archive (name/hash from tools/liblzo) from OpenWrt mirrors before make.
bash "$ROOT/scripts/hybrid-prefetch-host-sources.sh" "$IMM" "$CACHE_DL"
phase tools tools/install
# Device FITs use the mkimage compiled by OpenWrt tools/mkimage.
# Check for it here, before the longer kernel and package build phases.
HOST_MKIMAGE="$IMM/staging_dir/host/bin/mkimage"
[[ -x "$HOST_MKIMAGE" ]] || {
  echo "::error::tools/install did not provide the host mkimage binary: $HOST_MKIMAGE" >&2
  exit 1
}
phase toolchain toolchain/install
phase apk-host package/system/apk/host/compile
APK="$IMM/staging_dir/host/bin/apk"
test -x "$APK"

# ---------------------------------------------------------------------------
# 5. Official indexes and the userland closure — before the long compile
# ---------------------------------------------------------------------------
T1="$(date +%s)"
KEYS="$WORK/official-keys"
KEYRING_SHA="$(sed -n 's/^PKG_SOURCE_VERSION:=\([0-9a-f]\{40\}\)$/\1/p' package/system/openwrt-keyring/Makefile)"
hybrid_official_keys "$KEYRING_SHA" "$KEYS" "$WORK"
hybrid_official_indexes "$LOCK" "$APK" "$KEYS" "$WORK/official-indexes"
: > "$WORK/extra-local.txt"
for attempt in 1 2; do
  "${HB[@]}" plan --packageinfo tmp/.packageinfo --config .config \
    --extra-local "$WORK/extra-local.txt" --output "$OUT/local-plan.json"
  "${HB[@]}" closure --plan "$OUT/local-plan.json" --lock "$LOCK" "${HYBRID_INDEX_ARGS[@]}" \
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
# NO_DEPS: scripts/LuCI/base files; their userland dependencies come from the
# official repositories and must not be rebuilt here.
phase local-userland NO_DEPS=1 "${USER_TARGETS[@]}"

PKG_DIR="$(make -s val.PACKAGE_DIR | tail -n1)"
[[ "$PKG_DIR" == "$IMM/bin/targets/qualcommax/ipq60xx/packages" ]]
not_built=()
while IFS= read -r name; do
  [[ -n "$(find "$IMM/bin" -type f -name "$name-[0-9]*.apk" -print -quit)" ]] || not_built+=("$name")
done < <(jq -r '.local_packages[].apk_name' "$OUT/local-plan.json")
(( ${#not_built[@]} == 0 )) || { echo "::error::Not built locally: ${not_built[*]}" >&2; exit 1; }
# Dependencies built on the way (master-ABI libraries etc.) must not reach the
# ImageBuilder, which copies every APK under bin/: the official build of the
# same library is the one the image uses.
"${HB[@]}" prune-local --plan "$OUT/local-plan.json" --dir "$IMM/bin" | tee "$OUT/pruned-local.txt" | tail -n1
find "$IMM/bin" -type f -name '*.apk' -printf '%f\n' | sort > "$OUT/local-apks.txt"

# ---------------------------------------------------------------------------
# 7. Mirror the official userland into the standalone ImageBuilder repository
# ---------------------------------------------------------------------------
T2="$(date +%s)"
hybrid_mirror "$OUT/official-apks.json" "$PKG_DIR" "$APK" "$KEYS" "$WORK" "$IMM/bin"
mark official-mirror "$T2"
# ImageBuilder ships the staging rootfs keyring; no package/install ran here.
STAGING_ROOT="$(make -s val.STAGING_DIR_ROOT | tail -n1)"
[[ "$STAGING_ROOT" == "$IMM"/staging_dir/* ]]
mkdir -p "$STAGING_ROOT/etc/apk/keys"
cp "$IMM/public-key.pem" "$KEYS/"*.pem "$STAGING_ROOT/etc/apk/keys/"

# ---------------------------------------------------------------------------
# 8. Device kernel FIT -> standalone ImageBuilder + SDK
# ---------------------------------------------------------------------------
# ImageBuilder only copies existing $(KERNEL_BUILD_DIR)/* files. target/compile
# builds the raw kernel but does NOT install the per-device FIT (uImage.itb).
# Build the RE-SS-01 FIT from THIS kernel + DTS before packaging the IB.
mapfile -t fit_dirs < <(find "$IMM/build_dir" -mindepth 2 -maxdepth 2 -type d \
  -name linux-qualcommax_ipq60xx -print | sort)
(( ${#fit_dirs[@]} == 1 )) || {
  echo "::error::Expected one qualcommax/ipq60xx kernel build directory, got ${#fit_dirs[@]}" >&2
  exit 1
}
# target/compile completes modules, but only the kernel .image target invokes
# Kernel/CompileImage and copies the raw Image into KERNEL_BUILD_DIR.
# Do not run target/linux/install here: that also runs full image/rootfs logic.
KDIR="${fit_dirs[0]}"
# Select the current kernel version from ImmortalWrt make, not a linux-* glob.
# Multiple source directories may legitimately coexist in the build tree.
LINUX_SRC="$(make -s -C "$IMM/target/linux/qualcommax" \
  "TOPDIR=$IMM" "TARGET_BUILD=1" val.LINUX_DIR)"
[[ "$LINUX_SRC" == "$KDIR"/linux-* && -d "$LINUX_SRC" ]] || {
  echo "::error::Configured LINUX_DIR is not inside RE-SS-01 kernel build tree: $LINUX_SRC" >&2
  find "$KDIR" -mindepth 1 -maxdepth 1 -type d -name "linux-*" -print >&2 || true
  exit 1
}
[[ -s "$LINUX_SRC/vmlinux" ]] || {
  echo "::error::Kernel modules phase did not produce vmlinux: $LINUX_SRC" >&2
  exit 1
}
phase kernel-image -C target/linux/qualcommax "TOPDIR=$IMM" "TARGET_BUILD=1" "$LINUX_SRC/.image"
[[ -s "$KDIR/Image" ]] || {
  echo "::error::Kernel/CompileImage did not copy Image into $KDIR" >&2
  exit 1
}
FIT="$KDIR/jdcloud_re-ss-01-uImage.itb"
# The direct image Makefile bypasses top-level Make's host-tools PATH setup.
# Its FIT rule invokes bare mkimage; use the matching OpenWrt host binary.
PATH="$IMM/staging_dir/host/bin:$PATH" phase device-fit -C target/linux/qualcommax/image "TOPDIR=$IMM" "$FIT"
[[ -s "$FIT" && ! -L "$FIT" ]] || {
  echo "::error::RE-SS-01 FIT was not generated from the locally compiled kernel: $FIT" >&2
  exit 1
}
(( $(stat -c %s "$FIT") <= 6144 * 1024 )) || {
  echo "::error::RE-SS-01 FIT exceeds its 6144 KiB kernel partition" >&2
  exit 1
}
if ! fdtget -l "$FIT" /configurations | tr "[:space:]" "\n" | grep -Fxq "config@cp03-c2"; then
  echo "::error::RE-SS-01 FIT lacks the required config@cp03-c2 boot configuration" >&2
  exit 1
fi
printf "RE-SS-01 FIT: %s (%s bytes)\n" "$FIT" "$(stat -c %s "$FIT")"
phase imagebuilder NO_DEPS=1 target/imagebuilder/install
phase sdk NO_DEPS=1 target/sdk/install
TARGET_BIN="$IMM/bin/targets/qualcommax/ipq60xx"
IB_ARCHIVE="$(find "$TARGET_BIN" -maxdepth 1 -type f -name '*imagebuilder*.tar.zst' -print -quit)"
SDK_ARCHIVE="$(find "$TARGET_BIN" -maxdepth 1 -type f -name 'immortalwrt-sdk-*.tar.zst' -print -quit)"
test -s "$IB_ARCHIVE" && test -s "$SDK_ARCHIVE"
cp "$IB_ARCHIVE" "$SDK_ARCHIVE" "$OUT/"
IB_ARCHIVE="$OUT/$(basename "$IB_ARCHIVE")"
SDK_ARCHIVE="$OUT/$(basename "$SDK_ARCHIVE")"
# Ensure the releasable ImageBuilder actually contains the exact device FIT
# we generated, rather than merely succeeding at package installation.
FIT_REL="${FIT#"$IMM"/}"
IB_TOP="$(basename "$IB_ARCHIVE" .tar.zst)"
tar -I zstd -tf "$IB_ARCHIVE" > "$WORK/ib-archive-contents.txt"
if ! grep -Fxq "$IB_TOP/$FIT_REL" "$WORK/ib-archive-contents.txt"; then
  echo "::error::ImageBuilder archive omitted $FIT_REL" >&2
  exit 1
fi
(( $(stat -c '%s' "$SDK_ARCHIVE") < 2147483648 ))
hybrid_check_archive_keys "$IB_ARCHIVE"
tar -I zstd -tf "$SDK_ARCHIVE" > "$WORK/sdk-contents.txt"
for required in '^[^/]+/rules[.]mk$' '^[^/]+/include/kernel[.]mk$' \
  '^[^/]+/staging_dir/toolchain-[^/]+/bin/' \
  '^[^/]+/build_dir/target-[^/]+/linux-[^/]+/linux-[^/]+/Module[.]symvers$'; do
  grep -Eq "$required" "$WORK/sdk-contents.txt" || { echo "::error::SDK lacks $required" >&2; exit 1; }
done
refuse 'SDK still contains HomeProxy' \
  grep -Eiq '(^|/)(luci-app-homeproxy|luci-i18n-homeproxy-zh-cn)(/|$)' "$WORK/sdk-contents.txt"

T3="$(date +%s)"
IB_TEST="$WORK/ib-manifest"
mkdir -p "$IB_TEST"
tar -I zstd -xf "$IB_ARCHIVE" -C "$IB_TEST"
IB_DIR="$(find "$IB_TEST" -mindepth 1 -maxdepth 1 -type d -name '*imagebuilder*' -print -quit)"
[[ -s "$IB_DIR/$FIT_REL" ]] && cmp -s "$FIT" "$IB_DIR/$FIT_REL" || {
  echo "::error::Unpacked ImageBuilder FIT differs from locally generated RE-SS-01 FIT" >&2
  exit 1
}
hybrid_ib_manifest "$IB_DIR" "$OUT" "$OUT/local-apks.txt"
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
hybrid_info "$WORK/hybrid-info.json" "$IDENTITY" "$KERNEL_IDENTITY" "$BUILT_AT" "" "$KEYRING_SHA"
python3 scripts/immortalwrt_builder.py metadata --mode hybrid --snapshot-lock "$LOCK" \
  --hybrid-info "$WORK/hybrid-info.json" \
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
ccache --show-stats > "$OUT/ccache-stats.txt" || true
mark total "$T0"
hybrid_summary "$OUT" "Hybrid Builder (full build)"
echo "Hybrid Builder ready: $(jq -r .tag "$OUT/builder-metadata.json")"
