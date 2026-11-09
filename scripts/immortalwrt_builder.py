#!/usr/bin/env python3
"""Version and integrity metadata for the reusable ImmortalWrt NSS ImageBuilder."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
# Only source-build inputs belong here; overlay, plugin selections and
# metadata scripts can change without invalidating a compiled ImageBuilder.
CORE_RECIPE = "scripts/build-immortalwrt.sh"
FIRMWARE_ONLY_BEGIN = b"# BEGIN firmware-only overlay (excluded from Builder fingerprint)\n"
FIRMWARE_ONLY_END = b"# END firmware-only overlay\n"


def core_recipe_bytes(raw: bytes) -> bytes:
    """Exclude only the explicitly marked firmware-overlay staging block.

    Changes to kernel, feeds, NSS and compile commands outside these markers
    still invalidate the ABI-matched Builder. A missing/duplicate marker is
    a hard error; never accidentally hash the wrong script portion.
    """
    if raw.count(FIRMWARE_ONLY_BEGIN) != 1 or raw.count(FIRMWARE_ONLY_END) != 1:
        raise ValueError("Firmware-only overlay markers missing or duplicated")
    before, tail = raw.split(FIRMWARE_ONLY_BEGIN, 1)
    firmware_only, after = tail.split(FIRMWARE_ONLY_END, 1)
    if not firmware_only:
        raise ValueError("Empty firmware-only overlay section")
    return before + b"# firmware-only overlay omitted from core fingerprint\n" + after


CORE_FILES = (
    CORE_RECIPE,
    "scripts/reuse-official-toolchain.sh",
    "scripts/port-ppe-nss-to-immortalwrt.sh",
    "scripts/apply-immortalwrt-compat.sh",
    "config/immortalwrt-re-ss-01.config",
)
# Package selection is not a kernel ABI constraint, but rebuilding the
# package repository after a change requires a distinct immutable Release.
PACKAGE_FILES = ("config/add.txt", "config/remove.txt")
SHA = re.compile(r"^[a-f0-9]{40}$")
FP_SHA = re.compile(r"^[a-f0-9]{64}$")
PROFILE = "jdcloud_re-ss-01"
CHANNEL = "re-ss-01-immortal-imagebuilder"

# Actions run 42594186291 created this *complete* standalone Builder with the
# original metadata schema. Later edits changed source-provenance bookkeeping
# and optional firmware overlays, not its kernel, NSS, or package ABI.
# This is a single audited legacy release, NOT a wildcard bypass for old builds.
LEGACY_TAG = "imm-builder-4765b657-7d65a3ed-5796d271-gfe40805a5baf"
LEGACY_SOURCE_COMMIT = "b546e0cc79ab1328f24f120e88d7a9407575a277"
LEGACY_META_SHA256 = "f0d03f353eadf9b9dc913770ef08157a34a2d3a1b8bd74196ac613479bbfe450"
LEGACY_CORE_RECIPE_SHA256 = "2744befd95c62e0a76564eb5edb0f587f68f5b70f4476e773f18f6b18e32a9b9"
# Hashes of *source-build* dependencies, unchanged since that successful run.
# These are canonical Git blob object IDs, independent of Git checkout depth.
LEGACY_CORE_BLOBS = {
    "scripts/reuse-official-toolchain.sh": "0dee01da44c211d1b1716e8861bdff002e0b8fbd",
    "scripts/port-ppe-nss-to-immortalwrt.sh": "fbc6a29a065b0bb0361aa71d4e0c7982014575cb",
    "scripts/apply-immortalwrt-compat.sh": "4e967a80d2ce1a9e7865122167e0e0e1ee0d59eb",
    "config/immortalwrt-re-ss-01.config": "490f353437cfc11c7af3411acda56d4d3a419a90",
}
# GitHub's published SHA256 digests for the immutable Builder input files.
LEGACY_ASSET_SHA256 = {
    "archive": "8fdd1c39ce2d64fc92f19c7028c38181450e814397c64529b9d35de4bb3ed4e0",
    "overlay": "eec8cfb7eecc3841fa9086c4822f3f618dd0ee41ca55645893a5ec3e23ff5042",
    "packages": "19278099026c4f608b4d95460a73cecbcaf74a3f909db64498ea15961d1f2f44",
}


def fingerprint(root: Path = ROOT) -> str:
    digest = hashlib.sha256()
    for name in CORE_FILES:
        data = (root / name).read_bytes()
        if name == CORE_RECIPE:
            data = core_recipe_bytes(data)
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(data)
        digest.update(b"\0")
    return digest.hexdigest()


def package_fingerprint(root: Path = ROOT) -> str:
    digest = hashlib.sha256()
    for name in PACKAGE_FILES:
        digest.update(name.encode("utf-8") + b"\0")
        digest.update((root / name).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def release_tag(immortal: str, ppe: str, base: str, core: str, packages: str,
                feeds: str) -> str:
    for value in (immortal, ppe, base):
        check_sha(value)
    if any(not FP_SHA.fullmatch(value) for value in (core, packages, feeds)):
        raise ValueError("Expected SHA256 fingerprints")
    return (f"imm-builder-{immortal[:8]}-{ppe[:8]}-{base[:8]}"
            f"-g{core[:12]}-p{packages[:8]}-f{feeds[:8]}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check_sha(value: str) -> None:
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ValueError("Expected a 40-character lowercase SHA")


def git_blob_id(data: bytes) -> str:
    """Match Git's content-addressed blob ID without needing full Git history."""
    return hashlib.sha1(f"blob {len(data)}".encode() + bytes((0,)) + data).hexdigest()


