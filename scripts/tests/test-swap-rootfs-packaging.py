#!/usr/bin/env python3
"""Unit tests for intentionally non-deployable mixed rootfs packaging."""
import importlib.util
import io
import json
import stat
import struct
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "research_rootfs_pack", ROOT / "scripts/pack-swap-research-rootfs.py")
pack = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(pack)

with tempfile.TemporaryDirectory() as tmp:
    base = Path(tmp)
    modules = base / "lib/modules/6.18.60"
    modules.mkdir(parents=True)
    (modules / "f2fs.ko").write_bytes(b"f2fs-test")
    (modules / "nss-wifi-drv.ko").write_bytes(b"nss-test")
    (modules / "wireguard.ko").write_bytes(b"wg-test")
    (base / "link").symlink_to("lib/modules/6.18.60")
    original = pack.byte_manifest(base)
    assert original["link"] == ("symlink", "lib/modules/6.18.60")
    assert original["lib/modules/6.18.60/f2fs.ko"][0] == "file"
    (modules / "f2fs.ko").write_bytes(b"changed")
    assert pack.byte_manifest(base) != original

    fit = base / "kernel.fit"
    squash = base / "root.squashfs"
    bundle = base / "research.tar"
    header = bytearray(4096)
    header[:4] = pack.probe.FIT_MAGIC
    struct.pack_into(">I", header, 4, len(header))
    fit.write_bytes(header)
    squash.write_bytes(pack.probe.SQUASHFS_MAGIC + bytes(4092))
    result = pack.write_research_tar(fit, squash, bundle)
    assert result["control_board_identity"] == "research-invalid-not-a-real-device"
    assert result["kernel_fit_sha256"] == pack.sha256_file(fit)
    assert result["rootfs_squashfs_sha256"] == pack.sha256_file(squash)
    with tarfile.open(bundle) as archive:
        entries = archive.getnames()
        assert entries == [pack.RESEARCH_PREFIX + "/" + x
                           for x in ("CONTROL", "kernel", "root")]
        body = archive.extractfile(entries[0]).read()
        assert body == pack.RESEARCH_CONTROL
        assert b"jdcloud,re-ss-01" not in body

    fit.write_bytes(b"bad" + bytes(4093))
    try:
        pack.write_research_tar(fit, squash, bundle)
    except ValueError as error:
        assert "FIT magic" in str(error)
    else:
        raise AssertionError("Invalid FIT accepted")
    fit.write_bytes(header)
    squash.write_bytes(b"bad!" + bytes(4092))
    try:
        pack.write_research_tar(fit, squash, bundle)
    except ValueError as error:
        assert "SquashFS" in str(error)
    else:
        raise AssertionError("Invalid SquashFS accepted")

print("PASS research packaging guardrails and archive byte integrity")
