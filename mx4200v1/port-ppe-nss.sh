#!/usr/bin/env bash
# Port Julius' IPQ8074 PPE + ath11k NSS-WiFi code into ImmortalWrt 6.18.
# Explicitly separate from the existing JDCloud ipq60xx port.
set -Eeuo pipefail

: "${IMM_SOURCE_DIR:?set IMM_SOURCE_DIR}"
: "${PPE_SOURCE_DIR:?set PPE_SOURCE_DIR}"
imm="$(cd "$IMM_SOURCE_DIR" && pwd)"
ppe="$(cd "$PPE_SOURCE_DIR" && pwd)"

require() {
  test -f "$ppe/$1" || { echo "::error::Missing PPE/NSS source: $1" >&2; exit 1; }
}
copy_file() {
  require "$1"
  install -D -m 0644 "$ppe/$1" "$imm/$1"
}
copy_tree() {
  test -d "$ppe/$1" || { echo "::error::Missing PPE/NSS source directory: $1" >&2; exit 1; }
  mkdir -p "$imm/$1"
  rsync -a --delete "$ppe/$1/" "$imm/$1/"
}

test -f "$imm/target/linux/qualcommax/Makefile"
grep -Fq 'KERNEL_PATCHVER:=6.18' "$imm/target/linux/qualcommax/Makefile" || {
  echo "::error::ImmortalWrt qualcommax must use Linux 6.18; review this port." >&2
  exit 1
}
for patch in 0952-net-ethernet-qca-add-ppe.patch 0953-net-ethernet-qca-add-EDMA.patch; do
  test -f "$imm/target/linux/qualcommax/patches-6.18/$patch" || {
    echo "::error::Missing required ImmortalWrt PPE/EDMA kernel patch: $patch" >&2
    exit 1
  }
done

# Take the complete compatible wireless datapath, not the old ECM/qca-nss-dp stack.
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
for file in qca_edma.h qca_ppe.h; do
  copy_file "target/linux/qualcommax/files/include/linux/soc/qcom/$file"
done

# MX4200 v1: IPQ8174 uses the IPQ8074 ESS/NSS integration. Do not copy the
# IPQ6018 board DTS or JDCloud upgrade platform.sh from the Arthur build.
for file in ipq8074-ess.dtsi ipq8074-nss.dtsi; do
  copy_file "target/linux/qualcommax/files/arch/arm64/boot/dts/qcom/$file"
done
copy_file target/linux/qualcommax/dts/ipq8174-mx4x00.dtsi

# ipq8074-nss.dtsi references &nss_region; upstream 0931 labels that node.
# Apply patches with the upstream ordering. An incompatible rebase must fail.
for file in \
  0819-remoteproc-qcom-wcss-sec-don-t-hold-recovery-for-a-coredump.patch \
  0931-arm64-dts-ipq8074-rename-nss-region.patch; do
  copy_file "target/linux/qualcommax/patches-6.18/$file"
done

image_mk="$imm/target/linux/qualcommax/image/ipq807x.mk"
test -s "$image_mk"
grep -Fq 'KERNEL_SIZE := 6144k' "$image_mk" || {
  echo "::error::MX4200 6 MiB kernel constraint changed; review image layout." >&2
  exit 1
}
grep -Fq '#include "ipq8074-nss.dtsi"' \
  "$imm/target/linux/qualcommax/dts/ipq8174-mx4x00.dtsi"
grep -Fq 'nss_region' \
  "$imm/target/linux/qualcommax/files/arch/arm64/boot/dts/qcom/ipq8074-nss.dtsi"
grep -Fq 'config ATH11K_NSS_WIFI' "$imm/package/kernel/mac80211/ath.mk"
test -f "$imm/package/kernel/nss-wifi-drv/Makefile"
echo "MX4200 v1 IPQ8074 PPE/NSS source port staged; hardware testing is still required."
