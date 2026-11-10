#!/usr/bin/env python3
"""Validate the complete user plugin matrix in the ImmortalWrt firmware."""
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[2]

def read_packages(name):
    result = []
    for raw in (root / name).read_text(encoding="utf-8").splitlines():
        result.extend(raw.split("#", 1)[0].strip().split())
    return result

added = read_packages("config/add.txt")
removed = read_packages("config/remove.txt")
required = {
    "block-mount", "kmod-fs-ext4", "e2fsprogs", "kmod-fs-f2fs", "f2fs-tools",
    "curl", "jsonfilter", "luci-proto-wireguard", "wireguard-tools",
    "tcpdump", "ip-full", "conntrack", "kmod-nf-conntrack-netlink",
    "luci-app-filemanager", "luci-app-ttyd", "luci-app-nlbwmon",
    "luci-app-wifihistory", "luci-app-irqbalance",
    "luci-app-lldpd", "luci-app-pbr",
    "luci-i18n-base-zh-cn", "luci-i18n-firewall-zh-cn",
    "luci-i18n-package-manager-zh-cn", "luci-i18n-sqm-zh-cn",
    "luci-i18n-bcp38-zh-cn", "luci-i18n-filemanager-zh-cn",
    "luci-i18n-ttyd-zh-cn", "luci-i18n-nlbwmon-zh-cn",
    "luci-i18n-wifihistory-zh-cn",
    "luci-i18n-irqbalance-zh-cn", "luci-i18n-lldpd-zh-cn",
    "luci-i18n-pbr-zh-cn",
    "tailscale", "luci-app-tailscale-community",
    "luci-i18n-tailscale-community-zh-cn", "kmod-tun",
    "sing-box", "flock", "kmod-inet-diag", "luci-app-sing-box",
    "luci-app-autoreboot", "luci-i18n-autoreboot-zh-cn",
    "luci-app-cpufreq", "luci-i18n-cpufreq-zh-cn", "cpufreq",
    "default-settings-chn", "autocore",
    "luci-app-ddns-go", "luci-i18n-ddns-go-zh-cn",
    "luci-app-wol", "etherwake", "luci-i18n-wol-zh-cn",
}
assert required <= set(added), sorted(required - set(added))
assert not set(added) & set(removed)
assert len(added) == len(set(added))
excluded_luci = {
    "luci-app-diskman", "luci-i18n-diskman-zh-cn",
    "luci-app-statistics", "luci-i18n-statistics-zh-cn",
}
assert excluded_luci <= set(removed), sorted(excluded_luci - set(removed))
assert not excluded_luci & set(added)
assert "luci-app-sing-box" in added
assert "luci-app-homeproxy" not in added
assert {"luci-app-homeproxy", "luci-i18n-homeproxy-zh-cn"} <= set(removed)

build = (root / "scripts/build-immortalwrt.sh").read_text()
config = (root / "config/immortalwrt-re-ss-01.config").read_text()
assert 'scripts/prepare-sing-box-luci.sh" "$IMM/package/luci-app-sing-box"' in build
assert "for excluded in luci-app-homeproxy" in build
assert "for excluded in luci-app-homeproxy" in (root / "scripts/repack-immortalwrt.sh").read_text()
assert "luci-app-ddns-go" in build
assert "luci-theme-aurora.git v1.4.0" in build
for name in ("luci-app-sing-box", "luci-theme-aurora",
             "kmod-nss-wifi-drv", "kmod-wireguard"):
    assert f"CONFIG_PACKAGE_{name}=y" in config
assert 'append_packages "$ROOT/config/add.txt" y' in build
assert "scripts/immortalwrt_ota.py" in build
assert "scripts/apply-immortalwrt-compat.sh" in build

assert "CONFIG_PACKAGE_luci-app-homeproxy=y" not in config
hook = root / "files/etc/uci-defaults/95-sing-box-tun-user"
assert hook.is_file()
subprocess.run(["sh", "-n", str(hook)], check=True)
assert "sing-box.main.user=\'root\'" in hook.read_text()
helper = root / "scripts/prepare-sing-box-luci.sh"
assert helper.is_file()
subprocess.run(["bash", "-n", str(helper)], check=True)
assert "fde997eb88c5d8d9b6dbc138b36e8a298402b03c" in helper.read_text()
assert 'src-link sing_box $WORK/git/sing_box' in (root / "scripts/rebuild-missing-apks.sh").read_text()
# default-settings-chn changes the APK mirror by default; keep this
# ABI-matched NSS firmware on its original ImmortalWrt distfeeds.
feed_hook = root / "files/etc/uci-defaults/98-keep-immortalwrt-apk-feed"
assert feed_hook.is_file()
subprocess.run(["sh", "-n", str(feed_hook)], check=True)
assert "https://downloads.immortalwrt.org" in feed_hook.read_text()
assert "system.@imm_init[0].apk_mirror" in feed_hook.read_text()
for private in ("files/etc/sing-box/config.json", "config.json"):
    assert not (root / private).exists(), private

readme = (root / "README.md").read_text()
for item in ("VPN → Tailscale", "服务 → sing-box", "服务 → 网络唤醒", "docs/SINGBOX.md"):
    assert item in readme
assert "Tailscale" in (root / "docs/SINGBOX.md").read_text()
assert "sing-box" in (root / "docs/TAILSCALE-WOL.md").read_text()
subprocess.run(["bash", "-n", str(root / "scripts/build-immortalwrt.sh")], check=True)
subprocess.run(["bash", "-n", str(root / "scripts/repack-immortalwrt.sh")], check=True)
print("PASS complete ImmortalWrt plugin matrix, LuCI and storage packages")
