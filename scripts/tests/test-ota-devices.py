#!/usr/bin/env python3
"""Shared OTA regression: three board IDs, isolated release namespaces, one engine."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("immortalwrt_ota", ROOT / "scripts/immortalwrt_ota.py")
ota = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(ota)

source = (ROOT / "files/usr/sbin/ppe-update").read_text()
assert "sysupgrade -T" in source and "cmd_auto()" in source
assert set(ota.DEVICES) == {"arthur", "mx4200v1", "wma301"}


def prepare_sample(root: Path, device: str):
    image = root / "overlay"
    (image / "usr/sbin").mkdir(parents=True)
    (image / "usr/sbin/ppe-update").write_text(source)
    flash = image / "www/luci-static/resources/view/system/flash.js"
    flash.parent.mkdir(parents=True)
    flash.write_bytes((ROOT / "files/www/luci-static/resources/view/system/flash.js").read_bytes())
    name = ota.DEVICES[device]["tag_prefix"] + "test-1"
    ota.prepare(image, name, 12345, device=device)
    return image, name


with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    arthur, arthur_tag = prepare_sample(root / "arthur", "arthur")
    mx, mx_tag = prepare_sample(root / "mx", "mx4200v1")
    wma, wma_tag = prepare_sample(root / "wma", "wma301")
    src_arthur = (arthur / "usr/sbin/ppe-update").read_text()
    src_mx = (mx / "usr/sbin/ppe-update").read_text()
    for device, backend, tag in [
        ("arthur", src_arthur, arthur_tag),
        ("mx4200v1", src_mx, mx_tag),
        ("wma301", (wma / "usr/sbin/ppe-update").read_text(), wma_tag),
    ]:
        cfg = ota.DEVICES[device]
        assert cfg["channel"] in backend
        assert cfg["board"] in backend
        assert cfg["profile"] in backend
        assert cfg["group"] in backend
        assert cfg["image"] in backend
        assert 'startswith("' + cfg["tag_prefix"] + '")' in backend
        assert 'sysupgrade -T' in backend
        assert 'apk add' in backend
        rel = {"arthur": arthur, "mx4200v1": mx, "wma301": wma}[device] / "etc/immortal-ppe-ota-release"
        assert "OTA_TAG=" + tag in rel.read_text()
        assert "OTA_CHANNEL=" + cfg["channel"] in rel.read_text()
        menu = json.loads((({"arthur": arthur, "mx4200v1": mx, "wma301": wma}[device]) /
                           "usr/share/luci/menu.d/zzzz-ota-flash-cache.json").read_text())
        action = menu["admin/system/flash"]["action"]
        assert action["type"] == "view"
        assert action["path"].startswith("system/flash-ota-b12345-")
        assert len(menu) == 1  # no second OTA menu or changed router URL
    assert "imm-mx4200v1-" not in src_arthur
    assert "imm-arthur-" not in src_mx
    assert "jdcloud,re-ss-01" not in src_mx
    assert "linksys,mx4200v1" not in src_arthur

    for device in ("arthur", "mx4200v1", "wma301"):
        cfg = ota.DEVICES[device]
        base = root / ("meta-" + device)
        base.mkdir()
        image = base / cfg["image"]
        with image.open("wb") as out:
            out.truncate(2_000_000)
        manifest = base / cfg["manifest"]
        manifest.write_text("pname - 2.0.0\n" * 20)
        data = base / "ota.json"
        tag = cfg["tag_prefix"] + "test-1"
        ota.metadata(tag, 12345, "a" * 40,
                     "" if device == "wma301" else "b" * 40,
                     image, manifest, data, source_commit="c" * 40, device=device)
        result = json.loads(data.read_text())
        assert result["channel"] == cfg["channel"]
        assert result["board"] == cfg["board"]
        assert result["profile"] == cfg["profile"]
        assert result["group"] == cfg["group"]
        assert result["target"] == cfg["target"]
        assert result["image_sha256"] == ota.sha256(image)
        assert result["manifest_sha256"] == ota.sha256(manifest)
        wrong_device = "mx4200v1" if device == "arthur" else "arthur"
        try:
            ota.metadata(tag, 12345, "a" * 40, "b" * 40, image, manifest, data,
                         device=wrong_device)
        except ValueError:
            pass
        else:
            raise AssertionError("Cross-channel OTA metadata was accepted")
        try:
            ota.prepare(root / "not-used", ota.DEVICES[wrong_device]["tag_prefix"] + "wrong", 1, device)
        except ValueError:
            pass
        else:
            raise AssertionError("Cross-channel OTA image identity was accepted")

    wma_shell = (wma / "usr/sbin/ppe-update").read_text()
    assert "ppe-update-wma301-preflight" in wma_shell
    assert "WMA301 unattended OTA is disabled" in wma_shell
    assert "cmd_auto() {\n\t# WMA301 never installs unattended.\n\treturn 0" in wma_shell
    assert 'meta layout' in wma_shell
    assert "ppe-update-wma301-preflight" not in src_mx + src_arthur
    assert 'imm-wma301-' not in src_mx + src_arthur
    assert "ppe_nss_commit" not in json.loads((root / "meta-wma301/ota.json").read_text())
    assert json.loads((root / "meta-wma301/ota.json").read_text())["layout"] == ota.DEVICES["wma301"]["layout"]

    # Staging MX only: no eMMC platform.sh, no inherited Arthur /etc/fstab,
    # and no old one-time script deleting the newly installed updater.
    staging = root / "mx-staging"
    for name in ("etc/init.d/ppe-update", "etc/config/ppe-update",
                 "etc/uci-defaults/99-remove-ppe-update"):
        path = staging / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#! /bin/sh\n")
    subprocess.run(["bash", str(ROOT / "mx4200v1/stage-overlay.sh"), str(staging)],
                   check=True, capture_output=True)
    assert (staging / "usr/sbin/ppe-update").is_file()
    assert (staging / "etc/init.d/ppe-update").is_file()
    # Shared Arthur/MX LuCI features must not drift. MX keeps its own OTA
    # identity and native NAND upgrade, but uses the same read-only PPE/NSS
    # monitor, Chinese language defaults and feed retention.
    for required in (
        "usr/share/rpcd/ucode/luci.ppe-nss-monitor",
        "usr/libexec/ppe-nss-telemetry",
        "usr/share/luci/menu.d/luci-app-ppe-nss-monitor.json",
        "www/luci-static/resources/view/status/ppe-nss-monitor-native.js",
        "etc/uci-defaults/95-luci-preferences",
        "etc/uci-defaults/98-keep-immortalwrt-apk-feed",
    ):
        assert (staging / required).is_file(), f"Missing shared feature: {required}"
    for excluded in ("etc/config/drcom", "etc/init.d/drcom",
                     "usr/libexec/drcom-web"):
        assert not (staging / excluded).exists(), f"DrCOM exclusion drift: {excluded}"
    assert not (staging / "etc/uci-defaults/99-remove-ppe-update").exists()
    assert not (staging / "lib/upgrade/platform.sh").exists()
    assert not (staging / "etc/config/fstab").exists()
    flash = (staging / "www/luci-static/resources/view/system/flash.js").read_text()
    assert "在线固件更新" in flash and "GitHub 代理" in flash
    assert "MX4200 v1 PPE+NSS" not in flash
    assert "option github_proxy 'direct'" in (
        staging / "etc/config/ppe-update").read_text()
    assert (staging / "usr/share/rpcd/acl.d/luci-app-ppe-update.json").is_file()
    assert not (staging / "usr/share/luci/menu.d/luci-app-pzcn-ota.json").exists()
    assert (staging / "etc/uci-defaults/98-mx4200v1-ota-manual-default").is_file()
    assert "auto='0'" in (
        staging / "etc/uci-defaults/98-mx4200v1-ota-manual-default").read_text()
    try:
        (staging / "lib/upgrade").mkdir(parents=True, exist_ok=True)
        (staging / "lib/upgrade/platform.sh").write_text("eMMC override\n")
        subprocess.run(["bash", str(ROOT / "mx4200v1/stage-overlay.sh"), str(staging)],
                       check=True, capture_output=True)
    except subprocess.CalledProcessError:
        pass
    else:
        raise AssertionError("MX4200 accepted an override of NAND platform.sh")

print("PASS: shared OTA, isolated release channels, and safe MX staging")
