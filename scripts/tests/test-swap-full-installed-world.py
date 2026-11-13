#!/usr/bin/env python3
"""Synthetic full stock world, donor-kmod gap, exact userspace selection."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sp = importlib.util.spec_from_file_location(
    "full_world_swap", ROOT / "scripts/plan-swap-full-installed-world.py")
mod = importlib.util.module_from_spec(sp)
assert sp.loader
sp.loader.exec_module(mod)


def p(name, v="1-r1", feed="base"):
    return {"name": name, "version": v, "arch": "aarch64_cortex-a53",
            "feed": feed, "depends": []}


users = [p("pkg" + str(x)) for x in range(20)]
installed = users + [
    p("kernel", "6.18.55-r1"), p("kmod-nft-fullcone", "6.18.55-r1"),
    p("kmod-fs-f2fs", "6.18.55-r1"), p("firewall4", "2025-old-r1"),
]
donor = [
    p("kernel", "6.18.60~julius-r1", "target"),
    p("kmod-fs-f2fs", "6.18.60-r1", "target"),
    p("kmod-wireguard", "6.18.60-r1", "target"),
    p("kmod-nss-wifi-drv", "6.18.60-r1", "target"),
    p("firewall4", "2026-julius-r1", "target"),
]
official = {feed: [] for feed in mod.stock.FEEDS}
official["base"].extend(users)
official["base"].append(p("firewall4", "2025-old-r1"))
world = "\n".join(x["name"] for x in installed)
result = mod.plan(installed, world, donor, official)
assert result["stock_installed_count"] == 24
assert result["exact_official_userland_pinned_count"] == 20
assert result["julius_kernel_kmod_pinned_count"] == 4
assert result["julius_firewall4_exception_count"] == 1
assert result["missing_stock_kernel_or_kmods"] == ["kmod-nft-fullcone"]
assert "kernel=6.18.60~julius-r1" in result["version_pins"]
assert "firewall4=2026-julius-r1" in result["version_pins"]
assert not any(pin.startswith("kmod-nft-fullcone=")
               for pin in result["version_pins"])
assert not result["complete_stock_kernel_kmod_coverage"]
assert not result["full_world_solver_passed"]
assert not result["publishable"]
print("PASS full stock world reports missing donor kmods and pins 20 exact official userland packages")
