#!/usr/bin/env python3
"""Offline checks: official asset provenance, ELF target and safe FILES stage."""
import hashlib
import importlib.util
import io
from pathlib import Path
import struct
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("sing_box_pre", ROOT / "scripts/sing_box_pre.py")
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)
assert mod.VERSION == "1.15.0-alpha.13"
assert mod.ASSET.endswith("-linux-arm64-musl.tar.gz")


def archive(path: Path, data: bytes, *, name: str | None = None, symlink: bool = False):
    with tarfile.open(path, "w:gz") as tar:
        info = tarfile.TarInfo(name or "sing-box-1.15.0-alpha.13-linux-arm64-musl/sing-box")
        if symlink:
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            tar.addfile(info)
        else:
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def fail(fn):
    try:
        fn()
    except ValueError:
        pass
    else:
        raise AssertionError("Unsafe sing-box asset was accepted")


with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    asset = root / mod.ASSET
    data = bytearray(1024)
    data[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<H", data, 18, 183)
    archive(asset, bytes(data))
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    stage = root / "rootfs"
    stage.mkdir()
    out = root / "artifacts/sing-box-core.json"
    result = mod.stage(asset, stage, out, expected=digest)
    assert result["version"] == mod.VERSION
    assert result["placement"] == "firmware-squashfs"
    assert out.is_file() and (stage / "etc/sing-box-core.json").is_file()
    assert (stage / "usr/bin/sing-box").read_bytes() == data
    fail(lambda: mod.validated_core(asset, mod.ARCHIVE_SHA256))
    x86 = bytearray(data)
    struct.pack_into("<H", x86, 18, 62)
    archive(asset, bytes(x86))
    fail(lambda: mod.validated_core(asset, hashlib.sha256(asset.read_bytes()).hexdigest()))
    archive(asset, bytes(data), name="../sing-box")
    fail(lambda: mod.validated_core(asset, hashlib.sha256(asset.read_bytes()).hexdigest()))
    archive(asset, bytes(data), symlink=True)
    fail(lambda: mod.validated_core(asset, hashlib.sha256(asset.read_bytes()).hexdigest()))

for rel in ["scripts/repack-immortalwrt.sh", "mx4200v1/repack-hybrid.sh",
            "mx4200v1/build-hybrid.sh", "mx4200v1/build.sh"]:
    assert 'scripts/stage-sing-box-pre.sh' in (ROOT / rel).read_text()
print("PASS sing-box prerelease SHA/ELF/symlink/traversal and firmware staging")
