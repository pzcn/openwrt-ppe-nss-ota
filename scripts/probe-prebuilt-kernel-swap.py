#!/usr/bin/env python3
"""Read-only FIT + squashfs inspection for an ImmortalWrt/Julius kernel swap.

This script DOES NOT assemble, sign, or publish flashable firmware. It verifies
that the two official RE-SS-01 sysupgrade files share the same physical image
layout before any attempt to substitute a kernel or its ABI-bound modules.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

FIT_MAGIC = b"\xd0\x0d\xfe\xed"
SQUASHFS_MAGIC = b"hsqs"
KERNEL_PARTITION_LIMIT = 6144 * 1024  # both upstream jdcloud RE-SS-01 recipes
BLOCK = 64 * 1024
MIN_SQUASHFS_HEADER = 96


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inspect_sysupgrade(path: Path, *, extracted: Path | None = None,
                       name: str = "firmware") -> dict:
    data = path.read_bytes()
    if len(data) < 1024 * 1024:
        raise ValueError(f"Firmware too small: {name}")
    if data[:4] != FIT_MAGIC:
        raise ValueError(f"{name}: expected an ARM64 FIT image at byte zero, not a raw/UBI image")
    if len(data) < 40:
        raise ValueError(f"{name}: incomplete FIT header")
    fit_size = struct.unpack_from(">I", data, 4)[0]
    if not (1024 < fit_size <= KERNEL_PARTITION_LIMIT):
        raise ValueError(f"{name}: FIT size {fit_size} outside RE-SS-01 kernel limit")
    offsets = [offset for offset in range(
        (fit_size + BLOCK - 1) // BLOCK * BLOCK, KERNEL_PARTITION_LIMIT + 1, BLOCK
    ) if data[offset:offset + 4] == SQUASHFS_MAGIC]
    if len(offsets) != 1:
        raise ValueError(f"{name}: expected exactly one 64KiB-aligned squashfs after FIT, got {offsets}")
    rootfs_at = offsets[0]
    if rootfs_at < fit_size:
        raise ValueError(f"{name}: rootfs overlaps FIT")
    if len(data) < rootfs_at + MIN_SQUASHFS_HEADER:
        raise ValueError(f"{name}: truncated squashfs header")
    major, minor = struct.unpack_from("<HH", data, rootfs_at + 28)
    if (major, minor) != (4, 0):
        raise ValueError(f"{name}: unsupported squashfs format {major}.{minor}")
    bytes_used = struct.unpack_from("<Q", data, rootfs_at + 40)[0]
    if not (MIN_SQUASHFS_HEADER < bytes_used <= len(data) - rootfs_at):
        raise ValueError(f"{name}: invalid squashfs size {bytes_used}")
    fit = data[:fit_size]
    rootfs = data[rootfs_at:rootfs_at + bytes_used]
    if extracted is not None:
        extracted.mkdir(parents=True, exist_ok=True)
        (extracted / f"{name}.fit").write_bytes(fit)
        (extracted / f"{name}.squashfs").write_bytes(rootfs)
    return {
        "filename": path.name,
        "file_bytes": len(data),
        "file_sha256": sha256(data),
        "fit_bytes": fit_size,
        "fit_sha256": sha256(fit),
        "kernel_max_bytes": KERNEL_PARTITION_LIMIT,
        "rootfs_offset": rootfs_at,
        "rootfs_bytes": bytes_used,
        "rootfs_sha256": sha256(rootfs),
        "squashfs_version": "4.0",
        "kernel_padding_bytes": rootfs_at - fit_size,
    }


def compare(imm: dict, julius: dict) -> dict:
    return {
        "schema": 1,
        "status": "experimental-inspection-only-not-flashable",
        "hardware": "jdcloud,re-ss-01",
        "board": "qualcommax/ipq60xx",
        "official_immortalwrt": imm,
        "julius_ppe_nss": julius,
        "same_layout": all((
            imm["squashfs_version"] == julius["squashfs_version"],
            imm["kernel_max_bytes"] == julius["kernel_max_bytes"],
            imm["rootfs_offset"] % BLOCK == 0,
            julius["rootfs_offset"] % BLOCK == 0,
        )),
        "julius_kernel_fits_target_partition": julius["fit_bytes"] <= KERNEL_PARTITION_LIMIT,
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
    print("ImmortalWrt FIT/rootfs: ", imm["fit_bytes"], imm["rootfs_bytes"])
    print("Julius NSS FIT/rootfs: ", julius["fit_bytes"], julius["rootfs_bytes"])
    print("FIT layout compatible:", report["same_layout"])
    print("No flashable firmware built. Kernel module ABI remains unverified.")


if __name__ == "__main__":
    main()
