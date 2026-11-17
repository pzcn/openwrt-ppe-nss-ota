#!/usr/bin/env python3
"""Offline WMA301 integration contracts: shared LuCI/OTA and fail-closed FIT."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from stage_unified_ota import stage
from pack_unified_ota import pack, IMAGE, MANIFEST

ROOT = Path(__file__).resolve().parents[2]
WMA = Path(__file__).resolve().parents[1]
tag = "imm-wma301-SNAPSHOT-r42542-202611161651"
build = 1794819098
source = "a" * 40
upstream = "e695009c15" + "b" * 30
assert len(upstream) == 40
with TemporaryDirectory() as tmp:
    base = Path(tmp)
    overlay = base / "overlay"
    platform = overlay / "lib/upgrade/platform.sh"
    platform.parent.mkdir(parents=True)
    platform.write_text("#!/bin/sh\n# WMA301 fit_do_upgrade, preserved\n")
    stage(overlay, tag, build)
    assert platform.read_text().endswith("preserved\n")
    for path in (
        "usr/sbin/ppe-update",
        "usr/libexec/ppe-update-wma301-preflight",
        "etc/config/ppe-update", "etc/init.d/ppe-update",
        "usr/share/rpcd/acl.d/luci-app-ppe-update.json",
        "usr/share/luci/menu.d/zzzz-ota-flash-cache.json",
    ):
        assert (overlay / path).is_file(), path
    app = (overlay / "www/luci-static/resources/view/system/flash.js").read_text()
    assert "在线固件更新" in app and "GitHub 代理" in app
    assert "row('启用自动更新', auto)" in app
    assert "row('检查时间', hour)" in app
    assert "row('延迟天数', delay)" in app
    assert not (overlay / "etc/uci-defaults/98-wma301-ota-manual-only").exists()
    backend = (overlay / "usr/sbin/ppe-update").read_text()
    assert "imm-wma301-" in backend
    assert "wma301-immortal-filogic" in backend
    assert "WMA301 unattended OTA is disabled" not in backend
    assert "cmd_auto() {\n\t[ \"$(uci" in backend
    assert "ppe-update-wma301-preflight" in backend
    assert "releases?per_page=100" in backend
    assert "sysupgrade -T" in backend
    assert backend.index("ppe-update-wma301-preflight") < backend.index(
        'sysupgrade -T "$WORK/$IMAGE"')
    assert "WMA301 OTA layout mismatch" in backend
    for bad in ("usr/libexec/ppe-nss-telemetry",
                "usr/share/luci/menu.d/luci-app-ppe-nss-monitor.json"):
        assert not (overlay / bad).exists(), bad
    assert "ubi[0-9]*_[0-9]*/name" in (
        overlay / "usr/libexec/ppe-update-wma301-preflight").read_text()

    dist = base / "dist"
    images = base / "images"
    out = base / "out"
    for directory in (dist, images):
        directory.mkdir()
    filename = "immortalwrt-snapshot-r42542-mediatek-filogic-tplink_wma301-v2-squashfs-sysupgrade.itb"
    raw = dist / filename
    raw.write_bytes(b"VERIFIED-FAKE-FIT" * 70000)
    digest = hashlib.sha256(raw.read_bytes()).hexdigest()
    (dist / "SHA256SUMS").write_text(f"{digest}  {filename}\n")
    installed = [
        "luci - 1", "luci-app-filemanager - 1", "luci-app-wol - 1",
        "autocore - 42",
        "luci-i18n-base-zh-cn - 1", "luci-app-pbr - 1",
        "wireguard-tools - 1", "kmod-mt7915e - 1",
        "kmod-mt7981-firmware - 1", "mt7981-wo-firmware - 1",
        "luci-theme-bootstrap - 1", "luci-theme-aurora - 1.4.0-r1",
        "luci-app-ttyd - 1",
    ]
    pkg = images / "immortalwrt-mediatek-filogic-tplink_wma301-v2.manifest"
    pkg.write_text("\n".join(installed) + "\n")
    aurora_apk = base / "luci-theme-aurora-1.4.0-r1.apk"
    aurora_apk.write_bytes(b"NATIVE-APK-FIXTURE-" * 150)
    provenance = {
        "source": "ImmortalWrt master SNAPSHOT (official binaries)",
        "target": "mediatek/filogic",
        "version": "r42542-e695009c15",
        "source_revision": "e695009c15",
        "imagebuilder_sha256": "c" * 64,
    }
    provfile = base / "official-provenance.json"
    provfile.write_text(json.dumps(provenance))
    report = {
        "build": "official-imagebuilder-fast",
        "device": "tplink,wma301-v2",
        "local_sha": source,
        "hardware_validation": "NOT_TESTED",
        "installed_theme": {
            "name": "luci-theme-aurora", "version": "1.4.0-r1",
            "architecture": "noarch",
            "sha256": hashlib.sha256(aurora_apk.read_bytes()).hexdigest(),
        },
        "builder": provenance,
        "output": {
            "file": filename,
            "sha256": digest,
            "fit_hashes": "pass",
            "mode": "squashfs-persistent",
            "dts": {
                "compatible": "tplink,wma301-v2",
                "factory_info_protected": True,
            },
        },
    }
    (dist / "manifest.json").write_text(json.dumps(report))
    pack(images, dist, overlay, out, tag, build, upstream, source, provfile, aurora_apk)
    meta = json.loads((out / "ota.json").read_text())
    assert meta["repository"] == "pzcn/openwrt-ppe-nss-ota"
    assert meta["board"] == "tplink,wma301-v2"
    assert meta["target"] == "mediatek/filogic"
    assert meta["image"] == IMAGE and meta["manifest"] == MANIFEST
    assert meta["tag"] == tag and meta["build"] == build
    assert "ppe_nss_commit" not in meta and "sing_box_core" not in meta
    assert "layout" in meta and "ubi" in meta["layout"]
    assert (out / IMAGE).read_bytes() == raw.read_bytes()
    assert (out / aurora_apk.name).read_bytes() == aurora_apk.read_bytes()
    assert "sha256sums" in [x.name for x in out.iterdir()]
    # v2.1 gets exactly the same package/UBI integration, with its own board ID.
    overlay21 = base / "overlay-v21"
    platform21 = overlay21 / "lib/upgrade/platform.sh"
    platform21.parent.mkdir(parents=True)
    platform21.write_text("#!/bin/sh\n# same single-UBI upgrade\n")
    tag21 = tag.replace("imm-wma301-", "imm-wma301v21-")
    stage(overlay21, tag21, build, "wma301v21")
    updater21 = (overlay21 / "usr/sbin/ppe-update").read_text()
    assert "tplink,wma301-v2-1" in updater21 and "wma301v21-immortal-filogic" in updater21
    assert "ppe-update-wma301-preflight" in updater21
    images21, dist21 = base / "images-v21", base / "dist-v21"
    images21.mkdir()
    dist21.mkdir()
    filename21 = filename.replace("wma301-v2-squashfs", "wma301-v2-1-squashfs")
    (dist21 / filename21).write_bytes(raw.read_bytes())
    (dist21 / "SHA256SUMS").write_text(f"{digest}  {filename21}\n")
    (images21 / "immortalwrt-mediatek-filogic-tplink_wma301-v2-1.manifest").write_text(
        "\n".join(installed) + "\n")
    report21 = json.loads(json.dumps(report))
    report21["device"] = "tplink,wma301-v2-1"
    report21["output"]["file"] = filename21
    report21["output"]["dts"]["compatible"] = "tplink,wma301-v2-1"
    (dist21 / "manifest.json").write_text(json.dumps(report21))
    out21 = base / "out-v21"
    pack(images21, dist21, overlay21, out21, tag21, build,
         upstream, source, provfile, aurora_apk, device="wma301v21")
    meta21 = json.loads((out21 / "ota.json").read_text())
    assert meta21["board"] == "tplink,wma301-v2-1"
    assert meta21["profile"] == "tplink_wma301-v2-1"
    assert meta21["image"].endswith("tplink_wma301-v2-1-squashfs-sysupgrade.itb")
    assert meta21["channel"] == "wma301v21-immortal-filogic"
    assert meta21["tag"] == tag21
    assert meta21["layout"] == meta["layout"]
    assert (out21 / meta21["image"]).read_bytes() == raw.read_bytes()

    # Reject regressions that silently remove the temperature RPC backend.
    pkg.write_text("\n".join(p for p in installed if not p.startswith("autocore ")) + "\n")
    try:
        pack(images, dist, overlay, base / "bad-no-tempinfo", tag, build,
             upstream, source, provfile, aurora_apk)
    except ValueError:
        pass
    else:
        raise AssertionError("accepted firmware without autocore temperature backend")
    pkg.write_text("\n".join(installed) + "\n")
    # Never accept a synthetic package manifest based on the requested list.
    pkg.unlink()
    try:
        pack(images, dist, overlay, base / "bad-missing", tag, build, upstream,
             source, provfile, aurora_apk)
    except ValueError:
        pass
    else:
        raise AssertionError("accepted image without actual package manifest")
    pkg.write_text("\n".join(installed + ["tailscale - 1"]) + "\n")
    try:
        pack(images, dist, overlay, base / "bad-package", tag, build, upstream,
             source, provfile, aurora_apk)
    except ValueError:
        pass
    else:
        raise AssertionError("accepted forbidden Tailscale component")
    # Reject wrong upstream commit instead of silently mixing ABI.
    pkg.write_text("\n".join(installed) + "\n")
    try:
        pack(images, dist, overlay, base / "bad-upstream", tag, build,
             "d" * 40, source, provfile, aurora_apk)
    except ValueError:
        pass
    else:
        raise AssertionError("accepted unpinned upstream")
print("PASS WMA301 unified OTA: real manifest, hardware guards, ABI and package bans")
