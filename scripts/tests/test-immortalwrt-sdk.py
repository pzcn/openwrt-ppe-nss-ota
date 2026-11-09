#!/usr/bin/env python3
"""Offline SDK release, ABI pairing and pinned feeds regression tests."""
import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from immortalwrt_builder import metadata as builder_metadata
from immortalwrt_sdk import (
    FEEDS, SDK_CHANNEL, feed_fingerprint, make_metadata, verify_files
)


def commit_repo(folder: Path, content: str) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(folder)], check=True)
    (folder / "README").write_text(content)
    subprocess.run(["git", "-C", str(folder), "add", "README"], check=True)
    subprocess.run(
        ["git", "-C", str(folder), "-c", "user.name=CI",
         "-c", "user.email=ci@example.com", "commit", "-qm", "test"],
        check=True
    )
    return subprocess.check_output(
        ["git", "-C", str(folder), "rev-parse", "HEAD"], text=True
    ).strip()


with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    source = root / "immortalwrt"
    immortal = commit_repo(source, "ImmortalWrt")
    ppe_luci = root / "ppe-luci"
    feeds = {}
    for feed in FEEDS:
        folder = ppe_luci if feed == "ppe_qos_luci" else source / "feeds" / feed
        feeds[feed] = commit_repo(folder, feed)
    digest = feed_fingerprint(feeds)
    assert len(digest) == 64

    try:
        feed_fingerprint({"packages": "a" * 40})
    except ValueError:
        pass
    else:
        raise AssertionError("Allowed incomplete feed provenance")

    imagebuilder = root / "immortalwrt-imagebuilder-test.tar.zst"
    overlay = root / "base-overlay.tar.gz"
    packages = root / "imagebuilder-packages.txt"
    sdk_archive = root / "immortalwrt-sdk-qualcommax-ipq60xx_gcc-14.4.0_musl.Linux-x86_64.tar.zst"
    for a in (imagebuilder, overlay, packages, sdk_archive):
        a.write_bytes((a.name + " test\n").encode() * 40)
    builder_file = root / "builder-metadata.json"
    builder_metadata(argparse.Namespace(
        immortal=immortal, ppe="a" * 40, base="b" * 40,
        feeds=digest, archive=imagebuilder, overlay=overlay,
        packages=packages, output=builder_file,
    ))
    builder = json.loads(builder_file.read_text())
    toolchain_file = root / "official-toolchain-status.txt"
    toolchain_file.write_text("toolchain=official-immortalwrt\n")
    sdk_file = root / "sdk-metadata.json"
    lock_file = root / "sdk-feeds.lock.json"
    args = argparse.Namespace(
        source=source, ppe_luci=ppe_luci, toolchain_status=toolchain_file,
        output=sdk_file, feed_lock=lock_file, builder_metadata=builder_file,
        archive=sdk_archive,
    )
    make_metadata(args)
    first = sdk_file.read_bytes()
    make_metadata(args)
    assert sdk_file.read_bytes() == first, "SDK metadata is not deterministic"
    info = verify_files(sdk_file, builder_file, sdk_archive, lock_file)
    assert info["builder_tag"] == builder["tag"]
    assert info["builder_metadata_sha256"] and info["archive_sha256"]
    assert info["feed_lock_sha256"] and info["feeds_fingerprint"] == digest
    assert info["target"] == "qualcommax/ipq60xx"
    assert json.loads(lock_file.read_text())["feeds"] == feeds

    subprocess.run(
        [sys.executable, str(ROOT / "scripts/immortalwrt_sdk.py"), "verify",
         "--metadata", str(sdk_file), "--builder-metadata", str(builder_file),
         "--archive", str(sdk_archive), "--feed-lock", str(lock_file)],
        check=True, capture_output=True
    )

    sdk_archive.write_bytes(b"tampered sdk" * 100)
    try:
        verify_files(sdk_file, builder_file, sdk_archive, lock_file)
    except ValueError:
        pass
    else:
        raise AssertionError("Accepted tampered SDK archive")
    sdk_archive.write_bytes((sdk_archive.name + " test\n").encode() * 40)

    lock = json.loads(lock_file.read_text())
    lock["feeds"]["luci"] = "0" * 40
    lock_file.write_text(json.dumps(lock))
    try:
        verify_files(sdk_file, builder_file, sdk_archive, lock_file)
    except ValueError:
        pass
    else:
        raise AssertionError("Accepted mismatched package feed")
    make_metadata(args)

    wrong_builder = root / "other-builder.json"
    changed = dict(builder)
    changed["tag"] = "imm-builder-unrelated"
    wrong_builder.write_text(json.dumps(changed))
    try:
        verify_files(sdk_file, wrong_builder, sdk_archive, lock_file)
    except ValueError:
        pass
    else:
        raise AssertionError("Accepted another Builder release")

    # SDK packaging must refuse changing upstream HEAD during the same build.
    commit_repo(root / "not-the-builder-source", "unrelated")
    args.source = root / "not-the-builder-source"
    try:
        make_metadata(args)
    except (ValueError, subprocess.CalledProcessError):
        pass
    else:
        raise AssertionError("Accepted SDK source mismatch")

config = (ROOT / "config/immortalwrt-re-ss-01.config").read_text()
toolchain_script = (ROOT / "scripts/reuse-official-toolchain.sh").read_text()
build_script = (ROOT / "scripts/build-immortalwrt.sh").read_text()
builder_workflow = (ROOT / ".github/workflows/builder-immortalwrt.yml").read_text()
assert "CONFIG_SDK=y" in config
assert 'bash "$ROOT/scripts/test-sdk-smoke.sh" "$SDK_ARCHIVE" "$WORK/sdk-smoke"' in build_script
assert (ROOT / "scripts/test-sdk-smoke.sh").is_file()
subprocess.run(["bash", "-n", str(ROOT / "scripts/test-sdk-smoke.sh")],
               check=True, capture_output=True)

assert "CONFIG_EXTERNAL_TOOLCHAIN_SDK=y" in toolchain_script
assert "CONFIG_EXTERNAL_TOOLCHAIN_SDK=y" in build_script
assert "grep -Fqx 'CONFIG_SDK=y'" in build_script
assert "SDK_ARCHIVE=" in build_script
assert 'scripts/immortalwrt_sdk.py" metadata' in build_script
assert 'scripts/immortalwrt_sdk.py" verify' in build_script
assert 'sdk-metadata.json' in builder_workflow
assert 'sdk-feeds.lock.json' in builder_workflow
assert 'python3 scripts/tests/test-immortalwrt-sdk.py' in builder_workflow
assert 'gh release create "$TAG"' in builder_workflow
assert '"$SDK_ARCHIVE"' in builder_workflow
assert 'gh workflow run firmware-immortalwrt.yml' in builder_workflow
assert 'cron: "43 5 * * 0"' in builder_workflow

print("PASS matching SDK metadata, feed pinning, artifact integrity and CI publishing")
