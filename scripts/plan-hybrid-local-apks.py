#!/usr/bin/env python3
"""P3: identify all ABI-owned or custom packages missing from official APK mirror.

This step makes the local part of Hybrid compilation explicit and testable;
it never pretends those APKs exist or gives approval to publish firmware.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

PKG = re.compile(r"^[a-z0-9][a-z0-9+._-]*$")
MANDATORY = frozenset(("kmod-nss-wifi-drv", "kmod-fs-f2fs",
                       "base-files", "libc", "libgcc",
                       "qca-ppe-qos", "ppe-help", "sqm-scripts",
                       "luci-app-qca-ppe-qos", "luci-theme-aurora"))
KERNEL_ABI = frozenset(("base-files", "libc", "libgcc", "libstdcpp", "kernel"))


def parse_config(data: str) -> set[str]:
    return {line[len("CONFIG_PACKAGE_"):-2]
            for line in data.splitlines()
            if line.startswith("CONFIG_PACKAGE_") and line.endswith("=y")}


def classify(name: str) -> str:
    if name.startswith("kmod-") or name == "kernel":
        return "local-kernel"
    if name in KERNEL_ABI:
        return "local-base-abi"
    return "local-custom"


def plan(lock: dict, inventory: dict, audit: dict, config_text: str,
         *, compiled_names: set[str] | None = None) -> dict:
    if lock.get("schema") != 2:
        raise ValueError("Expected exact official Snapshot lock schema 2")
    fp = lock.get("lock_fingerprint")
    if (audit.get("snapshot_lock_fingerprint") != fp or
            inventory.get("snapshot_lock_fingerprint") != fp):
        raise ValueError("Snapshot, package inventory and audit disagree")
    if (inventory.get("status") != "P3-inventory-only-not-build-approved" or
            audit.get("status") != "P3-dependency-audit-not-build-approved"):
        raise ValueError("Wrong P3 inventory or audit status")
    if audit.get("unresolved") or audit.get("root_blockers"):
        raise ValueError("Official dependency audit still has unresolved packages")
    requested = {x["name"] for x in inventory["packages"]
                 if x["status"] in ("local-kernel", "local-custom", "abi-review")}
    transitive = set(audit.get("requires_local_provision", []))
    required = sorted(MANDATORY | requested | transitive)
    if any(not PKG.fullmatch(name) for name in required):
        raise ValueError("Invalid locally required APK package name")
    configured = parse_config(config_text)
    rows = []
    missing_kconfig = []
    uncompiled = []
    for name in required:
        kind = classify(name)
        if kind == "local-kernel" and name not in configured:
            missing_kconfig.append(name)
        if compiled_names is not None and name not in compiled_names:
            uncompiled.append(name)
        rows.append({
            "name": name,
            "owner": kind,
            "why": sorted(set(
                (["direct-package-request"] if name in requested else []) +
                (["transitive-official-dependency"] if name in transitive else []) +
                (["hybrid-mandatory"] if name in MANDATORY else [])
            )),
            "kernel_config_selected": name in configured if kind == "local-kernel" else None,
        })
    if missing_kconfig:
        raise ValueError("Hybrid kernel config omits locally required modules: " +
                         ", ".join(missing_kconfig))
    result = {
        "schema": 1,
        "status": "P3-local-compilation-plan-not-build-approved",
        "snapshot_lock_fingerprint": fp,
        "kernel_fingerprint": lock.get("kernel_fingerprint"),
        "local_packages": rows,
        "counts": {
            "kernel_modules": sum(x["owner"] == "local-kernel" for x in rows),
            "base_abi": sum(x["owner"] == "local-base-abi" for x in rows),
            "custom_userspace": sum(x["owner"] == "local-custom" for x in rows),
        },
        "kernel_kconfig_checked": True,
        "compiled_apk_inventory_supplied": compiled_names is not None,
        "not_yet_compiled": sorted(uncompiled) if compiled_names is not None else required,
        "local_kernel_abi_verified": False,
        "publishable": False,
    }
    result["plan_sha256"] = hashlib.sha256(json.dumps(
        result, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return result


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--lock", type=Path, required=True)
    p.add_argument("--inventory", type=Path, required=True)
    p.add_argument("--audit", type=Path, required=True)
    p.add_argument("--kernel-config", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--compiled-package-names", type=Path)
    args = p.parse_args()
    compiled_names = None
    if args.compiled_package_names:
        compiled_names = set(args.compiled_package_names.read_text().split())
        if any(not PKG.fullmatch(x) for x in compiled_names):
            raise ValueError("Invalid name in locally compiled APK inventory")
    result = plan(json.loads(args.lock.read_text()),
                  json.loads(args.inventory.read_text()),
                  json.loads(args.audit.read_text()),
                  args.kernel_config.read_text(), compiled_names=compiled_names)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("Hybrid local packages required: " + str(len(result["local_packages"])))
    for kind, number in result["counts"].items():
        print(f"  {kind}: {number}")
    print("Local output not compiled/ABI-verified, no Builder or OTA published.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, TypeError) as e:
        print(f"Hybrid local package plan failed: {e}", file=sys.stderr)
        sys.exit(1)
