#!/usr/bin/env python3
"""Independently audit a frozen official APK mirror before using it in a Builder.

This is a provenance/integrity check, NOT permission to publish firmware.
No online lookup is required: all filenames/hashes are anchored by the
separately produced Snapshot lock and content-hashed dependency audit.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "hybrid_mirror_lib", HERE / "mirror-hybrid-official-apks.py"
)
mirror_lib = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(mirror_lib)


def digest_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check(lock: dict, audit: dict, manifest: dict, root: Path, *,
          require_full: bool = True) -> dict:
    if lock.get("schema") != 2:
        raise ValueError("Expected official Snapshot lock schema 2")
    if audit.get("status") != "P3-dependency-audit-not-build-approved":
        raise ValueError("Not a frozen official APK dependency audit")
    if audit.get("snapshot_lock_fingerprint") != lock.get("lock_fingerprint"):
        raise ValueError("Dependency audit points to another Snapshot")
    a_hash = audit.get("audit_sha256")
    if a_hash != mirror_lib.sha(mirror_lib.canonical(
            {key: value for key, value in audit.items() if key != "audit_sha256"})):
        raise ValueError("Dependency audit integrity mismatch")
    if (not audit.get("mirror_plan_content_pinned") or
            audit.get("mirror_plan_missing_archives") or
            audit.get("root_blockers") or audit.get("unresolved")):
        raise ValueError("Dependency audit has unresolved download inputs")

    if manifest.get("schema") != 1 or manifest.get("status") !=             "P3-untrusted-userland-mirror-test-only":
        raise ValueError("Not a test-only official APK mirror manifest")
    if (manifest.get("snapshot_lock_fingerprint") != lock["lock_fingerprint"]
            or manifest.get("dependency_audit_sha256") != a_hash):
        raise ValueError("Offline mirror provenance does not match source lock")
    recorded = manifest.get("manifest_sha256")
    if recorded != mirror_lib.sha(mirror_lib.canonical(
            {key: value for key, value in manifest.items() if key != "manifest_sha256"})):
        raise ValueError("Offline mirror manifest integrity mismatch")
    if manifest.get("publishable") is not False or             manifest.get("kernel_abi_verified") is not False or             manifest.get("download_sha256_verified") is not True:
        raise ValueError("Invalid prepublication mirror status")

    expected = audit.get("mirror_plan")
    if not isinstance(expected, list) or not expected:
        raise ValueError("Missing locked dependency plan")
    planned = {entry["name"]: entry for entry in expected}
    if len(planned) != len(expected):
        raise ValueError("Duplicate candidate names in dependency plan")
    files = manifest.get("files")
    if not isinstance(files, list) or not files or len(files) > len(planned):
        raise ValueError("Invalid mirror file inventory")
    if manifest.get("download_count") != len(files):
        raise ValueError("Downloaded file count differs from manifest")
    if require_full and (manifest.get("full_candidate_closure_mirrored") is not True
                         or len(files) != len(planned)):
        raise ValueError("Offline mirror is only a partial candidate closure")

    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Missing mirror directory")
    seen: set[str] = set()
    inspected: set[Path] = set()
    bytes_total = 0
    for row in files:
        name = row["name"]
        if name in seen or name not in planned:
            raise ValueError("Duplicate or unapproved APK in mirror")
        seen.add(name)
        original = planned[name]
        if mirror_lib.inventory.is_kernel_owned(name) or                 name in mirror_lib.inventory.LOCAL_PACKAGES or                 name in mirror_lib.inventory.PROTECTED:
            raise ValueError("Forbidden ABI/custom package in official mirror")
        source, feed, filename = original["source"], original["feed"], original["filename"]
        rel = str(Path(source) / feed / filename)
        if (row.get("relative_path") != rel
                or row.get("source") != source
                or row.get("feed") != feed
                or row.get("filename") != filename
                or row.get("sha256") != original["sha256"]):
            raise ValueError(f"Mirror provenance mismatch: {name}")
        path = root / rel
        # Keep all validation local and fail on symlinks or path trickery.
        if path.is_symlink() or any(part.is_symlink() for part in path.parents
                                    if part != root and root in part.parents):
            raise ValueError(f"Symlink in APK path: {rel}")
        if not path.resolve().is_relative_to(root):
            raise ValueError(f"APK path escapes mirror directory: {rel}")
        if not path.is_file() or digest_file(path) != original["sha256"]:
            raise ValueError(f"Mirrored APK missing or corrupted: {rel}")
        inspected.add(path.resolve())
        bytes_total += path.stat().st_size
    if require_full and seen != set(planned):
        raise ValueError("Full candidate closure has missing APKs")

    present = {p.resolve() for p in root.rglob("*.apk") if p.is_file()}
    if inspected != present:
        raise ValueError("Unexpected or untracked APKs in offline mirror")

    return {
        "schema": 1,
        "status": "P3-offline-mirror-integrity-verified-no-abi-approval",
        "source_lock_fingerprint": lock["lock_fingerprint"],
        "dependency_audit_sha256": a_hash,
        "mirror_manifest_sha256": recorded,
        "verified_apks": len(inspected),
        "total_bytes": bytes_total,
        "full_candidate_closure_mirrored": len(files) == len(planned),
        "kernel_abi_verified": False,
        "apk_solver_full_firmware_verified": False,
        "trusted_snapshot_signature_verified": False,
        "publishable": False,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--lock", type=Path, required=True)
    p.add_argument("--audit", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--root", type=Path, required=True,
                   help="Directory containing target/ and arch/ subdirectories")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--allow-sample", action="store_true")
    args = p.parse_args()
    result = check(json.loads(args.lock.read_text()),
                   json.loads(args.audit.read_text()),
                   json.loads(args.manifest.read_text()),
                   args.root, require_full=not args.allow_sample)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"Verified {result['verified_apks']} official APK files, "
          f"{result['total_bytes']} bytes, against locked mirror plan.")
    print("No kernel ABI or full-image dependency approval; no release.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, TypeError) as error:
        print(f"Offline Hybrid mirror verification failed: {error}", file=sys.stderr)
        sys.exit(1)
