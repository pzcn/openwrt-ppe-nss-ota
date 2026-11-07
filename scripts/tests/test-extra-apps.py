#!/usr/bin/env python3
"""Offline checks for Tailscale, sing-box and translated Wake on LAN."""
import importlib.util
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[2]
build = (root / "scripts/build.sh").read_text(encoding="utf-8")
resolver_path = root / "scripts/resolve_packages.py"
spec = importlib.util.spec_from_file_location("resolve_packages", resolver_path)
resolver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resolver)

added = resolver.names(root / "config/add.txt")
removed = resolver.names(root / "config/remove.txt")
required = {
    "tailscale", "luci-app-tailscale-community",
    "luci-i18n-tailscale-community-zh-cn",
    "sing-box", "flock", "kmod-inet-diag", "kmod-tun",
    "luci-app-wol", "etherwake", "luci-i18n-wol-zh-cn",
}

assert required <= set(added), required - set(added)
assert not set(added) & set(removed)
assert not {"sing-box", "luci-app-sing-box"} & set(removed)
assert "luci-app-sing-box" not in added  # local, checksum-pinned APK
assert len(added) == len(set(added))
assert '["luci-theme-aurora", "luci-app-sing-box"]' in resolver_path.read_text()
assert "EXTRA_APPS_REV=tailscale-singbox047-wol1" in build
assert "SING_LUCI_TAG=v0.4.7" in build
assert "SING_LUCI_APK=luci-app-sing-box-0.4.7-r1.apk" in build
assert "SING_LUCI_SHA256=02de66fec60fc5a6cb635813afaaaa18f37e8a62023a3f6a655d73a6335f8bc3" in build
assert 'printf \'%s  %s\\n\' "$SING_LUCI_SHA256" "$WORK/$SING_LUCI_APK" | sha256sum -c -' in build
assert 'cp "$WORK/$SING_LUCI_APK" "$WORK/ib/packages/"' in build
assert "luci-app-tailscale-community luci-i18n-tailscale-community-zh-cn sing-box luci-app-sing-box flock kmod-tun kmod-inet-diag" in build
assert "luci-app-wol etherwake luci-i18n-wol-zh-cn" in build
assert "sing-box-luci-sha256.txt" in build
assert "Retired sing-box packages found in generated image manifest" not in build

hook = root / "files/etc/uci-defaults/95-sing-box-tun-user"
assert hook.is_file()
subprocess.run(["sh", "-n", str(hook)], check=True)
contents = hook.read_text()
assert "sing-box.main.user='root'" in contents
assert "sing-box.main.enabled" in contents

for private in ["files/etc/sing-box/config.json", "config.json"]:
    assert not (root / private).exists(), private

readme = (root / "README.md").read_text()
assert "VPN → Tailscale" in readme
assert "服务 → sing-box" in readme
assert "服务 → 网络唤醒" in readme
assert "docs/SINGBOX.md" in readme
assert "Tailscale" in (root / "docs/SINGBOX.md").read_text()
assert "sing-box" in (root / "docs/TAILSCALE-WOL.md").read_text()
subprocess.run(["bash", "-n", str(root / "scripts/build.sh")], check=True)
print("PASS: Tailscale + sing-box LuCI + translated WOL in the same image")
