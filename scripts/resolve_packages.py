#!/usr/bin/env python3
"""Reconstruct exactly the upstream firmware package set, with requested changes.

Only user-space additions use official @snapshot feeds. Kernel modules must
come from the upstream ImageBuilder's matching prebuilt package repository.
"""
import argparse
import json
from pathlib import Path
import re
import urllib.request

VALID = re.compile(r"^[a-z0-9][a-z0-9+._-]*$")


def get_json(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def names(path):
    result = []
    for line in Path(path).read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        for name in line.split():
            if not VALID.fullmatch(name):
                raise SystemExit(f"Invalid package name: {name!r}")
            if name not in result:
                result.append(name)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--group", default="ipq60xx-512m")
    parser.add_argument("--profile", default="jdcloud_re-ss-01")
    parser.add_argument("--site", default="https://ppenss.github.io")
    parser.add_argument("--add-file", default="config/add.txt")
    parser.add_argument("--remove-file", default="config/remove.txt")
    args = parser.parse_args()

    site = args.site.rstrip("/")
    boards = get_json(f"{site}/{args.tag}/boards.json")
    board = next((b for b in boards if b.get("group") == args.group
                  and b.get("profile") == args.profile), None)
    if board is None or not board.get("packages"):
        raise SystemExit("No upstream board/package manifest found for selected profile")

    profile_doc = get_json(f"{site}/{args.tag}/{args.group}/profiles.json")
    profile = profile_doc["profiles"][args.profile]
    defaults = profile_doc["default_packages"] + profile.get("device_packages", [])

    add = names(args.add_file)
    remove = names(args.remove_file)
    if set(add) & set(remove):
        raise SystemExit("Package cannot be both added and removed")

    upstream = [p for p in board["packages"] if p not in ("kernel", "libc")]
    base = [p for p in upstream if p not in remove]
    dropped = [f"-{p}" for p in defaults
               if not p.startswith("-") and p not in upstream and p not in remove]

    new = []
    for p in add:
        if p in base:
            continue
        # Never source external kernel modules from generic OpenWrt snapshot feeds.
        new.append(p if p.startswith("kmod-") else f"{p}@snapshot")

    # Aurora is the only externally pinned local APK.
    all_packages = base + new + ["luci-theme-aurora"]
    all_packages += [f"-{p}" for p in remove] + dropped
    print(" ".join(dict.fromkeys(all_packages)))


if __name__ == "__main__":
    main()
