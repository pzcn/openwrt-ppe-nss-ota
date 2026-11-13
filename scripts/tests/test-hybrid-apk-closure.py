#!/usr/bin/env python3
"""Offline tests for native apk recursive closure's provenance validation."""
import hashlib
import importlib.util
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "hybrid_closure", ROOT / "scripts/hybrid-verify-apk-closure.py")
closure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(closure)


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


with tempfile.TemporaryDirectory() as directory:
    folder = Path(directory)
    lock = {"lock_fingerprint": "1" * 64,
            "kernel_fingerprint": "2" * 64,
            "packages_fingerprint": "3" * 64}
    target = {"packages/etherwake-1.1-r1.apk": sha(b"official etherwake")}
    arch = {"base/libc-1.2-r1.apk": sha(b"official libc")}
    (folder / "etherwake-1.1-r1.apk").write_bytes(b"official etherwake")
    (folder / "libc-1.2-r1.apk").write_bytes(b"official libc")
    manifest = closure.verify(lock, target, arch, folder, ["etherwake"])
    assert manifest["count"] == 2
    assert manifest["status"] == "P3-official-userland-closure-test-only"
    assert manifest["all_download_sha256_matched"]
    assert not manifest["flashable_image_produced"]
    assert any(x["abi_review"] and x["name"] == "libc" for x in manifest["files"])
    assert any(x["name"] == "etherwake" and not x["abi_review"] for x in manifest["files"])

    # Missing requested root package must not be mistaken for a complete closure.
    try:
        closure.verify(lock, target, arch, folder, ["wireguard-tools"])
    except ValueError as error:
        assert "missing" in str(error)
    else:
        raise AssertionError("Accepted closure missing root package")

    # Only checksum-indexed files can be accepted.
    (folder / "etherwake-1.1-r1.apk").write_bytes(b"modified")
    try:
        closure.verify(lock, target, arch, folder, ["etherwake"])
    except ValueError as error:
        assert "uniquely identified" in str(error)
    else:
        raise AssertionError("Accepted unpinned APK")
    (folder / "etherwake-1.1-r1.apk").write_bytes(b"official etherwake")

    # A foreign kernel module, even with correct upstream hash, is forbidden.
    bad = folder / "kmod-wireguard-1.1-r1.apk"
    bad.write_bytes(b"official but foreign kernel")
    arch["packages/kmod-wireguard-1.1-r1.apk"] = sha(bad.read_bytes())
    try:
        closure.verify(lock, target, arch, folder, ["etherwake"])
    except ValueError as error:
        assert "kmod" in str(error)
    else:
        raise AssertionError("Accepted official kernel module in custom firmware")
    bad.unlink()

    custom = folder / "sqm-scripts-1.8-r1.apk"
    custom.write_bytes(b"official but lacks PPE patch")
    arch["packages/sqm-scripts-1.8-r1.apk"] = sha(custom.read_bytes())
    try:
        closure.verify(lock, target, arch, folder, ["etherwake"])
    except ValueError as error:
        assert "Patched custom" in str(error)
    else:
        raise AssertionError("Accepted official SQM instead of local PPE patch")
    custom.unlink()

    # A malicious symlink masquerading as an official APK is forbidden.
    link = folder / "wireguard-tools-1.0-r1.apk"
    link.symlink_to(folder / "libc-1.2-r1.apk")
    arch["packages/wireguard-tools-1.0-r1.apk"] = sha(b"official libc")
    try:
        closure.verify(lock, target, arch, folder, ["etherwake"])
    except ValueError as error:
        assert "symlink" in str(error)
    else:
        raise AssertionError("Accepted an APK symlink")
    link.unlink()

print("PASS native apk closure checksum and kernel/custom contamination checks")
