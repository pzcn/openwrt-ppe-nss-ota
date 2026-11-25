#!/usr/bin/env python3
"""Network-free contract test for the disposable WMA301 RAM-only integration."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare import DEVICE
from prepare_ramboot import MARKER, prepare_ramboot
from verify_ramboot import EXPECTED_NAME, MAX_SIZE


def test() -> None:
    with tempfile.TemporaryDirectory() as folder:
        upstream = Path(folder)
        images = upstream / "target/linux/mediatek/image"
        dt = upstream / "target/linux/mediatek/dts"
        images.mkdir(parents=True)
        dt.mkdir(parents=True)
        img = images / "filogic.mk"
        img.write_text("define Device/a_device\n  IMAGES := sysupgrade.bin\nendef\n"
                       + MARKER + "\n" + DEVICE)
        common = dt / "mt7981b-tplink-wma301-v2-common.dtsi"
        common.write_text(
            '/ { chosen {\n\t\tbootargs-append = " root=/dev/fit0 rootwait";\n'
            '\t\trootdisk = <&ubi_rootdisk>;\n};\n'
            '\t\t\t\tcompatible = "linux,ubi";\n};\n')
        (dt / "mt7981b-tplink-wma301-v2.dts").write_text("/dts-v1/;\n")
        prepare_ramboot(upstream)
        src = img.read_text()
        assert src.count("IMAGES := sysupgrade.bin") == 1
        assert "IMAGES := sysupgrade.itb" not in src
        assert "IMAGE/sysupgrade.itb" not in src
        assert "KERNEL_INITRAMFS" in src
        dtb_src = common.read_text()
        assert "root=/dev/ram0" in dtb_src
        assert "rootdisk =" not in dtb_src
        assert "linux,ubi" not in dtb_src
        assert (upstream / "files/etc/diag.sh").is_file()
        assert not (upstream / "files/usr/libexec").exists()
        try:
            prepare_ramboot(upstream)
        except ValueError:
            pass
        else:
            raise AssertionError("second run should be rejected")
    assert EXPECTED_NAME.endswith("-initramfs-recovery.itb")
    assert 0 < MAX_SIZE < 0x2000000
    print("RAM recovery DTS, packages and no-flash image definition: PASS")


if __name__ == "__main__":
    test()
