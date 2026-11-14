#!/usr/bin/env python3
"""Audit EVERY package selected by native apk3 during the mixed core dry-run.

A successful solver solution is not evidence that official userspace binaries
were chosen for transitive dependencies. Match (package name, exact version)
against frozen official indexes and the content-pinned donor IB repository.
No firmware, package installation or executable content is produced.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "swap_dependency_audit", ROOT / "scripts/hybrid-dependency-audit.py")
dep = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(dep)

INSTALLED = re.compile(
    r"^\(\s*(\d+)/(\d+)\)\s+Installing\s+([A-Za-z0-9+._-]+)\s+\(([^()\s]+)\)$"
)
CORE_LIBRARY_PREFIXES = ("libubox", "libubus", "libblobmsg-json", "libuci", "libgcc")


def audit_solver(log: str, donor: list[dict],
                 official: dict[str, list[dict]], roots: list[dict]) -> dict:
    if not re.search(r"^OK: .* in \d+ packages$", log, re.M):
        raise ValueError("APK simulation did not terminate successfully")
    selected: list[tuple[str, str]] = []
    expected_total: int | None = None
    for line in log.splitlines():
        match = INSTALLED.fullmatch(line.strip())
        if not match:
            continue
        no, total = int(match[1]), int(match[2])
        if expected_total is None:
            expected_total = total
        if expected_total != total or no != len(selected) + 1:
            raise ValueError("Invalid or incomplete APK simulation numbering")
        selected.append((match[3], match[4]))
    if not selected or len(selected) != expected_total:
        raise ValueError("APK installed list is incomplete")
    if len(selected) != len(set(name for name, _ in selected)):
        raise ValueError("APK proposed conflicting duplicate package names")

    lookups: dict[tuple[str, str], set[str]] = defaultdict(set)
    for p in donor:
        lookups[(p["name"], p["version"])].add("julius")
    for feed, packages in official.items():
        for p in packages:
            lookups[(p["name"], p["version"])].add("immortalwrt:" + feed)
    roots_lookup = {p["name"]: p for p in roots}
    records = []
    blockers: list[str] = []
    families: dict[str, list[str]] = defaultdict(list)
    for name, version in selected:
        origins = sorted(lookups.get((name, version), ()))
        donor_present = "julius" in origins
        official_present = any(x.startswith("immortalwrt:") for x in origins)
        if not origins:
            blockers.append(name + ":version-not-in-verified-indexes")
        if name == "kernel" or name.startswith("kmod-"):
            if not donor_present:
                blockers.append(name + ":foreign-kmod-or-kernel")
            if official_present:
                blockers.append(name + ":ambiguous-donor-kmod-version")
        if name in roots_lookup:
            wanted = roots_lookup[name]
            if version != wanted["version"]:
                blockers.append(name + ":pinned-version-changed")
            if wanted["origin"] == "immortalwrt-userspace" and not official_present:
                blockers.append(name + ":official-userspace-not-in-index")
            if wanted["origin"] in ("julius-kernel", "julius-userspace-exception") and not donor_present:
                blockers.append(name + ":donor-root-not-in-index")
        for prefix in CORE_LIBRARY_PREFIXES:
            if name.startswith(prefix):
                families[prefix].append(name)
        records.append({
            "name": name, "version": version, "candidate_origins": origins,
            "donor_candidate": donor_present, "official_candidate": official_present,
            "ambiguous_binary_origin": donor_present and official_present,
            "pinned_root": name in roots_lookup,
        })
    for root in roots:
        if root["name"] not in {p["name"] for p in records}:
            blockers.append(root["name"] + ":requested-root-missing-from-solver")
    multi_lib = {n: sorted(set(xs)) for n, xs in families.items()
                 if len(set(xs)) > 1}
    return {
        "schema": 1,
        "status": "native-solver-provenance-audit-only",
        "selected_package_count": len(records),
        "donor_only_count": sum(x["donor_candidate"] and not x["official_candidate"] for x in records),
        "official_only_count": sum(x["official_candidate"] and not x["donor_candidate"] for x in records),
        "ambiguous_identical_name_version_count": sum(x["ambiguous_binary_origin"] for x in records),
        "selected_kernel_module_count": sum(
            x["name"] == "kernel" or x["name"].startswith("kmod-") for x in records),
        "all_kernel_modules_candidate_from_donor": not any(
            "foreign-kmod-or-kernel" in s for s in blockers),
        "mixed_abi_libraries": multi_lib,
        "blockers": sorted(set(blockers)),
        "records": records,
        "file_conflicts_checked": False,
        "runtime_abi_verified": False,
        "official_rootfs_world_fully_solved": False,
        "publishable": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--donor-index", type=Path, required=True)
    parser.add_argument("--official-index-dir", type=Path, required=True)
    parser.add_argument("--roots", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    donor = dep.parse_adbdump(args.donor_index.read_text(), "target")
    official = {
        feed: dep.parse_adbdump((args.official_index_dir / (feed + ".txt")).read_text(), feed)
        for feed in ("target", "base", "packages", "luci", "routing", "telephony")
    }
    roots = json.loads(args.roots.read_text())["roots"]
    result = audit_solver(args.log.read_text(), donor, official, roots)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print("APK solver candidate count:", result["selected_package_count"])
    print("Julius-only:", result["donor_only_count"],
          "ImmortalWrt-only:", result["official_only_count"],
          "ambiguous identical versions:", result["ambiguous_identical_name_version_count"])
    print("Multi-version ABI library families:", json.dumps(result["mixed_abi_libraries"]))
    print("Blockers:", result["blockers"])
    print("Source candidate identity is NOT verified binary origin or file-overlap compatibility.")


if __name__ == "__main__":
    main()
