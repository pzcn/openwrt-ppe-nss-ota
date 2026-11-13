#!/usr/bin/env python3
"""Offline tests for Hybrid's locally compiled kernel, ABI and patched packages."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "localplan", ROOT / "scripts/plan-hybrid-local-apks.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

lock = {"schema": 2, "lock_fingerprint": "a" * 64,
        "kernel_fingerprint": "b" * 64}
inventory = {
    "status": "P3-inventory-only-not-build-approved",
    "snapshot_lock_fingerprint": lock["lock_fingerprint"],
    "packages": [
        {"name": "kmod-tun", "status": "local-kernel"},
        {"name": "luci-app-sing-box", "status": "local-custom"},
        {"name": "etherwake", "status": "official-candidate"},
    ],
}
audit = {
    "status": "P3-dependency-audit-not-build-approved",
    "snapshot_lock_fingerprint": lock["lock_fingerprint"],
    "requires_local_provision": [
        "kmod-nft-core", "kmod-wireguard", "libc", "sqm-scripts",
    ],
    "unresolved": [],
    "root_blockers": [],
}
kernel_mods = ("kmod-nss-wifi-drv", "kmod-fs-f2fs",
               "kmod-nft-core", "kmod-wireguard", "kmod-tun")
config = "\n".join("CONFIG_PACKAGE_" + p + "=y" for p in kernel_mods) + "\n"
plan = mod.plan(lock, inventory, audit, config)
assert plan["counts"]["kernel_modules"] == len(kernel_mods)
assert plan["counts"]["custom_userspace"] >= 3
assert plan["counts"]["base_abi"] >= 2
assert not plan["publishable"]
assert not plan["local_kernel_abi_verified"]
assert plan == mod.plan(lock, inventory, audit, config)

names = {x["name"] for x in plan["local_packages"]}
assert {"base-files", "libc", "libgcc", "sqm-scripts", "luci-app-sing-box"} <= names
assert all(x["owner"] == "local-kernel" for x in plan["local_packages"]
           if x["name"].startswith("kmod-"))
partial = mod.plan(lock, inventory, audit, config, compiled_names={"libc", "libgcc"})
assert "kmod-wireguard" in partial["not_yet_compiled"]
assert "libc" not in partial["not_yet_compiled"]
assert partial["compiled_apk_inventory_supplied"]

try:
    mod.plan(lock, inventory, audit, config.replace("CONFIG_PACKAGE_kmod-wireguard=y", ""))
except ValueError as e:
    assert "kmod-wireguard" in str(e)
else:
    raise AssertionError("Undeclared transitive local kmod accepted")
changed = json.loads(json.dumps(audit))
changed["snapshot_lock_fingerprint"] = "b" * 64
try:
    mod.plan(lock, inventory, changed, config)
except ValueError as e:
    assert "Snapshot" in str(e)
else:
    raise AssertionError("Mixed Snapshot fingerprints accepted")

print("PASS Hybrid local kmod, base ABI and patched userspace build-plan gates")
