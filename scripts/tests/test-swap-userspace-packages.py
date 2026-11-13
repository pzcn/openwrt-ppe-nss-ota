#!/usr/bin/env python3
"""Core APK version drift checker: controlled synthetic feed/index records."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "core_apk_compare", ROOT / "scripts/compare-swap-userspace-packages.py")
mod = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(mod)

donor = [
    "openwrt-imagebuilder/packages/base-files-2026.11-r1.apk",
    "openwrt-imagebuilder/packages/libc-1.2.6-r1.apk",
    "openwrt-imagebuilder/packages/busybox-1.36-r1.apk",
    "openwrt-imagebuilder/packages/kmod-fs-f2fs-6.18.60-r1.apk",
]
official = [
    "packages/base-files-2026.10-r1.apk",
    "base/libc-1.2.6-r1.apk",
    "base/busybox-1.37-r1.apk",
]
report = mod.inspect(donor, official)
rows = {p["name"]: p for p in report["packages"]}
assert rows["base-files"]["status"] == "different-or-multiple-versions"
assert rows["libc"]["status"] == "same-filename-version"
assert rows["busybox"]["status"] == "different-or-multiple-versions"
assert rows["procd"]["status"] == "missing-one-or-both"
assert not report["publishable"]
assert report["matching_versions"] == 1
assert report["different_versions"] == 2
assert mod.parse_checksums("a" * 64 + " *base/libc-1.2.6-r1.apk\n") == [
    "base/libc-1.2.6-r1.apk"
]
try:
    mod.parse_checksums("f" * 64 + " *../libc.apk\n")
except ValueError:
    pass
else:
    raise AssertionError("Accepted traversal in package sha256sums")

print("PASS userland APK version-drift inspection without false ABI approval")
