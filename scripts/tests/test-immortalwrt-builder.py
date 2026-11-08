#!/usr/bin/env python3
"""Offline checks for deterministic, ABI-locked ImmortalWrt ImageBuilder releases."""
import argparse
import importlib.util
import json
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "immortalwrt_builder", ROOT / "scripts/immortalwrt_builder.py"
)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)

imm = "a" * 40
ppe = "b" * 40
base = "c" * 40

with tempfile.TemporaryDirectory() as d:
    tmp = Path(d)
    for name in mod.CORE_FILES:
        p = tmp / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("core configuration\n")
    one = mod.fingerprint(tmp)
    assert len(one) == 64
    assert mod.tag(imm, ppe, base, tmp) != mod.tag(imm, "d" * 40, base, tmp)
    path = tmp / mod.CORE_FILES[-1]
    path.write_text("changed core configuration\n")
    assert mod.fingerprint(tmp) != one

    archive = tmp / "immortalwrt-imagebuilder-test.tar.zst"
    overlay = tmp / "base-overlay.tar.gz"
    packages = tmp / "imagebuilder-packages.txt"
    for artifact in (archive, overlay, packages):
        artifact.write_bytes(b"test artifact file content" * 10)
    metadata = tmp / "builder-metadata.json"
    mod.metadata(argparse.Namespace(
        immortal=imm, ppe=ppe, base=base,
        archive=archive, overlay=overlay, packages=packages,
        output=metadata
    ))
    doc = json.loads(metadata.read_text())
    assert doc["packaging"] == "standalone"
    assert doc["archive"] == archive.name
    assert doc["packages"] == packages.name
    assert doc["channel"] == mod.CHANNEL
    kwargs = dict(metadata=metadata, archive=archive,
                  overlay=overlay, packages=packages)
    mod.verify(argparse.Namespace(**kwargs))

    packages.write_bytes(b"tampered packages" * 10)
    try:
        mod.verify(argparse.Namespace(**kwargs))
    except ValueError:
        pass
    else:
        raise AssertionError("ImageBuilder accepted a tampered package manifest")

    try:
        mod.tag(imm, "wrong", base)
    except ValueError:
        pass
    else:
        raise AssertionError("ImageBuilder accepted a malformed upstream SHA")

print("PASS reusable NSS ImageBuilder metadata, integrity and core fingerprint")

# Cache wiring is part of the CI contract, not only a documentation claim.
full_build = (ROOT / "scripts/build-immortalwrt.sh").read_text()
config = (ROOT / "config/immortalwrt-re-ss-01.config").read_text()
assert "CONFIG_CCACHE=y" in config
assert 'ln -s "$CACHE_DL" "$IMM/dl"' in full_build
assert 'ln -s "$CACHE_CCACHE" "$IMM/.ccache"' in full_build
assert 'ccache --show-stats' in full_build
for name in ("build-immortalwrt.yml", "immortalwrt-reusable.yml"):
    workflow = (ROOT / ".github" / "workflows" / name).read_text()
    assert "actions/cache@v4" in workflow
    assert ".build-cache/dl" in workflow
    assert ".build-cache/ccache" in workflow
print("PASS Actions source download cache and ccache wiring")
