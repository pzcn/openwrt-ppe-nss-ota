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

    # The same native LuCI panel and GitHub proxy settings as Arthur/MX4200.
    # WMA301 does not support auto-installation, so do not expose fake controls.
    flash = overlay / COMMON["files/www/luci-static/resources/view/system/flash.js"]
    ui = flash.read_text()
    before_rows = (
        "\t\t\trow('启用自动更新', auto),\n"
        "\t\t\trow('检查时间', hour),\n"
        "\t\t\trow('延迟天数', delay),"
    )
    if ui.count(before_rows) != 1:
        raise ValueError("LuCI OTA schedule layout has changed")
    ui = ui.replace(
        before_rows,
        "\t\t\tE('p', { 'class': 'cbi-value-description' }, "
        "'WMA301 仅允许手动更新，自动安装已禁用。'),"
    )
    original_auto = "'checked': uci.get('ppe-update', 'main', 'auto') == '1' ? '' : null"
    if ui.count(original_auto) != 1:
        raise ValueError("LuCI auto checkbox API has changed")
    ui = ui.replace(original_auto, "'checked': null")
    flash.write_text(ui)

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
        "WMA301 unattended OTA is disabled",
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

    defaults = overlay / "etc/uci-defaults/98-wma301-ota-manual-only"
    defaults.parent.mkdir(parents=True, exist_ok=True)
    defaults.write_text(
        "#!/bin/sh\n"
        "# Always disable unattended installation, including restored UCI settings.\n"
        "uci -q set ppe-update.main.auto='0'\n"
        "uci -q commit ppe-update\n"
        "exit 0\n"
    )
    defaults.chmod(0o755)
    if existing_upgrade.read_bytes() != before:
        raise ValueError("shared OTA overwrote WMA301 NAND upgrade hooks")
    for forbidden in (
        "usr/libexec/ppe-nss-telemetry",
        "usr/share/luci/menu.d/luci-app-ppe-nss-monitor.json",
        "etc/uci-defaults/95-sing-box-tun-user",
    ):
        if (overlay / forbidden).exists():
            raise ValueError(f"Qualcomm or proxy component leaked: {forbidden}")
    print(f"Shared manual-only WMA301 OTA staged: {tag} (build={build})")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--build", type=int, required=True)
    args = parser.parse_args()
    stage(args.overlay, args.tag, args.build)


if __name__ == "__main__":
    main()
