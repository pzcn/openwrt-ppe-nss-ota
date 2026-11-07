#!/usr/bin/env python3
"""Offline regression checks for sing-box and Wake on LAN image integration."""
import importlib.util
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[2]
script = (root / "scripts/build.sh").read_text(encoding="utf-8")
add_file = root / "config/add.txt"
resolver_path = root / "scripts/resolve_packages.py"

spec = importlib.util.spec_from_file_location("resolve_packages", resolver_path)
resolver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resolver)
packages = resolver.names(add_file)
mandatory = {
    "sing-box", "flock", "kmod-tun", "kmod-inet-diag",
    "luci-app-wol", "luci-i18n-wol-zh-cn", "etherwake",
}
assert mandatory <= set(packages), mandatory - set(packages)
assert len(packages) == len(set(packages))
assert "luci-app-sing-box" not in packages  # bundled as a pinned APK
assert '["luci-theme-aurora", "luci-app-sing-box"]' in resolver_path.read_text()
assert "SING_LUCI_TAG=v0.4.7" in script
assert "SING_LUCI_APK=luci-app-sing-box-0.4.7-r1.apk" in script
assert "SING_LUCI_SHA256=02de66fec60fc5a6cb635813afaaaa18f37e8a62023a3f6a655d73a6335f8bc3" in script
assert "sha256sum -c -" in script
assert 'cp "$WORK/$SING_LUCI_APK" "$WORK/ib/packages/"' in script
assert 'EXTRA_APPS_REV=singbox047-wol1' in script
assert "for p in luci-theme-aurora luci-app-sing-box sing-box kmod-tun kmod-inet-diag flock luci-app-wol etherwake luci-i18n-wol-zh-cn" in script
assert "Missing optional application dependency" in script

hook = root / "files/etc/uci-defaults/95-sing-box-tun-user"
assert hook.is_file()
subprocess.run(["sh", "-n", str(hook)], check=True)
contents = hook.read_text()
assert "sing-box.main.user='root'" in contents
assert "sing-box.main.enabled" in contents
assert not (root / "files/etc/sing-box/config.json").exists()
assert not (root / "config.json").exists()
assert not (root / "files/etc/config/sing-box").exists()
assert "sing-box 与网络唤醒" in (root / "README.md").read_text()
assert "Windows" in (root / "docs/SINGBOX-WOL.md").read_text()
print("PASS: pinned sing-box LuCI APK, native WOL translation and private config isolation")
