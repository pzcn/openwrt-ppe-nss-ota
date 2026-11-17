#!/usr/bin/env python3
"""Fast, network-free unit tests for the official ImageBuilder integration."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from official_builder import (
    IMAGEBUILDER, PROFILE, parse_checksums, register_profile, resolve,
    prepare_kernel_image, locate_kernel, read_packages,
)


def run() -> None:
    digest = hashlib.sha256(b"official").hexdigest()
    assert parse_checksums(f"{digest}  {IMAGEBUILDER}\n")[IMAGEBUILDER] == digest
    for invalid in (
        f"{digest}  ../../builder.tar.zst",
        f"{digest}  {IMAGEBUILDER}\n{digest}  {IMAGEBUILDER}",
    ):
        try:
            parse_checksums(invalid)
        except RuntimeError:
            pass
        else:
            raise AssertionError("invalid sha256sums accepted")

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        index = root / "index"
        index.mkdir()
        (index / "version.buildinfo").write_text("r42542-e695009c15\n")
        (index / "sha256sums").write_text(
            f"{digest}  {IMAGEBUILDER}\n"
            f"{digest}  immortalwrt-sdk-mediatek-filogic_gcc-14.4.0_musl.Linux-x86_64.tar.zst\n"
        )
        output = root / "provenance.json"
        metadata = resolve(index, output)
        assert metadata["source_revision"] == "e695009c15"
        assert metadata["imagebuilder_sha256"] == digest
        assert metadata["sdk_sha256"] == digest
        assert metadata["source"] == "ImmortalWrt master SNAPSHOT (official binaries)"
        assert json.loads(output.read_text()) == metadata
        (index / "version.buildinfo").write_text("invalid\n")
        try:
            resolve(index, output)
        except RuntimeError:
            pass
        else:
            raise AssertionError("untrusted version accepted")

        packages = root / "packages.txt"
        packages.write_text("# base\nluci # Web UI\n-kmod-test\n")
        assert read_packages(packages) == ["luci", "-kmod-test"]
        packages.write_text("luci\nluci\n")
        try:
            read_packages(packages)
        except RuntimeError:
            pass
        else:
            raise AssertionError("duplicate package was accepted")
        for bad in ("luci;id", "$(echo unsafe)", "../../package", "luci something"):
            packages.write_text(bad + "\n")
            try:
                read_packages(packages)
            except RuntimeError:
                pass
            else:
                raise AssertionError(f"unsafe package name was accepted: {bad}")

        target = root / ".targetinfo"
        target.write_text(
            "Target: mediatek\nTarget-Profile: Default\n@@\n"
            "Target: mediatek/filogic\nTarget-Profile: DEVICE_existing\n"
            "Target-Profile-Packages: kmod-foo\n@@\n"
            "Target: other/target\nTarget-Profile: DEVICE_next\n@@\n"
        )
        register_profile(target)
        contents = target.read_text()
        profile = f"Target-Profile: DEVICE_{PROFILE}"
        assert contents.count(profile + "\n") == 1
        assert contents.count("Target-Profile: DEVICE_tplink_wma301-v2-1\n") == 1
        assert contents.index(profile) < contents.index("Target: other/target")
        assert "Target-Profile-SupportedDevices: tplink,wma301-v2" in contents
        try:
            register_profile(target)
        except RuntimeError:
            pass
        else:
            raise AssertionError("duplicate WMA301 profile accepted")

        builder = root / "builder"
        kdir = builder / "build_dir/target-aarch64_cortex-a53_musl/linux-mediatek_filogic"
        linux = kdir / "linux-6.18.55"
        (linux / "arch/arm64/boot/dts/mediatek").mkdir(parents=True)
        (linux / "arch/arm64/boot/dts/mediatek/mt7981b.dtsi").touch()
        (kdir / "Image").write_bytes(os.urandom(220_000))
        found, source = locate_kernel(builder)
        assert found == kdir and source == linux
        gzip = prepare_kernel_image(kdir)
        assert gzip.read_bytes()[:2] == b"\x1f\x8b"
    print("Official Builder resolution, device metadata, kernel reuse: PASS")


if __name__ == "__main__":
    run()
