#!/usr/bin/env python3
"""Check parity of portable Arthur packages and WMA301 hardware exclusions."""
from pathlib import Path
from official_builder import read_packages

ROOT = Path(__file__).resolve().parents[1]
names = read_packages(ROOT / "configs/official-packages.txt")
selected = set(p for p in names if not p.startswith("-"))
removed = set(p[1:] for p in names if p.startswith("-"))
required = {
    "luci", "luci-theme-bootstrap", "luci-i18n-base-zh-cn", "autocore", "luci-i18n-firewall-zh-cn",
    "luci-app-filemanager", "luci-app-ttyd", "luci-app-nlbwmon",
    "luci-app-wifihistory", "luci-app-irqbalance", "luci-app-lldpd",
    "luci-app-pbr", "luci-app-autoreboot", "luci-proto-wireguard",
    "wireguard-tools", "luci-app-wol", "etherwake",
    "cpufreq", "luci-app-cpufreq", "luci-i18n-cpufreq-zh-cn",
    "default-settings-chn",
}
assert required <= selected, sorted(required - selected)
assert {"luci-app-homeproxy", "luci-app-diskman", "luci-app-statistics"} <= removed
optional_disabled = {
    "tailscale", "luci-app-tailscale-community",
    "luci-i18n-tailscale-community-zh-cn", "kmod-tun",
    "luci-app-ddns-go", "luci-i18n-ddns-go-zh-cn",
}
assert optional_disabled <= removed, sorted(optional_disabled - removed)
assert not selected & removed
for banned in ("sing-box", "luci-app-sing-box", "flock", "kmod-inet-diag"):
    assert banned not in selected, f"unexpected proxy component: {banned}"
assert not any("nss" in p or "qca-ppe" in p or "f2fs" in p for p in selected)
script = ROOT / "files/etc/uci-defaults/95-luci-preferences"
assert script.is_file()
assert script.stat().st_mode & 0o111, "LuCI preference script lacks executable mode"
assert "luci-theme-aurora" in selected, "Pinned Aurora must be installed by APK"
print(f"Arthur common software: {len(selected)} selected; "
      f"{len(removed)} excluded; Tailscale/DDNS-Go disabled; no sing-box; MT7981 checks PASS")
