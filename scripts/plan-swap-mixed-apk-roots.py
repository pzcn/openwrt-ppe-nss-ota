#!/usr/bin/env python3
"""Make explicit native-apk test roots for a mixed ImmortalWrt/Julius set.

This prepares exact *core* package version requests for the real apk3 solver;
it cannot by itself establish a consistent rootfs. The donor owns kernel and
all kmod-*; ImmortalWrt owns userspace.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "hybrid_audit", ROOT / "scripts/hybrid-dependency-audit.py")
audit = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(audit)

DONOR_ROOTS = ("kernel", "kmod-fs-f2fs", "kmod-nss-wifi-drv", "kmod-wireguard")
OFFICIAL_ROOTS = (
    "base-files", "libc", "busybox", "procd", "netifd", "ubus",
    "firewall4", "dnsmasq", "dropbear", "rpcd", "uhttpd", "odhcp6c",
)
FEEDS = ("target", "base", "packages", "luci", "routing", "telephony")


def unique_package(indexes: list[dict], name: str) -> tuple[dict | None, str | None]:
    found = [x for x in indexes if x["name"] == name]
    variants = {(x["version"], x["arch"]) for x in found}
    if len(variants) == 1:
        return found[0], None
    if not found:
        return None, f"{name}:not-found"
    return None, f"{name}:multiple-versions"


def plan(donor: list[dict], official: dict[str, list[dict]]) -> dict:
    if any(feed not in official for feed in FEEDS):
        raise ValueError("Missing pinned official index")
    official_all = [x for feed in FEEDS for x in official[feed]]
    roots: list[dict] = []
    blockers: list[str] = []
    for owner, selected, index in (
        ("julius-kernel", DONOR_ROOTS, donor),
        ("immortalwrt-userspace", OFFICIAL_ROOTS, official_all),
    ):
        for name in selected:
            item, problem = unique_package(index, name)
            if problem:
                blockers.append(problem)
                continue
            if owner == "immortalwrt-userspace" and (
                name == "kernel" or name.startswith("kmod-")
            ):
                raise ValueError("Foreign official kernel package in userspace roots")
            if owner == "julius-kernel" and not (
                name == "kernel" or name.startswith("kmod-")
            ):
                raise ValueError("Non-kernel package selected from donor")
            roots.append({
                "name": name,
                "version": item["version"],
                "arch": item["arch"],
                "origin": owner,
                "source": item["feed"],
                "pin": name + "=" + item["version"],
                "depends": item.get("depends", []),
                "provides": item.get("provides", []),
            })

    if not any(x["name"] == "kernel" and x["origin"] == "julius-kernel" for x in roots):
        blockers.append("missing-julius-kernel-root")
    if not any(x["name"] == "base-files" and
               x["origin"] == "immortalwrt-userspace" for x in roots):
        blockers.append("missing-immortalwrt-base-files-root")
    return {
        "schema": 1,
        "status": "core-native-apk-solver-roots-only",
        "root_count": len(roots),
        "donor_kernel_root_count": sum(
            x["origin"] == "julius-kernel" for x in roots),
        "official_userspace_root_count": sum(
            x["origin"] == "immortalwrt-userspace" for x in roots),
        "roots": roots,
        "blockers": blockers,
        "version_pins": [x["pin"] for x in roots],
        "kernel_abi_verified": False,
        "complete_firmware_dependency_closure_verified": False,
        "publishable": False,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--donor-index", type=Path, required=True)
    p.add_argument("--official-index-dir", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--pins", type=Path, required=True)
    args = p.parse_args()

    donor = audit.parse_adbdump(args.donor_index.read_text(), "target")
    official = {
        feed: audit.parse_adbdump((args.official_index_dir / (feed + ".txt")).read_text(), feed)
        for feed in FEEDS
    }
    result = plan(donor, official)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    args.pins.parent.mkdir(parents=True, exist_ok=True)
    args.pins.write_text("\n".join(result["version_pins"]) + "\n")
    print("Requested roots:", len(result["roots"]))
    print("Donor kernel modules:", result["donor_kernel_root_count"])
    print("Official core userspace:", result["official_userspace_root_count"])
    for reason in result["blockers"]:
        print("BLOCKER", reason)
    print("Test only: awaiting actual apk3 --simulate dependency resolution.")


if __name__ == "__main__":
    main()
