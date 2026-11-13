#!/usr/bin/env python3
"""Audit every package INSTALLED in the official ImmortalWrt RE-SS-01 rootfs.

The source of truth is the shipped /lib/apk/db/installed, NOT just a handful
of user-requested core roots. Compare exact versions with frozen Snapshot
indices to identify unavoidable userspace drift before building a hybrid.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sp = importlib.util.spec_from_file_location(
    "swap_world_dependency_audit", ROOT / "scripts/hybrid-dependency-audit.py")
dep = importlib.util.module_from_spec(sp)
assert sp.loader
sp.loader.exec_module(dep)

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9+._-]*")
VERSION = re.compile(r"[^\s\x00-\x1f]+")
FEEDS = ("target", "base", "packages", "luci", "routing", "telephony")


def parse_installed_plaintext(text: str) -> list[dict]:
    """OpenWrt apk3 installed database has P:name and V:version records."""
    output = []
    block: dict[str, str] = {}
    def finish() -> None:
        nonlocal block
        if not block:
            return
        if not block.get("name") or not block.get("version"):
            raise ValueError("Incomplete installed APK record")
        if not NAME.fullmatch(block["name"]) or not VERSION.fullmatch(block["version"]):
            raise ValueError("Invalid installed package field")
        output.append(block)
        block = {}

    for line in text.splitlines() + [""]:
        if not line:
            finish()
        elif line.startswith("P:"):
            if "name" in block:
                finish()
            block["name"] = line[2:]
        elif line.startswith("V:"):
            block["version"] = line[2:]
        # Remaining fields describe file ownership, dependencies, scripts.
    if len(output) < 20:
        raise ValueError("Official image installed package DB is unexpectedly small")
    names = [x["name"] for x in output]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate installed package names")
    return output


def audit_world(installed: list[dict], indexes: dict[str, list[dict]],
                world: str) -> dict:
    if any(feed not in indexes for feed in FEEDS):
        raise ValueError("Missing pinned official repository indexes")
    known: dict[str, set[str]] = {}
    for feed in FEEDS:
        for pkg in indexes[feed]:
            known.setdefault(pkg["name"], set()).add(pkg["version"])
    roots = [line.strip() for line in world.splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    userland = [p for p in installed if
                p["name"] != "kernel" and not p["name"].startswith("kmod-")]
    packages = []
    for p in userland:
        alternatives = sorted(known.get(p["name"], set()))
        status = ("exact-official-snapshot-archive" if p["version"] in alternatives
                  else "official-name-version-rotated" if alternatives
                  else "absent-from-current-official-index")
        packages.append({
            "name": p["name"], "installed_version": p["version"],
            "matching_index_status": status,
            "available_official_versions": alternatives,
        })
    status_counts = {
        key: sum(p["matching_index_status"] == key for p in packages)
        for key in ("exact-official-snapshot-archive",
                    "official-name-version-rotated",
                    "absent-from-current-official-index")
    }
    return {
        "schema": 1,
        "status": "official-installed-world-availability-audit",
        "installed_package_count": len(installed),
        "installed_kernel_and_kmod_count": len(installed) - len(userland),
        "installed_userland_count": len(userland),
        "world_root_count": len(roots),
        "world_roots": roots,
        "counts": status_counts,
        "installed_userland_packages": packages,
        "exact_full_official_userspace_rebuild_possible_from_current_indexes":
            all(p["matching_index_status"] == "exact-official-snapshot-archive"
                for p in packages),
        "julius_kernel_dependencies_solved_with_full_world": False,
        "kernel_module_migration_verified": False,
        "publishable": False,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--installed-db", type=Path, required=True)
    ap.add_argument("--world", type=Path, required=True)
    ap.add_argument("--official-index-dir", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    data = args.installed_db.read_text()
    installed = parse_installed_plaintext(data)
    indexes = {
        feed: dep.parse_adbdump((args.official_index_dir / (feed + ".txt")).read_text(), feed)
        for feed in FEEDS
    }
    report = audit_world(installed, indexes, args.world.read_text())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print("Installed official packages:", report["installed_package_count"])
    print("Official userspace:", report["installed_userland_count"])
    print("Root world requirements:", report["world_root_count"])
    print("Exact published APK availability:", report["counts"])
    print("Cannot treat latest arch snapshots as exact older target packages without comparing hashes.")


if __name__ == "__main__":
    main()
