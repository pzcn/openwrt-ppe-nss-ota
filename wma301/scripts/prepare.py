#!/usr/bin/env python3
"""Add WMA301 v2 OEM-layout support to a freshly cloned ImmortalWrt tree.

Fail closed if upstream defines the board or expected extension hooks change.
Only writes inside the downloaded, disposable upstream checkout.
"""
from __future__ import annotations
import argparse
import re
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parents[1]
DEVICE = """\
define Device/tplink_wma301-v2
  DEVICE_VENDOR := TP-Link
  DEVICE_MODEL := WMA301 v2.0 (OEM BL2/BL31 + custom BL33)
  DEVICE_DTS := mt7981b-tplink-wma301-v2
  DEVICE_DTS_DIR := ../dts
  SUPPORTED_DEVICES := tplink,wma301-v2
  DEVICE_PACKAGES := kmod-mt7915e kmod-mt7981-firmware mt7981-wo-firmware \\
	uboot-envtools
  BLOCKSIZE := 128k
  PAGESIZE := 2048
  UBINIZE_OPTS := -E 5
  KERNEL_IN_UBI := 1
  UBOOTENV_IN_UBI := 1
  IMAGES := sysupgrade.itb
  KERNEL_INITRAMFS_SUFFIX := -recovery.itb
  KERNEL := kernel-bin | gzip
  KERNEL_INITRAMFS := kernel-bin | lzma | \\
        fit lzma $$(KDIR)/image-$$(firstword $$(DEVICE_DTS)).dtb with-initrd | pad-to 64k
  IMAGE/sysupgrade.itb := append-kernel | \\
        fit gzip $$(KDIR)/image-$$(firstword $$(DEVICE_DTS)).dtb external-static-with-rootfs | append-metadata
endef
TARGET_DEVICES += tplink_wma301-v2
"""

def need(condition: bool, msg: str):
    if not condition:
        raise RuntimeError(msg)

def change(path: Path, old: str, new: str):
    src=path.read_text()
    need(src.count(old)==1, f"Upstream hook changed: {path}: {old!r} appeared {src.count(old)} times")
    path.write_text(src.replace(old,new,1))

def inject_case(path: Path, func: str | None, body: str):
    """Insert body right after the first `case "$board" in` (inside func, or top level if func is None)."""
    src=path.read_text()
    if func is None:
        first=0
    else:
        match=re.search(r"(?m)^"+re.escape(func)+r"\(\)\s*\{",src)
        first=match.start() if match else -1
        need(first>=0, f"missing function {func}: {path}")
    part=src[first:]
    case_match=re.search(r'(?m)^\s*case\s+(?:"\$board"|\$board)\s+in',part)
    need(case_match is not None, f"cannot locate board case inside {func}")
    hook=case_match.group(0)
    at=case_match.start()
    pre=src[:first]
    rest=src[first:]
    need("tplink,wma301-v2" not in rest[:at+len(hook)], "board already provided")
    rest=rest.replace(hook,hook+'\n'+body,1)
    path.write_text(pre+rest)

def prepare(upstream: Path):
    need((upstream/"target/linux/mediatek/image/filogic.mk").is_file(),
         "not an ImmortalWrt / OpenWrt source checkout")
    image=upstream/"target/linux/mediatek/image/filogic.mk"
    text=image.read_text()
    need("define Device/tplink_wma301-v2" not in text,
         "upstream already has WMA301 v2; reconcile instead of overriding")
    need("TARGET_DEVICES +=" in text, "missing expected image makefile hook")
    with image.open("a") as f:
        f.write("\n# Local WMA301 OEM-layout integration (generated, never committed upstream)\n")
        f.write(DEVICE)

    dest=upstream/"target/linux/mediatek/dts"
    need(dest.is_dir(), "missing DTS directory")
    for name in ("mt7981b-tplink-wma301-v2-common.dtsi",
                 "mt7981b-tplink-wma301-v2.dts"):
        target=dest/name
        need(not target.exists(), f"upstream already has {name}: reconcile first")
        shutil.copy2(HERE/"device"/name,target)

    network=upstream/"target/linux/mediatek/filogic/base-files/etc/board.d/02_network"
    src=network.read_text()
    need("tplink,wma301-v2" not in src,"upstream network support changed")
    # Add a new top-priority board case; preserve all other upstream defaults.
    inject_case(network,"mediatek_setup_interfaces",
                '\ttplink,wma301-v2)\n\t\tucidef_set_interfaces_lan_wan "lan1 lan2 lan3" wan\n\t\t;;')

    platform=upstream/"target/linux/mediatek/filogic/base-files/lib/upgrade/platform.sh"
    text=platform.read_text()
    need("tplink,wma301-v2" not in text,"upstream upgrade support changed")
    inject_case(platform,"platform_do_upgrade",
                '\ttplink,wma301-v2)\n\t\tfit_do_upgrade "$1"\n\t\t;;')
    inject_case(platform,"platform_check_image",
                '\ttplink,wma301-v2)\n\t\tfit_check_image "$1"\n\t\treturn $?\n\t\t;;')

    # fw_printenv / fw_setenv: U-Boot env lives in UBI volumes ubootenv/ubootenv2 (0x1f000 = 124k).
    envtools=upstream/"package/boot/uboot-tools/uboot-envtools/files/mediatek_filogic"
    need(envtools.is_file(),"missing uboot-envtools mediatek_filogic")
    src=envtools.read_text()
    need("tplink,wma301-v2" not in src,"upstream envtools support changed")
    need("ubootenv_add_ubi_default()" in (envtools.parent/"uboot-envtools.sh").read_text(),
         "upstream removed ubootenv_add_ubi_default")
    inject_case(envtools,None,'tplink,wma301-v2)\n\tubootenv_add_ubi_default\n\t;;')

    # Wi-Fi MAC as OEM: base=factory_info@0x1c, 2.4G=+1, 5G=+2 (LAN=+0, WAN=+3 in DTS).
    wifimac=upstream/"target/linux/mediatek/filogic/base-files/etc/hotplug.d/ieee80211/11_fix_wifi_mac"
    need(wifimac.is_file(),"missing 11_fix_wifi_mac")
    need("tplink,wma301-v2" not in wifimac.read_text(),"upstream wifi mac support changed")
    inject_case(wifimac,None,
                '\ttplink,wma301-v2)\n'
                '\t\taddr=$(mtd_get_mac_binary factory_info 0x1c)\n'
                '\t\t[ "$PHYNBR" = "0" ] && macaddr_add $addr 1 > /sys${DEVPATH}/macaddress\n'
                '\t\t[ "$PHYNBR" = "1" ] && macaddr_add $addr 2 > /sys${DEVPATH}/macaddress\n'
                '\t\t;;')

    need('label = "ubi";' in (dest/"mt7981b-tplink-wma301-v2-common.dtsi").read_text(),
         "missing Linux UBI partition")
    print("WMA301 OEM device integration: OK")

if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--upstream",type=Path,required=True)
    args=parser.parse_args()
    prepare(args.upstream.resolve())
