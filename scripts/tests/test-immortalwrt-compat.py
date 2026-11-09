#!/usr/bin/env python3
"""Offline fixture tests for F2FS and eMMC sysupgrade compatibility."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
script = root / "scripts/apply-immortalwrt-compat.sh"
build = (root / "scripts/build-immortalwrt.sh").read_text()
repack = (root / "scripts/repack-immortalwrt.sh").read_text()
config = (root / "config/immortalwrt-re-ss-01.config").read_text()
add = (root / "config/add.txt").read_text()
for name in ("kmod-fs-f2fs", "f2fs-tools"):
    assert name in add
    assert "CONFIG_PACKAGE_" + name + "=y" in config
assert "scripts/apply-immortalwrt-compat.sh" in build
assert "base-overlay-for-imagebuilder" in build
assert 'test -s "$WORK/overlay/lib/upgrade/platform.sh"' in repack
subprocess.run(["bash", "-n", str(script)], check=True)
with tempfile.TemporaryDirectory() as tmp:
    src = Path(tmp) / "source"
    out = Path(tmp) / "files"
    device = src / "target/linux/qualcommax/image/ipq60xx.mk"
    platform = src / "target/linux/qualcommax/ipq60xx/base-files/lib/upgrade/platform.sh"
    device.parent.mkdir(parents=True)
    platform.parent.mkdir(parents=True)
    device.write_text(
        "define Device/jdcloud_re-cs-02\n"
        "\tDEVICE_PACKAGES := ipq-wifi-jdcloud_re-cs-02\nendef\n"
        "define Device/jdcloud_re-cs-07\n"
        "\tDEVICE_PACKAGES := -kmod-ath11k-ahb f2fs-tools\nendef\n"
        "define Device/jdcloud_re-ss-01\n"
        "\tDEVICE_PACKAGES := ipq-wifi-jdcloud_re-ss-01\nendef\n")
    platform.write_text("#!/bin/sh\nplatform_do_upgrade() {\n"
                        '  emmc_do_upgrade "$1"\n}\n')
    for _ in range(2):
        subprocess.run(["bash", str(script), str(src), str(out)], check=True)
    content = device.read_text()
    assert content.count("kmod-fs-f2fs") == 3
    assert content.count("f2fs-tools") == 3
    assert "-kmod-ath11k-ahb f2fs-tools kmod-fs-f2fs" in content
    upgrade = (out / "lib/upgrade/platform.sh").read_text()
    assert upgrade.count("platform_copy_config()") == 1
    for board in ("jdcloud,re-cs-02", "jdcloud,re-cs-07", "jdcloud,re-ss-01",
                  "link,nn6000-v1", "link,nn6000-v2"):
        assert board in upgrade
    subprocess.run(["sh", "-n", str(out / "lib/upgrade/platform.sh")], check=True)
    platform.write_text("#!/bin/sh\n"
                        'platform_do_upgrade() { emmc_do_upgrade "$1"; }\n'
                        "platform_copy_config() {\n"
                        '  case "$(board_name)" in\n'
                        "    jdcloud,re-ss-01) emmc_copy_config;;\n"
                        "  esac\n}\n")
    subprocess.run(["bash", str(script), str(src), str(out)], check=True)
    assert (out / "lib/upgrade/platform.sh").read_text().count("platform_copy_config()") == 1
print("PASS temporary F2FS and eMMC sysupgrade fixes")
