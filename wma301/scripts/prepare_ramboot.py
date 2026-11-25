#!/usr/bin/env python3
"""Turn a *disposable* prepared WMA301 full-source checkout into RAM-only recovery.

Call scripts/prepare.py first. Do not touch the checked-in persistent-boot DTS
or the official ImageBuilder/OTA path. RAM boot must not depend on /dev/fit0,
auto-attach UBI, or create a flashable sysupgrade image.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
MARKER = "# Local WMA301 OEM-layout integration (generated, never committed upstream)"


def replace_once(source: str, old: str, new: str, name: str) -> str:
    count = source.count(old)
    if count != 1:
        raise ValueError(f"{name}: expected one exact match, got {count}: {old!r}")
    return source.replace(old, new, 1)


def prepare_ramboot(upstream: Path) -> None:
    image = upstream / "target/linux/mediatek/image/filogic.mk"
    common = upstream / "target/linux/mediatek/dts/mt7981b-tplink-wma301-v2-common.dtsi"
    board = upstream / "target/linux/mediatek/dts/mt7981b-tplink-wma301-v2.dts"
    for path in (image, common, board):
        if not path.is_file():
            raise ValueError(f"missing prepared WMA301 source: {path}")

    # Never produce a flashable image from the RAM-only device recipe.
    content = image.read_text()
    if content.count(MARKER) != 1:
        raise ValueError("WMA301 integration marker missing or duplicated")
    normal, local = content.split(MARKER, 1)
    local = replace_once(local, "  IMAGES := sysupgrade.itb\n", "  IMAGES :=\n", "WMA301 ramboot image list")
    local = replace_once(
        local,
        "  IMAGE/sysupgrade.itb := append-kernel | \\\n"
        "        fit gzip $$(KDIR)/image-$$(firstword $$(DEVICE_DTS)).dtb external-static-with-rootfs | append-metadata\n",
        "",
        "WMA301 persistent FIT recipe",
    )
    image.write_text(normal + MARKER + local)

    # Do not select FIT rootfs or implicitly attach NAND UBI.
    # Keep the NAND partition definitions for manual diagnostics.
    content = common.read_text()
    content = replace_once(
        content,
        '\t\tbootargs-append = " root=/dev/fit0 rootwait";\n\t\trootdisk = <&ubi_rootdisk>;\n',
        '\t\tbootargs-append = " root=/dev/ram0";\n',
        "RAM root bootargs",
    )
    content = replace_once(
        content,
        '\t\t\t\tcompatible = "linux,ubi";\n',
        '\t\t\t\t/* RAM boot: UBI attach is explicit, never automatic. */\n',
        "UBI auto-attach marker",
    )
    common.write_text(content)

    # prepare.py already integrates board.d networking and Wi-Fi MAC handling.
    # Carry only the dual-revision LED logic; no OTA or persistent services.
    overlay = upstream / "files"
    overlay.mkdir(exist_ok=True)
    diag_dst = overlay / "etc/diag.sh"
    diag_dst.parent.mkdir(parents=True, exist_ok=True)
    if diag_dst.exists():
        raise ValueError(f"RAM overlay unexpectedly already defines {diag_dst}")
    shutil.copy2(HERE / "files/etc/diag.sh", diag_dst)
    diag_dst.chmod(diag_dst.stat().st_mode | 0o111)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", type=Path, required=True)
    args = parser.parse_args()
    prepare_ramboot(args.upstream.resolve())
    print("RAM-only WMA301: no flash image, no fit0 root, no UBI auto-attach")


if __name__ == "__main__":
    main()
