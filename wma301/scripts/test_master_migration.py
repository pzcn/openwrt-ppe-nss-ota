#!/usr/bin/env python3
"""WMA301 master/6.18 remains an isolated official Snapshot fast-path."""
from pathlib import Path

wma = Path(__file__).resolve().parents[1]
root = wma.parent
workflow = (root / ".github/workflows/wma301-firmware.yml").read_text()
builder = (wma / "scripts/official_builder.py").read_text()
verifier = (wma / "scripts/verify.py").read_text()
device = (wma / "scripts/prepare.py").read_text()

assert "https://downloads.immortalwrt.org/snapshots/targets/mediatek/filogic" in workflow
assert "KFILE=upstream/target/linux/generic/kernel-6.18" in workflow
assert 'VERSION="6.18.$PATCH"' in workflow
assert "refs/heads/master" in workflow or 'commits/$SHORT' in workflow
assert "immortalwrt-imagebuilder-mediatek-filogic.Linux-x86_64.tar.zst" in builder
assert "ImmortalWrt master SNAPSHOT (official binaries)" in builder
assert '"branch":"master"' in verifier
assert "kmod-mt7915e kmod-mt7981-firmware mt7981-wo-firmware" in device
assert "KERNEL_IN_UBI := 1" in device
assert "UBOOTENV_IN_UBI := 1" in device
assert "25.12-SNAPSHOT" not in workflow + builder
assert "wma301" in workflow and "pack_unified_ota.py" in workflow
assert "WMA301_ENABLE_OTA: 'false'" in workflow, "old OTA must not be staged"
print("WMA301 integrated official master 6.18 migration contracts: PASS")
