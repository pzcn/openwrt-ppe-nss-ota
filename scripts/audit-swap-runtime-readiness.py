#!/usr/bin/env python3
"""Audit the boot/upgrade layer and static module ABI of an APK-only mixed root.

Compares carefully selected files in the SHA-pinned original ImmortalWrt
SquashFS against the installed disposable mixed APK root. Reports evidence
without silently copying boot configuration or claiming runtime compatibility.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

EXPECTED_KERNEL_RELEASE = "6.18.60"
# Inspect the boot path, board configuration, startup services and upgrade
# scripts. Do not copy files from the original root: some bind old kernel ABI.
BOOT_BASELINE = (
    "bin/sh",
    "sbin/init",
    "etc/preinit",
    "etc/inittab",
    "etc/openwrt_release",
    "etc/board.d",
    "etc/config",
    "etc/hotplug.d",
    "etc/init.d",
    "etc/uci-defaults",
    "lib/preinit",
    "lib/upgrade",
    "lib/functions.sh",
)


def path_signature(path: Path) -> tuple[str, str] | None:
    """Return file-type-aware signature; do not dereference symlinks."""
    try:
        kind = path.lstat().st_mode
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(kind):
        return ("symlink", os.readlink(path))
    if stat.S_ISDIR(kind):
        return ("directory", "")
    if stat.S_ISREG(kind):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for data in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(data)
        return ("file", digest.hexdigest())
    return ("special", stat.filemode(kind))


def inventory(base: Path) -> dict[str, tuple[str, str]]:
    if not base.is_dir():
        raise ValueError("Missing scan directory " + str(base))
    results = {}
    for root in BOOT_BASELINE:
        rootpath = base / root
        if path_signature(rootpath) is None:
            continue
        scan = [rootpath]
        if rootpath.is_dir() and not rootpath.is_symlink():
            scan.extend(rootpath.rglob("*"))
        for item in scan:
            signature = path_signature(item)
            if signature is not None:
                results[str(item.relative_to(base))] = signature
    return results


def compare_roots(official: Path, mixed: Path) -> dict:
    before = inventory(official)
    after = inventory(mixed)
    missing = sorted(set(before) - set(after))
    modified = sorted(path for path in before.keys() & after.keys()
                      if before[path] != after[path])
    unexpected = sorted(set(after) - set(before))
    # A failed comparison is a diagnostic, not permission to transplant the
    # old official kernel modules or blindly overwrite Julius init scripts.
    return {
        "original_boot_paths": len(before),
        "mixed_boot_paths": len(after),
        "identical_original_boot_paths": len(set(before) & set(after)) - len(modified),
        "missing_original_boot_paths": missing,
        "different_original_boot_paths": modified,
        "additional_mixed_boot_paths": unexpected,
        "missing_boot_path_count": len(missing),
        "different_boot_path_count": len(modified),
        "unchanged_stock_boot_files": not missing and not modified,
        "baseline_original_files": [p for p in BOOT_BASELINE if p in before],
        "baseline_mixed_files": [p for p in BOOT_BASELINE if p in after],
        "missing_top_level_boot_paths": [p for p in BOOT_BASELINE
                                         if p in before and p not in after],
    }


def scan_vermagic(root: Path, expected: str = EXPECTED_KERNEL_RELEASE) -> dict:
    module_root = root / "lib/modules"
    if not module_root.is_dir():
        raise ValueError("Missing /lib/modules in disposable root")
    releases = sorted(p.name for p in module_root.iterdir() if p.is_dir())
    found = []
    missing = []
    wrong = []
    compressed = []
    for path in sorted(module_root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if path.name.endswith((".ko.gz", ".ko.zst", ".ko.xz")):
            compressed.append(str(path.relative_to(root)))
            continue
        if not path.name.endswith(".ko"):
            continue
        relative = str(path.relative_to(root))
        data = path.read_bytes()
        # Linux .ko ELF modules carry a NUL-terminated .modinfo vermagic
        # string. The payload may be stripped, but never rely on filename only.
        match = re.search(rb"(?:^|\x00)vermagic=([^\x00]+)", data)
        if not match:
            missing.append(relative)
            continue
        value = match.group(1).decode("ascii", "replace")
        found.append(relative)
        if value.split()[0] != expected:
            wrong.append({"path": relative, "vermagic": value})
    return {
        "kernel_module_directories": releases,
        "modules_with_vermagic": len(found),
        "modules_missing_vermagic": missing,
        "modules_wrong_vermagic": wrong,
        "compressed_modules_not_scanned": compressed,
        "matching_module_version_strings": (
            releases == [expected] and bool(found) and
            not missing and not wrong and not compressed
        ),
        "modules_dep_file_present": (module_root / expected / "modules.dep").is_file(),
        "modules_alias_file_present": (module_root / expected / "modules.alias").is_file(),
        "nss_wifi_module_present": any("nss-wifi-drv" in p for p in found),
        "f2fs_module_present": any(p.endswith("/f2fs.ko") for p in found),
        "wireguard_module_present": any(p.endswith("/wireguard.ko") for p in found),
        "vermagic_is_not_runtime_symbol_or_hardware_proof": True,
    }


def analyze(official_squashfs: Path, mixed_root: Path) -> dict:
    if not official_squashfs.is_file() or not mixed_root.is_dir():
        raise ValueError("Missing original SquashFS or mixed root")
    with tempfile.TemporaryDirectory(prefix="swap-stock-boot-",
                                     dir=os.environ.get("RUNNER_TEMP")) as tmp:
        extracted = Path(tmp) / "official"
        subprocess.run(
            ["unsquashfs", "-no-progress", "-no-xattrs", "-d",
             str(extracted), str(official_squashfs), *BOOT_BASELINE],
            check=True, stdout=subprocess.DEVNULL,
        )
        boot = compare_roots(extracted, mixed_root)
    abi = scan_vermagic(mixed_root)
    return {
        "schema": 1,
        "status": "static-boot-and-module-vermagic-diagnostics-only",
        "comparison": boot,
        "kernel_abi_string_inspection": abi,
        "base_userland_upgrade_scripts_identical_to_stock":
            boot["unchanged_stock_boot_files"],
        "target_postinstall_scripts_executed": False,
        "first_boot_uci_defaults_executed": False,
        "early_f2fs_mount_tested": False,
        "nss_runtime_verified": False,
        "sysupgrade_configuration_preservation_tested": False,
        "fullcone_nat_parity_verified": False,
        "readiness_for_flash_proven": False,
        "publishable": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official-squashfs", type=Path, required=True)
    parser.add_argument("--mixed-rootfs", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = analyze(args.official_squashfs, args.mixed_rootfs)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    boot = report["comparison"]
    abi = report["kernel_abi_string_inspection"]
    print("Original boot paths:", boot["original_boot_paths"])
    print("Mixed boot paths:", boot["mixed_boot_paths"])
    print("Missing stock boot paths:", boot["missing_boot_path_count"])
    print("Changed stock boot paths:", boot["different_boot_path_count"])
    print("Missing core root files:", boot["missing_top_level_boot_paths"])
    print("Modules carrying release-matched vermagic:", abi["modules_with_vermagic"])
    print("Modules with missing/wrong vermagic:",
          len(abi["modules_missing_vermagic"]), len(abi["modules_wrong_vermagic"]))
    print("Static checks only. No runtime, sysupgrade or NSS boot verified.")


if __name__ == "__main__":
    main()
