#!/usr/bin/env python3
"""Proof-only kernel member graft tests; archives are synthetic and unbootable."""
import importlib.util
import io
import struct
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "research_swap", ROOT / "scripts/build-research-prebuilt-kernel-swap.py")
mod = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(mod)


def make_tar(path: Path, marker: int) -> None:
    kernel = bytearray(4096)
    kernel[:4] = mod.probe.FIT_MAGIC
    struct.pack_into(">I", kernel, 4, len(kernel))
    kernel[-1] = marker
    root = bytearray(8192)
    root[:4] = mod.probe.SQUASHFS_MAGIC
    struct.pack_into("<HH", root, 28, 4, 0)
    struct.pack_into("<Q", root, 40, len(root))
    root[-1] = marker
    with tarfile.open(path, "w") as archive:
        for n, payload in (("CONTROL", b"BOARD=jdcloud,re-ss-01\n"),
                           ("kernel", bytes(kernel)), ("root", bytes(root))):
            member = tarfile.TarInfo("sysupgrade-jdcloud_re-ss-01/" + n)
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))


with tempfile.TemporaryDirectory() as dirname:
    d = Path(dirname)
    off, jul, test = d / "official.bin", d / "julius.bin", d / "research-only.tar"
    make_tar(off, 13)
    make_tar(jul, 29)
    report = mod.swap_kernel(off, jul, test)
    a_kernel, a_root, _ = mod.probe.read_sysupgrade_members(off, "official")
    j_kernel, j_root, _ = mod.probe.read_sysupgrade_members(jul, "julius")
    s_kernel, s_root, _ = mod.probe.read_sysupgrade_members(test, "swapped")
    assert s_kernel == j_kernel
    assert s_root == a_root
    assert s_root != j_root
    assert s_kernel != a_kernel
    assert not report["publishable"]
    assert not report["julius_module_abi_migrated"]
    assert not report["package_database_reconciled"]
    assert report["official_immortalwrt_userland_retained"]
    assert len(report["untouched_official_tar_entry_sha256"]) == 2
    with tarfile.open(test, "r:") as archive:
        ctl = archive.extractfile("sysupgrade-jdcloud_re-ss-01/CONTROL").read()
    assert ctl == b"BOARD=jdcloud,re-ss-01\n"

print("PASS research-only kernel replacement, preserved root+CONTROL, never flashable")
