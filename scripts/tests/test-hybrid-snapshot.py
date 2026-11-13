#!/usr/bin/env python3
"""Offline regression tests for the read-only Snapshot resolver."""
import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("snapshot", ROOT / "scripts/resolve-immortalwrt-snapshot.py")
snap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snap)


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def fixture(root):
    target = root / "targets/qualcommax/ipq60xx"
    arch = root / "packages/aarch64_cortex-a53"
    target.mkdir(parents=True)
    arch.mkdir(parents=True)
    feeds = ("src-git packages https://github.com/immortalwrt/packages.git^" + "a" * 40 + "\n"
             "src-git luci https://github.com/immortalwrt/luci.git^" + "b" * 40 + "\n"
             "src-git routing https://github.com/openwrt/routing.git^" + "c" * 40 + "\n"
             "src-git telephony https://github.com/openwrt/telephony.git^" + "d" * 40 + "\n")
    archfeeds = ("src-git-full base https://github.com/immortalwrt/immortalwrt.git^" + "e" * 40 + "\n" + feeds)
    files = {
        "version.buildinfo": b"r42542-e695009c15\n",
        "feeds.buildinfo": feeds.encode(),
        "config.buildinfo": b"CONFIG_TARGET_qualcommax=y\n",
    }
    entries = [sha(blob) + " *" + name for name, blob in files.items()]
    for kind in ("imagebuilder", "sdk", "toolchain"):
        entries.append("1" * 64 + " *immortalwrt-" + kind + "-qualcommax-ipq60xx_gcc-14.4.0_musl.Linux-x86_64.tar.zst")
    (target / "sha256sums").write_text("\n".join(entries) + "\n")
    for name, blob in files.items():
        (target / name).write_bytes(blob)
    (arch / "feeds.conf").write_text(archfeeds)
    return target, arch


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    target, arch = fixture(root)
    first = snap.resolve(root)
    assert first == snap.resolve(root), "Lock must be deterministic"
    assert first["target"] == "qualcommax/ipq60xx"
    assert first["target_commit_prefix"] == "e695009c15"
    assert set(first["assets"]) == {"imagebuilder", "sdk", "toolchain"}
    assert first["status"] == "resolver-only-not-build-approved"
    assert snap.classify(first, first) == "unchanged"
    assert snap.classify(None, first) == "kernel-or-target"
    (arch / "feeds.conf").write_text(
        (arch / "feeds.conf").read_text().replace("e" * 40, "f" * 40))
    arch_change = snap.resolve(root)
    assert snap.classify(first, arch_change) == "packages-only"
    assert first["kernel_fingerprint"] == arch_change["kernel_fingerprint"]
    (target / "version.buildinfo").write_text("r42543-fffffffffff\n")
    try:
        snap.resolve(root)
    except ValueError as e:
        assert "Checksum mismatch" in str(e)
    else:
        raise AssertionError("Accepted changed target metadata not in sha256sums")
    fixture_root = root / "clean"
    fixture(fixture_root)
    clean = fixture_root / "targets/qualcommax/ipq60xx"
    (clean / "sha256sums").write_text((clean / "sha256sums").read_text().replace(
        " *version.buildinfo", " *../version.buildinfo"))
    try:
        snap.resolve(fixture_root)
    except ValueError as e:
        assert "Unsafe checksum path" in str(e)
    else:
        raise AssertionError("Accepted checksum path traversal")
    assert len(snap.parse_feeds(
        b"src-git packages https://example.org/x.git^" + b"a" * 40 + b"\n"
        b"src-git luci https://example.org/y.git^" + b"b" * 40 + b"\n"
        b"src-git routing https://example.org/z.git^" + b"c" * 40 + b"\n"
        b"src-git telephony https://example.org/t.git^" + b"d" * 40 + b"\n"
    )) == 4

print("PASS read-only official Snapshot resolver, metadata checksums and change classification")