def legacy_sources_compatible(root: Path = ROOT) -> bool:
    """Fail closed if kernel, NSS, toolchain or source recipe is modified.

    The firmware-only overlay is intentionally outside the ABI comparison;
    editing LuCI, Dr.COM, OTA or other files/ assets cannot require a rebuild.
    """
    try:
        recipe = core_recipe_bytes((root / CORE_RECIPE).read_bytes())
        if hashlib.sha256(recipe).hexdigest() != LEGACY_CORE_RECIPE_SHA256:
            return False
        return all(git_blob_id((root / name).read_bytes()) == old
                   for name, old in LEGACY_CORE_BLOBS.items())
    except (OSError, ValueError):
        return False


def check_metadata(path: Path) -> tuple[dict, bool]:
    """Return (metadata, is_pinned_legacy_builder) on ABI-safe metadata."""
    doc = json.loads(path.read_text())
    if doc.get("schema") != 1 or doc.get("channel") != CHANNEL:
        raise ValueError("Wrong builder channel or schema")
    if doc.get("profile") != PROFILE or doc.get("packaging") != "standalone":
        raise ValueError("Builder target or packaging mismatch")
    for key in ("immortalwrt_commit", "ppe_nss_commit", "base_overlay_commit"):
        check_sha(doc.get(key, ""))

    if doc.get("tag") == LEGACY_TAG:
        # Both its metadata and its compiler provenance are pinned. The old
        # schema lacks feed/package digests, so do not accept any other tag.
        if sha256(path) != LEGACY_META_SHA256:
            raise ValueError("Pinned legacy Builder metadata integrity mismatch")
        if not legacy_sources_compatible():
            raise ValueError("Legacy Builder kernel/NSS build inputs have changed")
        return doc, True

    packages = doc.get("package_fingerprint", "")
    feeds = doc.get("feeds_fingerprint", "")
    if not isinstance(packages, str) or not FP_SHA.fullmatch(packages):
        raise ValueError("Missing package fingerprint in Builder metadata")
    if not isinstance(feeds, str) or not FP_SHA.fullmatch(feeds):
        raise ValueError("Missing feeds fingerprint in Builder metadata")
    expected = release_tag(doc["immortalwrt_commit"], doc["ppe_nss_commit"],
                           doc["base_overlay_commit"], fingerprint(), packages,
                           feeds)
    if doc.get("tag") != expected or doc.get("fingerprint") != fingerprint():
        raise ValueError("Builder is stale for current core config; regenerate it")
    return doc, False


