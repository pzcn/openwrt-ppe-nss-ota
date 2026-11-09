#!/usr/bin/env python3
"""Offline checks for deterministic, ABI-locked ImmortalWrt ImageBuilder releases."""
import argparse
import importlib.util
import json
import subprocess
import sys
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
    for name in mod.PACKAGE_FILES:
        p = tmp / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("initial package selection\n")
    one = mod.fingerprint(tmp)
    assert len(one) == 64
    assert mod.tag(imm, ppe, base, tmp) != mod.tag(imm, "d" * 40, base, tmp)
    package_before = mod.package_fingerprint(tmp)
    (tmp / "config/add.txt").parent.mkdir(parents=True, exist_ok=True)
    (tmp / "config/add.txt").write_text("sample-new-plugin\n")
    (tmp / "config/remove.txt").write_text("")
    assert mod.fingerprint(tmp) == one, "Plugin selections must not alter the core ABI"
    assert mod.package_fingerprint(tmp) != package_before
    assert mod.tag(imm, ppe, base, tmp) != mod.release_tag(
        imm, ppe, base, one, package_before)
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

    # Verify CLI metadata arguments (not just the internal Python call).
    cli_meta = tmp / "cli-metadata.json"
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/immortalwrt_builder.py"),
         "metadata", "--immortal", imm, "--ppe", ppe, "--base", base,
         "--archive", str(archive), "--overlay", str(overlay),
         "--packages", str(packages), "--output", str(cli_meta)],
        check=True, capture_output=True, text=True
    )
    assert json.loads(cli_meta.read_text())["packages"] == packages.name
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/immortalwrt_builder.py"),
         "verify", "--metadata", str(cli_meta), "--archive", str(archive),
         "--overlay", str(overlay), "--packages", str(packages)],
        check=True, capture_output=True, text=True
    )

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
official = (ROOT / "scripts/reuse-official-toolchain.sh").read_text()
assert "CONFIG_EXTERNAL_TOOLCHAIN_IB=y" in official
assert "14.4.0" in official and "1.2.6" in official
assert "sha256sum -c --status" in official
assert 'IMM_USE_OFFICIAL_TOOLCHAIN' in official
# Regression: relative "bash scripts/ext-toolchain.sh" configures a fake
# scripts/ext-toolchain.sh/.config and fails 20 minutes later at wrapper.
assert 'bash "$IMM/scripts/ext-toolchain.sh" \\' in official
assert 'bash scripts/ext-toolchain.sh' not in official
assert 'CONFIG_TOOLCHAIN_ROOT=' in official
assert 'External toolchain root missing after make defconfig' in full_build
assert 'ln -s "$CACHE_DL" "$IMM/dl"' in full_build
assert 'ln -s "$CACHE_CCACHE" "$IMM/.ccache"' in full_build
assert 'ccache --show-stats' in full_build
assert "reuse-official-toolchain.sh" in full_build
assert 'Built firmware manifest missing' in full_build
assert 'Standalone ImageBuilder repack smoke test' in full_build
assert 'IMMORTAL_OUT_DIR=' in full_build
assert 'PACKAGES+=" -$pkg"' in (ROOT / "scripts/repack-immortalwrt.sh").read_text()
builder_workflow = (ROOT / ".github/workflows/builder-immortalwrt.yml").read_text()
firmware_workflow = (ROOT / ".github/workflows/firmware-immortalwrt.yml").read_text()
assert "actions/cache@v4" in builder_workflow
assert ".build-cache/dl" in builder_workflow
assert ".build-cache/ccache" in builder_workflow
assert "gh workflow run firmware-immortalwrt.yml" in builder_workflow
assert "PUBLISH_RELEASE: \"false\"" in builder_workflow
assert "scripts/repack-immortalwrt.sh" in firmware_workflow
assert "run: bash scripts/build-immortalwrt.sh" not in firmware_workflow
assert "19 4 * * *" in firmware_workflow
assert "43 5 * * *" in builder_workflow
assert "UTC_DAY % 2" in builder_workflow
assert "scripts/apply-immortalwrt-compat.sh" in mod.CORE_FILES
assert "config/add.txt" not in mod.CORE_FILES
assert "config/add.txt" in mod.PACKAGE_FILES
print("PASS separate daily firmware / two-day Builder Actions, cache and provenance")
