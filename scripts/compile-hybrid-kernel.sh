#!/usr/bin/env bash
# P2: compile only the custom kernel, NSS/PPE and ABI-matched modules.
# Official userland reuse and matching SDK/ImageBuilder production are P3.
set -Eeuo pipefail
trap 'echo "::error::Hybrid kernel compile failed at line $LINENO" >&2' ERR

ROOT="${GITHUB_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
WORK="${HYBRID_WORK_DIR:-${RUNNER_TEMP:-/tmp}/immortal-hybrid-kernel}"
IMM="$WORK/immortalwrt"
OUT="${HYBRID_OUT_DIR:-$ROOT/out-hybrid-kernel-test}"
CACHE_ROOT="${IMMORTAL_CACHE_ROOT:-$ROOT/.build-cache}"

phase() {
  local key="$1"
  shift
  local begin
  begin="$(date +%s)"
  local -a make_args
  make_args=("-j$(nproc)")
  # A top-level OpenWrt make without V=s or V=sc only reports the
  # generic 'target/linux failed to build' wrapper. Always preserve
  # inner compiler/patch output for the critical kernel phase.
  if [[ "$key" == "linux-target" ]]; then
    make_args+=("V=sc")
  fi
  echo "::group::Hybrid selective phase: $key"
  echo "make ${make_args[*]} $*"
  if (cd "$IMM" && make "${make_args[@]}" "$@") > "$OUT/$key.log" 2>&1; then
    tail -n 12 "$OUT/$key.log"
    printf '%s\n' "$(( $(date +%s) - begin ))" > "$OUT/$key.seconds"
    echo "::endgroup::"
    return 0
  fi

  # The initial failure can be in an internal parallel worker and lost
  # among the last lines. Extract high-signal diagnostics before exit.
  echo "::error::Phase '$key' failed. Detailed log: $OUT/$key.log" >&2
  echo "::group::Failure diagnostics: $key"
  grep -Ein 'error:|fatal:|patch failed|failed hunk|hunk #[0-9]+ failed|rejected|no rule to make target|undefined reference|module.symvers|cannot find|no such file'     "$OUT/$key.log" | tail -n 100 >&2 || true
  tail -n 130 "$OUT/$key.log" >&2
  echo "::endgroup::"

  # If the kernel failure remains opaque, force OpenWrt's documented
  # serial-verbose diagnosis. Keep the first failure as failure; never
  # silently publish a one-off successful retry.
  if [[ "$key" == "linux-target" ]] &&
     ! grep -Eiq 'error:|fatal:|patch failed|hunk #[0-9]+ failed|undefined reference|no rule to make target' "$OUT/$key.log"; then
    echo "::group::Serial verbose kernel diagnostic (-j1 V=sc)"
    (cd "$IMM" && make -j1 V=sc "$@")       > "$OUT/$key.serial-verbose.log" 2>&1 || true
    grep -Ein 'error:|fatal:|patch failed|failed hunk|hunk #[0-9]+ failed|rejected|no rule to make target|undefined reference|module.symvers'       "$OUT/$key.serial-verbose.log" | tail -n 90 >&2 || true
    tail -n 180 "$OUT/$key.serial-verbose.log" >&2
    echo "::endgroup::"
  fi
  printf '%s\n' "$(( $(date +%s) - begin ))" > "$OUT/$key.failed.seconds"
  exit 1
}
# A lightweight executable control-flow check used by CI. It must reach
# this function *as code*, not accidentally swallow it in a quoted regex.
if [[ "${1:-}" == "--self-test" ]]; then
  [[ "$(type -t phase)" == function ]] || exit 1
  [[ "${BASH_SOURCE[0]}" == *compile-hybrid-kernel.sh ]]
  echo "PASS hybrid compile control flow: phase() available"
  exit 0
fi

LOCK="${1:?Pass snapshot-lock.json}"
LOCK="$(realpath "$LOCK")"
OUT="${2:-$OUT}"
mkdir -p "$OUT" "$CACHE_ROOT/dl" "$CACHE_ROOT/ccache"
[[ -s "$LOCK" && -s "$IMM/.config" && -s "$IMM/feeds.conf" ]] || {
  echo "::error::Prepare and configure the pinned hybrid source before compiling." >&2
  exit 1
}
# Reuse source archives and compiler objects, never build_dir/staging_dir kernel state.
for name in dl .ccache; do
  target="$CACHE_ROOT/$name"
  [[ "$name" == .ccache ]] && target="$CACHE_ROOT/ccache"
  if [[ -d "$IMM/$name" && ! -L "$IMM/$name" ]]; then
    rsync -a "$IMM/$name/" "$target/"
    rm -rf "$IMM/$name"
  fi
  if [[ ! -L "$IMM/$name" ]]; then
    ln -s "$target" "$IMM/$name"
  fi