def tag(immortal: str, ppe: str, base: str, root: Path = ROOT,
        feeds: str = "0" * 64) -> str:
    return release_tag(immortal, ppe, base, fingerprint(root),
                       package_fingerprint(root), feeds)


def metadata(args: argparse.Namespace) -> None:
    for value in (args.immortal, args.ppe, args.base):
        check_sha(value)
    feeds = getattr(args, "feeds", "0" * 64)
    if not FP_SHA.fullmatch(feeds):
        raise ValueError("Invalid upstream feeds digest")
    for path in (args.archive, args.overlay, args.packages):
        if not path.is_file() or path.stat().st_size < 100:
            raise ValueError(f"Missing/empty builder artifact: {path}")
    doc = {
        "schema": 1,
        "channel": CHANNEL,
        "profile": PROFILE,
        "packaging": "standalone",
        "tag": tag(args.immortal, args.ppe, args.base, feeds=feeds),
        "fingerprint": fingerprint(),
        "feeds_fingerprint": feeds,
        "package_fingerprint": package_fingerprint(),
        "immortalwrt_commit": args.immortal,
        "ppe_nss_commit": args.ppe,
        "base_overlay_commit": args.base,
        "archive": args.archive.name,
        "archive_sha256": sha256(args.archive),
        "overlay": args.overlay.name,
        "overlay_sha256": sha256(args.overlay),
        "packages": args.packages.name,
        "packages_sha256": sha256(args.packages),
    }
    args.output.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")


def verify(args: argparse.Namespace) -> None:
    doc, legacy = check_metadata(args.metadata)
    for key, path, checksum in (
        ("archive", args.archive, "archive_sha256"),
        ("overlay", args.overlay, "overlay_sha256"),
        ("packages", args.packages, "packages_sha256"),
    ):
        actual_hash = sha256(path)
        if path.name != doc.get(key) or actual_hash != doc.get(checksum):
            raise ValueError(f"Builder artifact integrity mismatch: {key}")
        if legacy and actual_hash != LEGACY_ASSET_SHA256[key]:
            raise ValueError(f"Pinned legacy Builder asset digest mismatch: {key}")
    print(f"Verified ImageBuilder: {doc['tag']}"
          + (" (audited legacy ABI)" if legacy else ""))


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="action", required=True)
    sub.add_parser("fingerprint")
    t = sub.add_parser("tag")
    for name in ("immortal", "ppe", "base"):
        t.add_argument(f"--{name}", required=True)
    t.add_argument("--feeds", default="0" * 64)
    m = sub.add_parser("metadata")
    for name in ("immortal", "ppe", "base"):
        m.add_argument(f"--{name}", required=True)
    m.add_argument("--feeds", default="0" * 64)
    m.add_argument("--archive", required=True, type=Path)
    m.add_argument("--overlay", required=True, type=Path)
    m.add_argument("--packages", required=True, type=Path)
    m.add_argument("--output", required=True, type=Path)
    c = sub.add_parser("check")
    c.add_argument("--metadata", required=True, type=Path)
    v = sub.add_parser("verify")
    for name in ("metadata", "archive", "overlay", "packages"):
        v.add_argument(f"--{name}", required=True, type=Path)
    args = p.parse_args()
    if args.action == "fingerprint":
        print(fingerprint())
    elif args.action == "tag":
        print(tag(args.immortal, args.ppe, args.base, feeds=args.feeds))
    elif args.action == "metadata":
        metadata(args)
    elif args.action == "check":
        doc, legacy = check_metadata(args.metadata)
        print("Compatible Builder: " + doc["tag"]
              + (" (audited legacy ABI)" if legacy else ""))
    else:
        verify(args)


if __name__ == "__main__":
    main()
