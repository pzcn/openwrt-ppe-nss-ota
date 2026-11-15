#!/usr/bin/env python3
"""Select a verified candidate Arthur ImageBuilder without building a new one.

Priority: newest stable Hybrid > explicitly allowlisted prerelease Hybrid.
Legacy full-source remains available via explicit workflow input; the default
must not silently fall back to the old package baseline.
A prerelease Builder can only produce inspectable, NON-STABLE firmware.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

TAG = re.compile(r"^imm-builder-[a-zA-Z0-9._-]+$")
IB = re.compile(r"^immortalwrt-imagebuilder-qualcommax-ipq60xx[^/]*[.]tar[.]zst$")
SDK = re.compile(r"^immortalwrt-sdk-qualcommax-ipq60xx[^/]*[.]tar[.]zst$")
REQUIRED = {
    "builder-metadata.json", "base-overlay.tar.gz", "imagebuilder-packages.txt",
}
HYBRID_REQUIRED = REQUIRED | {
    "snapshot-lock.json", "official-apks.json",
    "sdk-metadata.json", "sdk-feeds.lock.json",
}


def asset_names(release: dict) -> set[str]:
    assets = release.get("assets")
    if not isinstance(assets, list):
        return set()
    return {asset["name"] for asset in assets
            if isinstance(asset, dict) and isinstance(asset.get("name"), str)}


def valid(release: dict, hybrid: bool) -> bool:
    if (not isinstance(release, dict) or release.get("draft") is not False
            or type(release.get("prerelease")) is not bool
            or not TAG.fullmatch(str(release.get("tag_name", "")))):
        return False
    names = asset_names(release)
    needed = HYBRID_REQUIRED if hybrid else REQUIRED
    if not needed <= names or sum(bool(IB.fullmatch(n)) for n in names) != 1:
        return False
    if hybrid:
        if not str(release.get("name", "")).startswith("Hybrid ImageBuilder + SDK "):
            return False
        if sum(bool(SDK.fullmatch(n)) for n in names) != 1:
            return False
    return True


def choose(releases: list[dict], policy: dict, requested: str = "") -> dict:
    if not isinstance(releases, list) or not isinstance(policy, dict):
        raise ValueError("Invalid GitHub release index or policy")
    approved = policy.get("preferred_prerelease_tag")
    if (policy.get("schema") != 1 or not isinstance(approved, str)
            or not TAG.fullmatch(approved)):
        raise ValueError("Invalid pinned Hybrid candidate policy")

    if requested:
        if not TAG.fullmatch(requested):
            raise ValueError("Invalid requested Builder tag")
        matches = [x for x in releases if x.get("tag_name") == requested]
        if len(matches) != 1:
            raise ValueError("Requested Builder release is not available")
        release = matches[0]
        hybrid = str(release.get("name", "")).startswith("Hybrid ImageBuilder + SDK ")
        if not valid(release, hybrid):
            raise ValueError("Requested Builder lacks required verified assets")
        if release["prerelease"] and (not hybrid or requested != approved):
            raise ValueError("Unapproved prerelease Builder cannot feed firmware")
        reason = "explicit request"
    else:
        # Prefer only stable Hybrid releases once hardware validation promotes
        # them. Never rank an old Full Source Builder above a tested Hybrid.
        stable = [x for x in releases if valid(x, True) and not x["prerelease"]]
        if stable:
            release = max(stable, key=lambda x: x.get("published_at") or "")
            reason = "newest stable Hybrid"
        else:
            matches = [x for x in releases if x.get("tag_name") == approved]
            if len(matches) != 1 or not valid(matches[0], True):
                raise ValueError("No approved Hybrid Builder: refusing silent Full Source fallback")
            release = matches[0]
            reason = "pinned CI-tested Hybrid preview"
        hybrid = True

    return {
        "tag": release["tag_name"],
        "hybrid": hybrid,
        "prerelease": release["prerelease"],
        "reason": reason,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--releases", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--requested-tag", default="")
    args = parser.parse_args()
    result = choose(
        json.loads(args.releases.read_text()),
        json.loads(args.policy.read_text()),
        args.requested_tag,
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"Arthur Builder resolution: {exc}", file=sys.stderr)
        sys.exit(2)
