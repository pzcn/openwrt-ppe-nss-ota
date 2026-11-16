#!/usr/bin/env python3
"""Build-side identity and metadata for one WMA301 OTA feed."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
from pathlib import Path

REPO = "pzcn/wma301-immortalwrt"
BOARD = "tplink,wma301-v2"
PROFILE = "tplink_wma301-v2"
LAYOUT = "oem-bl2-bl31-custom-bl33-single-ubi-v1"
IMAGE = "immortalwrt-mediatek-filogic-tplink_wma301-v2-squashfs-sysupgrade.itb"
# Official ImageBuilder prepends its snapshot version to the local FIT name.
# The published OTA asset is always renamed to IMAGE for stable device URLs.
SOURCE_IMAGE_RE = re.compile(r"immortalwrt(?:-[a-z0-9.]+)*-mediatek-filogic-"
                             r"tplink_wma301-v2-squashfs-sysupgrade\.itb\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
MAX_IMAGE = 96 * 1024 * 1024


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise ValueError(reason)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stamp(out: Path, build: int, source: str, builder: str = "") -> dict:
    require(build > 0 and build < 10**20, "invalid GitHub run ID")
    require(SHA.fullmatch(source) is not None, "invalid integration SHA")
    require(not builder or SHA256.fullmatch(builder) is not None,
            "invalid ImageBuilder hash")
    info = {"schema": 2, "repository": REPO, "board": BOARD, "profile": PROFILE,
            "layout": LAYOUT, "build": build, "source_sha": source,
            "builder_sha256": builder}
    target = out / "etc/wma301-ota-release"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "# Generated at build-time; not a sysupgrade configuration.\n" +
        "".join(f"OTA_{key.upper()}={shlex.quote(str(value))}\n"
                for key, value in info.items())
    )
    return info


def metadata(dist: Path, build: int, source: str, out: Path) -> dict:
    require(SHA.fullmatch(source) is not None, "invalid source SHA")
    require(0 < build < 10**20, "invalid source run ID")
    doc = json.loads((dist / "manifest.json").read_text())
    require(doc.get("build") == "official-imagebuilder-fast", "not an official Builder FIT")
    require(doc.get("device") == BOARD and doc.get("hardware_validation") == "NOT_TESTED",
            "unexpected board or verification status")
    require(doc.get("local_sha") == source, "artifact source commit mismatch")
    ota = doc.get("ota", {})
    require(ota.get("schema") == 2 and ota.get("build") == build and
            ota.get("repository") == REPO and ota.get("board") == BOARD and
            ota.get("layout") == LAYOUT and ota.get("source_sha") == source,
            "no matching in-image OTA identity")
    builder = doc.get("builder", {})
    require(builder.get("target") == "mediatek/filogic", "unexpected builder target")
    require(builder.get("imagebuilder_sha256") == ota.get("builder_sha256") and
            SHA256.fullmatch(ota.get("builder_sha256", "")) is not None,
            "ImageBuilder identity mismatch")
    # Do not pin the source snapshot version into the firmware filename.
    names = [p for p in dist.iterdir()
             if p.is_file() and SOURCE_IMAGE_RE.fullmatch(p.name)]
    require(len(names) == 1, "expected exactly one WMA301 sysupgrade FIT")
    image = names[0]
    require(1_000_000 < image.stat().st_size < MAX_IMAGE,
            "unexpected FIT size")
    digest = sha256(image)
    report = doc.get("output", {})
    require(report.get("file") == image.name and report.get("sha256") == digest and
            report.get("fit_hashes") == "pass" and
            report.get("mode") == "squashfs-persistent" and
            report.get("dts", {}).get("compatible") == BOARD and
            report.get("dts", {}).get("factory_info_protected") is True,
            "FIT did not pass WMA301 offline inspection")
    sums = (dist / "SHA256SUMS").read_text().splitlines()
    require(sums == [f"{digest}  {image.name}"], "SHA256SUMS mismatch")
    tag = f"wma301-ota-r{build}"
    data = {"schema": 3, "repository": REPO,
            "tag": tag, "build": build, "board": BOARD, "profile": PROFILE,
            "layout": LAYOUT, "image": IMAGE, "source_image": image.name,
            "image_sha256": digest,
            "image_size": image.stat().st_size, "source_sha": source,
            "immortalwrt_revision": builder.get("source_revision", ""),
            "builder_sha256": ota["builder_sha256"],
            "hardware_validation": "NOT_TESTED",
            "auto_upgrade": False}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return data


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="mode", required=True)
    s = sub.add_parser("stamp")
    s.add_argument("--overlay", type=Path, required=True)
    s.add_argument("--build", type=int, required=True)
    s.add_argument("--source-sha", required=True)
    s.add_argument("--builder-sha256", default="")
    m = sub.add_parser("metadata")
    m.add_argument("--dist", type=Path, required=True)
    m.add_argument("--build", type=int, required=True)
    m.add_argument("--source-sha", required=True)
    m.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.mode == "stamp":
        print(json.dumps(stamp(args.overlay, args.build, args.source_sha,
                               args.builder_sha256), indent=2))
    else:
        print(json.dumps(metadata(args.dist, args.build, args.source_sha,
                                  args.output), indent=2))


if __name__ == "__main__":
    main()
