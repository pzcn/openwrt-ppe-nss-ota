#!/usr/bin/env python3
"""Mirror exact SHA256-pinned userland APKs from a Hybrid P3 dependency audit.

Only produces an offline APK cache and immutable provenance manifest. It never
modifies ImageBuilder repositories, mixes official kmods or publishes firmware.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "hybrid_inventory_mirror", ROOT / "scripts/hybrid-official-apk-plan.py")
inventory = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(inventory)


def sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def canonical(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def check_audit(doc: dict, lock: dict, target: dict[str, str],
                arch: dict[str, str]) -> list[dict]:
    """Reject stale plans, unpinned paths, forbidden kernel or local packages."""
    if (doc.get("schema") != 1 or doc.get("status") !=
            "P3-dependency-audit-not-build-approved"):
        raise ValueError("Input is not a P3 dependency audit")
    if doc.get("snapshot_lock_fingerprint") != lock.get("lock_fingerprint"):
        raise ValueError("Audit and official Snapshot lock differ")
    saved = doc.get("audit_sha256")
    payload = {k: v for k, v in doc.items() if k != "audit_sha256"}
    if saved != sha(canonical(payload)):
        raise ValueError("Audited dependency graph was modified")
    if (not doc.get("mirror_plan_content_pinned") or
            doc.get("mirror_plan_missing_archives") or
            doc.get("root_blockers") or doc.get("unresolved")):
        raise ValueError("The P3 audit has missing or unpinned inputs")
    assets = doc.get("mirror_plan")
    if not isinstance(assets, list) or not assets:
        raise ValueError("Empty official userland mirror plan")
    if len(assets) != doc.get("candidate_closure_size"):
        raise ValueError("P3 mirror plan is not the full candidate closure")
    checked = []
    names: set[str] = set()
    paths: set[str] = set()
    for entry in assets:
        name, filename = entry["name"], entry["filename"]
        source, feed = entry["source"], entry["feed"]
        if inventory.is_kernel_owned(name) or name in inventory.LOCAL_PACKAGES \
                or name in inventory.PROTECTED:
            raise ValueError(f"Forbidden official kernel, ABI or custom APK: {name}")
        if source not in ("target", "arch"):
            raise ValueError("Unexpected official package source")
        if feed not in (("packages",) if source == "target" else
                        tuple(inventory.ALLOWED_ARCH_FEEDS)):
            raise ValueError("Unexpected feed in mirror plan")
        if inventory.package_name(filename) != name:
            raise ValueError("APK filename differs from package name")
        expected_rel = feed + "/" + filename
        if entry.get("path") != expected_rel:
            raise ValueError("Unexpected APK path")
        origin_index = target if source == "target" else arch
        if origin_index.get(expected_rel) != entry.get("sha256"):
            raise ValueError("APK is not in locked official checksum index")
        origin_url = (lock["target_url"] if source == "target"
                      else lock["architecture_url"]) + "/" + expected_rel
        if entry.get("url") != origin_url:
            raise ValueError("Official URL is inconsistent with Snapshot lock")
        if name in names or (source, expected_rel) in paths:
            raise ValueError("Duplicate APK package identity")
        names.add(name)
        paths.add((source, expected_rel))
        checked.append(entry)
    return checked


def mirror(doc: dict, lock: dict, dest: Path, packages: list[str],
           *, fixture: Path | None = None, jobs: int = 4) -> dict:
    target, arch = inventory.verified_indexes(lock, fixture=fixture)
    approved = check_audit(doc, lock, target, arch)
    if jobs < 1 or jobs > 8:
        raise ValueError("Use between 1 and 8 download workers")
    candidates = {p["name"]: p for p in approved}
    if len(packages) != len(set(packages)) or not packages:
        raise ValueError("Select at least one unique candidate")
    if any(p not in candidates for p in packages):
        raise ValueError("Requested APK is not part of locked official closure")
    dest.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = [
            pool.submit(inventory.copy_verified_package, candidates[name],
                        dest, fixture=fixture)
            for name in sorted(packages)
        ]
        files = [task.result() for task in futures]
    # Check both indices again so a live Snapshot rotation cannot produce a
    # releasable mixed-version archive without being detected.
    inventory.verified_indexes(lock, fixture=fixture)
    result = {
        "schema": 1,
        "status": "P3-untrusted-userland-mirror-test-only",
        "snapshot_lock_fingerprint": lock["lock_fingerprint"],
        "dependency_audit_sha256": doc["audit_sha256"],
        "full_candidate_closure_mirrored": len(files) == len(approved),
        "download_count": len(files),
        "files": sorted(files, key=lambda f: f["name"]),
        "download_sha256_verified": True,
        "kernel_abi_verified": False,
        "repository_signatures_verified": False,
        "publishable": False,
    }
    result["manifest_sha256"] = sha(canonical(result))
    return result


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--lock", type=Path, required=True)
    p.add_argument("--audit", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--all", action="store_true")
    p.add_argument("--sample", nargs="+")
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--fixture-dir", type=Path)
    args = p.parse_args()
    if args.all == bool(args.sample):
        raise ValueError("Specify exactly one of --all or --sample")
    lock = json.loads(args.lock.read_text())
    audit = json.loads(args.audit.read_text())
    if args.all:
        packages = [x["name"] for x in audit["mirror_plan"]]
    else:
        packages = args.sample
    result = mirror(audit, lock, args.output_dir / "apks", packages,
                    fixture=args.fixture_dir, jobs=args.jobs)
    output = args.output_dir / "offline-mirror-manifest.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"Mirrored {result['download_count']} SHA256-verified userland APKs")
    print(f"Full candidate set: {result['full_candidate_closure_mirrored']}")
    print("Test only: repository signatures, kernel ABI and firmware are NOT approved.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError) as exc:
        print(f"Hybrid mirror verification error: {exc}", file=sys.stderr)
        sys.exit(1)
