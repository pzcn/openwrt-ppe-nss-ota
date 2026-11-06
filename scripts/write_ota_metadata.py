#!/usr/bin/env python3
"""Create immutable per-Release OTA metadata for the JDCloud RE-SS-01.

The image contains its own build number in /etc/pzcn-ota-release.
The firmware and its manifest are hashed *after* ImageBuilder runs.
This script is deliberately deterministic except for build epoch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import time

REPOSITORY = "pzcn/openwrt-ppe-nss-ota"
CHANNEL = "re-ss-01-custom"
BOARD = "jdcloud,re-ss-01"
PROFILE = "jdcloud_re-ss-01"
GROUP = "ipq60xx-512m"
IMAGE = "openwrt-pzcn-qualcommax-ipq60xx-jdcloud_re-ss-01-squashfs-sysupgrade.bin"
MANIFEST = "openwrt-pzcn-qualcommax-ipq60xx-jdcloud_re-ss-01.manifest"
SAFE_TAG = re.compile(r"^ota-ppe-nss-[A-Za-z0-9._-]+$")
UPSTREAM_TAG = re.compile(r"^ppe-nss-[A-Za-z0-9._-]+$")


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def generate(tag: str, build: int, upstream: str, group: str, profile: str,
             image: Path, manifest: Path, epoch: int | None = None) -> dict:
    if not SAFE_TAG.fullmatch(tag):
        raise ValueError("Invalid custom OTA release tag")
    if not UPSTREAM_TAG.fullmatch(upstream):
        raise ValueError("Invalid upstream PPE+NSS release tag")
    if not (build > 0 and group == GROUP and profile == PROFILE):
        raise ValueError("Invalid build id, group or profile")
    if image.name != IMAGE or manifest.name != MANIFEST:
        raise ValueError("Unexpected firmware or manifest filename")
    if not image.is_file() or image.stat().st_size < 1_000_000:
        raise ValueError("Firmware does not exist or is unexpectedly small")
    if not manifest.is_file() or manifest.stat().st_size < 100:
        raise ValueError("Package manifest does not exist or is unexpectedly small")
    if epoch is None:
        epoch = int(time.time())
    if epoch <= 0:
        raise ValueError("Invalid build epoch")

    return {
        "schema": 1,
        "channel": CHANNEL,
        "repository": REPOSITORY,
        "tag": tag,
        "build": build,
        "epoch": epoch,
        "board": BOARD,
        "profile": PROFILE,
        "group": GROUP,
        "upstream_tag": upstream,
        "image": IMAGE,
        "image_size": image.stat().st_size,
        "image_sha256": digest(image),
        "manifest": MANIFEST,
        "manifest_sha256": digest(manifest),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--build", type=int, required=True)
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--group", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    metadata = generate(
        args.tag, args.build, args.upstream, args.group, args.profile,
        args.image, args.manifest,
    )
    args.output.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    print(f"Custom OTA metadata for {metadata['tag']} (build {metadata['build']})")


if __name__ == "__main__":
    main()
