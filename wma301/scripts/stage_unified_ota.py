#!/usr/bin/env python3
"""Stage the shared OTA UI and updater for WMA301 without Qualcomm payloads."""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
WMA = Path(__file__).resolve().parents[1]
COMMON = {
    "files/usr/sbin/ppe-update": "usr/sbin/ppe-update",
    "files/usr/share/rpcd/acl.d/luci-app-ppe-update.json":
        "usr/share/rpcd/acl.d/luci-app-ppe-update.json",
    "files/www/luci-static/resources/view/system/flash.js":
        "www/luci-static/resources/view/system/flash.js",
}
MX_SERVICE = {
    "mx4200v1/files/etc/config/ppe-update": "etc/config/ppe-update",
    "mx4200v1/files/etc/init.d/ppe-update": "etc/init.d/ppe-update",
    "mx4200v1/files/etc/uci-defaults/zz-ppe-update":
        "etc/uci-defaults/zz-ppe-update",
    "mx4200v1/files/lib/upgrade/keep.d/ppe-update":
        "lib/upgrade/keep.d/ppe-update",
}
WMA_ONLY = {
    "files/usr/libexec/ppe-update-wma301-preflight":
        "usr/libexec/ppe-update-wma301-preflight",
}


def stage(overlay: Path, tag: str, build: int) -> None:
    if not overlay.is_dir() or not tag.startswith("imm-wma301-SNAPSHOT-r") or build < 1:
        raise ValueError("invalid WMA301 overlay/version")
    existing_upgrade = overlay / "lib/upgrade/platform.sh"
    if not existing_upgrade.is_file():
        raise ValueError("missing original WMA301 NAND/UBI sysupgrade integration")
    before = existing_upgrade.read_bytes()
    for group, origin in ((COMMON, ROOT), (MX_SERVICE, ROOT), (WMA_ONLY, WMA)):
        for source, dest in group.items():
            src = origin / source
            target = overlay / dest
            if not src.is_file() or target.exists():
                raise ValueError(f"missing or colliding staged OTA file: {source} -> {dest}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)

    # Use the shared LuCI panel unchanged, including the optional scheduled
    # update settings. Device-specific NAND checks remain in the backend.
    spec = importlib.util.spec_from_file_location(
        "shared_ota", ROOT / "scripts/immortalwrt_ota.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load shared OTA implementation")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.prepare(overlay, tag, build, "wma301")
    backend = overlay / "usr/sbin/ppe-update"
    source = backend.read_text()
    required = (
        "ppe-update-wma301-preflight",
        "WMA301 OTA layout mismatch",
        "imm-wma301-",
        "tplink,wma301-v2",
    )
    if not all(piece in source for piece in required):
        raise ValueError("WMA301 safety hooks lost from the updater")
    subprocess.run(["sh", "-n", str(backend)], check=True)
    subprocess.run(
        ["sh", "-n",
         str(overlay / "usr/libexec/ppe-update-wma301-preflight")], check=True)

    if existing_upgrade.read_bytes() != before:
        raise ValueError("shared OTA overwrote WMA301 NAND upgrade hooks")
    for forbidden in (
        "usr/libexec/ppe-nss-telemetry",
        "usr/share/luci/menu.d/luci-app-ppe-nss-monitor.json",
        "etc/uci-defaults/95-sing-box-tun-user",
    ):
        if (overlay / forbidden).exists():
            raise ValueError(f"Qualcomm or proxy component leaked: {forbidden}")
    print(f"Shared WMA301 OTA staged: {tag} (build={build})")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--build", type=int, required=True)
    args = parser.parse_args()
    stage(args.overlay, args.tag, args.build)


if __name__ == "__main__":
    main()
