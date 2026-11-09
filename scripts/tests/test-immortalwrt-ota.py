#!/usr/bin/env python3
"""Offline tests for the independent ImmortalWrt PPE/NSS update channel."""
import importlib.util
import json
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("immortalwrt_ota", ROOT / "scripts/immortalwrt_ota.py")
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)

# The real customized updater is the input. No network, flashing, or changes
# to the existing OpenWrt channel are involved.
source = (ROOT / "files/usr/sbin/ppe-update").read_text()
assert "sysupgrade -T" in source

with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    overlay = root / "overlay"
    path = overlay / "usr/sbin/ppe-update"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    tag = "imm-ppe-nss-6a123456-9b123456-g12345678-b7-a1"
    mod.prepare(overlay, tag, 71)
    result = path.read_text()
    assert "releases?per_page=100" in result
    assert 'startswith("imm-ppe-nss-")' in result
    assert "re-ss-01-immortal-ppe-nss" in result
    assert "/etc/immortal-ppe-ota-release" in result
    assert "immortalwrt-qualcommax-ipq60xx-jdcloud_re-ss-01-squashfs-sysupgrade.bin" in result
    assert "sysupgrade -T" in result
    assert "apk add" in result
    assert "cmd_auto()" in result
    release = (overlay / "etc/immortal-ppe-ota-release").read_text()
    assert "OTA_BUILD=71" in release and f"OTA_TAG={tag}" in release

    image = root / mod.IMAGE
    manifest = root / mod.MANIFEST
    with image.open("wb") as fd:
        fd.truncate(1_300_000)
    manifest.write_text("example-package 1\n" * 10)
    output = root / "ota.json"
    commit1 = "a" * 40
    commit2 = "b" * 40
    mod.metadata(tag, 71, commit1, commit2, image, manifest, output)
    data = json.loads(output.read_text())
    assert data["channel"] == "re-ss-01-immortal-ppe-nss"
    assert data["board"] == "jdcloud,re-ss-01"
    assert data["build"] == 71
    assert data["image_sha256"] == mod.sha256(image)
    assert data["upstream_tag"] == "immortal-" + "a" * 12
    assert data["ppe_nss_commit"] == commit2

    # Cross-channel tags and wrong image names must be rejected.
    try:
        mod.prepare(overlay, "ota-ppe-nss-old", 100)
    except ValueError:
        pass
    else:
        raise AssertionError("Cross-channel tag was accepted")
    try:
        mod.metadata(tag, 71, commit1, commit2, root / "wrong.bin", manifest, output)
    except ValueError:
        pass
    else:
        raise AssertionError("Unexpected image was accepted")

print("PASS independent ImmortalWrt OTA metadata and shell preparation")
