#!/usr/bin/env bash
# P2 test: compile ONLY customized kernel and selected PPE/NSS modules.
# The official architecture APK reuse and Builder/SDK release belong to P3.
set -Eeuo pipefail
trap 'echo "::error::Hybrid selective compilation failed at line '"$LINENO"'." >&2' ERR

ROOT="${GITHUB_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
LOCK="${1:?Expected snapshot-lock.json}"
LOCK="$(realpath "$LOCK")"
WORK="${HYBRID_WORK_DIR:-${RUNNER_TEMP:-/tmp}/immortal-hybrid-kernel}"
IMM="$WORK/immortalwrt"
OUT="${2:-$ROOT/out-hybrid-kernel-test}"
CACHE_ROOT="${IMMORTAL_CACHE_ROOT:-$ROOT/.build-cache}"
mkdir -p "$OUT" "$CACHE_ROOT/dl" "$CACHE_ROOT/ccache"
[[ -s "$LOCK" && -s "$IMM/.config" && -s "$IMM/feeds.conf" ]] || {
  echo "::error::Prepare and configure the pinned hybrid source before compiling." >&2
  exit 1
}
# Reuse archive and compiler caches; never inject old ABI-specific kernel trees.
for name in dl .ccache; do
  target="$CACHE_ROOT/$name"
  [[ "$name" == .ccache ]] && target="$CACHE_ROOT/ccache"
  if [[ -d "$IMM/$name" && ! -L "$IMM/$name" ]]; then
    rsync -a "$IMM/$name/" "$target/"
    rm -rf "$IMM/$name"
  fi
  if [[ ! -L "$IMM/$name" ]]; then ln -s "$target" "$IMM/$name"; fi
done
export CCACHE_DIR="$CACHE_ROOT/ccache"
ccache --max-size 1600M
# Must use SHA256 of *this* Snapshot, not the older hardcoded SHA.
export IMM_OFFICIAL_SNAPSHOT_LOCK="$LOCK"
export IMM_USE_OFFICIAL_TOOLCHAIN=required
export IMM_HYBRID_KERNEL_ONLY=1
(
  cd "$IMM"
  bash "$ROOT/scripts/reuse-official-toolchain.sh" \
    "$IMM" "$CACHE_ROOT/dl" "$OUT/official-toolchain-status.txt"
  make defconfig > "$OUT/final-defconfig.log" 2>&1
)
grep -Fxq 'toolchain=official-immortalwrt' "$OUT/official-toolchain-status.txt" || {
  echo "::error::Official toolchain was not reused"; exit 1;
}
for required in \
  'CONFIG_ATH11K_NSS_WIFI=y' \
  'CONFIG_PACKAGE_kmod-nss-wifi-drv=y' \
  'CONFIG_PACKAGE_kmod-fs-f2fs=y'; do
  grep -Fqx "$required" "$IMM/.config" || {
    echo "::error::External toolchain defconfig removed $required"; exit 1;
  }
done
# This stage must not trigger extra SDK-only tools such as lzop/liblzo.
if grep -Eq '^CONFIG_(IB|IB_STANDALONE|SDK|BUILD_ALL_HOST_TOOLS)=y
  echo "::error::Unexpected heavy user-space selection"; exit 1;
fi

phase() {
  local key="$1"; shift
  local begin="$(date +%s)"
  echo "::group::Hybrid selective phase: $key"
  echo "make -j$(nproc) $*"
  if ! (cd "$IMM" && make -j"$(nproc)" "$@") > "$OUT/$key.log" 2>&1; then
    tail -n 200 "$OUT/$key.log" >&2
    echo "::error::See $OUT/$key.log for the complete build failure" >&2
    exit 1
  fi
  tail -n 12 "$OUT/$key.log"
  printf '%s\n' "$(( $(date +%s) - begin ))" > "$OUT/$key.seconds"
  echo "::endgroup::"
}
# A 2026-11-13 run spent 13 minutes in tools/liblzo without a
# successful archive. Download verified upstream source via OpenWrt's
# mirrors first; keep running normal host build, without spoofing stamps.
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

# No publishing or flashing. Require actual compiled kernel and relevant APKs.
VMLINUX="$(find "$IMM/build_dir" -type f -name vmlinux -print -quit)"
[[ -n "$VMLINUX" && -s "$VMLINUX" ]] || {
  echo "::error::No compiled vmlinux found"; exit 1;
}
find "$IMM/bin" -type f -name '*.apk' -printf '%P\n' | sort \
  > "$OUT/compiled-apks.txt"
