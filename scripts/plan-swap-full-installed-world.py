#!/usr/bin/env python3
"""Check the entire stock ImmortalWrt installed world against Julius kmods.

For kernel/kmods: the donor must provide a package with the same name.
For userspace: the exact package/version INSTALLED in the official image
must remain available in the frozen official signed index.
The sole reviewed diagnostic exception is Julius firewall4 (fullcone module).
This does not produce a flashable image or hide missing modules.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "swap_full_stock", ROOT / "scripts/audit-swap-official-world.py")
stock = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(stock)

dep_sp = importlib.util.spec_from_file_location(
    "swap_dependency_index", ROOT / "scripts/hybrid-dependency-audit.py")
dep = importlib.util.module_from_spec(dep_sp)
assert dep_sp.loader
dep_sp.loader.exec_module(dep)

MANDATORY_EXTRA_MODULES = ("kmod-fs-f2fs", "kmod-nss-wifi-drv",
                           "kmod-wireguard")
WORLD_NAME = re.compile(r"^([A-Za-z0-9][A-Za-z0-9+._-]*)")


def choose_exact(index: list[dict], name: str, version: str | None = None) -> dict | None:
    variants = [p for p in index if p["name"] == name and
                (version is None or p["version"] == version)]
    unique = {(x["version"], x["arch"]) for x in variants}
    if len(unique) != 1:
        return None
    return variants[0]


def plan(installed: list[dict], world: str,
         donor: list[dict], official: dict[str, list[dict]]) -> dict:
    if any(feed not in official for feed in stock.FEEDS):
        raise ValueError("Incomplete official index set")
    official_all = [p for feed in stock.FEEDS for p in official[feed]]
    installed_by_name = {p["name"]: p for p in installed}
    if len(installed_by_name) != len(installed):
        raise ValueError("Duplicate installed stock package")
    donor_available = {p["name"] for p in donor}
    missing_kmods: list[str] = []
    missing_userland: list[str] = []
    pins = []
    roots = []
    for pkg in sorted(installed, key=lambda x: x["name"]):
        name = pkg["name"]
        if name == "kernel" or name.startswith("kmod-"):
            item = choose_exact(donor, name)
            if not item:
                missing_kmods.append(name)
                continue
            origin = "julius-kernel"
        elif name == "firewall4":
            item = choose_exact(donor, name)
            if not item:
                missing_userland.append(name + ":julius-firewall4-missing")
                continue
            origin = "julius-firewall4-exception"
        else:
            item = choose_exact(official_all, name, pkg["version"])
            if not item:
                missing_userland.append(name + ":official-version-unavailable")
                continue
            origin = "immortalwrt-exact-installed"
        rows = {
            "name": name, "version": item["version"],
            "original_version": pkg["version"],
            "origin": origin,
            "pin": name + "=" + item["version"],
            "depends": item.get("depends", []),
        }
        roots.append(rows)
        pins.append(rows["pin"])

    # Explicitly require NSS and overlay/F2FS modules even if absent from
    # official stock, but never duplicate a root already installed.
    for name in MANDATORY_EXTRA_MODULES:
        if name in installed_by_name:
            continue
        item = choose_exact(donor, name)
        if item is None:
            missing_kmods.append(name)
            continue
        rows = {"name": name, "version": item["version"],
                "original_version": None,
                "origin": "julius-added-kmod",
                "pin": name + "=" + item["version"],
                "depends": item.get("depends", [])}
        roots.append(rows)
        pins.append(rows["pin"])

    world_roots = []
    for line in world.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = WORLD_NAME.match(line)
        if not m:
            raise ValueError("Invalid official world package requirement: " + line)
        world_roots.append(m.group(1))
    missing_world = sorted(set(world_roots) - set(installed_by_name))
    if not any(p["name"] == "kernel" and p["origin"] == "julius-kernel" for p in roots):
        missing_kmods.append("kernel")
    return {
        "schema": 1,
        "status": "full-installed-world-swap-plan-incomplete-until-verified",
        "stock_installed_count": len(installed),
        "stock_world_roots": len(world_roots),
        "stock_installed_kernel_kmod_count": sum(
            p["name"] == "kernel" or p["name"].startswith("kmod-")
            for p in installed),
        "exact_official_userland_pinned_count": sum(
            p["origin"] == "immortalwrt-exact-installed" for p in roots),
        "julius_firewall4_exception_count": sum(
            p["origin"] == "julius-firewall4-exception" for p in roots),
        "julius_kernel_kmod_pinned_count": sum(
            p["origin"] in ("julius-kernel", "julius-added-kmod")
            for p in roots),
        "missing_stock_kernel_or_kmods": sorted(set(missing_kmods)),
        "missing_stock_userland": sorted(set(missing_userland)),
        "world_roots_not_installed": missing_world,
        "roots": roots,
        "version_pins": pins,
        "complete_stock_kernel_kmod_coverage": not missing_kmods,
        "complete_stock_userland_coverage": not missing_userland,
        "full_world_solver_passed": False,
        "file_overlap_abi_verified": False,
        "publishable": False,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--installed-db", type=Path, required=True)
    ap.add_argument("--world", type=Path, required=True)
    ap.add_argument("--donor-index", type=Path, required=True)
    ap.add_argument("--official-index-dir", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--pins", type=Path, required=True)
    args = ap.parse_args()
    installed = stock.parse_installed_plaintext(args.installed_db.read_text())
    donor = dep.parse_adbdump(args.donor_index.read_text(), "target")
    official = {
        feed: dep.parse_adbdump((args.official_index_dir / (feed + ".txt")).read_text(), feed)
        for feed in stock.FEEDS
    }
    result = plan(installed, args.world.read_text(), donor, official)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    args.pins.parent.mkdir(parents=True, exist_ok=True)
    args.pins.write_text("\n".join(result["version_pins"]) + "\n")
    print("Stock installed:", result["stock_installed_count"])
    print("Official exact userspace roots:", result["exact_official_userland_pinned_count"])
    print("Julius kernel/kmod roots:", result["julius_kernel_kmod_pinned_count"])
    print("Kmods absent in Julius IB:", len(result["missing_stock_kernel_or_kmods"]))
    for name in result["missing_stock_kernel_or_kmods"]:
        print("MISSING_JULIUS_KMOD:", name)
    for name in result["missing_stock_userland"]:
        print("MISSING_OFFICIAL_USERLAND:", name)
    print("No automatic module removal, no ABI overrides, no firmware.")


if __name__ == "__main__":
    main()
