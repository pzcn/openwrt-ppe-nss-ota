#!/usr/bin/env python3
"""Immutable, device-scoped OTA tags using REAL ImmortalWrt Snapshot revisions.

  imm-<device>-SNAPSHOT-r<official revision>-<Asia/Shanghai YYYYMMDDHHMM>

MX4200 uses the signed official userspace Snapshot in its immutable lock.
Arthur uses an official Snapshot lock when the Builder has one; its legacy
full-source Builder instead uses the exact pinned ImmortalWrt master commit
and the upstream revision baseline from scripts/getver.sh.

The numeric OTA build is still the Unix epoch (seconds), not a string tag.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import subprocess

DEVICES = ("arthur", "mx4200v1")
BEIJING = timezone(timedelta(hours=8))
REVISION_PATTERN = re.compile(r"^(r[1-9][0-9]{3,7})(?:-[0-9a-f]{7,40})?$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
TAG_PATTERN = re.compile(
    r"^imm-(arthur|mx4200v1)-SNAPSHOT-r[1-9][0-9]{3,7}-[0-9]{12}$"
)
# Exact baseline from immortalwrt/immortalwrt scripts/getver.sh at the pinned
# source revision. GitHub compare.ahead_by counts commits after this baseline;
# unlike compare.total_commits, ahead_by is NOT capped at 10,000.
REVISION_BASE = "ee53a240ac902dc83209008a2671e7fdcf55957a"


def short_revision(revision: str) -> str:
    """Extract official numeric r-number, never fabricate one from a date."""
    if not isinstance(revision, str):
        raise ValueError("Snapshot revision must be a string")
    match = REVISION_PATTERN.fullmatch(revision)
    if not match:
        raise ValueError(f"Not an official Snapshot revision: {revision!r}")
    return match.group(1)


def source_revision(commit: str) -> str:
    """Resolve official ImmortalWrt source commit via the getver.sh baseline.

    A repository's own full-source Builder may predate its current official
    Snapshot APKs; never copy the newer snapshot number onto that old kernel.
    """
    if not isinstance(commit, str) or not COMMIT_PATTERN.fullmatch(commit):
        raise ValueError("Expected pinned ImmortalWrt 40-character source SHA")
    endpoint = f"repos/immortalwrt/immortalwrt/compare/{REVISION_BASE}...{commit}"
    try:
        output = subprocess.run(
            ["gh", "api", endpoint,
             "--jq", "{ahead_by:.ahead_by,behind_by:.behind_by,"
                      "status:.status,merge_base:.merge_base_commit.sha}"],
            check=True, text=True, capture_output=True, timeout=90,
        ).stdout
        info = json.loads(output)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired,
            json.JSONDecodeError) as exc:
        raise ValueError("Cannot verify ImmortalWrt upstream revision") from exc
    number = info.get("ahead_by")
    if (info.get("status") != "ahead" or info.get("behind_by") != 0 or
            info.get("merge_base") != REVISION_BASE or
            type(number) is not int or not 1000 <= number <= 99999999):
        raise ValueError("Unverified ImmortalWrt upstream revision ancestry")
    return f"r{number}"


def select_revision(*, device: str, revision: str | None = None,
                    snapshot_lock: Path | None = None,
                    builder_metadata: Path | None = None,
                    source_commit: str | None = None) -> str:
    """Use exactly one authenticated provenance source; reject missing data."""
    if device not in DEVICES:
        raise ValueError(f"Unsupported OTA device: {device}")
    if sum(x is not None for x in
           (revision, snapshot_lock, builder_metadata, source_commit)) != 1:
        raise ValueError("Supply exactly one official Snapshot revision source")
    if revision is not None:
        return short_revision(revision)
    if source_commit is not None:
        return source_revision(source_commit)
    if snapshot_lock is not None:
        lock = json.loads(snapshot_lock.read_text())
        if (device != "mx4200v1" or lock.get("schema") != 2 or
                lock.get("target") != "qualcommax/ipq807x"):
            raise ValueError("Wrong MX4200 official Snapshot lock")
        return short_revision(lock.get("snapshot_version"))
    if builder_metadata is not None:
        metadata = json.loads(builder_metadata.read_text())
        if (device != "arthur" or metadata.get("schema") != 1 or
                metadata.get("profile") != "jdcloud_re-ss-01" or
                metadata.get("channel") != "re-ss-01-immortal-imagebuilder"):
            raise ValueError("Wrong Arthur Builder provenance")
        official = metadata.get("official_snapshot")
        if official is not None:
            if metadata.get("build_mode") != "hybrid":
                raise ValueError("Official Snapshot attached to nonhybrid Builder")
            return short_revision(official.get("snapshot_version"))
        return source_revision(metadata.get("immortalwrt_commit"))
    raise AssertionError("No version provenance")


def make_tag(device: str, build_epoch: int, revision: str) -> str:
    if device not in DEVICES:
        raise ValueError(f"Unsupported OTA device: {device}")
    if type(build_epoch) is not int or build_epoch < 1_000_000_000:
        raise ValueError("Expected a Unix epoch build number in seconds")
    dt = datetime.fromtimestamp(build_epoch, tz=BEIJING)
    rev = short_revision(revision)
    tag = f"imm-{device}-SNAPSHOT-{rev}-{dt:%Y%m%d%H%M}"
    if not TAG_PATTERN.fullmatch(tag):
        raise ValueError("Invalid OTA tag")
    return tag


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("device", choices=DEVICES)
    parser.add_argument("build_epoch", type=int)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--revision")
    source.add_argument("--snapshot-lock", type=Path)
    source.add_argument("--builder-metadata", type=Path)
    source.add_argument("--source-commit")
    args = parser.parse_args()
    rev = select_revision(
        device=args.device, revision=args.revision,
        snapshot_lock=args.snapshot_lock,
        builder_metadata=args.builder_metadata,
        source_commit=args.source_commit,
    )
    print(make_tag(args.device, args.build_epoch, rev))


if __name__ == "__main__":
    main()
