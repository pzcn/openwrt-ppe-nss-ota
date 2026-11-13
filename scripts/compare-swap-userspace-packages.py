#!/usr/bin/env python3
"""Compare core official ImmortalWrt APKs with a prebuilt Julius ImageBuilder.

Only an inventory: matching package names/versions do not prove ABI. If a
version differs, apk solver and dependency metadata still need validation.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

CORE = (
    "base-files", "libc", "libgcc", "libstdcpp", "busybox", "procd", "netifd",
    "ubus", "libubox", "uci", "libuci", "apk-tools", "firewall4", "fw4",
    "nftables", "dnsmasq", "dropbear", "odhcp6c", "rpcd", "logd", "uhttpd",
)


def parse_name_version(filename: str, name: str) -> str | None:
    match = re.fullmatch(re.escape(name) + r"-([0-9][A-Za-z0-9.+~:_-]*)\.apk", filename)
    return match.group(1) if match else None


def inspect(julius_files: list[str], official_files: list[str]) -> dict:
    results = []
    for name in CORE:
        donor_versions: set[str] = set()
        official_versions: set[str] = set()
        for entry in julius_files:
            if "/packages/" not in entry:
                continue
            version = parse_name_version(entry.rsplit("/", 1)[-1], name)
            if version:
                donor_versions.add(version)
        for entry in official_files:
            version = parse_name_version(entry.rsplit("/", 1)[-1], name)
            if version:
                official_versions.add(version)
        if not donor_versions or not official_versions:
            status = "missing-one-or-both"
        elif donor_versions == official_versions and len(donor_versions) == 1:
            status = "same-filename-version"
        else:
            status = "different-or-multiple-versions"
        results.append({
            "name": name,
            "official_immortalwrt_versions": sorted(official_versions),
            "julius_openwrt_versions": sorted(donor_versions),
            "status": status,
        })
    return {
        "schema": 1,
        "status": "core-apk-comparison-only-not-build-approved",
        "packages": results,
        "matching_versions": sum(x["status"] == "same-filename-version" for x in results),
        "different_versions": sum(x["status"] == "different-or-multiple-versions" for x in results),
        "missing_or_not_embedded": sum(x["status"] == "missing-one-or-both" for x in results),
        "userland_abi_verified": False,
        "kernel_abi_verified": False,
        "publishable": False,
    }


def parse_checksums(data: str) -> list[str]:
    out: list[str] = []
    for line in data.splitlines():
        line = line.strip()
        if not line:
            continue
        match = re.fullmatch(r"([0-9a-f]{64})\s+\*?([A-Za-z0-9._+~:@%=-]+(?:/[A-Za-z0-9._+~:@%=-]+)*)", line)
        if not match:
            raise ValueError("Malformed snapshot sha256sums entry")
        out.append(match.group(2))
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--julius-imagebuilder-list", type=Path, required=True)
    p.add_argument("--official-target-sums", type=Path, required=True)
    p.add_argument("--official-arch-sums", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    official = (parse_checksums(args.official_target_sums.read_text()) +
                parse_checksums(args.official_arch_sums.read_text()))
    data = inspect(args.julius_imagebuilder_list.read_text().splitlines(), official)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print("Core userspace package versions: match =", data["matching_versions"],
          "differ =", data["different_versions"],
          "missing =", data["missing_or_not_embedded"])
    for pkg in data["packages"]:
        if pkg["status"] != "same-filename-version":
            print(pkg["name"], pkg["official_immortalwrt_versions"],
                  "Julius:", pkg["julius_openwrt_versions"])
    print("No ABI approval or firmware publication.")


if __name__ == "__main__":
    main()