done
export CCACHE_DIR="$CACHE_ROOT/ccache"
ccache --max-size 1600M

# Pin and import the official cross toolchain from this exact Snapshot.
export IMM_OFFICIAL_SNAPSHOT_LOCK="$LOCK"
export IMM_USE_OFFICIAL_TOOLCHAIN=required
export IMM_HYBRID_KERNEL_ONLY=1
(
  cd "$IMM"
  bash "$ROOT/scripts/reuse-official-toolchain.sh" \
    "$IMM" "$CACHE_ROOT/dl" "$OUT/official-toolchain-status.txt"
  make defconfig > "$OUT/final-defconfig.log" 2>&1
)
grep -Fxq 'toolchain=official-immortalwrt' \
  "$OUT/official-toolchain-status.txt" || {
    echo "::error::The pinned official toolchain was not reused" >&2
    exit 1
  }
for required in \
  'CONFIG_ATH11K_NSS_WIFI=y' \
  'CONFIG_PACKAGE_kmod-nss-wifi-drv=y' \
  'CONFIG_PACKAGE_kmod-fs-f2fs=y' \
  'CONFIG_PACKAGE_kmod-wireguard=y' \
  'CONFIG_PACKAGE_kmod-sched-core=y'; do
  grep -Fqx "$required" "$IMM/.config" || {
    echo "::error::External toolchain defconfig dropped $required" >&2
    exit 1
  }
done
# Critically, SDK and IB must remain OFF for this isolated kernel build.
if grep -Eq '^CONFIG_(IB|IB_STANDALONE|SDK|BUILD_ALL_HOST_TOOLS)=y$' \
  "$IMM/.config"; then
  echo "::error::SDK/IB or ALL_HOST_TOOLS unexpectedly enabled in P2" >&2
  exit 1
fi
if grep -Eq '^CONFIG_(ALL_KMODS|ALL_NONSHARED|PACKAGE_(sing-box|tailscale|ddns-go))=y$' \
  "$IMM/.config"; then
  echo "::error::Heavy userspace selection or ALL_KMODS enabled in P2" >&2
  exit 1
fi

# Do not waste minutes on the upstream LZO source host; this is content-pinned.
bash "$ROOT/scripts/hybrid-prefetch-host-sources.sh" "$CACHE_ROOT/dl"
phase download download
phase host-tools tools/install
phase toolchain toolchain/install
phase linux-target target/linux/compile
phase kernel-packages package/kernel/linux/compile
phase mac80211 package/kernel/mac80211/compile
phase nss-wifi package/kernel/nss-wifi-drv/compile
phase qca-ppe-qos package/network/config/qca-ppe-qos/compile
phase ppe-help package/utils/ppe-help/compile

# No firmware/SDK/IB release. Require a real built kernel and NSS APK.
[[ -d "$IMM/build_dir" ]] || {
  echo "::error::Kernel build_dir missing after compilation" >&2
  exit 1
}
VMLINUX="$(find "$IMM/build_dir" -type f -name vmlinux -print -quit)"
[[ -n "$VMLINUX" && -s "$VMLINUX" ]] || {
  echo "::error::No compiled vmlinux found after kernel build" >&2
  exit 1
}
[[ -d "$IMM/bin" ]] || {
  echo "::error::No package output directory after targeted build" >&2
  exit 1
}
find "$IMM/bin" -type f -name '*.apk' -printf '%P\n' | sort \
  > "$OUT/compiled-apks.txt"
test -s "$OUT/compiled-apks.txt"
grep -q 'kmod-nss-wifi-drv-' "$OUT/compiled-apks.txt" || {
  echo "::error::NSS Wi-Fi kmod APK was not produced" >&2
  exit 1
}

jq -n --arg snapshot "$(jq -er .snapshot_version "$LOCK")" \
  --arg snapshot_lock "$(jq -er .lock_fingerprint "$LOCK")" \
  --arg toolchain_sha "$(jq -er .assets.toolchain.sha256 "$LOCK")" \
  --arg kernel_sha "$(sha256sum "$VMLINUX" | cut -d' ' -f1)" \
  '{schema:1,status:"test-only-no-imagebuilder-or-firmware",
    snapshot:$snapshot,lock_fingerprint:$snapshot_lock,
    toolchain_sha256:$toolchain_sha,compiled_kernel_sha256:$kernel_sha}' \
  > "$OUT/compile-metadata.json"
cp "$IMM/.config" "$OUT/selected-build-config"
ccache --show-stats > "$OUT/ccache-stats.txt" || true
echo "Hybrid kernel and selected PPE/NSS modules compiled. NOT a flashable image."
