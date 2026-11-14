#!/usr/bin/env python3
"""Synthetic tests for original-stock boot-path drift and .ko vermagic audit."""
import importlib.util
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "swap_runtime_readiness", ROOT / "scripts/audit-swap-runtime-readiness.py")
mod = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(mod)

with tempfile.TemporaryDirectory() as tmp:
    base = Path(tmp)
    original, mixed = base / "official", base / "mixed"
    for directory in (original, mixed):
        (directory / "etc/init.d").mkdir(parents=True)
        (directory / "etc/init.d/network").write_bytes(b"#!/bin/sh\n")
        (directory / "etc/preinit").write_bytes(b"init\n")
        (directory / "sbin").mkdir()
        (directory / "sbin/init").symlink_to("../bin/busybox")
        (directory / "bin").mkdir()
        (directory / "bin/busybox").write_bytes(b"busybox")
        (directory / "bin/sh").symlink_to("busybox")
    compare = mod.compare_roots(original, mixed)
    assert compare["unchanged_stock_boot_files"]
    assert compare["missing_boot_path_count"] == 0
    (mixed / "etc/init.d/network").write_bytes(b"changed\n")
    (mixed / "etc/preinit").unlink()
    compare = mod.compare_roots(original, mixed)
    assert "etc/preinit" in compare["missing_original_boot_paths"]
    assert "etc/init.d/network" in compare["different_original_boot_paths"]
    assert not compare["unchanged_stock_boot_files"]

    kdir = mixed / "lib/modules/6.18.60"
    kdir.mkdir(parents=True)
    (kdir / "modules.dep").write_text("f2fs.ko:\n")
    (kdir / "modules.alias").write_text("# aliases\n")
    for name in ("f2fs.ko", "wireguard.ko", "nss-wifi-drv.ko"):
        (kdir / name).write_bytes(
            b"\x7fELF" + b"\x00vermagic=6.18.60 SMP mod_unload aarch64\x00")
    report = mod.scan_vermagic(mixed)
    assert report["matching_module_version_strings"]
    assert report["f2fs_module_present"]
    assert report["wireguard_module_present"]
    assert report["nss_wifi_module_present"]
    assert report["modules_dep_file_present"]

    (kdir / "wireguard.ko").write_bytes(b"\x00vermagic=6.18.55 SMP\x00")
    report = mod.scan_vermagic(mixed)
    assert not report["matching_module_version_strings"]
    assert report["modules_wrong_vermagic"][0]["path"].endswith("wireguard.ko")
    (kdir / "wireguard.ko").write_bytes(b"no-module-metadata")
    report = mod.scan_vermagic(mixed)
    assert not report["matching_module_version_strings"]
    assert report["modules_missing_vermagic"][0].endswith("wireguard.ko")

print("PASS stock boot-file drift and module vermagic inspection")
