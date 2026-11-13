#!/usr/bin/env python3
"""P3 official APK dependency *audit*, using verified apk-tools adbdump output.

This is not a substitute for apk's real solver: version constraints, virtual
provides, replaces and the locally compiled kernel ABI still need final checks.
No firmware is built or published by this module.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import deque
from pathlib import Path

SCHEMA = 1
ARCHES = ("aarch64_cortex-a53", "noarch", "all")
FIELDS = ("depends", "provides")
KNOWN_FEEDS = ("target", "base", "packages", "luci", "routing", "telephony")
PKG_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+._:-]*$")
DEP_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+._:/-]*$")
OPERATOR = re.compile(r"^(.*?)(?:[<>=~]{1,2}.*)?$")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_adbdump(contents: str, feed: str) -> list[dict]:
    if feed not in KNOWN_FEEDS:
        raise ValueError(f"Unexpected APK index feed: {feed}")
    if "packages:" not in contents or "#%SCHEMA:" not in contents:
        raise ValueError(f"Not a valid apk-tools adbdump: {feed}")
    packages: list[dict] = []
    seen: set[tuple[str, str]] = set()
    package: dict | None = None
    section: str | None = None

    def commit() -> None:
        nonlocal package
        if package is None:
            return
        if not all(package.get(k) for k in ("name", "version", "arch")):
            raise ValueError(f"Incomplete package entry in {feed}")
        if not PKG_NAME.fullmatch(package["name"]):
            raise ValueError(f"Invalid indexed package name in {feed}")
        if package["arch"] not in ARCHES:
            raise ValueError(f"Wrong architecture {package['arch']!r} in {feed}")
        key = (package["name"], package["version"])
        if key in seen:
            raise ValueError(f"Duplicate package name/version in {feed}: {key}")
        seen.add(key)
        packages.append(package)

    for line in contents.splitlines():
        if line.startswith("  - name: "):
            commit()
            package = {"name": line[10:].strip(), "feed": feed,
                       "depends": [], "provides": []}
            section = None
        elif package is not None and line.startswith("    ") and not line.startswith("      "):
            m = re.fullmatch(r"    ([a-z-]+):\s*(.*)", line)
            if m:
                key, value = m.groups()
                section = key if key in FIELDS else None
                if key in ("version", "arch"):
                    package[key] = value.strip()
        elif package is not None and line.startswith("      - ") and section:
            token = line[8:].strip()
            if token:
                package[section].append(token)
    commit()
    if not packages:
        raise ValueError(f"Empty index: {feed}")
    return packages


def dependency_base(value: str) -> str:
    # Record version constraints separately rather than claiming to solve them.
    value = value.strip()
    if value.startswith("!"):
        # Conflict atoms are not requirements; the real solver must check them.
        return ""
    base = re.split(r"[<>=~]", value, maxsplit=1)[0].strip()
    if not base or not DEP_NAME.fullmatch(base):
        raise ValueError(f"Unexpected dependency atom: {value!r}")
    return base


def review(inventory: dict, indexes: dict[str, list[dict]]) -> dict:
    if inventory.get("schema") != 1 or inventory.get("status") != \
            "P3-inventory-only-not-build-approved":
        raise ValueError("Not a pinned P3 inventory")
    if not all(name in indexes for name in KNOWN_FEEDS):
        raise ValueError("Missing official index feed")

    by_name: dict[str, list[dict]] = {}
    by_provide: dict[str, list[dict]] = {}
    for feed in KNOWN_FEEDS:
        for package in indexes[feed]:
            by_name.setdefault(package["name"], []).append(package)
            for provided in package["provides"]:
                base = dependency_base(provided)
                if base:
                    by_provide.setdefault(base, []).append(package)

    rows = inventory["packages"]
    roots = {r["name"]: r for r in rows}
    official_roots = [r for r in rows if r["status"] == "official-candidate"]
    local_names = {r["name"] for r in rows
                   if r["status"] in ("local-kernel", "local-custom", "abi-review")}
    local_names.update(("kernel", "base-files", "libc", "libgcc", "libstdcpp"))
    candidates: dict[str, dict] = {}
    unknown: set[str] = set()
    ambiguous: set[str] = set()
    local_deps: set[str] = set()
    virtual_deps: set[str] = set()
    constraints: set[str] = set()
    pending: deque[dict] = deque()
    blockers = [r["name"] for r in rows if r["status"] in ("missing", "ambiguous")]

    for root in official_roots:
        feed = "target" if root["source"] == "target" else root["feed"]
        matched = [p for p in indexes[feed] if p["name"] == root["name"]
                   and root["filename"] == p["name"] + "-" + p["version"] + ".apk"]
        if len(matched) != 1:
            # Filename-only matches never authorize dependency mirroring.
            blockers.append(root["name"] + ":index-filename-mismatch")
        else:
            pending.append(matched[0])

    while pending:
        p = pending.popleft()
        name = p["name"]
        if name in candidates:
            if candidates[name]["version"] != p["version"] or \
                    candidates[name]["feed"] != p["feed"]:
                ambiguous.add(name)
            continue
        if name in local_names or name.startswith("kmod-"):
            local_deps.add(name)
            continue
        candidates[name] = {
            "name": name, "version": p["version"], "feed": p["feed"],
            "dependency_atoms": p["depends"],
        }
        for atom in p["depends"]:
            if any(op in atom for op in ("<", ">", "=", "~")):
                constraints.add(atom)
            base = dependency_base(atom)
            if not base:
                constraints.add(atom)
                continue
            if base in local_names or base.startswith("kmod-"):
                local_deps.add(base)
                continue
            providers = by_name.get(base, [])
            if not providers:
                providers = by_provide.get(base, [])
                if providers:
                    virtual_deps.add(base)
            if not providers:
                unknown.add(base)
            elif len(providers) > 1:
                ambiguous.add(base)
            else:
                pending.append(providers[0])

    report = {
        "schema": SCHEMA,
        "status": "P3-dependency-audit-not-build-approved",
        "inventory_fingerprint": inventory["inventory_fingerprint"],
        "snapshot_lock_fingerprint": inventory["snapshot_lock_fingerprint"],
        "requested_official_packages": len(official_roots),
        "candidate_closure_size": len(candidates),
        "official_candidates": sorted(candidates.values(), key=lambda x: x["name"]),
        "requires_local_provision": sorted(local_deps),
        "unresolved": sorted(unknown),
        "ambiguous": sorted(ambiguous),
        "root_blockers": sorted(blockers),
        "version_constraints_for_apk_solver": sorted(constraints),
        "virtual_provides_for_apk_solver": sorted(virtual_deps),
        "dependency_closure_verified": False,
        "apk_solver_verified": False,
        "kernel_abi_verified": False,
        "checksums_authenticated": False,
        "publishable": False,
    }
    report["audit_sha256"] = digest(json.dumps(
        report, sort_keys=True, separators=(",", ":")).encode())
    return report


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--inventory", required=True, type=Path)
    p.add_argument("--index-dir", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    indexes = {}
    for feed in KNOWN_FEEDS:
        path = args.index_dir / (feed + ".txt")
        indexes[feed] = parse_adbdump(path.read_text(), feed)
    data = review(json.loads(args.inventory.read_text()), indexes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print("Hybrid APK dependency audit:")
    print(f"  requested official APKs: {data['requested_official_packages']}")
    print(f"  candidate transitive closure: {data['candidate_closure_size']}")
    for name in ("requires_local_provision", "unresolved", "ambiguous",
                 "version_constraints_for_apk_solver", "virtual_provides_for_apk_solver"):
        print(f"  {name}: {len(data[name])}")
    print("NOT a publishable Builder: real apk solver, local ABI, and signed origins are pending.")


if __name__ == "__main__":
    main()
