#!/usr/bin/env python3
"""Verify apk-tools' fetched recursive closure against *locked* official sha256sums.

This validates file provenance and forbids foreign kernel modules. A verified
sample closure is not yet a matched Builder or a full ABI compatibility proof.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "hybrid_official_inventory", ROOT / "scripts/hybrid-official-apk-plan.py")
inventory = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(inventory)


def file_sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify(lock: dict, target_sums: dict[str, str],
           arch_sums: dict[str, str], folder: Path,
           requested: list[str]) -> dict:
    if not folder.is_dir():
        raise ValueError("Missing apk fetch closure directory")
    if not requested:
        raise ValueError("At least one requested root package is required")
    candidates: dict[str, list[dict]] = {}
    for where, sums in (("target", target_sums), ("arch", arch_sums)):
        for name, entries in inventory.entries(sums, where).items():
            for item in entries:
                candidates.setdefault(item["filename"], []).append(item)
    downloaded = sorted(folder.glob("*.apk"))
    if not downloaded or len(downloaded) > 512:
        raise ValueError("Unexpected empty or excessive APK dependency closure")
    output: list[dict] = []
    seen_names: set[str] = set()
    for path in downloaded:
        if not path.is_file() or path.is_symlink():
            raise ValueError("APK closure contains symlinks or non-regular files")
        pkg = inventory.package_name(path.name)
        if inventory.is_kernel_owned(pkg):
            raise ValueError(f"Official kmod/kernel contaminates hybrid closure: {pkg}")
        if pkg in inventory.LOCAL_PACKAGES:
            raise ValueError(f"Patched custom package sourced from official: {pkg}")
        actual = file_sha(path)
        origins = [
            item for item in candidates.get(path.name, [])
            if item["sha256"] == actual
        ]
        if len(origins) != 1:
            raise ValueError(f"APK not uniquely identified in locked indexes: {path.name}")
        origin = origins[0]
        if pkg in seen_names:
            raise ValueError(f"Duplicate package versions in closure: {pkg}")
        seen_names.add(pkg)
        output.append({
            "name": pkg,
            "filename": path.name,
            "sha256": actual,
            "source": origin["source"],
            "feed": origin["feed"],
            "origin_path": origin["path"],
            "abi_review": pkg in inventory.PROTECTED,
        })
    if any(n not in seen_names for n in requested):
        raise ValueError("Requested package(s) missing from recursive APK fetch")
    return {
        "schema": 1,
        "status": "P3-official-userland-closure-test-only",
        "snapshot_lock_fingerprint": lock["lock_fingerprint"],
        "kernel_fingerprint": lock["kernel_fingerprint"],
        "packages_fingerprint": lock["packages_fingerprint"],
        "requested": sorted(requested),
        "files": output,
        "count": len(output),
        "all_download_sha256_matched": True,
        "official_kernel_import_forbidden": True,
        "custom_kernel_abi_verified": False,
        "full_firmware_dependencies_verified": False,
        "flashable_image_produced": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--download-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--requested", nargs="+", required=True)
    parser.add_argument("--fixture-dir", type=Path)
    args = parser.parse_args()
    lock = json.loads(args.lock.read_text())
    t, a = inventory.verified_indexes(lock, fixture=args.fixture_dir)
    manifest = verify(lock, t, a, args.download_dir, args.requested)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"Verified {manifest['count']} APKs against pinned target/arch hashes")
    print("No foreign kernel modules, no locally patched packages, no firmware published.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError) as error:
        print(f"Hybrid APK closure validation error: {error}", file=sys.stderr)
        sys.exit(1)
