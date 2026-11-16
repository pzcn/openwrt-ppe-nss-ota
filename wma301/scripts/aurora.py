#!/usr/bin/env python3
"""Build pinned Aurora LuCI theme as a real noarch APK with official ImageBuilder tools.

The official ImageBuilder bundles OpenWrt apk-tools mkpkg. Aurora is static
LuCI content, so this does not require SDK, compiler, or target ABI rebuild.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

VERSION = "1.4.0"
TAG = f"v{VERSION}"
PACKAGE_VERSION = f"{VERSION}-r1"
PACKAGE_NAME = "luci-theme-aurora"
COMMIT = "84c27b66952e6fc4be60128067a6b88bfd34afb5"
SOURCE = "https://github.com/eamonxg/luci-theme-aurora.git"
REQUIRED = (
    "htdocs/luci-static/aurora/main.css",
    "htdocs/luci-static/aurora/login.css",
    "htdocs/luci-static/resources/menu-aurora.js",
    "htdocs/luci-static/resources/router-aurora.js",
    "ucode/template/themes/aurora/header.ut",
    "ucode/template/themes/aurora/footer.ut",
    "ucode/template/themes/aurora/sysauth.ut",
    "LICENSE",
)
THEME_METADATA = {"name": "luci-theme-aurora", "version": VERSION,
                  "source": SOURCE, "commit": COMMIT,
                  "fast_build_installation": "imagebuilder-local-noarch-apk"}


def check_layout(source: Path) -> None:
    for rel in REQUIRED:
        obj = source / rel
        if not obj.is_file() or obj.is_symlink() or obj.stat().st_size == 0:
            raise ValueError(f"Missing, empty or unsafe Aurora source: {rel}")
    for directory in ("htdocs", "ucode"):
        for obj in (source / directory).rglob("*"):
            if obj.is_symlink():
                raise ValueError(f"Theme symlink not supported: {obj}")


def check_source(source: Path) -> None:
    check_layout(source)
    actual = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    if actual != COMMIT:
        raise ValueError(f"Aurora tag differs from pinned {TAG}: {actual} != {COMMIT}")


def substitute_version(text: str) -> str:
    """Mirror LuCI feeds/luci/luci.mk SubstituteVersion for .ut templates."""
    text = re.sub(r"\{# *([^ ]*)PKG_VERSION *#\}",
                  lambda m: m.group(1) + VERSION, text)
    text = re.sub(r'"(\{\{ *?(?:media|resource) *?\}\}[^"]*\.(?:js|css))"',
                  lambda m: '"' + m.group(1) + "?v=" + VERSION + '"', text)
    return text


def stage_contents(source: Path, overlay: Path) -> list[str]:
    """Install upstream LuCI assets into an isolated package payload root."""
    check_layout(source)
    written: list[str] = []
    for source_prefix, destination_prefix in (
        ("htdocs", "www"), ("ucode", "usr/share/ucode/luci"),
    ):
        for obj in sorted((source / source_prefix).rglob("*")):
            if not obj.is_file():
                continue
            rel = obj.relative_to(source / source_prefix)
            target = overlay / destination_prefix / rel
            if target.exists() or target.is_symlink():
                raise ValueError(f"Aurora would overwrite an existing file: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if obj.suffix == ".ut":
                target.write_text(substitute_version(obj.read_text()))
            else:
                shutil.copy2(obj, target)
            written.append(target.relative_to(overlay).as_posix())
    license_out = overlay / "usr/share/licenses/luci-theme-aurora/LICENSE"
    if license_out.exists():
        raise ValueError("Aurora license file conflicts with another asset")
    license_out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / "LICENSE", license_out)
    written.append(license_out.relative_to(overlay).as_posix())
    for required in (
        "www/luci-static/aurora/main.css",
        "www/luci-static/resources/menu-aurora.js",
        "usr/share/ucode/luci/template/themes/aurora/header.ut",
        "usr/share/ucode/luci/template/themes/aurora/sysauth.ut",
    ):
        if not (overlay / required).is_file():
            raise ValueError(f"Aurora staging missed {required}")
    return written


def build_apk(source: Path, builder: Path) -> dict:
    """Generate a native APK v3, indexed and installed by ImageBuilder.

    Crucially, Aurora files do not go into FILES= overlay: all theme assets
    must be owned by apk and appear in the installed package manifest.
    """
    check_source(source)
    apk = builder / "staging_dir/host/bin/apk"
    if not apk.is_file() or not apk.stat().st_mode & 0o111:
        raise ValueError("Official ImageBuilder has no executable host apk mkpkg")
    package_dir = builder / "packages"
    if not package_dir.is_dir():
        raise ValueError("Official ImageBuilder local packages directory missing")
    payload = builder / "build_dir/aurora-noarch-payload"
    if payload.exists():
        raise ValueError("Refusing to reuse old Aurora APK payload")
    payload.mkdir(parents=True)
    files = stage_contents(source, payload)
    if (payload / "etc/uci-defaults/30_luci-theme-aurora").exists():
        raise ValueError("Aurora upstream UCI defaults must not override user theme")
    target = package_dir / f"{PACKAGE_NAME}-{PACKAGE_VERSION}.apk"
    if target.exists():
        raise ValueError(f"Refusing to overwrite an existing APK: {target}")
    command = [
        str(apk), "mkpkg",
        "--info", f"name:{PACKAGE_NAME}",
        "--info", f"version:{PACKAGE_VERSION}",
        "--info", "arch:noarch",
        "--info", "license:Apache-2.0",
        "--info", "description:Aurora theme for the LuCI web interface",
        "--info", "origin:luci-theme-aurora",
        "--info", "url:https://github.com/eamonxg/luci-theme-aurora",
        "--info", "depends:luci-base",
        "--files", str(payload),
        "--output", str(target),
    ]
    subprocess.run(command, check=True)
    if not target.is_file() or target.stat().st_size < 1024:
        raise ValueError("Aurora APK build produced no valid archive")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    metadata = {
        **THEME_METADATA,
        "package_version": PACKAGE_VERSION,
        "architecture": "noarch",
        "filename": target.name,
        "sha256": digest,
        "files_packaged": len(files),
    }
    print(json.dumps(metadata, indent=2))
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["check", "apk"])
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--builder", type=Path)
    args = parser.parse_args()
    if args.action == "check":
        check_source(args.source)
        print(json.dumps(THEME_METADATA, indent=2))
    else:
        if args.builder is None:
            parser.error("--builder is required for APK compilation")
        build_apk(args.source, args.builder)


if __name__ == "__main__":
    main()
