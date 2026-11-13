#!/usr/bin/env python3
"""Offline synthetic dependency-audit checks (no network/SDK/kernel build)."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "dep_audit", ROOT / "scripts/hybrid-dependency-audit.py")
audit = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(audit)


def adb(*packages):
    lines = ["#%SCHEMA: 78646E69",
             "# ADB block, size: 200, compat: 0, ver: 0",
             f"packages: # {len(packages)} items"]
    for name, version, deps, provides in packages:
        lines.extend((f"  - name: {name}", f"    version: {version}",
                      "    arch: aarch64_cortex-a53"))
        if deps:
            lines.append(f"    depends: # {len(deps)} items")
            lines.extend("      - " + dep for dep in deps)
        if provides:
            lines.append(f"    provides: # {len(provides)} items")
            lines.extend("      - " + provided for provided in provides)
    return "\n".join(lines)


base = audit.parse_adbdump(adb(
    ("alpha", "1.0-r1", ["libc", "libhelper>=2.0", "so:libx.so.1", "kmod-wireguard"], []),
    ("libhelper", "2.1-r1", ["libc"], []),
    ("runtime", "1.1-r1", ["libc"], ["so:libx.so.1"]),
), "base")
assert [p["name"] for p in base] == ["alpha", "libhelper", "runtime"]
assert base[0]["depends"][1] == "libhelper>=2.0"
assert audit.dependency_base("libhelper>=2.0") == "libhelper"
assert audit.dependency_base("so:libx.so.1") == "so:libx.so.1"
assert audit.dependency_base("!conflicting") == ""
assert audit.dependency_base("kernel=6.18.55-1-abcdef") == "kernel"

inventory = {
    "schema": 1,
    "status": "P3-inventory-only-not-build-approved",
    "inventory_fingerprint": "a" * 64,
    "snapshot_lock_fingerprint": "b" * 64,
    "packages": [
        {"name": "alpha", "status": "official-candidate",
         "source": "arch", "feed": "base", "filename": "alpha-1.0-r1.apk"},
        {"name": "kmod-wireguard", "status": "local-kernel"},
        {"name": "luci-app-sing-box", "status": "local-custom"},
    ],
}
indexes = {"target": []}
for f in audit.KNOWN_FEEDS[1:]:
    indexes[f] = base if f == "base" else []
first = audit.review(inventory, indexes)
assert not first["publishable"] and not first["dependency_closure_verified"]
assert first == audit.review(inventory, indexes), "Audit must be deterministic"
assert first["candidate_closure_size"] == 3
# Join the verified binary-index result to the exact official checksum map.
archive_sums = {"target": {}, "arch": {
    "base/alpha-1.0-r1.apk": "1" * 64,
    "base/libhelper-2.1-r1.apk": "2" * 64,
    "base/runtime-1.1-r1.apk": "3" * 64,
}}
origin_lock = {
    "lock_fingerprint": "b" * 64,
    "target_url": "https://downloads.immortalwrt.org/snapshots/targets/qualcommax/ipq60xx",
    "architecture_url": "https://downloads.immortalwrt.org/snapshots/packages/aarch64_cortex-a53",
}
pinned = audit.review(inventory, indexes, locked_sums=archive_sums, lock=origin_lock)
assert pinned["mirror_plan_content_pinned"]
assert len(pinned["mirror_plan"]) == 3
assert pinned["mirror_plan"][0]["name"] == "alpha"
assert pinned["mirror_plan"][0]["sha256"] == "1" * 64
assert not pinned["publishable"]  # SHA checks do not prove ABI or signature trust.

# A target package is indexed under the special "target" feed but its
# official checksum URL/path must be "packages/<filename>.apk".
extra_indexes = dict(indexes)
extra_indexes["target"] = audit.parse_adbdump(adb(
    ("targettool", "1.0-r1", [], [])), "target")
target_inventory = json.loads(json.dumps(inventory))
target_inventory["packages"].append({
    "name": "targettool", "status": "official-candidate",
    "source": "target", "feed": "packages",
    "filename": "targettool-1.0-r1.apk",
})
with_target = audit.review(
    target_inventory, extra_indexes,
    locked_sums={"target": {"packages/targettool-1.0-r1.apk": "4" * 64},
                 "arch": archive_sums["arch"]},
    lock=origin_lock)
target_assets = [x for x in with_target["mirror_plan"]
                 if x["name"] == "targettool"]
assert len(target_assets) == 1
assert target_assets[0]["feed"] == "packages"
assert target_assets[0]["path"] == "packages/targettool-1.0-r1.apk"
assert target_assets[0]["source"] == "target"
assert with_target["mirror_plan_content_pinned"]
missing_archive = {"target": {}, "arch": {"base/alpha-1.0-r1.apk": "1" * 64}}
incomplete = audit.review(inventory, indexes, locked_sums=missing_archive, lock=origin_lock)
assert not incomplete["mirror_plan_content_pinned"]
assert set(incomplete["mirror_plan_missing_archives"]) == {
    "base/libhelper-2.1-r1.apk", "base/runtime-1.1-r1.apk",
}
try:
    audit.review(inventory, indexes, locked_sums=archive_sums,
                 lock={**origin_lock, "lock_fingerprint": "9" * 64})
except ValueError as error:
    assert "same revision" in str(error)
else:
    raise AssertionError("Accepted an unrelated Snapshot's checksum map")
assert first["unresolved"] == []
assert first["ambiguous"] == []
assert "libc" in first["requires_local_provision"]
assert "kmod-wireguard" in first["requires_local_provision"]
assert "libhelper>=2.0" in first["version_constraints_for_apk_solver"]
assert "so:libx.so.1" in first["virtual_provides_for_apk_solver"]

wrong = json.loads(json.dumps(inventory))
wrong["packages"][0]["filename"] = "alpha-0.5.apk"
assert any("index-filename-mismatch" in x for x in
           audit.review(wrong, indexes)["root_blockers"])

broken = dict(indexes)
broken["base"] = audit.parse_adbdump(adb(
    ("alpha", "1.0-r1", ["unavailable-lib"], [])), "base")
assert "unavailable-lib" in audit.review(inventory, broken)["unresolved"]

dup = dict(indexes)
dup["luci"] = audit.parse_adbdump(adb(
    ("libhelper", "2.1-r1", ["libc"], [])), "luci")
assert "libhelper" in audit.review(inventory, dup)["ambiguous"]

for bad_text in ("", "not an adb index", "#%SCHEMA: 78646E69\npackages: # 0 items"):
    try:
        audit.parse_adbdump(bad_text, "base")
    except ValueError:
        pass
    else:
        raise AssertionError("Accepted invalid binary APK index dump")

try:
    audit.parse_adbdump(adb(("wrong", "1.0", [], [])), "unexpected-feed")
except ValueError:
    pass
else:
    raise AssertionError("Accepted arbitrary feed name")

print("PASS P3 binary APK dependency audit, local ABI boundary and ambiguous-provider gates")
