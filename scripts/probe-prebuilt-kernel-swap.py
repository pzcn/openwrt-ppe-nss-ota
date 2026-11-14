#!/usr/bin/env python3
"""Inspect RE-SS-01 OpenWrt sysupgrade TARs to compare prebuilt FIT kernels.

The device image recipe is 'sysupgrade-tar | append-metadata', NOT a raw FIT
image. Extract only the embedded kernel and root members. Never assemble or
publish flashable firmware from this read-only compatibility experiment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import tarfile
from pathlib import Path, PurePosixPath

FIT_MAGIC = b"\xd0\x0d\xfe\xed"
SQUASHFS_MAGIC = b"hsqs"
KERNEL_PARTITION_LIMIT = 6144 * 1024  # both RE-SS-01 upstream device recipes
MAX_ROOTFS_MEMBER = 128 * 1024 * 1024
MIN_SQUASHFS_HEADER = 96


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_tar_member_name(name: str) -> bool:
    path = PurePosixPath(name)
    return not path.is_absolute() and all(p not in ("", ".", "..") for p in path.parts)


def read_sysupgrade_members(path: Path, name: str) -> tuple[bytes, bytes, dict]:
    try:
        with tarfile.open(path, mode="r:") as archive:
            members = archive.getmembers()
            if len(members) > 512:
                raise ValueError(f"{name}: excessive sysupgrade member count")
            for m in members:
                if not safe_tar_member_name(m.name):
                    raise ValueError(f"{name}: unsafe tar member path")
            kernels = [m for m in members
                       if m.isfile() and m.name.endswith("/kernel")]
            roots = [m for m in members
                     if m.isfile() and m.name.endswith("/root")]
            if len(kernels) != 1 or len(roots) != 1:
                raise ValueError(f"{name}: expected unique sysupgrade kernel/root entries")
            kern, root = kernels[0], roots[0]
            if kern.name.rsplit("/", 1)[0] != root.name.rsplit("/", 1)[0]:
                raise ValueError(f"{name}: kernel/root belong to different profiles")
            if kern.size < 1024 or kern.size > KERNEL_PARTITION_LIMIT:
                raise ValueError(f"{name}: kernel member exceeds RE-SS-01 partition limit")
            if root.size < MIN_SQUASHFS_HEADER or root.size > MAX_ROOTFS_MEMBER:
                raise ValueError(f"{name}: invalid rootfs member size")
            kernel_file = archive.extractfile(kern)
            root_file = archive.extractfile(root)
            if kernel_file is None or root_file is None:
                raise ValueError(f"{name}: missing sysupgrade payload")
            kernel = kernel_file.read()
            rootfs = root_file.read()
            return kernel, rootfs, {
                "sysupgrade_prefix": kern.name.rsplit("/", 1)[0],
                "kernel_member": kern.name,
                "rootfs_member": root.name,
                "kernel_member_bytes": len(kernel),
                "rootfs_member_bytes": len(rootfs),
            }
    except (tarfile.TarError, EOFError) as e:
        raise ValueError(f"{name}: invalid sysupgrade TAR: {e}") from e


def inspect_sysupgrade(path: Path, *, extracted: Path | None = None,
                       name: str = "firmware") -> dict:
    kernel, rootfs, meta = read_sysupgrade_members(path, name)
    if kernel[:4] != FIT_MAGIC:
        raise ValueError(f"{name}: kernel TAR member is not an ARM64 FIT")
    fit_size = struct.unpack_from(">I", kernel, 4)[0]
    if not (1024 < fit_size <= len(kernel) <= KERNEL_PARTITION_LIMIT):
        raise ValueError(f"{name}: invalid FIT size outside RE-SS-01 kernel limit")
    if rootfs[:4] != SQUASHFS_MAGIC:
        raise ValueError(f"{name}: expected SquashFS root TAR member")
    major, minor = struct.unpack_from("<HH", rootfs, 28)
    if (major, minor) != (4, 0):
        raise ValueError(f"{name}: unsupported squashfs format {major}.{minor}")
    bytes_used = struct.unpack_from("<Q", rootfs, 40)[0]
    if not (MIN_SQUASHFS_HEADER < bytes_used <= len(rootfs)):
        raise ValueError(f"{name}: invalid squashfs size {bytes_used}")
    fit = kernel[:fit_size]
    squashfs = rootfs[:bytes_used]
    if extracted is not None:
        extracted.mkdir(parents=True, exist_ok=True)
        (extracted / f"{name}.fit").write_bytes(fit)
        (extracted / f"{name}.squashfs").write_bytes(squashfs)
    return {
        **meta,
        "sysupgrade_format": "openwrt-sysupgrade-tar",
        "filename": path.name,
        "file_bytes": path.stat().st_size,
        "fit_bytes": fit_size,
        "fit_sha256": sha256(fit),
        "kernel_max_bytes": KERNEL_PARTITION_LIMIT,
        "rootfs_bytes": bytes_used,
        "rootfs_sha256": sha256(squashfs),
        "squashfs_version": "4.0",
        "kernel_padding_bytes": len(kernel) - fit_size,
        "rootfs_padding_bytes": len(rootfs) - bytes_used,
    }


def compare(imm: dict, julius: dict) -> dict:
    return {
        "schema": 2,
        "status": "experimental-inspection-only-not-flashable",
        "hardware": "jdcloud,re-ss-01",
        "board": "qualcommax/ipq60xx",
        "official_immortalwrt": imm,
        "julius_ppe_nss": julius,
        "same_layout": (
            imm["sysupgrade_format"] == julius["sysupgrade_format"] and
            imm["squashfs_version"] == julius["squashfs_version"] and
            imm["kernel_max_bytes"] == julius["kernel_max_bytes"]
        ),
        "julius_kernel_fits_target_partition": julius["kernel_member_bytes"] <= KERNEL_PARTITION_LIMIT,
        "same_kernel_binary": imm["fit_sha256"] == julius["fit_sha256"],
        "official_kmods_must_not_be_used_with_julius_kernel": True,
        "julius_kmods_and_firmware_must_be_provided": True,
        "kernel_abi_verified": False,
        "f2fs_boot_support_verified": False,
        "nss_services_verified": False,
        "flashable_image_produced": False,
        "publishable": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--immortalwrt", type=Path, required=True)
    parser.add_argument("--julius", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--extract-dir", type=Path)
    args = parser.parse_args()
    imm = inspect_sysupgrade(args.immortalwrt, extracted=args.extract_dir, name="immortalwrt")
    julius = inspect_sysupgrade(args.julius, extracted=args.extract_dir, name="julius")
    report = compare(imm, julius)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print("ImmortalWrt FIT/rootfs bytes:", imm["fit_bytes"], imm["rootfs_bytes"])
    print("Julius FIT/rootfs bytes:", julius["fit_bytes"], julius["rootfs_bytes"])
    print("TAR/FIT layout compatible:", report["same_layout"])
    print("No firmware built. Kernel module ABI remains unverified.")


if __name__ == "__main__":
    main()
