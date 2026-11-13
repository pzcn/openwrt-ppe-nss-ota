#!/usr/bin/env bash
# Port the PPE + NSS Wi-Fi datapath onto an ImmortalWrt 6.18 source tree.
# The firmware base, packages and LuCI remain ImmortalWrt; only the
# Qualcomm/ath11k integration is taken from openwrt-ppe-nss.
set -Eeuo pipefail

: "${IMM_SOURCE_DIR:?set IMM_SOURCE_DIR}"
: "${PPE_SOURCE_DIR:?set PPE_SOURCE_DIR}"
imm="$(cd "$IMM_SOURCE_DIR" && pwd)"
ppe="$(cd "$PPE_SOURCE_DIR" && pwd)"

require() {
  test -f "$ppe/$1" || { echo "Missing PPE/NSS source: $1" >&2; exit 1; }
}
copy_file() {
  require "$1"
  install -D -m 0644 "$ppe/$1" "$imm/$1"
}
copy_tree() {
  test -d "$ppe/$1" || { echo "Missing PPE/NSS source directory: $1" >&2; exit 1; }
  mkdir -p "$imm/$1"
  rsync -a --delete "$ppe/$1/" "$imm/$1/"
}

test -f "$imm/target/linux/qualcommax/Makefile"
grep -Fq 'KERNEL_PATCHVER:=6.18' "$imm/target/linux/qualcommax/Makefile" || {
  echo "ImmortalWrt Qualcomm kernel is not 6.18; review the PPE port" >&2
  exit 1
}
# We need the mainline PPE/EDMA stack, not the older ECM + qca-nss-dp stack.
for f in 0952-net-ethernet-qca-add-ppe.patch 0953-net-ethernet-qca-add-EDMA.patch; do
  test -f "$imm/target/linux/qualcommax/patches-6.18/$f" || {
    echo "Missing upstream PPE/EDMA support: $f" >&2; exit 1;
  }
done

copy_tree package/kernel/nss-wifi-drv
copy_tree package/network/config/qca-ppe-qos
copy_tree package/utils/ppe-help
copy_tree package/kernel/mac80211/patches/nss-wifi
copy_tree package/kernel/mac80211/patches/ath11k
copy_file package/kernel/mac80211/Makefile
copy_file package/kernel/mac80211/ath.mk

for file in \
  qca_edma.c qca_edma.h qca_ppe.h qca_ppe_flow.c \
  qca_ppe_flow_offload.c qca_ppe_main.c qca_ppe_scheduler.c; do
  copy_file "target/linux/qualcommax/files/drivers/net/ethernet/qualcomm/$file"
done
# Two different EDMA interfaces exist upstream:
# include/linux/qca_edma.h: switch/conduit functions used by PPE and EDMA
# include/linux/soc/qcom/qca_edma.h: NSS firmware queue routing API.
# Both are required; copying only the soc/qcom variant breaks qca_ppe_main.c.
copy_file target/linux/qualcommax/files/include/linux/qca_edma.h
for file in qca_edma.h qca_ppe.h; do
  copy_file "target/linux/qualcommax/files/include/linux/soc/qcom/$file"
done
for file in ipq6018-ess.dtsi ipq6018-nss.dtsi; do
  copy_file "target/linux/qualcommax/files/arch/arm64/boot/dts/qcom/$file"
done
copy_file target/linux/qualcommax/dts/ipq6000-re-ss-01.dts

# These patches were not present in ImmortalWrt master when this port
# was prepared; keep their original ordering and do not replace the
# rest of ImmortalWrt's kernel patch set.
for file in \
  0192-clk-qcom-gcc-ipq6018-enable-the-source-PLL-across-the-NSS-crypto-RCG-switch.patch \
  0193-clk-qcom-gcc-ipq6018-add-fallback-names-for-the-bias-PLL-parents.patch \
  0819-remoteproc-qcom-wcss-sec-don-t-hold-recovery-for-a-coredump.patch; do
  copy_file "target/linux/qualcommax/patches-6.18/$file"
done

grep -Fq 'CONFIG_ATH11K_NSS_WIFI' "$imm/package/kernel/mac80211/Makefile"
grep -Fq '#include "ipq6018-nss.dtsi"' "$imm/target/linux/qualcommax/dts/ipq6000-re-ss-01.dts"
grep -Fq 'qcom,nss' "$imm/target/linux/qualcommax/files/arch/arm64/boot/dts/qcom/ipq6018-nss.dtsi"
grep -Fq 'config ATH11K_NSS_WIFI' "$imm/package/kernel/mac80211/ath.mk"
test -f "$imm/package/kernel/nss-wifi-drv/Makefile"
echo "PPE/NSS source port staged. Compile and on-device verification are still required."