test -s "$OUT/compiled-apks.txt"
if ! grep -q 'kmod-nss-wifi-drv-' "$OUT/compiled-apks.txt"; then
  echo "::error::No NSS Wi-Fi kmod APK produced"; exit 1;
fi

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
echo "Hybrid kernel + selected PPE/NSS modules compiled. NOT a flashable image."
 "$IMM/.config"; then
  echo "::error::SDK/IB is enabled in P2 kernel-only stage" >&2
  exit 1
fi
if grep -Eq '^CONFIG_(ALL_KMODS|ALL_NONSHARED|PACKAGE_(sing-box|tailscale|ddns-go))=y
  echo "::error::Unexpected heavy user-space selection"; exit 1;
fi

phase() {
  local key="$1"; shift
  local begin="$(date +%s)"
  echo "::group::Hybrid selective phase: $key"
  echo "make -j$(nproc) $*"
  if ! (cd "$IMM" && make -j"$(nproc)" "$@") > "$OUT/$key.log" 2>&1; then
    tail -n 200 "$OUT/$key.log" >&2
    echo "::error::See $OUT/$key.log for the complete build failure" >&2
    exit 1
  fi
  tail -n 12 "$OUT/$key.log"
  printf '%s\n' "$(( $(date +%s) - begin ))" > "$OUT/$key.seconds"
  echo "::endgroup::"
}
# A 2026-11-13 run spent 13 minutes in tools/liblzo without a
# successful archive. Download verified upstream source via OpenWrt's
# mirrors first; keep running normal host build, without spoofing stamps.
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

# No publishing or flashing. Require actual compiled kernel and relevant APKs.
VMLINUX="$(find "$IMM/build_dir" -type f -name vmlinux -print -quit)"
[[ -n "$VMLINUX" && -s "$VMLINUX" ]] || {
  echo "::error::No compiled vmlinux found"; exit 1;
}
find "$IMM/bin" -type f -name '*.apk' -printf '%P\n' | sort \
  > "$OUT/compiled-apks.txt"
test -s "$OUT/compiled-apks.txt"
if ! grep -q 'kmod-nss-wifi-drv-' "$OUT/compiled-apks.txt"; then
  echo "::error::No NSS Wi-Fi kmod APK produced"; exit 1;
fi

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
echo "Hybrid kernel + selected PPE/NSS modules compiled. NOT a flashable image."
 "$IMM/.config"; then
  echo "::error::Unexpected heavy user-space selection"; exit 1;
fi

phase() {
  local key="$1"; shift
  local begin="$(date +%s)"
  echo "::group::Hybrid selective phase: $key"
  echo "make -j$(nproc) $*"
  if ! (cd "$IMM" && make -j"$(nproc)" "$@") > "$OUT/$key.log" 2>&1; then
    tail -n 200 "$OUT/$key.log" >&2
    echo "::error::See $OUT/$key.log for the complete build failure" >&2
    exit 1
  fi
  tail -n 12 "$OUT/$key.log"
  printf '%s\n' "$(( $(date +%s) - begin ))" > "$OUT/$key.seconds"
  echo "::endgroup::"
}
# A 2026-11-13 run spent 13 minutes in tools/liblzo without a
# successful archive. Download verified upstream source via OpenWrt's
# mirrors first; keep running normal host build, without spoofing stamps.
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

# No publishing or flashing. Require actual compiled kernel and relevant APKs.
VMLINUX="$(find "$IMM/build_dir" -type f -name vmlinux -print -quit)"
[[ -n "$VMLINUX" && -s "$VMLINUX" ]] || {
  echo "::error::No compiled vmlinux found"; exit 1;
}
find "$IMM/bin" -type f -name '*.apk' -printf '%P\n' | sort \
  > "$OUT/compiled-apks.txt"
test -s "$OUT/compiled-apks.txt"
if ! grep -q 'kmod-nss-wifi-drv-' "$OUT/compiled-apks.txt"; then
  echo "::error::No NSS Wi-Fi kmod APK produced"; exit 1;
fi

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
echo "Hybrid kernel + selected PPE/NSS modules compiled. NOT a flashable image."
