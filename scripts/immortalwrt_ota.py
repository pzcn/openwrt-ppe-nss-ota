#!/usr/bin/env python3
"""Prepare an independent ImmortalWrt PPE/NSS OTA channel and its release metadata."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import time

REPOSITORY = "pzcn/openwrt-ppe-nss-ota"
CHANNEL = "re-ss-01-immortal-ppe-nss"
GROUP = "ipq60xx-512m"
PROFILE = "jdcloud_re-ss-01"
BOARD = "jdcloud,re-ss-01"
IMAGE = "immortalwrt-qualcommax-ipq60xx-jdcloud_re-ss-01-squashfs-sysupgrade.bin"
MANIFEST = "immortalwrt-qualcommax-ipq60xx-jdcloud_re-ss-01.manifest"
TAG_PATTERN = re.compile(r"^imm-ppe-nss-[a-zA-Z0-9._-]+$")
SHA_PATTERN = re.compile(r"^[a-f0-9]{40}$")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fd:
        for chunk in iter(lambda: fd.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def replace_once(source: str, before: str, after: str) -> str:
    count = source.count(before)
    if count != 1:
        raise ValueError(f"Expected one occurrence, found {count}: {before[:80]}")
    return source.replace(before, after)


def prepare(overlay: Path, tag: str, build: int) -> None:
    if not TAG_PATTERN.fullmatch(tag) or build < 1:
        raise ValueError("Invalid release tag/build")
    ota = overlay / "usr/sbin/ppe-update"
    source = ota.read_text()
    patches = [
        ('[ -r "${PPE_RELEASE:=/etc/ppe-release}" ] && . "$PPE_RELEASE"',
         "GROUP='ipq60xx-512m'"),
        ('[ -r "${PZCN_RELEASE:=/etc/pzcn-ota-release}" ] && . "$PZCN_RELEASE"',
         '[ -r "${PZCN_RELEASE:=/etc/immortal-ppe-ota-release}" ] && . "$PZCN_RELEASE"'),
        ("RELEASE_API='https://api.github.com/repos/pzcn/openwrt-ppe-nss-ota/releases/latest'",
         "RELEASE_API='https://api.github.com/repos/pzcn/openwrt-ppe-nss-ota/releases?per_page=100'"),
        ("RELEASE_CHANNEL='re-ss-01-custom'",
         f"RELEASE_CHANNEL='{CHANNEL}'"),
        ("EXPECTED_IMAGE='openwrt-pzcn-qualcommax-ipq60xx-jdcloud_re-ss-01-squashfs-sysupgrade.bin'",
         f"EXPECTED_IMAGE='{IMAGE}'"),
        ("EXPECTED_MANIFEST='openwrt-pzcn-qualcommax-ipq60xx-jdcloud_re-ss-01.manifest'",
         f"EXPECTED_MANIFEST='{MANIFEST}'"),
        ("LATEST=$(jsonfilter -i \"$WORK/github.json\" -e '@.tag_name')",
         """if ! jq -e 'type == "array"' "$WORK/github.json" >/dev/null 2>&1; then
    die "invalid GitHub Releases API response"
fi
LATEST=$(jq -r 'map(select(.draft == false and (.tag_name | startswith("imm-ppe-nss-")))) | .[0].tag_name // empty' "$WORK/github.json") ||
    die "failed to parse GitHub firmware release index"
[ -n "$LATEST" ] || die "no ImmortalWrt firmware release is published on this channel" """),
        ('\tota-ppe-nss-*) ;;', '\timm-ppe-nss-*) ;;'),
        ('\tppe-nss-*) ;;', '\timmortal-*) ;;'),
    ]
    for before, after in patches:
        source = replace_once(source, before, after)
    if "sysupgrade -T" not in source or "cmd_auto()" not in source:
        raise ValueError("OTA backend lost firmware validation/automatic update")
    ota.write_text(source)
    ota.chmod(0o755)

    release = overlay / "etc/immortal-ppe-ota-release"
    release.parent.mkdir(parents=True, exist_ok=True)
    release.write_text(
        f"OTA_TAG={shlex.quote(tag)}\n"
        f"OTA_BUILD={build}\n"
        f"OTA_CHANNEL={shlex.quote(CHANNEL)}\n"
    )


def metadata(tag: str, build: int, upstream: str, ppe: str, image: Path,
             manifest: Path, output: Path) -> None:
    if not TAG_PATTERN.fullmatch(tag) or build < 1:
        raise ValueError("Invalid tag/build")
    if not SHA_PATTERN.fullmatch(upstream) or not SHA_PATTERN.fullmatch(ppe):
        raise ValueError("Expected 40-character source commit SHAs")
    if image.name != IMAGE or manifest.name != MANIFEST:
        raise ValueError("Unexpected image or manifest basename")
    if not image.is_file() or image.stat().st_size < 1_000_000:
        raise ValueError("Missing or unusually small firmware image")
    if not manifest.is_file() or manifest.stat().st_size < 100:
        raise ValueError("Missing package manifest")
    doc = {
        "schema": 1,
        "channel": CHANNEL,
        "repository": REPOSITORY,
        "tag": tag,
        "build": build,
        "epoch": int(time.time()),
        "board": BOARD,
        "profile": PROFILE,
        "group": GROUP,
        "upstream_tag": f"immortal-{upstream[:12]}",
        "immortalwrt_commit": upstream,
        "ppe_nss_commit": ppe,
        "image": IMAGE,
        "image_size": image.stat().st_size,
        "image_sha256": sha256(image),
        "manifest": MANIFEST,
        "manifest_sha256": sha256(manifest),
    }
    output.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="action", required=True)
    a = subs.add_parser("prepare")
    a.add_argument("--overlay", type=Path, required=True)
    a.add_argument("--tag", required=True)
    a.add_argument("--build", type=int, required=True)
    b = subs.add_parser("metadata")
    b.add_argument("--tag", required=True)
    b.add_argument("--build", type=int, required=True)
    b.add_argument("--immortal-commit", required=True)
    b.add_argument("--ppe-commit", required=True)
    b.add_argument("--image", type=Path, required=True)
    b.add_argument("--manifest", type=Path, required=True)
    b.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.overlay, args.tag, args.build)
    else:
        metadata(args.tag, args.build, args.immortal_commit, args.ppe_commit,
                 args.image, args.manifest, args.output)


if __name__ == "__main__":
    main()
