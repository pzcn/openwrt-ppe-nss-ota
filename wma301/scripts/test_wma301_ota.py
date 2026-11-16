#!/usr/bin/env python3
"""Offline OTA provenance tests: wrong board, source ID, hash and single feed."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from wma301_ota import BOARD, IMAGE, LAYOUT, REPO, metadata, sha256, stamp

with TemporaryDirectory() as folder:
    root = Path(folder)
    source = "a" * 40
    binary_sha = "b" * 64
    ota = stamp(root / "overlay", 12345, source, binary_sha)
    release = (root / "overlay/etc/wma301-ota-release").read_text()
    assert "OTA_BUILD=12345" in release
    assert "OTA_LAYOUT=" + LAYOUT in release
    assert "OTA_BOARD=" + BOARD in release
    dest = root / "dist"
    dest.mkdir()
    # Real ImageBuilder outputs contain a snapshot revision in the filename.
    source_image = ("immortalwrt-25.12-snapshot-r38263-84b665b5de-" +
                    "mediatek-filogic-tplink_wma301-v2-squashfs-sysupgrade.itb")
    image = dest / source_image
    image.write_bytes(b"Q" * 1_000_100)
    digest = sha256(image)
    manifest = {"build": "official-imagebuilder-fast", "device": BOARD,
                "hardware_validation": "NOT_TESTED", "local_sha": source,
                "ota": ota,
                "builder": {"target": "mediatek/filogic",
                            "imagebuilder_sha256": binary_sha,
                            "source_revision": "123456789abc"},
                "output": {"file": source_image, "sha256": digest,
                           "fit_hashes": "pass", "mode": "squashfs-persistent",
                           "dts": {"compatible": BOARD, "factory_info_protected": True}}}
    def save():
        (dest / "manifest.json").write_text(json.dumps(manifest))
        (dest / "SHA256SUMS").write_text(f"{sha256(image)}  {source_image}\n")
    save()
    data = metadata(dest, 12345, source, dest / "ota.json")
    assert data["tag"] == "wma301-ota-r12345"
    assert data["schema"] == 3 and "channel" not in data
    assert data["hardware_validation"] == "NOT_TESTED"
    assert data["image"] == IMAGE and data["source_image"] == source_image
    assert data["repository"] == REPO
    assert data["auto_upgrade"] is False
    assert json.loads((dest / "ota.json").read_text()) == data
    for mismatch in (
        {"device": "jdcloud,re-ss-01"},
        {"ota": dict(ota, build=555)},
        {"output": dict(manifest["output"], sha256="0" * 64)},
        {"builder": {"target": "mediatek/filogic", "imagebuilder_sha256": "0" * 64}},
    ):
        original = {k: manifest.get(k) for k in mismatch}
        manifest.update(mismatch)
        save()
        try:
            metadata(dest, 12345, source, dest / "ota.json")
        except ValueError:
            pass
        else:
            raise AssertionError(f"Invalid OTA release accepted: {mismatch}")
        manifest.update(original)
    save()
    image.write_bytes(b"R" * 1_000_100)
    try:
        metadata(dest, 12345, source, dest / "ota.json")
    except ValueError:
        pass
    else:
        raise AssertionError("Modified firmware accepted")
print("WMA301 OTA identity, source, digest and single-feed checks: PASS")
