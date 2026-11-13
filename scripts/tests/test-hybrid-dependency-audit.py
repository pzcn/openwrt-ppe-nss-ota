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
