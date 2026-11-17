#!/usr/bin/env python3
"""Stage source-controlled WMA301 files without bundling optional OTA by default.

The OTA source files remain in this repository. Set WMA301_ENABLE_OTA=true
in the invoking build to include the backend, LuCI view/menu/ACL and config.
"""
from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXECUTABLE_DIRS = {
    ("etc", "init.d"), ("etc", "uci-defaults"),
    ("usr", "sbin"), ("usr", "libexec"),
}


def ota_enabled() -> bool:
    return os.environ.get("WMA301_ENABLE_OTA", "false").strip().lower() == "true"


def is_ota_file(relative: Path) -> bool:
    name = relative.as_posix()
    return "wma301-ota" in name or "ppe-update-wma301-preflight" in name


def stage_files(source: Path, overlay: Path, *, include_ota: bool | None = None) -> list[str]:
    if include_ota is None:
        include_ota = ota_enabled()
    staged: list[str] = []
    for item in sorted(source.rglob("*")):
        if item.is_symlink():
            raise ValueError(f"symlink prohibited in overlay: {item}")
        if not item.is_file():
            continue
        rel = item.relative_to(source)
        if not include_ota and is_ota_file(rel):
            continue
        dest = overlay / rel
        if dest.exists():
            raise ValueError(f"custom overlay clashes with board file: {rel}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, dest)
        # Init scripts, helpers and UCI defaults must be executable in the
        # image even if the repository copy lost its mode bits.
        if rel.parts[:2] in EXECUTABLE_DIRS:
            dest.chmod(dest.stat().st_mode | 0o111)
        staged.append(rel.as_posix())
    return staged


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=ROOT / "files")
    parser.add_argument("--overlay", type=Path, required=True)
    args = parser.parse_args()
    print(f"Staged overlay files: {stage_files(args.source, args.overlay)}")
