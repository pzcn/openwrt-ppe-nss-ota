#!/usr/bin/env python3
"""Keep WMA301 full-source fallback package selection in sync with ImageBuilder.

The buildroot .config is disposable. Do not mutate configs/wma301.config, the
official checkout, or unrelated CONFIG_ flags in the repository.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from official_builder import read_packages

PACKAGE_LINE = re.compile(r"^(?:CONFIG_PACKAGE_([a-zA-Z0-9+._-]+)=.*|"
                          r"# CONFIG_PACKAGE_([a-zA-Z0-9+._-]+) is not set)$")


def selections(path: Path) -> dict[str, bool]:
    choices = {}
    for name in read_packages(path):
        pkg = name.removeprefix("-")
        if pkg in choices:
            raise ValueError(f"conflicting requested package: {pkg}")
        choices[pkg] = not name.startswith("-")
    return choices


def apply(packages: Path, config: Path) -> None:
    selected = selections(packages)
    if not config.is_file():
        raise ValueError(f"missing config: {config}")
    existing = config.read_text().splitlines()
    preserved = []
    for line in existing:
        match = PACKAGE_LINE.fullmatch(line)
        if match and (match.group(1) or match.group(2)) in selected:
            continue
        preserved.append(line)
    preserved.append("")
    preserved.append("# WMA301 shared Arthur packages (generated from official-packages.txt)")
    for name, enabled in sorted(selected.items()):
        if enabled:
            preserved.append(f"CONFIG_PACKAGE_{name}=y")
        else:
            preserved.append(f"# CONFIG_PACKAGE_{name} is not set")
    config.write_text("\n".join(preserved).rstrip() + "\n")


def check(packages: Path, config: Path) -> None:
    selected = selections(packages)
    final = config.read_text().splitlines()
    enabled = {line[len("CONFIG_PACKAGE_"):-2]
               for line in final if line.startswith("CONFIG_PACKAGE_") and line.endswith("=y")}
    missing = sorted(name for name, value in selected.items() if value and name not in enabled)
    accidentally_enabled = sorted(name for name, value in selected.items()
                                  if not value and name in enabled)
    if missing or accidentally_enabled:
        raise ValueError(f"feed or Kconfig mismatch; missing={missing}, unwanted={accidentally_enabled}")
    print(f"Full source package selection verified: {sum(selected.values())} selected")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["apply", "check"])
    p.add_argument("--packages", type=Path, required=True)
    p.add_argument("--config", type=Path, required=True)
    args = p.parse_args()
    if args.action == "apply":
        apply(args.packages, args.config)
    else:
        check(args.packages, args.config)


if __name__ == "__main__":
    main()
