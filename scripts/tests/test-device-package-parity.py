#!/usr/bin/env python3
"""Enforce one feature/package policy across Arthur and MX4200 v1.

Differences MUST be explicitly justified by hardware. The two build systems
can use separate target-specific ImageBuilders, but should not drift in apps.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Arthur's eMMC/extroot and F2FS support do not belong in MX NAND rootfs.
ARTHUR_STORAGE_ONLY = {
    "block-mount",
    "kmod-fs-ext4",
    "e2fsprogs",
    "kmod-fs-f2fs",
    "f2fs-tools",
}


def package_set(path: str) -> set[str]:
    result: set[str] = set()
    for line in (ROOT / path).read_text().splitlines():
        name = line.split("#", 1)[0].strip()
        if not name:
            continue
        if " " in name or "\t" in name:
            raise AssertionError(f"Expected one package per line: {path}: {name}")
        if name in result:
            raise AssertionError(f"Duplicate package {name} in {path}")
        result.add(name)
    return result


arthur = package_set("config/add.txt")
mx4200 = package_set("mx4200v1/packages.txt")
arthur_remove = package_set("config/remove.txt")
mx4200_remove = package_set("mx4200v1/remove.txt")

assert ARTHUR_STORAGE_ONLY <= arthur
assert not (ARTHUR_STORAGE_ONLY & mx4200)
shared = arthur - ARTHUR_STORAGE_ONLY
if shared != mx4200:
    raise AssertionError(
        "Device feature parity drift; update shared lists or document a "
        "genuine hardware-only exception. "
        f"MX missing: {sorted(shared - mx4200)}; "
        f"MX only: {sorted(mx4200 - shared)}"
    )
if arthur_remove != mx4200_remove:
    raise AssertionError(
        f"Exclusion drift: Arthur-only={arthur_remove - mx4200_remove}, "
        f"MX-only={mx4200_remove - arthur_remove}"
    )

for required in [
    "luci-app-sing-box", "sing-box", "flock", "kmod-inet-diag",
    "luci-app-wifihistory", "luci-app-cpufreq", "luci-app-tailscale-community",
    "luci-app-wol", "luci-app-ddns-go", "luci-app-pbr",
    "luci-proto-wireguard", "jq", "curl", "uclient-fetch", "jsonfilter",
]:
    assert required in shared, f"Required shared package disappeared: {required}"

assert "luci-app-homeproxy" in arthur_remove
assert "luci-app-diskman" in arthur_remove
assert "luci-app-statistics" in arthur_remove

print(
    "PASS both devices share "
    f"{len(shared)} userland packages and "
    f"{len(arthur_remove)} exclusions; "
    f"Arthur-specific storage packages: {len(ARTHUR_STORAGE_ONLY)}"
)
