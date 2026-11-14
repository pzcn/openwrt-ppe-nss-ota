#!/usr/bin/env python3
"""Resolve a pinned official ipq60xx Snapshot. Read-only: never builds or publishes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import urllib.request
from pathlib import Path

TARGET = "qualcommax/ipq60xx"
PROFILES = {"qualcommax/ipq60xx": "jdcloud_re-ss-01",
            "qualcommax/ipq807x": "linksys_mx4200v1"}
ARCH = "aarch64_cortex-a53"
ROOT = "https://downloads.immortalwrt.org/snapshots"
GITHUB_COMMITS_API = "https://api.github.com/repos/immortalwrt/immortalwrt/commits/"
ARCH_REPOS = ("base", "packages", "luci", "routing", "telephony")
PORT_KERNEL_LINE = "6.18"
SHA = re.compile(r"[0-9a-f]{64}")
GIT_SHA = re.compile(r"[0-9a-f]{40}")
VERSION = re.compile(r"r[0-9]+-([0-9a-f]{7,40})")
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+~:@%=-]*")
CHECKSUM_LINE = re.compile(r"^([0-9a-f]{64})\s+\*?(.+)$")
FEED_LINE = re.compile(r"^src-git(?:-full)?\s+([a-zA-Z0-9_-]+)\s+(https://[^\s^;]+)\^([0-9a-f]{40})$")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def fetch(url: str, *, fixture: Path | None = None) -> bytes:
    if fixture:
        if url.startswith(ROOT + "/"):
            path = fixture / url.removeprefix(ROOT + "/")
        elif url.startswith(GITHUB_COMMITS_API):
            path = fixture / "github-commits" / (url.removeprefix(GITHUB_COMMITS_API) + ".json")
        else:
            raise ValueError(f"Unsupported fixture URL: {url}")
        return path.read_bytes()
    headers = {"User-Agent": "RE-SS-01-hybrid-resolver/2",
               "Cache-Control": "no-cache"}
    if url.startswith(GITHUB_COMMITS_API) and os.environ.get("GH_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GH_TOKEN"]
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=35) as reply:
        data = reply.read(12 * 1024 * 1024 + 1)
    if len(data) > 12 * 1024 * 1024:
        raise ValueError(f"Metadata exceeds size limit: {url}")
    return data


def resolve_commit(short: str, *, fixture: Path | None = None) -> str:
    """GitHub commit API resolves buildinfo's abbreviated commit safely."""
    if not re.fullmatch(r"[0-9a-f]{7,40}", short):
        raise ValueError("Unsafe source revision")
    payload = json.loads(fetch(GITHUB_COMMITS_API + short, fixture=fixture))
    full = payload.get("sha")
    if not isinstance(full, str) or not GIT_SHA.fullmatch(full) or not full.startswith(short):
        raise ValueError("Source commit does not match official version.buildinfo")
    return full


def pick_index(sums: dict[str, str], filename: str) -> dict[str, str]:
    if filename not in sums:
        raise ValueError(f"Missing official package index: {filename}")
    return {"filename": filename, "sha256": sums[filename]}


def selected_kmod_index(sums: dict[str, str]) -> tuple[str, dict[str, str]]:
    names = [n for n in sums if re.fullmatch(r"kmods/[^/]+/packages\.adb", n)]
    if len(names) != 1:
        raise ValueError(f"Expected one official kernel ABI directory, got {len(names)}")
    abi = names[0].split("/")[1]
    if not re.fullmatch(r"\d+\.\d+\.\d+-\d+-[a-f0-9]+", abi):
        raise ValueError(f"Unexpected official kmod ABI: {abi}")
    return abi, pick_index(sums, names[0])


def verify_index(url: str, item: dict[str, str], *, fixture: Path | None = None) -> None:
    actual = digest(fetch(url + "/" + item["filename"], fixture=fixture))
    if actual != item["sha256"]:
        raise ValueError(f"Official package index hash changed: {item['filename']}")


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


def libc_version(checksums: dict[str, str]) -> str:
    """Official libc APK version: our locally built libc must match it."""
    found = [m.group(1) for name in checksums
             if (m := re.fullmatch(r"packages/libc-([0-9][A-Za-z0-9._+~-]*)\.apk", name))]
    if len(found) != 1:
        raise ValueError(f"Expected one official libc APK, got {len(found)}")
    return found[0]


def choose_asset(checksums: dict[str, str], kind: str) -> dict[str, str]:
    names = [name for name in checksums if name.startswith("immortalwrt-" + kind + "-" + TARGET.replace("/", "-"))
             and name.endswith(".tar.zst") and "/" not in name]
    if len(names) != 1:
        raise ValueError(f"Expected exactly one {kind} archive, got {len(names)}")
    return {"filename": names[0], "sha256": checksums[names[0]]}


