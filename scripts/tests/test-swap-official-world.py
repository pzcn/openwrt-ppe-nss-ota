#!/usr/bin/env python3
"""Stock ImageBuilder installed world parser and version-rotated repo tests."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "swap_stock_world", ROOT / "scripts/audit-swap-official-world.py")
mod = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(mod)

raw = "".join(f"P:pkg{i}\nV:1-r1\nA:aarch64_cortex-a53\n\n" for i in range(22))
installed = mod.parse_installed_plaintext(raw)
assert len(installed) == 22
idx = {feed: [] for feed in mod.FEEDS}
idx["base"].extend(
    {"name": f"pkg{i}", "version": "1-r1", "arch": "aarch64_cortex-a53"}
    for i in range(16)
)
idx["base"].extend(
    {"name": f"pkg{i}", "version": "2-r1", "arch": "aarch64_cortex-a53"}
    for i in range(16, 20)
)
report = mod.audit_world(installed, idx, "pkg0\npkg1\nkernel\n")
assert report["installed_userland_count"] == 22
assert report["world_root_count"] == 3
assert report["counts"]["exact-official-snapshot-archive"] == 16
assert report["counts"]["official-name-version-rotated"] == 4
assert report["counts"]["absent-from-current-official-index"] == 2
assert not report["exact_full_official_userspace_rebuild_possible_from_current_indexes"]
assert not report["publishable"]

for text in (raw + "P:pkg0\nV:1-r1\n\n", "P:missing\nV:1-r1\n\n", raw.replace("P:pkg0", "P:../evil")):
    try:
        mod.parse_installed_plaintext(text)
    except ValueError:
        pass
    else:
        raise AssertionError("Accepted malformed stock installed database")

print("PASS stock installed world audit, rotated versions, missing APKs, unsafe data")
