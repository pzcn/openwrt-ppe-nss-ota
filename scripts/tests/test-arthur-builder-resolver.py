#!/usr/bin/env python3
"""Offline contract for safe default Arthur Hybrid Builder selection."""
import importlib.util
import json
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[2]
source = ROOT / "scripts/arthur_builder_resolver.py"
spec = importlib.util.spec_from_file_location("arthur_builder_resolver", source)
resolver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resolver)
policy = json.loads((ROOT / "config/arthur-builder-policy.json").read_text())
approved = policy["preferred_prerelease_tag"]


def release(tag, hybrid, pre, published):
    assets = sorted(resolver.HYBRID_REQUIRED if hybrid else resolver.REQUIRED)
    assets.append("immortalwrt-imagebuilder-qualcommax-ipq60xx.Linux-x86_64.tar.zst")
    if hybrid:
        assets.append("immortalwrt-sdk-qualcommax-ipq60xx.Linux-x86_64.tar.zst")
    return {
        "tag_name": tag,
        "draft": False,
        "prerelease": pre,
        "name": "Hybrid ImageBuilder + SDK r42542" if hybrid else "Full Source Builder",
        "published_at": published,
        "assets": [{"name": x} for x in assets],
    }


old = release("imm-builder-legacy-stable", False, False, "2026-11-15T20:00:00Z")
trial = release(approved, True, True, "2026-11-14T09:42:53Z")
newer_unreviewed = release("imm-builder-branch-experimental", True, True, "2026-11-15T21:00:00Z")
stable_hybrid = release("imm-builder-approved-hybrid", True, False, "2026-11-14T08:00:00Z")

result = resolver.choose([old, newer_unreviewed, trial], policy)
assert result["tag"] == approved and result["prerelease"] is True
assert result["hybrid"] is True and "pinned" in result["reason"]
# Stable Hybrid always takes priority, even if the old Full Source is newer.
result = resolver.choose([old, trial, stable_hybrid], policy)
assert result["tag"] == stable_hybrid["tag_name"] and not result["prerelease"]
assert resolver.choose([old], policy, requested=old["tag_name"])["hybrid"] is False
assert resolver.choose([old, trial], policy, requested=approved)["prerelease"]

bad = [
    ([old, newer_unreviewed], policy, ""),
    ([old, trial], policy, newer_unreviewed["tag_name"]),
    ([old, newer_unreviewed], policy, newer_unreviewed["tag_name"]),
    ([dict(trial, draft=True), old], policy, ""),
    ([dict(trial, assets=[]), old], policy, ""),
    ([dict(trial, assets=old["assets"]), old], policy, ""),
]
for releases, config, request in bad:
    try:
        resolver.choose(releases, config, request)
    except ValueError:
        pass
    else:
        raise AssertionError(f"Unapproved or invalid Hybrid was selected: {request}")

# A renamed/pre-release Full Source must not become a trusted Hybrid.
try:
    resolver.choose([dict(old, prerelease=True)], policy, requested=old["tag_name"])
except ValueError:
    pass
else:
    raise AssertionError("Accepted prerelease Full Source Builder")

print("PASS: safe Hybrid-first resolver, preview isolation, explicit legacy escape hatch")
