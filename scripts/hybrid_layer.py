#!/usr/bin/env python3
"""Verified, standalone userland layer for an immutable Hybrid ImageBuilder.

A refresh does NOT republish the parent ImageBuilder/SDK. Its layer contains
only signed official APKs, plus a manifest binding them to a single parent
Builder, the locked snapshot, the old mirrored-file removal list and the
resolved package selection. The parent supplies all local kernel/kmod APKs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

from immortalwrt_builder import check_metadata, sha256

CHANNEL = "re-ss-01-hybrid-userland-layer"
ARCHIVE_NAME = "hybrid-userland-packages.tar.zst"
TAG = re.compile(r"^imm-layer-[0-9a-f]{24}$")
HEX = re.compile(r"^[0-9a-f]{64}$")
APK_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*\.apk$")
MAX_TOTAL_SIZE = 2 * 1024**3


def read_json(path: Path) -> dict:
    obj = json.loads(path.read_text())
    if not isinstance(obj, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return obj


def tag_for(base_tag: str, identity: str) -> str:
    raw = (base_tag + "\0" + identity).encode("ascii")
    return "imm-layer-" + hashlib.sha256(raw).hexdigest()[:24]


def mirror_records(doc: dict) -> list[dict]:
    """Bind the exact verified APK archive files to the official lock."""
    mirrored = doc.get("mirrored")
    mirror = doc.get("mirror")
    if (not isinstance(mirrored, list) or not isinstance(mirror, list)
            or doc.get("errors") or doc.get("local_fallback")):
        raise ValueError("Bad or incomplete official APK closure")
    files = {}
    for entry in mirror:
        if not isinstance(entry, dict):
            raise ValueError("Invalid official APK record")
        name, digest = entry.get("filename"), entry.get("sha256")
        if not isinstance(name, str) or not APK_NAME.fullmatch(name):
            raise ValueError(f"Unsafe official APK file: {name}")
        if not isinstance(digest, str) or not HEX.fullmatch(digest):
            raise ValueError(f"Missing official SHA256 for {name}")
        if name in files:
            raise ValueError(f"Duplicate official APK file: {name}")
        files[name] = digest
    if len(set(mirrored)) != len(mirrored) or any(n not in files for n in mirrored):
        raise ValueError("Mirrored file names do not match official closure")
    return [{"filename": name, "sha256": files[name]} for name in sorted(mirrored)]


def base_mirrors(doc: dict) -> list[str]:
    items = doc.get("mirrored")
    if not isinstance(items, list) or len(items) != len(set(items)):
        raise ValueError("Invalid original mirrored APK list")
    for name in items:
        if not isinstance(name, str) or not APK_NAME.fullmatch(name):
            raise ValueError(f"Unsafe original APK name: {name}")
    return sorted(items)


def base_builder(meta: Path) -> dict:
    parent, legacy = check_metadata(meta)
    if legacy or parent.get("build_mode") != "hybrid":
        raise ValueError("Userland layer needs a published hybrid Builder")
    return parent


def create(base: Path, base_official: Path, archive: Path, official: Path,
           packages: Path, snapshot: Path, identity: str, output: Path) -> dict:
    builder = base_builder(base)
    if not HEX.fullmatch(identity):
        raise ValueError("Invalid Hybrid Builder identity")
    if archive.name != ARCHIVE_NAME or not archive.is_file():
        raise ValueError("Unexpected userland layer archive")
    snap = read_json(snapshot)
    if snap.get("schema") != 2 or not HEX.fullmatch(snap.get("lock_fingerprint", "")):
        raise ValueError("Invalid official snapshot lock")
    if not packages.is_file() or not packages.read_text().strip():
        raise ValueError("Missing ImageBuilder package manifest")
    official_doc = read_json(official)
    removed = base_mirrors(read_json(base_official))
    records = mirror_records(official_doc)
    info = builder["hybrid"]
    doc = {
        "schema": 1,
        "channel": CHANNEL,
        "tag": tag_for(builder["tag"], identity),
        "base_builder_tag": builder["tag"],
        "base_builder_sha256": sha256(base),
        "hybrid": {
            "identity": identity,
            "kernel_identity": info["kernel_identity"],
            "kernel_built_at": info["kernel_built_at"],
        },
        "snapshot_version": snap["snapshot_version"],
        "snapshot_lock_fingerprint": snap["lock_fingerprint"],
        "snapshot_lock_sha256": sha256(snapshot),
        "archive": ARCHIVE_NAME,
        "archive_sha256": sha256(archive),
        "official_apks_sha256": sha256(official),
        "base_official_apks_sha256": sha256(base_official),
        "packages_sha256": sha256(packages),
        "remove": removed,
        "mirrored": records,
    }
    output.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    verify(base, base_official, output, archive, official, packages, snapshot)
    return doc


def check_header(base: Path, layer: Path) -> dict:
    builder = base_builder(base)
    doc = read_json(layer)
    info = doc.get("hybrid")
    if (doc.get("schema") != 1 or doc.get("channel") != CHANNEL
            or not isinstance(info, dict)
            or not HEX.fullmatch(info.get("identity", ""))
            or not HEX.fullmatch(info.get("kernel_identity", ""))
            or doc.get("tag") != tag_for(builder["tag"], info["identity"])
            or not TAG.fullmatch(doc["tag"])
            or doc.get("base_builder_tag") != builder["tag"]
            or doc.get("base_builder_sha256") != sha256(base)
            or info["kernel_identity"] != builder["hybrid"]["kernel_identity"]
            or info.get("kernel_built_at") != builder["hybrid"]["kernel_built_at"]
            or doc.get("archive") != ARCHIVE_NAME
            or not HEX.fullmatch(doc.get("archive_sha256", ""))):
        raise ValueError("Userland layer is not bound to this immutable Builder")
    return doc


def validate_layer(base: Path, base_official: Path, layer: Path, archive: Path,
                   official: Path, packages: Path, snapshot: Path) -> tuple[dict, list[dict]]:
    doc = check_header(base, layer)
    if archive.name != ARCHIVE_NAME:
        raise ValueError("Wrong userland layer archive")
    expected_files = {
        "archive_sha256": sha256(archive),
        "official_apks_sha256": sha256(official),
        "base_official_apks_sha256": sha256(base_official),
        "packages_sha256": sha256(packages),
        "snapshot_lock_sha256": sha256(snapshot),
    }
    for key, digest in expected_files.items():
        if doc.get(key) != digest:
            raise ValueError(f"Userland layer asset integrity mismatch: {key}")
    snap = read_json(snapshot)
    if (snap.get("lock_fingerprint") != doc.get("snapshot_lock_fingerprint")
            or snap.get("snapshot_version") != doc.get("snapshot_version")):
        raise ValueError("Layer snapshot lock mismatch")
    if not packages.read_text().strip():
        raise ValueError("Empty layer package selection")
    if doc.get("remove") != base_mirrors(read_json(base_official)):
        raise ValueError("Layer attempts to remove packages outside parent mirrors")
    records = mirror_records(read_json(official))
    if doc.get("mirrored") != records:
        raise ValueError("Layer APK list differs from locked official APK hashes")
    return doc, records


def inspect_archive(archive: Path, records: list[dict],
                    staging: Path | None = None) -> None:
    """Read zstd->tar as a stream, reject links/traversal, verify every APK."""
    expected = {x["filename"]: x["sha256"] for x in records}
    seen: set[str] = set()
    total = 0
    proc = subprocess.Popen(["zstd", "-dc", "--", str(archive)],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        assert proc.stdout is not None
        with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
            for member in tar:
                if member.name in ("packages", "packages/") and member.isdir():
                    continue
                if not member.isfile() or not member.name.startswith("packages/"):
                    raise ValueError(f"Unsafe layer archive entry: {member.name}")
                name = member.name[len("packages/"):]
                if name not in expected or name in seen or not APK_NAME.fullmatch(name):
                    raise ValueError(f"Unknown, duplicate or unsafe APK in layer: {name}")
                if member.size < 1 or total + member.size > MAX_TOTAL_SIZE:
                    raise ValueError("Userland layer has an oversized APK payload")
                total += member.size
                stream = tar.extractfile(member)
                if stream is None:
                    raise ValueError(f"Cannot read APK {name}")
                digest = hashlib.sha256()
                dest = staging / name if staging is not None else None
                with dest.open("wb") if dest is not None else stream as output:
                    # In read-only verification mode stream doubles as a sink.
                    while True:
                        block = stream.read(1024 * 1024)
                        if not block:
                            break
                        digest.update(block)
                        if dest is not None:
                            output.write(block)
                if digest.hexdigest() != expected[name]:
                    raise ValueError(f"Official APK checksum failed: {name}")
                seen.add(name)
        if seen != set(expected):
            raise ValueError("Layer archive missing official APK files")
    finally:
        if proc.stdout:
            proc.stdout.close()
        status = proc.wait()
    if status:
        raise ValueError("Failed to decompress userland layer archive")


def verify(base: Path, base_official: Path, layer: Path, archive: Path,
           official: Path, packages: Path, snapshot: Path,
           imagebuilder: Path | None = None) -> dict:
    doc, records = validate_layer(base, base_official, layer, archive,
                                  official, packages, snapshot)
    if imagebuilder is None:
        inspect_archive(archive, records)
    else:
        pkg_dir = imagebuilder / "packages"
        if not pkg_dir.is_dir() or not (imagebuilder / "Makefile").is_file():
            raise ValueError("Invalid parent ImageBuilder directory")
        with tempfile.TemporaryDirectory(prefix="hybrid-layer-") as tmp:
            staging = Path(tmp)
            inspect_archive(archive, records, staging=staging)
            to_remove = set(doc["remove"])
            for name in to_remove:
                path = pkg_dir / name
                if not path.is_file() or path.is_symlink():
                    raise ValueError(f"Original mirrored APK missing: {name}")
            for entry in records:
                name = entry["filename"]
                path = pkg_dir / name
                if path.exists() and name not in to_remove:
                    raise ValueError(f"Layer would overwrite local APK: {name}")
            for name in to_remove:
                (pkg_dir / name).unlink()
            for entry in records:
                name = entry["filename"]
                shutil.copy2(staging / name, pkg_dir / name)
            for name in ("packages.adb", "index.json"):
                (pkg_dir / name).unlink(missing_ok=True)
    return doc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    for action in ("create", "check-header", "verify", "install"):
        p = sub.add_parser(action)
        p.add_argument("--base-metadata", required=True, type=Path)
        p.add_argument("--metadata", required=True, type=Path)
        if action != "check-header":
            for option in ("base-official", "archive", "official", "packages", "snapshot"):
                p.add_argument("--" + option, required=True, type=Path)
        if action == "create":
            p.add_argument("--identity", required=True)
        if action == "install":
            p.add_argument("--imagebuilder", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.cmd == "check-header":
            doc = check_header(args.base_metadata, args.metadata)
        elif args.cmd == "create":
            doc = create(args.base_metadata, args.base_official, args.archive,
                         args.official, args.packages, args.snapshot,
                         args.identity, args.metadata)
        else:
            doc = verify(args.base_metadata, args.base_official, args.metadata,
                         args.archive, args.official, args.packages,
                         args.snapshot, getattr(args, "imagebuilder", None))
    except (ValueError, KeyError, OSError, tarfile.TarError) as exc:
        print(f"hybrid_layer: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"Verified layer {doc['tag']} -> {doc['base_builder_tag']}")


if __name__ == "__main__":
    main()
