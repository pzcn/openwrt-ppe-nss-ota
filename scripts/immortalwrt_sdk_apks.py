#!/usr/bin/env python3
"""Plan, cache and install APKs rebuilt with the exact ImageBuilder SDK.

Never mix target/kernel builds: every cached APK is tied to the immutable
Builder metadata + SDK archive checksums and package selection hash.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

from immortalwrt_builder import check_metadata, sha256
from immortalwrt_sdk import verify_files

PKG = re.compile(r"^[a-z0-9][a-z0-9+._-]*$")
APK = re.compile(r"^[a-z0-9][a-z0-9+._-]*-[0-9][a-zA-Z0-9.+_~-]*\.apk$")
PACKAGE_LIMIT = 256
CACHE_SCHEMA = 1
PROTECTED = frozenset(("kernel", "base-files", "libc", "libgcc", "libstdcpp"))


def apk_package_name(filename: str) -> str:
    """Extract the package name from OpenWrt APK: name-version[-rN].apk."""
    if not APK.fullmatch(filename):
        raise ValueError(f"Unexpected APK filename: {filename}")
    stem = filename[:-4]
    head, marker, release = stem.rpartition("-r")
    if marker and release.isdigit():
        stem = head
    name, sep, version = stem.rpartition("-")
    if not sep or not version[:1].isdigit() or not PKG.fullmatch(name):
        raise ValueError(f"Unrecognized APK package filename: {filename}")
    return name


def request_names(path: Path) -> list[str]:
    names: set[str] = set()
    for line in path.read_text().splitlines():
        clean = line.split("#", 1)[0].strip()
        for pkg in clean.split():
            if not PKG.fullmatch(pkg):
                raise ValueError(f"Invalid requested package: {pkg!r}")
            names.add(pkg)
    return sorted(names)


def package_in_directory(folder: Path, name: str) -> bool:
    return any(f.is_file() and apk_package_name(f.name) == name
               for f in folder.glob(name + "-*.apk"))


def missing_packages(imagebuilder: Path, add: Path) -> list[str]:
    repo = imagebuilder / "packages"
    if not repo.is_dir():
        raise ValueError("ImageBuilder has no local APK repository")
    return [name for name in request_names(add)
            if not package_in_directory(repo, name)]



def sdk_compile_targets(sdk: Path, packages: list[str]) -> list[str]:
    """Resolve binary APK names to individual OpenWrt source-package targets.

    OpenWrt's package/compile target builds every selected package; a reused
    SDK may select unrelated packages (including a Rust host toolchain).
    tmp/.packageinfo records the Source-Makefile for each binary package, so
    compile only the source directory needed for each missing APK.
    """
    info = sdk / "tmp/.packageinfo"
    if not info.is_file():
        raise ValueError("SDK package metadata is missing; run make defconfig first")
    source = ""
    sources: dict[str, set[str]] = {}
    for line in info.read_text().splitlines():
        if line.startswith("Source-Makefile: "):
            source = line.partition(":")[2].strip()
        elif line.startswith("Package: "):
            name = line.partition(":")[2].strip()
            if source and PKG.fullmatch(name):
                sources.setdefault(name, set()).add(source)

    targets: set[str] = set()
    for name in packages:
        if not PKG.fullmatch(name):
            raise ValueError(f"Invalid missing package: {name!r}")
        candidates: set[str] = set()
        for makefile in sources.get(name, ()):
            parts = makefile.split("/")
            # Reject malformed metadata, including paths escaping the SDK.
            if (not parts or parts[-1] != "Makefile" or
                    any(not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._+-]*", p)
                        or p in (".", "..") for p in parts)):
                continue
            if parts[0] == "feeds" and len(parts) >= 4:
                # feeds/<feed>/<category>/.../<source>/Makefile gets linked
                # into package/feeds/<feed>/<source>/Makefile by feeds install.
                directory = Path("package/feeds") / parts[1] / parts[-2]
            elif parts[0] == "package" and len(parts) >= 3:
                directory = Path(*parts[:-1])
            else:
                continue
            if (sdk / directory / "Makefile").is_file():
                candidates.add(directory.as_posix() + "/compile")
        if len(candidates) != 1:
            raise ValueError(
                f"Cannot uniquely map SDK package {name} to an installed "
                f"source: {sorted(candidates)} (metadata: {sorted(sources.get(name, ()))})")
        targets.update(candidates)
    if not targets:
        raise ValueError("No SDK package build targets were resolved")
    return sorted(targets)

def selection_sha(add: Path, remove: Path) -> str:
    digest = hashlib.sha256()
    for path in (add, remove):
        digest.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def trusted_context(builder_metadata: Path, sdk_metadata: Path,
                    sdk_archive: Path, feed_lock: Path,
                    add: Path, remove: Path) -> dict:
    builder, legacy = check_metadata(builder_metadata)
    if legacy:
        raise ValueError("Older Builder does not contain a matching SDK")
    sdk = verify_files(sdk_metadata, builder_metadata, sdk_archive, feed_lock)
    return {
        "schema": CACHE_SCHEMA,
        "builder_tag": builder["tag"],
        "builder_metadata_sha256": sha256(builder_metadata),
        "sdk_archive_sha256": sdk["archive_sha256"],
        "sdk_metadata_sha256": sha256(sdk_metadata),
        "feeds_fingerprint": sdk["feeds_fingerprint"],
        "package_selection_sha256": selection_sha(add, remove),
    }


def cache_manifest(cache: Path) -> Path:
    return cache / "apks-manifest.json"


def safe_apk_files(cache: Path, identity: dict, expected: list[str]) -> list[Path]:
    record = json.loads(cache_manifest(cache).read_text())
    if any(record.get(key) != value for key, value in identity.items()):
        raise ValueError("SDK compiled package cache belongs to a different Builder")
    available = record.get("files")
    if not isinstance(available, list) or not 0 < len(available) <= PACKAGE_LIMIT:
        raise ValueError("Invalid SDK package cache manifest")
    files = []
    names = set()
    for item in available:
        if not isinstance(item, dict):
            raise ValueError("Invalid APK manifest entry")
        name = item.get("name")
        checksum = item.get("sha256")
        if not isinstance(name, str) or not APK.fullmatch(name) or name in names:
            raise ValueError("Invalid, duplicate or unsafe APK filename")
        if not isinstance(checksum, str) or not re.fullmatch(r"[a-f0-9]{64}", checksum):
            raise ValueError("Invalid APK checksum")
        candidate = cache / name
        if not candidate.is_file() or candidate.is_symlink() or sha256(candidate) != checksum:
            raise ValueError("SDK-built APK has been altered")
        names.add(name)
        files.append(candidate)
    for pkg in expected:
        if not any(apk_package_name(f.name) == pkg for f in files):
            raise ValueError(f"SDK APK bundle is missing requested package {pkg}")
    return files


def collect(sdk_bin: Path, imagebuilder: Path, cache: Path,
            identity: dict, expected: list[str]) -> None:
    if not expected:
        raise ValueError("Cannot collect without missing packages")
    existing = imagebuilder / "packages"
    discovered = list(sdk_bin.rglob("*.apk"))
    if not discovered:
        raise ValueError("SDK did not compile any APKs")
    outputs: list[Path] = []
    filenames = set()
    existing_names = {apk_package_name(f.name)
                      for f in existing.glob("*.apk") if f.is_file()}
    for path in discovered:
        if not path.is_file() or not APK.fullmatch(path.name):
            raise ValueError(f"Unexpected compiled artifact: {path}")
        name = apk_package_name(path.name)
        if path.name in filenames:
            raise ValueError(f"Duplicate SDK APK basename: {path.name}")
        filenames.add(path.name)
        # Never introduce or replace toolchain ABI packages or any package
        # already provided by the immutable standalone ImageBuilder.
        if name in PROTECTED or name in existing_names:
            continue
        outputs.append(path)
    if not outputs or len(outputs) > PACKAGE_LIMIT:
        raise ValueError("Unexpected SDK APK output count")
    cache.mkdir(parents=True, exist_ok=True)
    manifest = dict(identity)
    manifest["files"] = []
    # Cache is empty or invalid whenever the compiled Builder/package set moves.
    for old in cache.glob("*.apk"):
        old.unlink()
    for path in sorted(outputs, key=lambda p: p.name):
        dest = cache / path.name
        shutil.copy2(path, dest)
        manifest["files"].append({"name": dest.name, "sha256": sha256(dest)})
    cache_manifest(cache).write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    safe_apk_files(cache, identity, expected)


def install(cache: Path, imagebuilder: Path, identity: dict, expected: list[str]) -> int:
    files = safe_apk_files(cache, identity, expected)
    repo = imagebuilder / "packages"
    existing_names = {apk_package_name(f.name)
                      for f in repo.glob("*.apk") if f.is_file()}
    installed = 0
    for file in files:
        pkg_name = apk_package_name(file.name)
        if pkg_name in PROTECTED:
            raise ValueError(f"SDK APK cannot replace toolchain ABI package: {pkg_name}")
        if pkg_name in existing_names and not (repo / file.name).exists():
            raise ValueError(f"SDK APK version conflicts with existing Builder: {pkg_name}")
        dest = repo / file.name
        if dest.exists():
            if sha256(dest) != sha256(file):
                raise ValueError(f"SDK APK cannot replace existing Builder APK: {dest.name}")
            continue
        shutil.copy2(file, dest)
        installed += 1
    for package in expected:
        if not package_in_directory(repo, package):
            raise ValueError(f"Missing after SDK APK install: {package}")
    return installed


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="action", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--imagebuilder", type=Path, required=True)
    plan.add_argument("--add", type=Path, required=True)
    targets = commands.add_parser("targets")
    targets.add_argument("--sdk", type=Path, required=True)
    targets.add_argument("--packages", nargs="+", required=True)
    for verb in ("collect", "install", "verify-cache"):
        command = commands.add_parser(verb)
        command.add_argument("--imagebuilder", type=Path, required=True)
        command.add_argument("--add", type=Path, required=True)
        command.add_argument("--remove", type=Path, required=True)
        command.add_argument("--builder-metadata", type=Path, required=True)
        command.add_argument("--sdk-metadata", type=Path, required=True)
        command.add_argument("--sdk-archive", type=Path, required=True)
        command.add_argument("--feed-lock", type=Path, required=True)
        command.add_argument("--cache", type=Path, required=True)
        if verb == "collect":
            command.add_argument("--sdk-bin", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "plan":
        print("\n".join(missing_packages(args.imagebuilder, args.add)))
        return
    if args.action == "targets":
        print("\n".join(sdk_compile_targets(args.sdk, args.packages)))
        return
    expected = missing_packages(args.imagebuilder, args.add)
    if not expected:
        print("All requested APKs already exist in the ImageBuilder")
        return
    identity = trusted_context(
        args.builder_metadata, args.sdk_metadata, args.sdk_archive,
        args.feed_lock, args.add, args.remove)
    if args.action == "collect":
        collect(args.sdk_bin, args.imagebuilder, args.cache, identity, expected)
    elif args.action == "install":
        count = install(args.cache, args.imagebuilder, identity, expected)
        print(f"Installed {count} SDK-compiled APK(s) into matching ImageBuilder")
    else:
        safe_apk_files(args.cache, identity, expected)
        print("SDK APK cache matches requested Builder and package set")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as error:
        print(f"SDK APK workflow error: {error}", file=sys.stderr)
        sys.exit(1)
