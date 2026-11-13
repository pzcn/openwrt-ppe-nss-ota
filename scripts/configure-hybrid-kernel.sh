#!/usr/bin/env bash
# P2 validation: resolve only the official source feed commits, then
# verify Kconfig preserves the small RE-SS-01 PPE/NSS kernel selection.
set -Eeuo pipefail
trap 'echo "::error::Hybrid Kconfig preflight failed at line '"$LINENO"'." >&2' ERR

ROOT="${GITHUB_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
LOCK="${1:?Expected official snapshot-lock.json}"
WORK="${HYBRID_WORK_DIR:-${RUNNER_TEMP:-/tmp}/immortal-hybrid-kernel}"
IMM="$WORK/immortalwrt"
OUT="${2:-$ROOT/out-hybrid-kernel-preflight}"
[[ -f "$IMM/package/kernel/nss-wifi-drv/Makefile" ]] || {
  echo "::error::Run prepare-hybrid-kernel.sh before configure"; exit 1;
}
[[ -s "$LOCK" ]] || exit 1
mkdir -p "$OUT"

jq -r '.target_feeds | to_entries[] | [.key,.value.url,.value.commit] | @tsv' "$LOCK" |
while IFS=$'\t' read -r feed url commit; do
  [[ "$feed" =~ ^[a-zA-Z0-9_-]+$ ]] || exit 1
  [[ "$url" == https://github.com/* && "$url" == *.git ]] || exit 1
  [[ "$commit" =~ ^[a-f0-9]{40}$ ]] || exit 1
  printf 'src-git %s %s^%s\n' "$feed" "$url" "$commit"
done > "$IMM/feeds.conf"
# NSS package feed is an external source not present in official builds.
# Resolve its branch once and freeze its actual full SHA for this job.
NSS_BRANCH_SHA="$(git ls-remote https://github.com/JuliusBairaktaris/nss-packages.git refs/heads/ppe-nss | awk '{print $1}')"
[[ "$NSS_BRANCH_SHA" =~ ^[a-f0-9]{40}$ ]] || {
  echo "::error::Cannot resolve a reproducible NSS feed SHA"; exit 1;
}
printf 'src-git nss https://github.com/JuliusBairaktaris/nss-packages.git^%s\n' \
  "$NSS_BRANCH_SHA" >> "$IMM/feeds.conf"
# Minimize only the known broken optional feed packages from the full builder.
(
  cd "$IMM"
  ./scripts/feeds update -a
  rm -rf feeds/packages/net/fwknop \
         feeds/packages/sound/squeezelite \
         feeds/luci/applications/luci-app-fwknopd
  ./scripts/feeds update -i packages
  ./scripts/feeds update -i luci
  ./scripts/feeds install -a
  make defconfig > "$OUT/defconfig.log" 2>&1 || {
    tail -n 100 "$OUT/defconfig.log"; exit 1;
  }
  if grep -Fq 'error: recursive dependency detected!' "$OUT/defconfig.log"; then
    tail -n 100 "$OUT/defconfig.log"
    echo "::error::Recursive Kconfig dependency detected" >&2
    exit 1
  fi
)
for required in \
  'CONFIG_TARGET_DEVICE_qualcommax_ipq60xx_DEVICE_jdcloud_re-ss-01=y' \
  'CONFIG_ATH11K_NSS_WIFI=y' \
  'CONFIG_PACKAGE_kmod-nss-wifi-drv=y' \
  'CONFIG_PACKAGE_kmod-fs-f2fs=y' \
  'CONFIG_IB=y' 'CONFIG_IB_STANDALONE=y' 'CONFIG_SDK=y'; do
  grep -Fqx "$required" "$IMM/.config" || {
    echo "::error::Kconfig dropped required selection: $required" >&2
    grep -E '^(CONFIG_(TARGET_DEVICE|ATH11K|PACKAGE_kmod-nss|IB|SDK))' "$IMM/.config" | head -n 70 || true
    exit 1
  }
done
# A real binary-index audit identified these additional target-owned modules.
# No official kmod APK is ever eligible for the Hybrid Builder.
for module in kmod-ifb kmod-inet-diag kmod-netlink-diag \
  kmod-nf-conntrack-netlink kmod-nft-core kmod-nft-nat kmod-sched-cake; do
  grep -Fqx "CONFIG_PACKAGE_${module}=y" "$IMM/.config" || {
    echo "::error::Kconfig omitted closure-required local module: $module" >&2
    exit 1
  }
done
if grep -Eq '^CONFIG_(ALL_KMODS|ALL_NONSHARED|PACKAGE_(sing-box|tailscale|ddns-go))=y
  echo "::error::Heavy userland packages or ALL_KMODS forced into kernel selection" >&2
  exit 1
fi
printf '%s\n' "$NSS_BRANCH_SHA" > "$OUT/nss-feed-sha.txt"
cp "$IMM/feeds.conf" "$OUT/pinned-feeds.conf"
sha256sum "$IMM/.config" > "$OUT/kernel-config.sha256"
grep -E '^(CONFIG_(TARGET|ATH11K|NSS_|PACKAGE_kmod-|IB|SDK|CCACHE)=)' "$IMM/.config" \
  > "$OUT/kernel-config-selected.txt" || true
echo "Pinned official feeds + NSS feed, Kconfig accepted kernel-only selection."
echo "NSS feed revision: $NSS_BRANCH_SHA"
echo "Heavy Go packages and ALL_KMODS are not selected."
 "$IMM/.config"; then
  echo "::error::Heavy userland packages or ALL_KMODS forced into kernel selection" >&2
  exit 1
fi
printf '%s\n' "$NSS_BRANCH_SHA" > "$OUT/nss-feed-sha.txt"
cp "$IMM/feeds.conf" "$OUT/pinned-feeds.conf"
sha256sum "$IMM/.config" > "$OUT/kernel-config.sha256"
grep -E '^(CONFIG_(TARGET|ATH11K|NSS_|PACKAGE_kmod-|IB|SDK|CCACHE)=)' "$IMM/.config" \
  > "$OUT/kernel-config-selected.txt" || true
echo "Pinned official feeds + NSS feed, Kconfig accepted kernel-only selection."
echo "NSS feed revision: $NSS_BRANCH_SHA"
echo "Heavy Go packages and ALL_KMODS are not selected."