def resolve(fixture: Path | None = None) -> dict:
    target_url = f"{ROOT}/targets/{TARGET}"
    arch_url = f"{ROOT}/packages/{ARCH}"
    # Freeze both independently-published repositories, not just the target.
    checksums_blob = fetch(f"{target_url}/sha256sums", fixture=fixture)
    arch_checksums_blob = fetch(f"{arch_url}/sha256sums", fixture=fixture)
    sums = parse_checksums(checksums_blob)
    arch_sums = parse_checksums(arch_checksums_blob)
    source_files = {}
    blobs = {}
    for filename in ("version.buildinfo", "feeds.buildinfo", "config.buildinfo"):
        blob = fetch(f"{target_url}/{filename}", fixture=fixture)
        sha = checked(blob, sums, filename)
        source_files[filename] = {"sha256": sha}
        blobs[filename] = blob
    subtarget = TARGET.split("/")[1]
    target_flag = f"CONFIG_TARGET_qualcommax_{subtarget}=y".encode()
    device_flag = f"CONFIG_TARGET_DEVICE_qualcommax_{subtarget}_DEVICE_{PROFILES[TARGET]}=y".encode()
    if target_flag not in blobs["config.buildinfo"] or device_flag not in blobs["config.buildinfo"]:
        raise ValueError(f"Official config lacks the {PROFILES[TARGET]} target profile")
    version = blobs["version.buildinfo"].decode().strip()
    match = VERSION.fullmatch(version)
    if not match:
        raise ValueError(f"Invalid snapshot version: {version}")
    full_commit = resolve_commit(match.group(1), fixture=fixture)
    target_feeds = parse_feeds(blobs["feeds.buildinfo"])
    arch_feeds_blob = fetch(f"{arch_url}/feeds.conf", fixture=fixture)
    checked(arch_feeds_blob, arch_sums, "feeds.conf")
    arch_feeds = parse_feeds(arch_feeds_blob)
    if "base" not in arch_feeds:
        raise ValueError("Arch feeds.conf has no base commit")
    if arch_feeds["base"]["url"] != "https://github.com/immortalwrt/immortalwrt.git":
        raise ValueError("Unexpected architecture base repository")

    # Snapshot APK indexes are binary (apk-tools v3), not plaintext Packages.
    # Pin and verify the exact official binary indexes before compiling anything.
    target_index = pick_index(sums, "packages/packages.adb")
    abi, kmod_index = selected_kmod_index(sums)
    arch_indexes = {
        feed: pick_index(arch_sums, f"{feed}/packages.adb")
        for feed in ARCH_REPOS
    }
    for item in (target_index, kmod_index):
        verify_index(target_url, item, fixture=fixture)
    for item in arch_indexes.values():
        verify_index(arch_url, item, fixture=fixture)

    kernel_line = ".".join(abi.split("-")[0].split(".")[:2])
    port_eligible = kernel_line == PORT_KERNEL_LINE
    result = {
        "schema": 2,
        "status": "resolver-only-not-build-approved",
        "target": TARGET,
        "architecture": ARCH,
        "target_url": target_url,
        "architecture_url": arch_url,
        "snapshot_version": version,
        "target_commit_prefix": match.group(1),
        "target_commit": full_commit,
        "target_sources": source_files,
        "target_feeds": target_feeds,
        "arch_feeds": arch_feeds,
        "arch_feeds_sha256": digest(arch_feeds_blob),
        "target_checksums_sha256": digest(checksums_blob),
        "arch_checksums_sha256": digest(arch_checksums_blob),
        "assets": {key: choose_asset(sums, key) for key in ("imagebuilder", "sdk", "toolchain")},
        "package_indexes": {
            "target": target_index,
            "kmods_read_only": kmod_index,
            "architecture": arch_indexes,
        },
        "package_counts": {
            "target_apks": sum(n.startswith("packages/") and n.endswith(".apk") for n in sums),
            "arch_apks": sum(n.endswith(".apk") for n in arch_sums),
        },
        "official_kernel_abi": abi,
        "libc_version": libc_version(sums),
        "compatibility": {
            "official_kernel_line": kernel_line,
            "port_requires_kernel_line": PORT_KERNEL_LINE,
            "ppe_port_kernel_line_matches": port_eligible,
            "arch_package_abi_verified": False,
            "checksum_signature_verified": False,
        },
    }
    # The builder can only reuse its kernel when target config, toolchain,
    # kernel ABI and target source+feed commits are all unchanged.
    result["kernel_fingerprint"] = digest(canonical({
        "source_commit": full_commit, "target_feeds": target_feeds,
        "config_sha256": source_files["config.buildinfo"]["sha256"],
        "toolchain": result["assets"]["toolchain"],
        "official_kernel_abi": abi,
    }))
    # Include content, not just the feed source revision, so that rebuilds
    # of arch APKs with identical feeds still register packages-only.
    result["packages_fingerprint"] = digest(canonical({
        "arch_checksums_sha256": result["arch_checksums_sha256"],
        "arch_feeds_sha256": result["arch_feeds_sha256"],
        "target_packages_index": target_index,
    }))
    result["lock_fingerprint"] = digest(canonical(result))

    # Catch a mirror rotating either repository while its indexes were read.
    if (fetch(f"{target_url}/sha256sums", fixture=fixture) != checksums_blob or
            fetch(f"{arch_url}/sha256sums", fixture=fixture) != arch_checksums_blob):
        raise ValueError("Official Snapshot changed during resolution; retry later")
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
    parser.add_argument("--target", choices=tuple(PROFILES), default="qualcommax/ipq60xx")
    args = parser.parse_args()
    global TARGET
    TARGET = args.target
    current = resolve(args.fixture_dir)
    previous = json.loads(args.previous.read_text()) if args.previous else None
    change = classify(previous, current)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
    print(f"Snapshot: {current['snapshot_version']}; change={change}; lock={current['lock_fingerprint'][:16]}")
    print("Kernel ABI: " + current["official_kernel_abi"] +
          "; PPE 6.18 port compatible: " +
          str(current["compatibility"]["ppe_port_kernel_line_matches"]))
    print("Resolver only: no compiled Builder or APK compatibility has been established.")
    if args.output.exists() and "GITHUB_OUTPUT" in __import__("os").environ:
        with open(__import__("os").environ["GITHUB_OUTPUT"], "a") as output:
            output.write(f"change={change}\n")
            output.write(f"lock_fingerprint={current['lock_fingerprint']}\n")


if __name__ == "__main__":
    main()
