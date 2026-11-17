#!/usr/bin/env python3
"""Reuse an official ImmortalWrt filogic ImageBuilder for WMA301 sysupgrade FITs.

The source checkout MUST match the commit recorded by the official ImageBuilder.
Only a DTB and the WMA301 FIT wrapper are built locally; no kernel or kmod
compilation is performed. This intentionally does not build initramfs recovery.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

from prepare import DEVICE, prepare
from aurora import build_apk as build_aurora_apk
from stage_files import stage_files

ROOT = Path(__file__).resolve().parents[1]
PROFILE = "tplink_wma301-v2"
PROFILE_V21 = "tplink_wma301-v2-1"
COMPATIBLE = "tplink,wma301-v2"
DEVICE_DTS = "mt7981b-tplink-wma301-v2"
DEVICE_DTS_V21 = "mt7981b-tplink-wma301-v2-1"
IMAGEBUILDER = "immortalwrt-imagebuilder-mediatek-filogic.Linux-x86_64.tar.zst"
SDK_RE = re.compile(r"immortalwrt-sdk-mediatek-filogic_[^/\s]+\.tar\.zst")
VERSION_RE = re.compile(r"r\d+-([0-9a-f]{10,40})")
HASH_RE = re.compile(r"([0-9a-f]{64})\s+[*]?(\S+)")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def parse_checksums(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        match = HASH_RE.fullmatch(line.strip())
        if not match:
            continue
        digest, name = match.groups()
        # Official sha256sums also lists files inside packages/ and kmods/.
        # Accept safe relative paths, but only consume the exact top-level
        # Builder and SDK archive names in resolve().
        parts = name.split("/")
        require(bool(name) and not name.startswith("/") and
                "\\" not in name and all(part not in ("", ".", "..") for part in parts),
                "unsafe checksum filename")
        require(name not in result, f"duplicate checksum entry: {name}")
        result[name] = digest
    return result


PACKAGE_RE = re.compile(r"-?[A-Za-z0-9][A-Za-z0-9_.+\-]*")


def read_packages(path: Path) -> list[str]:
    """Load an auditable ImageBuilder package list without shell interpolation."""
    names: list[str] = []
    seen: set[str] = set()
    for lineno, line in enumerate(path.read_text().splitlines(), start=1):
        name = line.split("#", 1)[0].strip()
        if not name:
            continue
        require(PACKAGE_RE.fullmatch(name) is not None,
                f"{path}:{lineno}: invalid package name: {name!r}")
        require(name not in seen, f"{path}:{lineno}: duplicate package: {name}")
        seen.add(name)
        names.append(name)
    return names


def resolve(index: Path, output: Path) -> dict:
    version = (index / "version.buildinfo").read_text().strip()
    match = VERSION_RE.fullmatch(version)
    require(match is not None, "unrecognized official version.buildinfo")
    checksums = parse_checksums((index / "sha256sums").read_text())
    require(IMAGEBUILDER in checksums, "official ImageBuilder missing from sha256sums")
    sdk_files = [name for name in checksums if SDK_RE.fullmatch(name)]
    require(len(sdk_files) <= 1, "ambiguous official SDK files")
    doc = {
        "schema": 1,
        "source": "ImmortalWrt master SNAPSHOT (official binaries)",
        "target": "mediatek/filogic",
        "version": version,
        "source_revision": match.group(1),
        "imagebuilder": IMAGEBUILDER,
        "imagebuilder_sha256": checksums[IMAGEBUILDER],
        "sdk": sdk_files[0] if sdk_files else None,
        "sdk_sha256": checksums[sdk_files[0]] if sdk_files else None,
        "hardware_validation": "NOT_TESTED",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(doc, indent=2) + "\n")
    return doc


def register_profile(targetinfo: Path) -> None:
    text = targetinfo.read_text()
    require(all(f"Target-Profile: DEVICE_{p}" not in text for p in (PROFILE, PROFILE_V21)),
            "WMA301 already registered in official ImageBuilder")
    # The metadata parser assigns every Target-Profile to the last Target block.
    # Insert in mediatek/filogic, NOT blindly at EOF.
    pattern = re.compile(r"(?m)^Target:\s*mediatek/filogic\s*$")
    targets = list(pattern.finditer(text))
    require(len(targets) == 1, "expected one mediatek/filogic target block")
    begin = targets[0].end()
    following = re.search(r"(?m)^Target:\s*", text[begin:])
    end = begin + following.start() if following else len(text)
    profile = (
        f"\nTarget-Profile: DEVICE_{PROFILE}\n"
        "Target-Profile-Name: TP-Link WMA301 v2.0\n"
        "Target-Profile-Packages: kmod-mt7915e kmod-mt7981-firmware "
        "mt7981-wo-firmware uboot-envtools\n"
        "Target-Profile-hasImageMetadata: 1\n"
        f"Target-Profile-SupportedDevices: {COMPATIBLE}\n"
        "Target-Profile-Description:\n"
        "@@\n"
    )
    v21 = (profile.replace(f"DEVICE_{PROFILE}", f"DEVICE_{PROFILE_V21}")
                   .replace("WMA301 v2.0", "WMA301 v2.1")
                   .replace("tplink,wma301-v2\n", "tplink,wma301-v2-1\n"))
    targetinfo.write_text(text[:end].rstrip("\n") + "\n" + profile + v21 + text[end:])


def locate_kernel(builder: Path) -> tuple[Path, Path]:
    candidates = sorted((builder / "build_dir").glob("target-*/linux-mediatek_filogic"))
    require(len(candidates) == 1, "cannot locate the official filogic kernel build directory")
    kdir = candidates[0]
    require((kdir / "Image").is_file(), "official Image missing; cannot reuse kernel")
    linux = [
        p for p in kdir.glob("linux-*")
        if p.is_dir() and
        (p / "arch/arm64/boot/dts/mediatek/mt7981b.dtsi").is_file()
    ]
    require(len(linux) == 1, "official kernel DTS sources missing from ImageBuilder")
    return kdir, linux[0]


def prepare_kernel_image(kdir: Path) -> Path:
    # Equivalent to the Device's 'kernel-bin | gzip' recipe. The Image is
    # copied from the official build, not rebuilt, reconfigured, or patched.
    dest = kdir / f"{PROFILE}-kernel.bin"
    with (kdir / "Image").open("rb") as src, dest.open("wb") as out:
        subprocess.run(["gzip", "-9", "-n", "-c"], stdin=src, stdout=out, check=True)
    require(dest.stat().st_size > 100_000, "unusually small official gzip kernel")
    # Both hardware revisions use the same official kernel. ImageBuilder
    # resolves the kernel filename from PROFILE, so stage it under both
    # names; the only per-revision payload is the compiled DTB.
    v21 = kdir / f"{PROFILE_V21}-kernel.bin"
    shutil.copyfile(dest, v21)
    require(v21.stat().st_size == dest.stat().st_size,
            "v2.1 official kernel copy is incomplete")
    return dest


def compile_dtb(builder: Path, kdir: Path, linux: Path, headers: Path,
                device_dts: str = DEVICE_DTS) -> Path:
    dts_dir = builder / "target/linux/mediatek/dts"
    src = dts_dir / f"{device_dts}.dts"
    require(src.is_file(), "WMA301 DTS not staged")
    kernel_dts = linux / "arch/arm64/boot/dts"
    dtc = linux / "scripts/dtc/dtc"
    require(dtc.is_file(), "official kernel dtc missing")
    require((headers / "dt-bindings/gpio/gpio.h").is_file(),
            "matching kernel dt-bindings headers missing")
    out = kdir / f"image-{device_dts}.dtb"
    temp = kdir / f"image-{device_dts}.dts.preprocessed"
    cmd = [
        "cpp", "-nostdinc", "-x", "assembler-with-cpp", "-undef", "-D__DTS__",
        "-I", str(dts_dir),
        "-I", str(kernel_dts / "mediatek"),
        "-I", str(kernel_dts),
        "-I", str(kernel_dts / "include"),
        "-I", str(headers),
        "-I", str(linux / "scripts/dtc/include-prefixes"),
        "-o", str(temp), str(src),
    ]
    subprocess.run(cmd, check=True)
    try:
        subprocess.run([str(dtc), "-@", "-O", "dtb", "-i", str(dts_dir),
                        "-o", str(out), str(temp)], check=True)
    finally:
        temp.unlink(missing_ok=True)
    require(out.stat().st_size > 1_000, "unusually small WMA301 DTB")
    return out


def stage_custom_files(overlay: Path) -> list[str]:
    """Stage source-controlled files; optional OTA is off unless explicitly enabled."""
    return stage_files(ROOT / "files", overlay)


def stage(builder: Path, upstream: Path, overlay: Path, expected_source: str,
          headers: Path, aurora_source: Path) -> None:
    require(re.fullmatch(r"[0-9a-f]{40}", expected_source) is not None,
            "expected-source must be a full Git commit SHA")
    actual = subprocess.check_output(
        ["git", "-C", str(upstream), "rev-parse", "HEAD"], text=True
    ).strip()
    require(actual == expected_source, "official source/Builder revision mismatch")
    require((builder / "target/linux/mediatek/image/filogic.mk").is_file(),
            "not an official mediatek/filogic ImageBuilder")
    require((builder / ".targetinfo").is_file(), "ImageBuilder metadata missing")
    require((builder / ".config").is_file(), "ImageBuilder .config missing")
    config = (builder / ".config").read_text()
    require("CONFIG_TARGET_mediatek_filogic=y" in config,
            "wrong ImageBuilder target")
    require("CONFIG_TARGET_ROOTFS_SQUASHFS=y" in config,
            "official Builder lacks squashfs support")
    require(not overlay.exists(), "firmware overlay destination already exists")

    # Reuse the existing upstream integration to generate board-specific
    # network, upgrade, Wi-Fi MAC, and U-Boot environment scripts at the
    # *same source revision* as the official compiled packages.
    prepare(upstream)
    filogic = "target/linux/mediatek/filogic/base-files"
    sources = {
        f"{filogic}/etc/board.d/02_network": "etc/board.d/02_network",
        f"{filogic}/lib/upgrade/platform.sh": "lib/upgrade/platform.sh",
        f"{filogic}/etc/hotplug.d/ieee80211/11_fix_wifi_mac":
            "etc/hotplug.d/ieee80211/11_fix_wifi_mac",
        "package/boot/uboot-tools/uboot-envtools/files/mediatek_filogic":
            "etc/uci-defaults/30_uboot-envtools",
    }
    for source, relative in sources.items():
        dst = overlay / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(upstream / source, dst)
        # Preserve executable mode of the upstream board/hotplug helpers.
        # UCI defaults must always be executable for first boot.
        if relative.startswith("etc/uci-defaults/"):
            dst.chmod(dst.stat().st_mode | 0o111)

    staged = stage_custom_files(overlay)
    print(f"Portable LuCI settings staged: {staged}")
    # Package Aurora with the official host apk. The resulting local noarch
    # package is installed by ImageBuilder itself; FILES= must not own its paths.
    theme = build_aurora_apk(aurora_source, builder)
    print(f"Native Aurora APK for ImageBuilder: {theme['filename']}")
    for forbidden in (
        "www/luci-static/aurora",
        "usr/share/ucode/luci/template/themes/aurora",
        "usr/share/licenses/luci-theme-aurora",
    ):
        require(not (overlay / forbidden).exists(),
                f"Aurora must be owned by APK, not FILES: {forbidden}")

    dts_dir = builder / "target/linux/mediatek/dts"
    require(dts_dir.is_dir(), "ImageBuilder lacks mediatek DTS directory")
    for name in (f"{DEVICE_DTS}-common.dtsi", f"{DEVICE_DTS}.dts",
                 f"{DEVICE_DTS_V21}.dts"):
        dest = dts_dir / name
        require(not dest.exists(), f"official Builder already defines {name}")
        shutil.copy2(ROOT / "device" / name, dest)

    filogic_mk = builder / "target/linux/mediatek/image/filogic.mk"
    original = filogic_mk.read_text()
    require(all(f"define Device/{p}" not in original for p in (PROFILE, PROFILE_V21)),
            "official image rules already define WMA301")
    filogic_mk.write_text(original.rstrip() +
                          "\n\n# Local WMA301 profile (ImageBuilder only)\n" +
                          DEVICE + "\n")
    register_profile(builder / ".targetinfo")
    (builder / ".profiles.mk").unlink(missing_ok=True)

    kdir, linux = locate_kernel(builder)
    dtb = compile_dtb(builder, kdir, linux, headers)
    dtb_v21 = compile_dtb(builder, kdir, linux, headers, DEVICE_DTS_V21)
    kernel = prepare_kernel_image(kdir)
    print(f"Official kernel reused: {kernel}")
    print(f"Local WMA301 DTB: {dtb}; v2.1: {dtb_v21}")
    print(f"Official ABI retained; firmware overlay: {overlay}")


def main() -> None:
    parser = argparse.ArgumentParser()
    cmds = parser.add_subparsers(dest="command", required=True)
    r = cmds.add_parser("resolve", help="resolve official snapshot metadata")
    r.add_argument("--index", type=Path, required=True)
    r.add_argument("--output", type=Path, required=True)
    s = cmds.add_parser("stage", help="extend an unpacked official ImageBuilder")
    s.add_argument("--builder", type=Path, required=True)
    s.add_argument("--upstream", type=Path, required=True)
    s.add_argument("--overlay", type=Path, required=True)
    s.add_argument("--expected-source", required=True)
    s.add_argument("--kernel-headers", type=Path, required=True)
    s.add_argument("--aurora-source", type=Path, required=True)
    p = cmds.add_parser("packages", help="print validated ImageBuilder package names")
    p.add_argument("--file", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "resolve":
        print(json.dumps(resolve(args.index, args.output), indent=2))
    elif args.command == "packages":
        print(" ".join(read_packages(args.file)))
    else:
        stage(args.builder.resolve(), args.upstream.resolve(),
              args.overlay.resolve(), args.expected_source,
              args.kernel_headers.resolve(), args.aurora_source.resolve())


if __name__ == "__main__":
    main()
