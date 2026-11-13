#!/usr/bin/env python3
"""Offline source-contract checks for the isolated MX4200 v1 build."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
config = (root / "mx4200v1/source.config").read_text()
port = (root / "mx4200v1/port-ppe-nss.sh").read_text()
build = (root / "mx4200v1/build.sh").read_text()
workflow = (root / ".github/workflows/mx4200v1.yml").read_text()
packages = (root / "mx4200v1/packages.txt").read_text()

for expected in (
    "CONFIG_TARGET_qualcommax_ipq807x=y",
    "CONFIG_TARGET_DEVICE_qualcommax_ipq807x_DEVICE_linksys_mx4200v1=y",
    "# CONFIG_TARGET_DEVICE_qualcommax_ipq807x_DEVICE_linksys_mx4200v2 is not set",
    "CONFIG_KERNEL_CC_STACKPROTECTOR_REGULAR=y",
    "CONFIG_ATH11K_NSS_WIFI=y",
    "CONFIG_PACKAGE_kmod-nss-wifi-drv=y",
    "CONFIG_IB=y",
    "CONFIG_SDK=y",
):
    assert expected in config, f"Missing source config: {expected}"

for expected in (
    "ipq8074-ess.dtsi",
    "ipq8074-nss.dtsi",
    "ipq8174-mx4x00.dtsi",
    "0931-arm64-dts-ipq8074-rename-nss-region.patch",
    "KERNEL_SIZE := 6144k",
):
    assert expected in port, f"Missing IPQ8074 port requirement: {expected}"

for forbidden in (
    "scripts/apply-immortalwrt-compat.sh",
    "scripts/immortalwrt_ota.py",
    "config/immortalwrt-re-ss-01.config",
    "scripts/port-ppe-nss-to-immortalwrt.sh",
):
    assert forbidden not in build, f"Arthur-only dependency leaked into MX4200 v1: {forbidden}"

assert "squashfs-factory.bin" in build and "squashfs-sysupgrade.bin" in build
assert "imagebuilder" in build and "sdk" in build.lower()
assert "workflow_dispatch:" in workflow and "mx4200v1/**" in workflow
assert "schedule:" not in workflow
assert "luci-app-wol" in packages and "luci-proto-wireguard" in packages
assert "kmod-fs-f2fs" not in packages and "sing-box" not in packages
print("MX4200 v1 static build contracts: OK (not a compilation or device test)")
