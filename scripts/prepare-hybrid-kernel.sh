#!/usr/bin/env bash
# Hybrid P2 preflight: pin official source, port PPE/NSS, and validate the
# minimal kernel profile. Never compiles images or publishes a Builder.
set -Eeuo pipefail
trap 'echo "::error::Hybrid kernel preflight failed at line '"$LINENO"'." >&2' ERR

ROOT="${GITHUB_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
LOCK="${1:?Expected resolved official snapshot-lock.json}"
OUT="${2:-$ROOT/out-hybrid-kernel-preflight}"
WORK="${HYBRID_WORK_DIR:-${RUNNER_TEMP:-/tmp}/immortal-hybrid-kernel}"
IMM="$WORK/immortalwrt"
PPE="$WORK/ppe-nss"
PPE_REF="${PPE_REF:-ppe-nss}"
[[ -s "$LOCK" ]] || { echo "::error::Missing snapshot lock"; exit 1; }
command -v jq >/dev/null
command -v rsync >/dev/null
mkdir -p "$WORK" "$OUT"

# Do not silently fall back to master when official snapshot is incompatible.
jq -e --arg profile "qualcommax/ipq60xx" \
  '.schema == 2 and .target == $profile and
   .status == "resolver-only-not-build-approved" and
   .compatibility.ppe_port_kernel_line_matches == true and
   (.target_commit | test("^[a-f0-9]{40}$"))' "$LOCK" >/dev/null || {
  echo "::error::Official Snapshot kernel does not match PPE/NSS 6.18; refusing preflight." >&2
  exit 1
}
TARGET_COMMIT="$(jq -er '.target_commit' "$LOCK")"
SOURCE_REVISION="$(jq -er '.snapshot_version' "$LOCK")"
test ! -e "$IMM" && test ! -e "$PPE" || {
  echo "::error::Preflight source directory already exists"; exit 1;
}
git init -q "$IMM"
git -C "$IMM" remote add origin https://github.com/immortalwrt/immortalwrt.git
# Pin to published snapshot, which may be weeks behind HEAD.
git -C "$IMM" fetch --quiet --depth=1 --filter=blob:none origin "$TARGET_COMMIT"
git -C "$IMM" -c advice.detachedHead=false checkout --quiet --detach FETCH_HEAD
[[ "$(git -C "$IMM" rev-parse HEAD)" == "$TARGET_COMMIT" ]] || {
  echo "::error::Official source checkout differs from lock"; exit 1;
}
git clone --quiet --depth=1 --single-branch --branch "$PPE_REF" \
  https://github.com/JuliusBairaktaris/openwrt-ppe-nss.git "$PPE"
PPE_SHA="$(git -C "$PPE" rev-parse HEAD)"
[[ "$PPE_SHA" =~ ^[a-f0-9]{40}$ ]] || exit 1

export IMM_SOURCE_DIR="$IMM" PPE_SOURCE_DIR="$PPE"
bash "$ROOT/scripts/port-ppe-nss-to-immortalwrt.sh"
for filename in \
  "$IMM/package/kernel/nss-wifi-drv/Makefile" \
  "$IMM/package/kernel/mac80211/Makefile" \
  "$IMM/target/linux/qualcommax/dts/ipq6000-re-ss-01.dts" \
  "$IMM/target/linux/qualcommax/files/drivers/net/ethernet/qualcomm/qca_ppe_main.c"; do
  test -s "$filename" || {
    echo "::error::PPE/NSS integration file missing: $filename" >&2; exit 1;
  }
done
grep -Fq 'KERNEL_PATCHVER:=6.18' "$IMM/target/linux/qualcommax/Makefile"
# No ALL_KMODS and no selected Go-heavy apps on the kernel-only path.
PROFILE="$ROOT/config/hybrid-kernel-re-ss-01.config"
test -s "$PROFILE"
for required in \
  'CONFIG_TARGET_DEVICE_qualcommax_ipq60xx_DEVICE_jdcloud_re-ss-01=y' \
  'CONFIG_ATH11K_NSS_WIFI=y' 'CONFIG_PACKAGE_kmod-nss-wifi-drv=y' \
  'CONFIG_PACKAGE_kmod-fs-f2fs=y' '# CONFIG_IB is not set' '# CONFIG_SDK is not set'; do
  grep -Fqx "$required" "$PROFILE" || {
    echo "::error::Hybrid kernel config missing: $required" >&2; exit 1;
  }
done
if grep -Eq '^CONFIG_(ALL_KMODS|ALL_NONSHARED|PACKAGE_(sing-box|tailscale|ddns-go))=y$' "$PROFILE"; then
  echo "::error::Hybrid profile selects full build or heavy user-space packages" >&2
  exit 1
fi
cp "$PROFILE" "$IMM/.config"

jq -n --arg snapshot "$SOURCE_REVISION" \
  --arg target_commit "$TARGET_COMMIT" --arg ppe_commit "$PPE_SHA" \
  --arg kernel_profile_sha256 "$(sha256sum "$PROFILE" | cut -d' ' -f1)" \
  --arg snapshot_lock_sha256 "$(sha256sum "$LOCK" | cut -d' ' -f1)" \
  '{schema:1, stage:"source-port-only-no-compile",snapshot:$snapshot,
    immortalwrt_commit:$target_commit,ppe_nss_commit:$ppe_commit,
    kernel_profile_sha256:$kernel_profile_sha256,
    snapshot_lock_sha256:$snapshot_lock_sha256}' > "$OUT/hybrid-kernel-preflight.json"
git -C "$IMM" status --short > "$OUT/ppe-port-changes.txt"
test -s "$OUT/ppe-port-changes.txt"

echo "PPE/NSS source port preflight passed:"
echo "  official snapshot: $SOURCE_REVISION"
echo "  official source:   $TARGET_COMMIT"
echo "  PPE/NSS source:    $PPE_SHA"
echo "  changed paths:     $(wc -l < "$OUT/ppe-port-changes.txt")"
echo "P2 still needs pinned feeds, toolchain, targeted kernel/kmod compile and ABI test."
