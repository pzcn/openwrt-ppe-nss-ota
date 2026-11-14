#!/usr/bin/env python3
"""MX4200 Builder resolver must use exact inputs, valid artifacts and safe fallback."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "mx4200_resolver", ROOT / "scripts/resolve-mx4200-builder.py")
resolver = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(resolver)

assert set(resolver.COMPATIBILITY_INPUTS) == {
    "mx4200v1/source.config", "mx4200v1/port-ppe-nss.sh",
    "mx4200v1/packages.txt", "mx4200v1/remove.txt",
}
assert len(resolver.REQUIRED_ARTIFACTS) == 3
sha1, sha2, sha3 = "a" * 40, "b" * 40, "c" * 40


def run(run_id: int, sha: str, *,
        name: str = "Unified PPE/NSS - Arthur and MX4200 v1",
        status: str = "completed", conclusion: str = "success") -> dict:
    return {"id": run_id, "head_sha": sha, "status": status,
            "conclusion": conclusion, "name": name}


def artifacts(*, expired: bool = False, missing: str = "",
              empty: bool = False) -> dict:
    return {"artifacts": [
        {"name": name, "expired": expired, "size_in_bytes": 0 if empty else 100}
        for name in resolver.REQUIRED_ARTIFACTS if name != missing
    ]}


old, candidate, fallback = run(501, sha1), run(502, sha2), run(503, sha3)

# A successful run may have skipped its MX4200 Builder job entirely.
assets = {501: artifacts(missing="mx4200v1-hybrid-diagnostics"),
          502: artifacts(), 503: artifacts()}
selected = resolver.choose_parent([old, candidate, fallback],
                                   lambda n: assets[n], lambda _: True)
assert selected == (502, sha2), selected

# No cross-branch reuse if the kernel recipe or requested package set changed.
selected = resolver.choose_parent([old, candidate, fallback],
                                   lambda n: assets[n], lambda s: s == sha3)
assert selected == (503, sha3), selected

# Expired, incomplete, zero-byte, incorrect-workflow and failed runs never qualify.
for invalid in [
    artifacts(expired=True),
    artifacts(empty=True),
    artifacts(missing="mx4200v1-hybrid-builder-sdk-test"),
]:
    assert not resolver.usable_artifacts(invalid)
for invalid_run in [
    run(501, sha1, status="in_progress", conclusion=""),
    run(501, sha1, conclusion="failure"),
    run(501, sha1, name="Firmware from released ImmortalWrt ImageBuilder"),
    run(501, "not-a-commit"),
]:
    assert resolver.choose_parent(
        [invalid_run], lambda _: artifacts(), lambda _: True) is None

# No compatible parent: full MX Builder instead of trying outdated artifacts.
with patch.object(resolver, "github_json", return_value={"workflow_runs": [old]}), \
     patch.object(resolver, "compatible_source", return_value=False):
    outcome = resolver.resolve("pzcn/openwrt-ppe-nss-ota", "auto", 1)
    assert outcome["mode"] == "full"
    assert outcome["parent_run"] == ""
    try:
        resolver.resolve("pzcn/openwrt-ppe-nss-ota", "repack", 1)
    except RuntimeError as exc:
        assert "no compatible" in str(exc)
    else:
        raise AssertionError("Explicit repack should reject unavailable parents")

# Full mode never needs an API call and never borrows another target's archive.
with patch.object(resolver, "github_json", side_effect=AssertionError("unexpected API")):
    outcome = resolver.resolve("pzcn/openwrt-ppe-nss-ota", "full", 1)
    assert outcome["mode"] == "full"

with patch.object(resolver, "github_json", side_effect=lambda repo, ep:
                  {"workflow_runs": [candidate]} if "runs?" in ep else artifacts()), \
     patch.object(resolver, "compatible_source", side_effect=lambda x: x == sha2):
    outcome = resolver.resolve("pzcn/openwrt-ppe-nss-ota", "auto", 1)
    assert outcome["mode"] == "repack", outcome
    assert outcome["parent_run"] == "502"
    assert outcome["parent_sha"] == sha2

dual = (ROOT / ".github/workflows/dual-device-immortalwrt.yml").read_text()
fast = (ROOT / ".github/workflows/mx4200v1-fast-repack.yml").read_text()
repack = (ROOT / "mx4200v1/repack-hybrid.sh").read_text()
assert "mx4200v1-resolve:" in dual
assert "needs.mx4200v1-resolve.outputs.mode == 'full'" in dual
assert "needs.mx4200v1-resolve.outputs.mode == 'repack'" in dual
assert "needs.mx4200v1-resolve.outputs.parent_run" in dual
assert "needs.mx4200v1-resolve.outputs.parent_sha" in dual
assert "mx_source_run_id" not in dual
assert "43602206711" not in dual + fast + repack
assert "5afd6581438af59b3392c35e82322ab41b09acb2" not in dual + fast + repack
for file in resolver.COMPATIBILITY_INPUTS:
    assert file in repack
assert 'BASE_RUN_ID: ${{ inputs.source_run_id }}' in fast
assert 'BASE_SOURCE_SHA: ${{ inputs.source_commit }}' in fast
print("PASS MX4200 compatible Builder resolver, artifact expiry and full fallback")
