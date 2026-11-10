#!/usr/bin/env python3
"""Derive an ABI-identical package-only Builder/SDK from a verified release.

Only APK selections, package sources and generated indexes are changed.
Kernel, DTB, NSS and compiler artifacts remain byte-for-byte in their trees.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil

from immortalwrt_builder import (
    check_metadata, metadata as create_builder_metadata, sha256,
    verify as verify_builder,
)
from immortalwrt_sdk import verify_files as verify_sdk, write_json
from immortalwrt_sdk_apks import request_names, package_in_directory

REMOVED = frozenset(("luci-app-homeproxy", "luci-i18n-homeproxy-zh-cn"))
PKG_NAME = re.compile(r"^[a-z0-9][a-z0-9+._-]*$")


def forbidden_file(path: Path) -> bool:
    name = path.name
    return name in REMOVED or any(
        name.startswith(pkg + "-") and name.endswith((".apk", ".ipk"))
        for pkg in REMOVED
    )


def prune_package_tree(root: Path, *, sdk: bool) -> list[str]:
    if not root.is_dir():
        raise ValueError(f"Missing extracted package tree: {root}")
    removed = []
    paths = sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True)
    for p in paths:
        if not forbidden_file(p):
            continue
        if p.is_symlink() or p.is_file():
            p.unlink()
        elif p.is_dir():
            shutil.rmtree(p)
        else:
            continue
        removed.append(str(p.relative_to(root)))

    # The earlier full Builder could have HomeProxy=y in its .config.
    cfg = root / ".config"
    if cfg.is_file():
        rewritten = []
        for line in cfg.read_text().splitlines(keepends=True):
            for pkg in REMOVED:
                if line.startswith(f"CONFIG_PACKAGE_{pkg}="):
                    line = f"# CONFIG_PACKAGE_{pkg} is not set\n"
                    break
            rewritten.append(line)
        cfg.write_text("".join(rewritten))

    if sdk:
        # Generated metadata can reference the old HomeProxy source even after
        # it is deleted. Recreate these files when locked feeds are installed.
        generated = ("feeds/luci.index", "tmp/.packageinfo",
                     "tmp/.config-package.in", "tmp/.packageauxvars",
                     "tmp/.packagedeps")
    else:
        # ImageBuilder regenerates repository index from the remaining APKs.
        generated = ("packages/packages.adb", "packages/Packages",
                     "packages/Packages.gz", "packages/Packages.sig")
    for name in generated:
        p = root / name
        if p.is_file() or p.is_symlink():
            p.unlink()

    if any(forbidden_file(p) for p in root.rglob("*")):
        raise ValueError("HomeProxy survived package-tree pruning")
    return removed


def sanitize(args: argparse.Namespace) -> None:
    ib, sdk = args.imagebuilder, args.sdk
    if not (ib / "Makefile").is_file() or not (sdk / "Makefile").is_file():
        raise ValueError("Input is not an extracted ImageBuilder and SDK")
    removed_ib = prune_package_tree(ib, sdk=False)
    removed_sdk = prune_package_tree(sdk, sdk=True)
    names = {s.strip() for s in args.parent_packages.read_text().splitlines()
             if s.strip()}
    if any(not PKG_NAME.fullmatch(n) for n in names):
        raise ValueError("Invalid parent package manifest")
    names.difference_update(REMOVED)
    requested = request_names(args.add)
    names.update(requested)
    if any(pkg in REMOVED for pkg in requested):
        raise ValueError("Cannot request HomeProxy in derived Builder")
    for pkg in requested:
        if not package_in_directory(ib / "packages", pkg):
            raise ValueError(f"Missing APK for requested package: {pkg}")
    for pkg in REMOVED:
        if package_in_directory(ib / "packages", pkg):
            raise ValueError(f"HomeProxy still present: {pkg}")
    args.output_packages.write_text("\n".join(sorted(names)) + "\n")
    print(f"Pruned HomeProxy: {len(removed_ib)} ImageBuilder paths; "
          f"{len(removed_sdk)} SDK paths; {len(names)} selected packages")


def derive_metadata(args: argparse.Namespace) -> None:
    verify_builder(argparse.Namespace(
        metadata=args.parent_builder_metadata,
        archive=args.parent_builder_archive,
        overlay=args.overlay,
        packages=args.parent_packages,
    ))
    parent, legacy = check_metadata(args.parent_builder_metadata)
    if legacy:
        raise ValueError("Package-only derivation requires modern Builder and SDK")
    original_sdk = verify_sdk(
        args.parent_sdk_metadata, args.parent_builder_metadata,
        args.parent_sdk_archive, args.parent_feed_lock
    )
    create_builder_metadata(argparse.Namespace(
        immortal=parent["immortalwrt_commit"],
        ppe=parent["ppe_nss_commit"],
        base=parent["base_overlay_commit"],
        feeds=parent["feeds_fingerprint"],
        archive=args.archive, overlay=args.overlay,
        packages=args.packages, output=args.builder_metadata,
    ))
    new, legacy = check_metadata(args.builder_metadata)
    if legacy or new["tag"] == parent["tag"]:
        raise ValueError("Derived Builder tag must be new and immutable")
    new["derived_from_builder"] = parent["tag"]
    new["derivation"] = "package-only-no-kernel-rebuild"
    write_json(args.builder_metadata, new)
    verify_builder(argparse.Namespace(
        metadata=args.builder_metadata,
        archive=args.archive, overlay=args.overlay, packages=args.packages,
    ))
    locked = json.loads(args.parent_feed_lock.read_text())
    locked["builder_tag"] = new["tag"]
    write_json(args.feed_lock, locked)
    sdk = dict(original_sdk)
    sdk.update(
        builder_tag=new["tag"],
        builder_metadata_sha256=sha256(args.builder_metadata),
        archive=args.sdk_archive.name,
        archive_sha256=sha256(args.sdk_archive),
        feed_lock=args.feed_lock.name,
        feed_lock_sha256=sha256(args.feed_lock),
        derived_from_builder=parent["tag"],
        derivation="package-only-no-kernel-rebuild",
    )
    write_json(args.sdk_metadata, sdk)
    verify_sdk(args.sdk_metadata, args.builder_metadata,
               args.sdk_archive, args.feed_lock)
    print(new["tag"])


def main() -> None:
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="action", required=True)
    s = subs.add_parser("sanitize")
    for flag in ("imagebuilder", "sdk", "parent-packages", "add", "output-packages"):
        s.add_argument("--" + flag, type=Path, required=True)
    m = subs.add_parser("metadata")
    for flag in ("parent-builder-metadata", "parent-builder-archive",
                 "parent-sdk-metadata", "parent-sdk-archive", "parent-feed-lock",
                 "archive", "sdk-archive", "overlay", "parent-packages", "packages",
                 "builder-metadata", "sdk-metadata", "feed-lock"):
        m.add_argument("--" + flag, type=Path, required=True)
    args = parser.parse_args()
    if args.action == "sanitize":
        sanitize(args)
    else:
        derive_metadata(args)


if __name__ == "__main__":
    main()
