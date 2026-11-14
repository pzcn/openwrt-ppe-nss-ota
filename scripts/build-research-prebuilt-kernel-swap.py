#!/usr/bin/env python3
"""Create a NON-FLASHABLE RESEARCH TAR: Julius FIT + untouched ImmortalWrt root.

This proves that the device-specific kernel TAR member can be substituted
without modifying the official ImmortalWrt SquashFS payload. The research
archive intentionally has NO sysupgrade metadata/signature; it is not a
deployable firmware image. Matching Julius kmods still must be installed.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import io
import json
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sp = importlib.util.spec_from_file_location(
    "prebuilt_swap_probe", HERE / "probe-prebuilt-kernel-swap.py")
probe = importlib.util.module_from_spec(sp)
assert sp.loader
sp.loader.exec_module(probe)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def swap_kernel(official: Path, donor: Path, output: Path) -> dict:
    official_kernel, official_root, meta = probe.read_sysupgrade_members(
        official, "official_immortalwrt")
    julius_kernel, _julius_root, jul_meta = probe.read_sysupgrade_members(
        donor, "julius_nss")
    if official_kernel[:4] != probe.FIT_MAGIC or julius_kernel[:4] != probe.FIT_MAGIC:
        raise ValueError("Both kernels must be verified FIT images")
    if len(julius_kernel) > probe.KERNEL_PARTITION_LIMIT:
        raise ValueError("Julius FIT exceeds board partition")
    if official_root[:4] != probe.SQUASHFS_MAGIC:
        raise ValueError("Not an official ImmortalWrt SquashFS image")
    output.parent.mkdir(parents=True, exist_ok=True)
    originals: dict[str, str] = {}
    try:
        with tarfile.open(official, "r:") as source, tarfile.open(output, "w") as result:
            for member in source.getmembers():
                if not probe.safe_tar_member_name(member.name):
                    raise ValueError("Unsafe original TAR entry")
                if member.isfile():
                    stream = source.extractfile(member)
                    if stream is None:
                        raise ValueError("Missing TAR member payload")
                    data = stream.read()
                    originals[member.name] = sha(data)
                    if member.name == meta["kernel_member"]:
                        data = julius_kernel
                    new_member = copy.copy(member)
                    new_member.size = len(data)
                    result.addfile(new_member, io.BytesIO(data))
                elif member.isdir():
                    result.addfile(copy.copy(member))
                else:
                    raise ValueError("Unexpected special sysupgrade TAR member")
        swapped_kernel, swapped_root, swapped = probe.read_sysupgrade_members(
            output, "research_tar")
        if (sha(swapped_kernel) != sha(julius_kernel)
                or sha(swapped_root) != sha(official_root)):
            raise ValueError("Kernel substitution changed payload identity")
        if swapped["sysupgrade_prefix"] != meta["sysupgrade_prefix"]:
            raise ValueError("Official board metadata path changed")
    except Exception:
        output.unlink(missing_ok=True)
        raise
    return {
        "schema": 1,
        "status": "research-tar-only-NOT-flashable",
        "device": "jdcloud,re-ss-01",
        "official_firmware_sha256": sha(official.read_bytes()),
        "julius_firmware_sha256": sha(donor.read_bytes()),
        "new_kernel_sha256": sha(julius_kernel),
        "official_rootfs_sha256": sha(official_root),
        "kernel_member": swapped["kernel_member"],
        "rootfs_member": swapped["rootfs_member"],
        "untouched_official_tar_entry_sha256": {
            k: v for k, v in sorted(originals.items()) if k != meta["kernel_member"]
        },
        "research_tar_sha256": sha(output.read_bytes()),
        "same_device_kernel_fit": (meta["kernel_member"].endswith("/kernel") and
                                   jul_meta["kernel_member"].endswith("/kernel")),
        "official_immortalwrt_userland_retained": True,
        "foreign_kernel_modules_present": True,
        "julius_module_abi_migrated": False,
        "f2fs_from_matching_julius_prebuilt_ib_installed": False,
        "package_database_reconciled": False,
        "sysupgrade_metadata_and_signature_present": False,
        "boot_tested": False,
        "publishable": False,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--immortalwrt", type=Path, required=True)
    p.add_argument("--julius", type=Path, required=True)
    p.add_argument("--research-tar", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    args = p.parse_args()
    report = swap_kernel(args.immortalwrt, args.julius, args.research_tar)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("PASS byte-exact Jules FIT substitution; ImmortalWrt rootfs unchanged")
    print("BLOCKED: no matching module APK database, no valid signed sysupgrade")
    print("This research TAR is deliberately not flashable.")


if __name__ == "__main__":
    main()
