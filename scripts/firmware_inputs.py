#!/usr/bin/env python3
"""Detect RE-SS-01 firmware inputs changed since an existing OTA release."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SHA = re.compile(r"^[0-9a-f]{40}$")
IMAGE_FILES = frozenset({
    "config/add.txt",
    "config/remove.txt",
    "scripts/repack-immortalwrt.sh",
    "scripts/rebuild-missing-apks.sh",
    "scripts/stage-firmware-overlay.sh",
    "scripts/exclude-drcom-from-firmware.sh",
    "scripts/build_luci_i18n.py",
    "scripts/immortalwrt_ota.py",
    "scripts/immortalwrt_builder.py",
    "scripts/immortalwrt_sdk.py",
    "scripts/immortalwrt_sdk_apks.py",
    "scripts/fit_configs.py",
    "scripts/prepare-sing-box-luci.sh",
})
IMAGE_PREFIXES = ("files/", "config/translations/")


def relevant(path: str) -> bool:
    return path in IMAGE_FILES or path.startswith(IMAGE_PREFIXES)


def changed_paths(base: str, head: str = "HEAD", root: Path = ROOT) -> list[str]:
    if not SHA.fullmatch(base):
        raise ValueError("Base must be a full commit SHA")
    if head != "HEAD" and not SHA.fullmatch(head):
        raise ValueError("Head must be HEAD or a full commit SHA")
    out = subprocess.run(
        ["git", "-C", str(root), "diff", "--name-only", "--no-renames",
         "-z", base, head, "--"], check=True, capture_output=True,
    ).stdout
    return sorted(p for raw in out.split(b"\0") if raw
                  if relevant(p := raw.decode("utf-8")))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args()
    try:
        paths = changed_paths(args.base, args.head)
    except (ValueError, subprocess.CalledProcessError, UnicodeDecodeError) as err:
        print(f"firmware_inputs: cannot compare commits: {err}", file=sys.stderr)
        sys.exit(2)
    print("changed=" + ("true" if paths else "false"))
    for path in paths:
        print("file=" + path)


if __name__ == "__main__":
    main()
