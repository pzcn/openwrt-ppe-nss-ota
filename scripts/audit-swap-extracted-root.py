#!/usr/bin/env python3
"""Audit the ACTUAL disposable APK-installed root, not only solver output.

Does not execute target binaries; checks exact pinned APK database versions,
kernel module tree, F2FS and NSS on-disk files and boot-autoload hints.
A successful file-level audit is NOT an actual IPQ60xx boot test.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sp = importlib.util.spec_from_file_location(
    "swap_world_installed_audit", ROOT / "scripts/audit-swap-official-world.py")
stock = importlib.util.module_from_spec(sp)
assert sp.loader
sp.loader.exec_module(stock)


def find_modules(rootfs: Path, phrase: str) -> list[str]:
    prefix = rootfs / "lib/modules/6.18.60"
    if not prefix.is_dir():
        return []
    return sorted(str(x.relative_to(rootfs)) for x in prefix.rglob("*")
                  if x.is_file() and ".ko" in x.name and phrase in x.name.lower())


def inspect(rootfs: Path, plan: dict) -> dict:
    db = rootfs / "lib/apk/db/installed"
    if not db.is_file():
        raise ValueError("Disposable root has no APK installed DB")
    installed = stock.parse_installed_plaintext(db.read_text())
    by_name = {p["name"]: p["version"] for p in installed}
    missing = []
    wrong = []
    for requirement in plan["roots"]:
        name, version = requirement["name"], requirement["version"]
        if name not in by_name:
            missing.append(name)
        elif by_name[name] != version:
            wrong.append({"name": name, "expected": version,
                          "actual": by_name[name]})
    kernel_release_dirs = []
    mods = rootfs / "lib/modules"
    if mods.is_dir():
        kernel_release_dirs = sorted(p.name for p in mods.iterdir()
                                     if p.is_dir())
    f2fs = find_modules(rootfs, "f2fs")
    nss = find_modules(rootfs, "nss")
    wg = find_modules(rootfs, "wireguard")
    init_paths = list((rootfs / "etc/modules-boot.d").glob("*")) \
        if (rootfs / "etc/modules-boot.d").is_dir() else []
    mod_paths = list((rootfs / "etc/modules.d").glob("*")) \
        if (rootfs / "etc/modules.d").is_dir() else []
    f2fs_boot = [str(x.relative_to(rootfs)) for x in init_paths
                 if "f2fs" in x.name.lower() or
                 (x.is_file() and "f2fs" in x.read_text(errors="replace").lower())]
    f2fs_autoload = [str(x.relative_to(rootfs)) for x in mod_paths
                     if "f2fs" in x.name.lower() or
                     (x.is_file() and "f2fs" in x.read_text(errors="replace").lower())]
    old_kmods = [k for k in by_name if
                 (k == "kernel" or k.startswith("kmod-")) and
                 by_name[k].startswith("6.18.55")]
    module_ok = kernel_release_dirs == ["6.18.60"] and bool(f2fs) and bool(wg) and bool(nss)
    installed_ok = not missing and not wrong and not old_kmods
    return {
        "schema": 1, "status": "disposable-installed-root-inventory",
        "apk_installed_package_count": len(installed),
        "exact_plan_pins_verified": installed_ok,
        "missing_plan_packages": missing,
        "mismatched_plan_versions": wrong,
        "unexpected_6_18_55_kernel_packages": old_kmods,
        "kernel_module_directories": kernel_release_dirs,
        "f2fs_kernel_module_files": f2fs,
        "nss_kernel_module_files": nss,
        "wireguard_kernel_module_files": wg,
        "f2fs_boot_autoload_files": sorted(f2fs_boot),
        "f2fs_regular_autoload_files": sorted(f2fs_autoload),
        "module_tree_structure_verified": module_ok,
        "package_scripts_executed": False,
        "early_overlay_boot_proven": False,
        "runtime_abi_verified": False,
        "file_provenance_digest_verified": False,
        "flashable_firmware_created": False,
        "publishable": False,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--rootfs", type=Path, required=True)
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    report = inspect(args.rootfs, json.loads(args.plan.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("Scratch installed APKs:", report["apk_installed_package_count"])
    print("Exact-version roots verified:", report["exact_plan_pins_verified"])
    print("Kernel module directories:", report["kernel_module_directories"])
    print("F2FS module files:", report["f2fs_kernel_module_files"][:6])
    print("F2FS early boot autoload:", report["f2fs_boot_autoload_files"])
    print("NSS module files:", report["nss_kernel_module_files"][:8])
    print("WireGuard module files:", report["wireguard_kernel_module_files"][:6])
    print("File layout only; no firmware or hardware boot verified.")


if __name__ == "__main__":
    main()
