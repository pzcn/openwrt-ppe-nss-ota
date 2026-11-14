#!/usr/bin/env python3
"""Check installed package version matches and kernel-only module tree."""
import importlib.util
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sp = importlib.util.spec_from_file_location(
    "swap_root_audit", ROOT / "scripts/audit-swap-extracted-root.py")
mod = importlib.util.module_from_spec(sp)
assert sp.loader
sp.loader.exec_module(mod)

with tempfile.TemporaryDirectory() as name:
    r = Path(name)
    db = r / "lib/apk/db/installed"
    db.parent.mkdir(parents=True)
    installed = [(f"core{x}", "1-r1") for x in range(20)] + [
        ("kernel", "6.18.60~hash-r1"), ("kmod-fs-f2fs", "6.18.60-r1"),
        ("kmod-nss-wifi-drv", "6.18.60-r1"), ("kmod-wireguard", "6.18.60-r1"),
    ]
    db.write_text("".join(f"P:{k}\nV:{v}\n\n" for k, v in installed))
    for name in ("fs/f2fs/f2fs.ko", "net/nss/nss_wifi_drv.ko",
                 "drivers/net/wireguard.ko"):
        f = r / "lib/modules/6.18.60" / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"not an executable test fixture")
    boot = r / "etc/modules-boot.d/f2fs"
    boot.parent.mkdir(parents=True, exist_ok=True)
    boot.write_text("f2fs\n")
    plan = {"roots": [{"name": k, "version": v} for k, v in installed]}
    result = mod.inspect(r, plan)
    assert result["exact_plan_pins_verified"]
    assert result["module_tree_structure_verified"]
    assert result["f2fs_boot_autoload_files"]
    assert not result["runtime_abi_verified"]
    assert not result["publishable"]
    plan["roots"][0]["version"] = "2-r1"
    wrong = mod.inspect(r, plan)
    assert not wrong["exact_plan_pins_verified"]
    assert wrong["mismatched_plan_versions"][0]["name"] == "core0"
    plan["roots"][0]["version"] = "1-r1"
    (r / "lib/modules/6.18.55").mkdir()
    wrong_abi = mod.inspect(r, plan)
    assert not wrong_abi["module_tree_structure_verified"]
print("PASS exact installed package pins and F2FS/NSS/WG module tree gate")
