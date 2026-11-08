#!/usr/bin/env python3
"""Version and integrity metadata for the reusable ImmortalWrt NSS ImageBuilder."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CORE_FILES = (
    "scripts/build-immortalwrt.sh",
    "scripts/port-ppe-nss-to-immortalwrt.sh",
    "scripts/immortalwrt_builder.py",
    "config/immortalwrt-re-ss-01.config",
    "config/add.txt",
    "config/remove.txt",
)
SHA = re.compile(r"^[a-f0-9]{40}$")
PROFILE = "jdcloud_re-ss-01"
CHANNEL = "re-ss-01-immortal-imagebuilder"


def fingerprint(root: Path = ROOT) -> str:
    digest = hashlib.sha256()
    for name in CORE_FILES:
        data = (root / name).read_bytes()
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(data)
        digest.update(b"\0")
    return digest.hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check_sha(value: str) -> None:
    if not SHA.fullmatch(value):
        raise ValueError("Expected a 40-character lowercase SHA")


def tag(immortal: str, ppe: str, base: str, root: Path = ROOT) -> str:
    for value in (immortal, ppe, base):
        check_sha(value)
    return f"imm-builder-{immortal[:8]}-{ppe[:8]}-{base[:8]}-g{fingerprint(root)[:12]}"


def metadata(args: argparse.Namespace) -> None:
    for value in (args.immortal, args.ppe, args.base):
        check_sha(value)
    for path in (args.archive, args.overlay, args.packages):
        if not path.is_file() or path.stat().st_size < 100:
            raise ValueError(f"Missing/empty builder artifact: {path}")
    doc = {
        "schema": 1,
        "channel": CHANNEL,
        "profile": PROFILE,
        "packaging": "standalone",
        "tag": tag(args.immortal, args.ppe, args.base),
        "fingerprint": fingerprint(),
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
    doc = json.loads(args.metadata.read_text())
    if doc.get("schema") != 1 or doc.get("channel") != CHANNEL:
        raise ValueError("Wrong builder channel or schema")
    if doc.get("profile") != PROFILE or doc.get("packaging") != "standalone":
        raise ValueError("Builder target or packaging mismatch")
    for key in ("immortalwrt_commit", "ppe_nss_commit", "base_overlay_commit"):
        check_sha(doc.get(key, ""))
    expected = tag(doc["immortalwrt_commit"], doc["ppe_nss_commit"],
                   doc["base_overlay_commit"])
    if doc.get("tag") != expected or doc.get("fingerprint") != fingerprint():
        raise ValueError("Builder is stale for current core config; regenerate it")
    for key, path, checksum in (
        ("archive", args.archive, "archive_sha256"),
        ("overlay", args.overlay, "overlay_sha256"),
        ("packages", args.packages, "packages_sha256"),
    ):
        if path.name != doc.get(key) or sha256(path) != doc.get(checksum):
            raise ValueError(f"Builder artifact integrity mismatch: {key}")
    print(f"Verified ImageBuilder: {doc['tag']}")


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="action", required=True)
    sub.add_parser("fingerprint")
    t = sub.add_parser("tag")
    for name in ("immortal", "ppe", "base"):
        t.add_argument(f"--{name}", required=True)
    m = sub.add_parser("metadata")
    for name in ("immortal", "ppe", "base"):
        m.add_argument(f"--{name}", required=True)
    m.add_argument("--archive", required=True, type=Path)
    m.add_argument("--overlay", required=True, type=Path)
    m.add_argument("--output", required=True, type=Path)
    v = sub.add_parser("verify")
    for name in ("metadata", "archive", "overlay", "packages"):
        v.add_argument(f"--{name}", required=True, type=Path)
    args = p.parse_args()
    if args.action == "fingerprint":
        print(fingerprint())
    elif args.action == "tag":
        print(tag(args.immortal, args.ppe, args.base))
    elif args.action == "metadata":
        metadata(args)
    else:
        verify(args)


if __name__ == "__main__":
    main()
