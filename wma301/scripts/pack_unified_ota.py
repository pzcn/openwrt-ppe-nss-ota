#!/usr/bin/env python3
"""Build device-scoped main-repository OTA assets from verified WMA301 FIT."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from aurora import PACKAGE_NAME, PACKAGE_VERSION
import shutil

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "immortalwrt-mediatek-filogic-tplink_wma301-v2-squashfs-sysupgrade.itb"
MANIFEST = "immortalwrt-mediatek-filogic-tplink_wma301-v2.manifest"
BOARD = "tplink,wma301-v2"
BANNED = {
    "sing-box", "luci-app-sing-box", "luci-app-homeproxy",
    "tailscale", "luci-app-tailscale-community",
    "luci-i18n-tailscale-community-zh-cn",
    "luci-app-ddns-go", "luci-i18n-ddns-go-zh-cn",
    "luci-app-ppe-qos", "luci-app-ppe-nss-monitor",
    "kmod-qca-nss-drv", "kmod-qca-nss-ecm",
}


def require(ok: bool, why: str) -> None:
    if not ok:
        raise ValueError(why)


def load_shared():
    spec = importlib.util.spec_from_file_location(
        "shared_ota", ROOT / "scripts/immortalwrt_ota.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot import shared OTA")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def pack(images: Path, dist: Path, overlay: Path, output: Path, tag: str,
         build: int, upstream: str, source: str, provenance: Path,
         aurora_apk: Path) -> None:
    require(re.fullmatch(r"imm-wma301-SNAPSHOT-r[0-9]+-[0-9]{12}", tag) is not None,
            "invalid unified WMA301 OTA tag")
    require(build >= 1_000_000_000, "WMA301 build must be a timestamp")
    for name, value in (("upstream", upstream), ("source", source)):
        require(re.fullmatch(r"[0-9a-f]{40}", value) is not None,
                f"invalid {name} commit")
    prov = json.loads(provenance.read_text())
    report = json.loads((dist / "manifest.json").read_text())
    require(prov == report["builder"], "builder provenance differs from verified FIT")
    require(prov["target"] == "mediatek/filogic" and
            re.fullmatch(r"r[0-9]+-[0-9a-f]{10,40}", prov["version"]) is not None and
            upstream.startswith(prov["source_revision"]),
            "unverified official Filogic Snapshot")
    require(report["build"] == "official-imagebuilder-fast" and
            report["device"] == BOARD and report["local_sha"] == source and
            report["hardware_validation"] == "NOT_TESTED",
            "wrong FIT/build identity")
    fit_report = report["output"]
    require(fit_report["fit_hashes"] == "pass" and
            fit_report["mode"] == "squashfs-persistent" and
            fit_report["dts"]["compatible"] == BOARD and
            fit_report["dts"]["factory_info_protected"] is True,
            "FIT verification did not pass")
    original = dist / fit_report["file"]
    require(original.is_file() and original.suffix == ".itb" and
            1_000_000 < original.stat().st_size < 96 * 1024 * 1024 and
            sha256(original) == fit_report["sha256"],
            "WMA301 FIT is missing or its SHA256 changed")
    require((dist / "SHA256SUMS").read_text().strip() ==
            f"{sha256(original)}  {original.name}",
            "original verified FIT checksum mismatch")
    # The manifest must reflect packages actually assembled by ImageBuilder.
    # Never synthesize it from requested_packages: dependencies matter for APK restore.
    candidates = sorted(p for p in images.iterdir() if p.is_file() and
                        p.name.endswith("tplink_wma301-v2.manifest"))
    require(len(candidates) == 1, "missing or ambiguous actual WMA301 APK manifest")
    names = set()
    for line in candidates[0].read_text().splitlines():
        fields = line.split()
        if not fields:
            continue
        require(len(fields) >= 2 and
                re.fullmatch(r"[a-zA-Z0-9_.+\-]+", fields[0]) is not None,
                "invalid ImageBuilder package manifest")
        names.add(fields[0])
    require(len(names) > 10, "incomplete ImageBuilder package manifest")
    forbidden = {n for n in names if n in BANNED or n.startswith(
        ("kmod-qca-nss", "luci-i18n-ppe-qos", "qca-nss"))}
    require(not forbidden, f"prohibited firmware packages: {sorted(forbidden)}")
    for needed in ("luci", "luci-app-wol", "luci-app-filemanager", "luci-theme-aurora"):
        require(needed in names, f"missing required WMA301 package: {needed}")
    # Reject legacy overlay-based builds, even if their selected package names
    # were modified to claim Aurora installation.
    theme = report.get("installed_theme")
    require(isinstance(theme, dict) and
            theme.get("name") == "luci-theme-aurora" and
            theme.get("version") == "1.4.0-r1" and
            theme.get("architecture") == "noarch" and
            re.fullmatch(r"[a-f0-9]{64}", str(theme.get("sha256", ""))) is not None,
            "Aurora must be installed as a native verified APK")
    require(not (overlay / "www/luci-static/aurora").exists() and
            not (overlay / "usr/share/ucode/luci/template/themes/aurora").exists(),
            "Aurora assets must be owned by the package manager")
    require(aurora_apk.is_file() and
            aurora_apk.name == f"{PACKAGE_NAME}-{PACKAGE_VERSION}.apk" and
            aurora_apk.stat().st_size > 1024 and
            sha256(aurora_apk) == theme["sha256"],
            "The published Aurora APK must match the installed verified package")
    local = (overlay / "etc/immortal-ppe-ota-release").read_text()
    for needle in (f"OTA_TAG={tag}", f"OTA_BUILD={build}",
                   "OTA_CHANNEL=wma301-immortal-filogic"):
        require(needle in local.splitlines(), f"wrong in-FIT OTA identity: {needle}")
    require((overlay / "usr/libexec/ppe-update-wma301-preflight").is_file(),
            "missing WMA301 hardware safety preflight")
    require("ppe-update-wma301-preflight" in
            (overlay / "usr/sbin/ppe-update").read_text(),
            "missing preflight hook in OTA backend")
    output.mkdir(parents=True, exist_ok=True)
    target = output / IMAGE
    shutil.copyfile(original, target)
    shutil.copyfile(candidates[0], output / MANIFEST)
    shutil.copyfile(dist / "manifest.json", output / "manifest.json")
    shutil.copyfile(provenance, output / "official-provenance.json")
    shutil.copyfile(aurora_apk, output / aurora_apk.name)
    shared = load_shared()
    shared.metadata(tag=tag, build=build, upstream=upstream, ppe="",
                    image=target, manifest=output / MANIFEST,
                    output=output / "ota.json", source_commit=source,
                    device="wma301")
    assert json.loads((output / "ota.json").read_text())["layout"] == (
        "oem-bl2-bl31-custom-bl33-single-ubi-v1")
    assets = (IMAGE, MANIFEST, "ota.json", "manifest.json",
              "official-provenance.json", aurora_apk.name)
    (output / "sha256sums").write_text("".join(
        f"{sha256(output / name)}  {name}\n" for name in assets))
    print(f"Verified WMA301 unified OTA assets: {tag}, packages={len(names)}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--images", type=Path, required=True)
    p.add_argument("--dist", type=Path, required=True)
    p.add_argument("--overlay", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--build", type=int, required=True)
    p.add_argument("--upstream", required=True)
    p.add_argument("--source", required=True)
    p.add_argument("--provenance", type=Path, required=True)
    p.add_argument("--aurora-apk", type=Path, required=True)
    a = p.parse_args()
    pack(a.images, a.dist, a.overlay, a.output, a.tag, a.build,
         a.upstream, a.source, a.provenance, a.aurora_apk)


if __name__ == "__main__":
    main()
