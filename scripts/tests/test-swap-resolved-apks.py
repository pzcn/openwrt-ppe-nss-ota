#!/usr/bin/env python3
"""Synthetic native APK simulation log provenance regression."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "swap_native_provenance", ROOT / "scripts/audit-swap-resolved-apks.py")
mod = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(mod)


def pkg(name, version, feed):
    return {"name": name, "version": version, "feed": feed, "arch": "aarch64_cortex-a53"}


donor = [pkg("kernel", "6.18.60-r1", "target"),
         pkg("kmod-fs-f2fs", "6.18.60-r1", "target"),
         pkg("firewall4", "2-r1", "target")]
official = {
    "target": [pkg("base-files", "official-r1", "target")],
    "base": [pkg("libc", "1.2.6-r5", "base")],
}
roots = [{"name": "kernel", "version": "6.18.60-r1", "origin": "julius-kernel"},
         {"name": "kmod-fs-f2fs", "version": "6.18.60-r1", "origin": "julius-kernel"},
         {"name": "firewall4", "version": "2-r1", "origin": "julius-userspace-exception"},
         {"name": "libc", "version": "1.2.6-r5", "origin": "immortalwrt-userspace"}]
log = """( 1/4) Installing libc (1.2.6-r5)
( 2/4) Installing kernel (6.18.60-r1)
( 3/4) Installing kmod-fs-f2fs (6.18.60-r1)
( 4/4) Installing firewall4 (2-r1)
OK: 500 KiB in 4 packages
"""
result = mod.audit_solver(log, donor, official, roots)
assert result["selected_package_count"] == 4
assert result["donor_only_count"] == 3
assert result["official_only_count"] == 1
assert result["selected_kernel_module_count"] == 2
assert result["all_kernel_modules_candidate_from_donor"]
assert not result["blockers"]
assert not result["publishable"]
assert not result["file_conflicts_checked"]

def rejects(source: str, reason: str):
    try:
        mod.audit_solver(source, donor, official, roots)
    except ValueError as err:
        assert reason in str(err)
    else:
        raise AssertionError("Accepted invalid solver log")

rejects(log.replace("( 4/4) Installing firewall4 (2-r1)\n", ""), "incomplete")
rejects(log.replace("OK: 500 KiB in 4 packages", "ERROR: unresolved"), "successfully")
assert mod.audit_solver(log.replace("6.18.60-r1", "6.18.59-r1"),
                        donor, official, roots)["blockers"]
print("PASS native APK simulation provenance, pinned roots and kernel ownership checks")
