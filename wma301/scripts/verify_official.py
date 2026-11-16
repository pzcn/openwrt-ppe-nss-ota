#!/usr/bin/env python3
"""Offline verification for official-ImageBuilder sysupgrade-only output.

Do not pretend that ImageBuilder built a recovery/initramfs FIT. The existing
full-source scripts/verify.py remains the authority for its two FIT outputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from verify import verify_one
from official_builder import read_packages
from wma301_ota import BOARD, LAYOUT, PROFILE, REPO, SHA256
from aurora import THEME_METADATA, VERSION

NAME_RE = re.compile(r".*tplink_wma301-v2-squashfs-sysupgrade\.itb$")


def verify_fast(images: Path, output: Path, provenance: Path, local_sha: str,
                packages_file: Path | None = None,
                aurora_overlay: Path | None = None,
                ota_stamp: Path | None = None) -> dict:
    candidates = sorted(p for p in images.iterdir()
                        if p.is_file() and NAME_RE.fullmatch(p.name))
    if len(candidates) != 1:
        raise ValueError(f"expected exactly one WMA301 sysupgrade FIT, found {len(candidates)}")
    source = json.loads(provenance.read_text())
    if source.get("target") != "mediatek/filogic":
        raise ValueError("wrong official ImageBuilder target")
    if source.get("source") != "ImmortalWrt master SNAPSHOT (official binaries)":
        raise ValueError("wrong ImmortalWrt upstream channel")
    if not re.fullmatch(r"[0-9a-f]{40}", local_sha):
        raise ValueError("invalid local commit")
    if aurora_overlay is not None:
        # Fail rather than claiming theme support when the overlay is incomplete.
        for rel in (
            "www/luci-static/aurora/main.css",
            "www/luci-static/aurora/login.css",
            "www/luci-static/resources/menu-aurora.js",
            "usr/share/ucode/luci/template/themes/aurora/header.ut",
            "usr/share/ucode/luci/template/themes/aurora/sysauth.ut",
            "usr/share/licenses/luci-theme-aurora/LICENSE",
            "etc/uci-defaults/95-luci-preferences",
        ):
            if not (aurora_overlay / rel).is_file():
                raise ValueError(f"missing bundled Aurora asset: {rel}")
        theme_template = (aurora_overlay /
                          "usr/share/ucode/luci/template/themes/aurora/header.ut").read_text()
        if f'data-asset-version="{VERSION}"' not in theme_template:
            raise ValueError("Aurora template was not version-stamped")
    report = verify_one(candidates[0], persistent=True)
    output.mkdir(parents=True, exist_ok=True)
    target = output / candidates[0].name
    target.write_bytes(candidates[0].read_bytes())
    manifest = {
        "build": "official-imagebuilder-fast",
        "device": "tplink,wma301-v2",
        "recovery": "NOT_BUILT_USE_FULL_SOURCE_WORKFLOW",
        "hardware_validation": "NOT_TESTED",
        "builder": source,
        "local_sha": local_sha,
        "requested_packages": read_packages(packages_file) if packages_file else [],
        "output": report,
    }
    if aurora_overlay is not None:
        manifest["bundled_theme"] = THEME_METADATA
    if ota_stamp is not None:
        # Parse data-only shell assignments. Never execute a downloaded stamp.
        values = {}
        for line in ota_stamp.read_text().splitlines():
            if not line.startswith("OTA_"):
                continue
            key, sep, value = line.partition("=")
            if not sep or not re.fullmatch(r"[a-zA-Z0-9,._/-]+", value):
                raise ValueError("unsafe OTA identity assignment")
            if key in values:
                raise ValueError("duplicate OTA identity field")
            values[key] = value
        if (values.get("OTA_SCHEMA") != "2" or
            values.get("OTA_REPOSITORY") != REPO or
            values.get("OTA_BOARD") != BOARD or
            values.get("OTA_PROFILE") != PROFILE or
            values.get("OTA_LAYOUT") != LAYOUT or
            values.get("OTA_SOURCE_SHA") != local_sha or
            values.get("OTA_BUILDER_SHA256") != source.get("imagebuilder_sha256") or
            SHA256.fullmatch(values.get("OTA_BUILDER_SHA256", "")) is None or
            not values.get("OTA_BUILD", "").isdigit() or
            int(values["OTA_BUILD"]) < 1):
            raise ValueError("WMA301 OTA stamp mismatches source/Builder/device")
        manifest["ota"] = {
            "schema": 2, "repository": REPO, "board": BOARD,
            "profile": PROFILE, "layout": LAYOUT,
            "source_sha": local_sha,
            "builder_sha256": values["OTA_BUILDER_SHA256"],
            "build": int(values["OTA_BUILD"]),
        }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (output / "SHA256SUMS").write_text(
        f"{hashlib.sha256(target.read_bytes()).hexdigest()}  {target.name}\n"
    )
    return manifest


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--images", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--provenance", type=Path, required=True)
    p.add_argument("--local-sha", required=True)
    p.add_argument("--packages-file", type=Path)
    p.add_argument("--aurora-overlay", type=Path)
    p.add_argument("--ota-stamp", type=Path)
    args = p.parse_args()
    print(json.dumps(verify_fast(args.images, args.output, args.provenance,
                                args.local_sha, args.packages_file,
                                args.aurora_overlay, args.ota_stamp), indent=2))
