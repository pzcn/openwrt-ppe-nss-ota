#!/usr/bin/env python3
"""Pin and bundle Aurora's *prebuilt* LuCI theme into a firmware overlay.

This is a no-SDK asset installation for the official ImageBuilder fast path.
The full-source fallback compiles the same source as a normal LuCI package.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

VERSION = "1.4.0"
TAG = f"v{VERSION}"
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
                  "fast_build_installation": "prebuilt-source-overlay-no-apk"}


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
    """Copy only the paths installed by luci.mk, never developer resources."""
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


def stage(source: Path, overlay: Path) -> dict:
    check_source(source)
    files = stage_contents(source, overlay)
    return {**THEME_METADATA, "files_staged": len(files)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["check", "stage"])
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--overlay", type=Path)
    args = parser.parse_args()
    if args.action == "check":
        check_source(args.source)
        print(json.dumps(THEME_METADATA, indent=2))
    else:
        if args.overlay is None:
            parser.error("--overlay is required for stage")
        print(json.dumps(stage(args.source, args.overlay), indent=2))


if __name__ == "__main__":
    main()
