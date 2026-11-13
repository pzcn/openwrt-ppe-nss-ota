#!/usr/bin/env python3
"""Plan and checksum-verify reusable official APKs for the Hybrid Builder.

P3 discovery stage, not a package solver. The resulting plan never approves
kernel modules, locally patched packages, or a firmware for publication.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "snapshot_resolver", ROOT / "scripts/resolve-immortalwrt-snapshot.py")
snapshot = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(snapshot)

# These binary packages are built from local patched sources, not the official
# repository. The SDK/Builder pipeline must later add their signed APKs.
LOCAL_PACKAGES = frozenset((
    "qca-ppe-qos", "ppe-help", "sqm-scripts", "luci-app-qca-ppe-qos",
    "luci-theme-aurora", "luci-app-sing-box",
))
PROTECTED = frozenset((
    "kernel", "libc", "libgcc", "libstdcpp", "base-files",
))
PKG = re.compile(r"^[a-z0-9][a-z0-9+._-]*$")
APK = re.compile(r"^([A-Za-z0-9][A-Za-z0-9+._-]*)-([0-9][A-Za-z0-9._+~:-]*)\.apk$")
ALLOWED_ARCH_FEEDS = frozenset(snapshot.ARCH_REPOS)


def parse_names(text: str) -> list[str]:
    output: set[str] = set()
    for raw in text.splitlines():
        line = raw.split("#", 1)[0]
        for item in line.split():
            if not PKG.fullmatch(item):
                raise ValueError(f"Invalid package in selection: {item}")
            output.add(item)
    return sorted(output)


def package_name(filename: str) -> str:
    match = APK.fullmatch(filename)
    if not match:
        raise ValueError(f"Malformed official APK filename: {filename}")
    return match.group(1)


def entries(sums: dict[str, str], where: str) -> dict[str, list[dict]]:
    output: dict[str, list[dict]] = {}
    for rel, sha in sums.items():
        if not rel.endswith(".apk"):
            continue
        parts = rel.split("/")
        if where == "target":
            if len(parts) != 2 or parts[0] != "packages":
                # Never bring the official target kmods into the hybrid build.
                continue
        else:
            if len(parts) != 2 or parts[0] not in ALLOWED_ARCH_FEEDS:
                continue
        name = package_name(parts[1])
        output.setdefault(name, []).append({
            "source": where,
            "feed": parts[0],
            "path": rel,
            "filename": parts[1],
            "sha256": sha,
        })
    return output


def is_kernel_owned(name: str) -> bool:
    return name == "kernel" or name.startswith("kmod-")


def plan(lock: dict, target_sums: dict[str, str], arch_sums: dict[str, str],
         requested: list[str], excluded: list[str]) -> dict:
    if lock.get("schema") != 2 or lock.get("target") != snapshot.TARGET \
            or lock.get("architecture") != snapshot.ARCH:
        raise ValueError("Wrong Snapshot lock")
    selected = set(requested) - set(excluded)
    both = entries(target_sums, "target")
    for key, values in entries(arch_sums, "arch").items():
        both.setdefault(key, []).extend(values)
    rows: list[dict] = []
    for name in sorted(selected):
        if not PKG.fullmatch(name):
            raise ValueError(f"Invalid package name: {name}")
        if is_kernel_owned(name):
            rows.append({"name": name, "status": "local-kernel", "reason": "new-kernel-abi"})
        elif name in LOCAL_PACKAGES:
            rows.append({"name": name, "status": "local-custom", "reason": "local-source-patch"})
        elif name in PROTECTED:
            rows.append({"name": name, "status": "abi-review", "reason": "base-abi-package"})
        else:
            options = both.get(name, [])
            if not options:
                rows.append({"name": name, "status": "missing", "reason": "not-in-official-index"})
            elif len(options) > 1:
                rows.append({"name": name, "status": "ambiguous", "candidates": options})
            else:
                item = options[0]
                rows.append({
                    "name": name, "status": "official-candidate",
                    **item,
                    "url": (lock["target_url"] if item["source"] == "target"
                            else lock["architecture_url"]) + "/" + item["path"],
                })
    result = {
        "schema": 1,
        "status": "P3-inventory-only-not-build-approved",
        "snapshot_lock_fingerprint": lock["lock_fingerprint"],
        "kernel_fingerprint": lock["kernel_fingerprint"],
        "packages_fingerprint": lock["packages_fingerprint"],
        "target": snapshot.TARGET,
        "architecture": snapshot.ARCH,
        "dependency_closure_verified": False,
        "apk_signatures_verified": False,
        "kernel_modules_official_reuse_permitted": False,
        "requested": sorted(selected),
        "packages": rows,
    }
    result["inventory_fingerprint"] = snapshot.digest(snapshot.canonical(result))
    return result


def verified_indexes(lock: dict, *, fixture: Path | None = None
                     ) -> tuple[dict[str, str], dict[str, str]]:
    if lock.get("schema") != 2:
        raise ValueError("Expected snapshot schema 2")
    blob_a = snapshot.fetch(lock["target_url"] + "/sha256sums", fixture=fixture)
    blob_b = snapshot.fetch(lock["architecture_url"] + "/sha256sums", fixture=fixture)
    if snapshot.digest(blob_a) != lock["target_checksums_sha256"]:
        raise ValueError("Target Snapshot changed since resolver locked it")
    if snapshot.digest(blob_b) != lock["arch_checksums_sha256"]:
        raise ValueError("Architecture Snapshot changed since resolver locked it")
    return snapshot.parse_checksums(blob_a), snapshot.parse_checksums(blob_b)


def copy_verified_package(entry: dict, dest: Path, *,
                          fixture: Path | None = None) -> dict:
    if entry.get("status") != "official-candidate":
        raise ValueError("Refusing to download an unapproved official candidate")
    if is_kernel_owned(entry["name"]) or entry["name"] in PROTECTED:
        raise ValueError("Official kernel/base ABI import is forbidden")
    rel = entry["path"]
    source = entry["source"]
    expected_url = (snapshot.ROOT + "/targets/" + snapshot.TARGET + "/" + rel
                    if source == "target"
                    else snapshot.ROOT + "/packages/" + snapshot.ARCH + "/" + rel)
    if entry.get("url") != expected_url:
        raise ValueError("Expected official target/arch download URL")
    if not re.fullmatch(r"[0-9a-f]{64}", entry.get("sha256", "")):
        raise ValueError("Invalid pinned checksum")
    if not rel.endswith("/" + entry["filename"]):
        raise ValueError("Package name and checksum-relative path differ")
    if not APK.fullmatch(entry["filename"]):
        raise ValueError("Unsafe package filename")
    directory = dest / source / entry["feed"]
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / entry["filename"]
    part = directory / (entry["filename"] + ".part")
    try:
        if fixture:
            data = snapshot.fetch(expected_url, fixture=fixture)
            part.write_bytes(data)
        else:
            request = urllib.request.Request(expected_url, headers={
                "User-Agent": "RE-SS-01-hybrid-apk-mirror/1"
            })
            with urllib.request.urlopen(request, timeout=90) as response, part.open("wb") as output:
                total = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > 128 * 1024 * 1024:
                        raise ValueError("Official APK exceeded download size limit")
                    output.write(chunk)
        with part.open("rb") as downloaded:
            actual = hashlib.file_digest(downloaded, "sha256").hexdigest()
        if actual != entry["sha256"]:
            raise ValueError("Downloaded APK does not match pinned official sha256sums")
        part.replace(final)
    finally:
        part.unlink(missing_ok=True)
    return {
        "name": entry["name"], "filename": final.name,
        "source": source, "feed": entry["feed"],
        "sha256": entry["sha256"],
        "relative_path": str(final.relative_to(dest)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--add", type=Path, default=ROOT / "config/add.txt")
    parser.add_argument("--remove", type=Path, default=ROOT / "config/remove.txt")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--download", nargs="*", default=[])
    parser.add_argument("--download-dir", type=Path)
    parser.add_argument("--fixture-dir", type=Path)
    args = parser.parse_args()
    lock = json.loads(args.lock.read_text())
    target_sums, arch_sums = verified_indexes(lock, fixture=args.fixture_dir)
    selected = parse_names(args.add.read_text())
    excluded = parse_names(args.remove.read_text())
    inventory = plan(lock, target_sums, arch_sums, selected, excluded)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(inventory, sort_keys=True, indent=2) + "\n")
    status_counts = {name: sum(r["status"] == name for r in inventory["packages"])
                     for name in ("official-candidate", "local-custom", "local-kernel",
                                  "abi-review", "missing", "ambiguous")}
    print("Hybrid requested-package coverage: " + json.dumps(status_counts, sort_keys=True))
    # No implicit download-all. The operator explicitly picks which confirmed
    # userland candidates to test, and every APK is content-pinned.
    if args.download:
        if args.download_dir is None:
            raise ValueError("--download-dir is required when --download is used")
        available = {r["name"]: r for r in inventory["packages"]}
        verified = []
        for name in args.download:
            if name not in available:
                raise ValueError(f"Package not in requested selection: {name}")
            verified.append(copy_verified_package(
                available[name], args.download_dir, fixture=args.fixture_dir))
        (args.output.parent / "downloaded-official-apks.json").write_text(
            json.dumps({"schema": 1, "files": verified,
                        "dependency_closure_verified": False}, indent=2) + "\n")
        print(f"Downloaded {len(verified)} checksum-verified userland APKs")
    if any(r["status"] in {"ambiguous", "missing"} for r in inventory["packages"]):
        print("Notice: some requested packages need selection resolution or local compilation.")
    print("This inventory is NOT a dependency closure, not a kernel module feed, and NOT a deployable Builder.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError) as exc:
        print(f"Hybrid official APK inventory error: {exc}", file=sys.stderr)
        sys.exit(1)
