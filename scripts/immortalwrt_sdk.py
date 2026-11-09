#!/usr/bin/env python3
"""Issue and verify an SDK bound to exactly one ImmortalWrt PPE/NSS Builder.

The SDK is uploaded alongside the ImageBuilder under the same immutable
imm-builder-* Release. Feed HEADs are locked so future package recompilation
cannot silently switch to newer userland or kernel-module sources.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from immortalwrt_builder import check_metadata, check_sha, sha256

SDK_CHANNEL = "re-ss-01-immortal-sdk"
SDK_TARGET = "qualcommax/ipq60xx"
FEEDS = ("packages", "luci", "routing", "telephony", "nss", "ppe_qos_luci")
SDK_NAME = re.compile(r"^immortalwrt-sdk-qualcommax-ipq60xx[0-9A-Za-z._+-]*\.tar\.zst$")


def feed_fingerprint(feeds: dict[str, str]) -> str:
    if set(feeds) != set(FEEDS):
        raise ValueError("Feed lock must contain precisely the six Builder feeds")
    for key in FEEDS:
        check_sha(feeds[key])
    raw = "".join(feeds[key] + "\n" for key in FEEDS).encode("ascii")
    return hashlib.sha256(raw).hexdigest()


def source_head(folder: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(folder), "rev-parse", "HEAD"],
        check=True, text=True, capture_output=True
    )
    head = result.stdout.strip()
    check_sha(head)
    return head


def write_json(path: Path, doc: dict) -> None:
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def make_metadata(args: argparse.Namespace) -> None:
    builder, legacy = check_metadata(args.builder_metadata)
    if legacy:
        raise ValueError("SDK publishing requires Builder metadata with locked feed revisions")
    if not SDK_NAME.fullmatch(args.archive.name) or not args.archive.is_file():
        raise ValueError("Missing or wrong-target qualcommax/ipq60xx SDK archive")
    if args.archive.stat().st_size < 100:
        raise ValueError("Empty SDK archive")
    if not args.toolchain_status.is_file():
        raise ValueError("Missing toolchain provenance")

    actual_source = source_head(args.source)
    if actual_source != builder["immortalwrt_commit"]:
        raise ValueError("SDK source is different from the Builder's ImmortalWrt commit")

    feeds = {
        name: source_head(args.ppe_luci if name == "ppe_qos_luci"
                          else args.source / "feeds" / name)
        for name in FEEDS
    }
    digest = feed_fingerprint(feeds)
    if digest != builder["feeds_fingerprint"]:
        raise ValueError("SDK feeds do not match the Builder's compiled package versions")
    mode = args.toolchain_status.read_text().splitlines()[0]
    if mode not in ("toolchain=official-immortalwrt", "toolchain=source"):
        raise ValueError("Unknown or empty toolchain provenance")

    lock = {
        "schema": 1,
        "channel": SDK_CHANNEL,
        "builder_tag": builder["tag"],
        "immortalwrt_commit": actual_source,
        "feeds": feeds,
        "feeds_fingerprint": digest,
    }
    write_json(args.feed_lock, lock)
    sdk = {
        "schema": 1,
        "channel": SDK_CHANNEL,
        "target": SDK_TARGET,
        "profile": builder["profile"],
        "builder_tag": builder["tag"],
        "builder_metadata_sha256": sha256(args.builder_metadata),
        "immortalwrt_commit": builder["immortalwrt_commit"],
        "ppe_nss_commit": builder["ppe_nss_commit"],
        "base_overlay_commit": builder["base_overlay_commit"],
        "feeds_fingerprint": digest,
        "toolchain": mode.split("=", 1)[1],
        "archive": args.archive.name,
        "archive_sha256": sha256(args.archive),
        "feed_lock": args.feed_lock.name,
        "feed_lock_sha256": sha256(args.feed_lock),
    }
    write_json(args.output, sdk)
    verify_files(args.output, args.builder_metadata, args.archive, args.feed_lock)


def verify_files(metadata: Path, builder_metadata: Path, archive: Path,
                 feed_lock: Path) -> dict:
    builder, legacy = check_metadata(builder_metadata)
    if legacy:
        raise ValueError("SDK cannot be verified against legacy Builder metadata")
    sdk = json.loads(metadata.read_text())
    lock = json.loads(feed_lock.read_text())
    if not SDK_NAME.fullmatch(archive.name):
        raise ValueError("Wrong-target SDK archive")
    expected = {
        "schema": 1,
        "channel": SDK_CHANNEL,
        "target": SDK_TARGET,
        "profile": builder["profile"],
        "builder_tag": builder["tag"],
        "builder_metadata_sha256": sha256(builder_metadata),
        "immortalwrt_commit": builder["immortalwrt_commit"],
        "ppe_nss_commit": builder["ppe_nss_commit"],
        "base_overlay_commit": builder["base_overlay_commit"],
        "feeds_fingerprint": builder["feeds_fingerprint"],
        "archive": archive.name,
        "archive_sha256": sha256(archive),
        "feed_lock": feed_lock.name,
        "feed_lock_sha256": sha256(feed_lock),
    }
    for key, value in expected.items():
        if sdk.get(key) != value:
            raise ValueError(f"SDK differs from the compiled Builder: {key}")
    if sdk.get("toolchain") not in ("official-immortalwrt", "source"):
        raise ValueError("Unknown SDK toolchain")
    if (lock.get("schema") != 1 or lock.get("channel") != SDK_CHANNEL
            or lock.get("builder_tag") != builder["tag"]
            or lock.get("immortalwrt_commit") != builder["immortalwrt_commit"]):
        raise ValueError("SDK feed lock references a different Builder")
    if feed_fingerprint(lock.get("feeds", {})) != builder["feeds_fingerprint"]:
        raise ValueError("SDK feed checkout is incompatible with Builder")
    if lock.get("feeds_fingerprint") != builder["feeds_fingerprint"]:
        raise ValueError("SDK feed lock fingerprint mismatch")
    print(f"Verified matching SDK: {archive.name} for {builder['tag']}")
    return sdk


def main() -> None:
    parser = argparse.ArgumentParser()
    command = parser.add_subparsers(dest="action", required=True)
    create = command.add_parser("metadata", help="create SDK metadata and feed lock")
    create.add_argument("--source", type=Path, required=True)
    create.add_argument("--ppe-luci", type=Path, required=True)
    create.add_argument("--toolchain-status", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--feed-lock", type=Path, required=True)
    verify = command.add_parser("verify", help="verify the exact SDK/Builder pair")
    verify.add_argument("--metadata", type=Path, required=True)
    verify.add_argument("--feed-lock", type=Path, required=True)
    for parser_ in (create, verify):
        parser_.add_argument("--builder-metadata", type=Path, required=True)
        parser_.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "metadata":
        make_metadata(args)
    else:
        verify_files(args.metadata, args.builder_metadata, args.archive, args.feed_lock)


if __name__ == "__main__":
    main()
