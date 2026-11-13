#!/usr/bin/env python3
"""Resolve a pinned official ipq60xx Snapshot. Read-only: never builds or publishes."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.request
from pathlib import Path

TARGET = "qualcommax/ipq60xx"
ARCH = "aarch64_cortex-a53"
ROOT = "https://downloads.immortalwrt.org/snapshots"
SHA = re.compile(r"[0-9a-f]{64}")
GIT_SHA = re.compile(r"[0-9a-f]{40}")
VERSION = re.compile(r"r[0-9]+-([0-9a-f]{7,40})")
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")
CHECKSUM_LINE = re.compile(r"^([0-9a-f]{64})\s+\*?(.+)$")
FEED_LINE = re.compile(r"^src-git(?:-full)?\s+([a-zA-Z0-9_-]+)\s+(https://[^\s^;]+)\^([0-9a-f]{40})$")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def fetch(url: str, *, fixture: Path | None = None) -> bytes:
    if fixture:
        # Fixture layout is deliberately separate from online URLs.
        suffix = url.removeprefix(ROOT + "/")
        path = fixture / suffix
        return path.read_bytes()
    request = urllib.request.Request(url, headers={"User-Agent": "RE-SS-01-hybrid-resolver/1"})
    with urllib.request.urlopen(request, timeout=35) as reply:
        data = reply.read(12 * 1024 * 1024 + 1)
    if len(data) > 12 * 1024 * 1024:
        raise ValueError(f"Metadata exceeds size limit: {url}")
    return data


def parse_checksums(data: bytes) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in data.decode("utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        match = CHECKSUM_LINE.fullmatch(line)
        if not match:
            raise ValueError(f"Malformed checksum line: {line[:100]}")
        sha, name = match.groups()
        # Nested package paths in the upstream sha256sums are legitimate.
        if name.startswith("/") or any(part in ("", ".", "..") for part in name.split("/")):
            raise ValueError("Unsafe checksum path")
        if any(not SAFE_NAME.fullmatch(part) for part in name.split("/")):
            raise ValueError("Unexpected filename in checksum index")
        if name in result:
            raise ValueError(f"Duplicate checksum entry: {name}")
        result[name] = sha
    if not result:
        raise ValueError("Empty sha256sums")
    return result


def parse_feeds(data: bytes) -> dict[str, dict[str, str]]:
    feeds = {}
    for raw in data.decode("utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = FEED_LINE.fullmatch(line)
        if not match:
            raise ValueError(f"Unsupported feed lock line: {line[:100]}")
        name, url, commit = match.groups()
        if name in feeds:
            raise ValueError(f"Duplicate feed: {name}")
        feeds[name] = {"url": url, "commit": commit}
    if not {"packages", "luci", "routing", "telephony"}.issubset(feeds):
        raise ValueError("Missing required upstream feeds")
    return feeds


def checked(blob: bytes, index: dict[str, str], filename: str) -> str:
    expected = index.get(filename)
    if not expected:
        raise ValueError(f"Missing checksum for {filename}")
    if digest(blob) != expected:
        raise ValueError(f"Checksum mismatch: {filename}")
    return expected


def choose_asset(checksums: dict[str, str], kind: str) -> dict[str, str]:
    names = [name for name in checksums if name.startswith("immortalwrt-" + kind + "-qualcommax-ipq60xx")
             and name.endswith(".tar.zst") and "/" not in name]
    if len(names) != 1:
        raise ValueError(f"Expected exactly one {kind} archive, got {len(names)}")
    return {"filename": names[0], "sha256": checksums[names[0]]}


def resolve(fixture: Path | None = None) -> dict:
    target_url = f"{ROOT}/targets/{TARGET}"
    arch_url = f"{ROOT}/packages/{ARCH}"
    checksums_blob = fetch(f"{target_url}/sha256sums", fixture=fixture)
    sums = parse_checksums(checksums_blob)
    source_files = {}
    blobs = {}
    for filename in ("version.buildinfo", "feeds.buildinfo", "config.buildinfo"):
        blob = fetch(f"{target_url}/{filename}", fixture=fixture)
        sha = checked(blob, sums, filename)
        source_files[filename] = {"sha256": sha}
        blobs[filename] = blob
    version = blobs["version.buildinfo"].decode().strip()
    match = VERSION.fullmatch(version)
    if not match:
        raise ValueError(f"Invalid snapshot version: {version}")
    target_feeds = parse_feeds(blobs["feeds.buildinfo"])
    arch_feeds_blob = fetch(f"{arch_url}/feeds.conf", fixture=fixture)
    arch_feeds = parse_feeds(arch_feeds_blob)
    if "base" not in arch_feeds:
        raise ValueError("Arch feeds.conf has no base commit")
    if arch_feeds["base"]["url"] != "https://github.com/immortalwrt/immortalwrt.git":
        raise ValueError("Unexpected architecture base repository")
    # Arch metadata is observed independently; never pretend it shares target ABI.
    result = {
        "schema": 1,
        "status": "resolver-only-not-build-approved",
        "target": TARGET,
        "architecture": ARCH,
        "target_url": target_url,
        "architecture_url": arch_url,
        "snapshot_version": version,
        "target_commit_prefix": match.group(1),
        "target_sources": source_files,
        "target_feeds": target_feeds,
        "arch_feeds": arch_feeds,
        "arch_feeds_sha256": digest(arch_feeds_blob),
        "target_checksums_sha256": digest(checksums_blob),
        "assets": {key: choose_asset(sums, key) for key in ("imagebuilder", "sdk", "toolchain")},
    }
    result["kernel_fingerprint"] = digest(canonical({
        "version": version, "target_feeds": target_feeds,
        "config_sha256": source_files["config.buildinfo"]["sha256"],
        "assets": result["assets"],
    }))
    result["packages_fingerprint"] = digest(canonical({
        "arch_feeds": arch_feeds, "arch_feeds_sha256": result["arch_feeds_sha256"]
    }))
    result["lock_fingerprint"] = digest(canonical(result))
    return result


def classify(old: dict | None, new: dict) -> str:
    if old is None:
        return "kernel-or-target"
    if old.get("kernel_fingerprint") != new.get("kernel_fingerprint"):
        return "kernel-or-target"
    if old.get("packages_fingerprint") != new.get("packages_fingerprint"):
        return "packages-only"
    return "unchanged"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--fixture-dir", type=Path)
    args = parser.parse_args()
    current = resolve(args.fixture_dir)
    previous = json.loads(args.previous.read_text()) if args.previous else None
    change = classify(previous, current)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
    print(f"Snapshot: {current['snapshot_version']}; change={change}; lock={current['lock_fingerprint'][:16]}")
    print("Resolver only: no compiled Builder or APK compatibility has been established.")
    if args.output.exists() and "GITHUB_OUTPUT" in __import__("os").environ:
        with open(__import__("os").environ["GITHUB_OUTPUT"], "a") as output:
            output.write(f"change={change}\n")
            output.write(f"lock_fingerprint={current['lock_fingerprint']}\n")


if __name__ == "__main__":
    main()
