#!/usr/bin/env python3
"""Regression checks for official Tailscale and translated Wake on LAN."""
import importlib.util
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[2]
build = (root / "scripts/build.sh").read_text(encoding="utf-8")
add_file = root / "config/add.txt"
remove_file = root / "config/remove.txt"
resolver_path = root / "scripts/resolve_packages.py"

spec = importlib.util.spec_from_file_location("resolve_packages", resolver_path)
resolver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resolver)
added = resolver.names(add_file)
removed = resolver.names(remove_file)

required = {
    "tailscale", "luci-app-tailscale-community",
    "luci-i18n-tailscale-community-zh-cn", "kmod-tun",
    "luci-app-wol", "etherwake", "luci-i18n-wol-zh-cn",
}
retired = {"sing-box", "luci-app-sing-box"}
assert required <= set(added), required - set(added)
assert retired <= set(removed), retired - set(removed)
assert not set(added) & set(removed)
assert not set(added) & retired
assert "flock" not in added
assert "kmod-inet-diag" not in added
assert len(added) == len(set(added))
assert "all_packages = base + new + [\"luci-theme-aurora\"]" in resolver_path.read_text()
assert "EXTRA_APPS_REV=tailscale-wol1" in build
assert "for p in luci-theme-aurora tailscale luci-app-tailscale-community luci-i18n-tailscale-community-zh-cn kmod-tun luci-app-wol etherwake luci-i18n-wol-zh-cn" in build
assert "Missing optional application dependency" in build
assert "Retired sing-box packages found in generated image manifest" in build
assert "sing-box-luci-sha256.txt" not in build
assert "SING_LUCI_" not in build
assert not (root / "files/etc/uci-defaults/95-sing-box-tun-user").exists()
assert not (root / "docs/SINGBOX-WOL.md").exists()
assert not (root / "files/etc/sing-box/config.json").exists()
assert not (root / "config.json").exists()
assert "Tailscale 与网络唤醒" in (root / "README.md").read_text()
assert "Tailscale 与网络唤醒" in (root / "docs/TAILSCALE-WOL.md").read_text()
assert "luci-app-tailscale-community" in (root / "docs/TAILSCALE-WOL.md").read_text()
subprocess.run(["sh", "-n", str(root / "scripts/build.sh")], check=True)
print("PASS: Tailscale + translated LuCI, Wake on LAN, and sing-box removal")
