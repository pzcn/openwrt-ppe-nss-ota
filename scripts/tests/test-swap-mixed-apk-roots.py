#!/usr/bin/env python3
"""Regression: donor kernel ownership and official base userland version pins."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sp = importlib.util.spec_from_file_location(
    "swap_apk_roots", ROOT / "scripts/plan-swap-mixed-apk-roots.py")
mod = importlib.util.module_from_spec(sp)
assert sp.loader
sp.loader.exec_module(mod)


def mk(name, version, feed):
    return {"name": name, "version": version, "arch": "aarch64_cortex-a53",
            "feed": feed, "depends": [], "provides": []}


donor = [mk(x, "6.18.60-r1", "target") for x in mod.DONOR_ROOTS]
official = {feed: [] for feed in mod.FEEDS}
official["target"].append(mk("base-files", "1955~official-r1", "target"))
official["base"].extend(
    mk(x, "1.1-r1", "base") for x in mod.OFFICIAL_ROOTS
    if x != "base-files"
)
result = mod.plan(donor, official)
assert not result["blockers"]
assert result["donor_kernel_root_count"] == 4
assert result["official_userspace_root_count"] == len(mod.OFFICIAL_ROOTS)
assert result["root_count"] == len(mod.DONOR_ROOTS) + len(mod.OFFICIAL_ROOTS)
assert "base-files=1955~official-r1" in result["version_pins"]
assert "kmod-fs-f2fs=6.18.60-r1" in result["version_pins"]
assert not result["publishable"]
assert not result["kernel_abi_verified"]

official["base"].append(mk("procd", "2.0-r1", "base"))
bad = mod.plan(donor, official)
assert "procd:multiple-versions" in bad["blockers"]
assert not any(x["name"] == "procd" for x in bad["roots"])
assert not mod.plan(donor[1:], official)["publishable"]
assert "missing-julius-kernel-root" in mod.plan(donor[1:], official)["blockers"]
donor.append(mk("firewall4", "2026.10.29~julius-r1", "target"))
alternative = mod.plan(donor, official, donor_exceptions=("firewall4",))
assert "firewall4=2026.10.29~julius-r1" in alternative["version_pins"]
assert "firewall4=1.1-r1" not in alternative["version_pins"]
assert alternative["donor_userspace_exceptions"] == ["firewall4"]
assert alternative["official_userspace_root_count"] == len(mod.OFFICIAL_ROOTS) - 1
assert len([x for x in alternative["roots"]
            if x["origin"] == "julius-userspace-exception"]) == 1
assert not alternative["publishable"]
try:
    mod.plan(donor, official, donor_exceptions=("base-files",))
except ValueError:
    pass
else:
    raise AssertionError("Accepted an unreviewed donor base-files substitution")

print("PASS mixed APK version pins, official userspace ownership and fail-closed ambiguity")
