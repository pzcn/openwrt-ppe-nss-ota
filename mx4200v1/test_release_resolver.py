#!/usr/bin/env python3
"""Offline regression tests for release-backed, no-compile MX4200 repack."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "mx_release_resolver", root / "mx4200v1/resolve-release.py")
resolver = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(resolver)

source_sha = "a" * 40
tag = "mx4200-builder-" + "b" * 24
release = {
    "id": 234, "tag_name": tag, "prerelease": True,
    "draft": False, "published_at": "2026-11-15T10:00:00Z",
}
assets = [
    {"name": name} for name in (
        "mx4200v1-hybrid-metadata.json", "base-overlay.tar.gz",
        "snapshot-lock.json", "sha256sums", "local-apks.txt",
        "immortalwrt-imagebuilder-qualcommax-ipq807x.Linux-x86_64.tar.zst",
    )
]
meta = {
    "target": "qualcommax/ipq807x",
    "profile": "linksys_mx4200v1",
    "source_commit": source_sha,
}
calls = []

def fake_run(*args):
    calls.append(args)
    if args[:2] == ("gh", "api"):
        return json.dumps([release] if args[2].endswith("releases?per_page=100")
                          else assets)
    if args[:3] == ("gh", "release", "download"):
        assert args[3] == tag
        assert args[-2:] == ("-O", "-")
        return json.dumps(meta)
    raise AssertionError(f"Unexpected command in firmware resolver: {args}")

with tempfile.TemporaryDirectory() as d:
    output = Path(d) / "github-output"
    env = {
        "GITHUB_REPOSITORY": "pzcn/openwrt-ppe-nss-ota",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_OUTPUT": str(output),
    }
    with patch.dict(os.environ, env), \
         patch.object(resolver, "run", side_effect=fake_run), \
         patch.object(resolver.subprocess, "run",
                      return_value=SimpleNamespace(returncode=0)) as git:
        resolver.main()
    contents = output.read_text().splitlines()
    assert contents == [
        "available=true", f"tag={tag}", f"source_commit={source_sha}"
    ], contents
    assert git.call_count == 2
    assert all(args[0][0] == "git" for args in git.call_args_list)
    assert all(args[0][0] == "gh" for args in calls)

    # No Builder is available. Pushes are skipped, NEVER auto-compile.
    output.write_text("")
    with patch.dict(os.environ, dict(env, GITHUB_EVENT_NAME="push")), \
         patch.object(resolver, "run", return_value="[]"):
        resolver.main()
    assert output.read_text() == "available=false\n"

    # Explicit manual repack reports missing Builder instead of compiling.
    with patch.dict(os.environ, env), \
         patch.object(resolver, "run", return_value="[]"):
        try:
            resolver.main()
        except SystemExit as exc:
            assert "No automatic compile" in str(exc)
        else:
            raise AssertionError("A missing Builder must not start compilation")

    # A different device target may never be used as a Builder.
    with patch.dict(os.environ, dict(env, GITHUB_EVENT_NAME="push")), \
         patch.object(resolver, "run", side_effect=fake_run), \
         patch.object(resolver.subprocess, "run",
                      return_value=SimpleNamespace(returncode=0)), \
         patch.dict(meta, target="qualcommax/ipq60xx"):
        output.write_text("")
        resolver.main()
    assert output.read_text() == "available=false\n"

print("PASS MX4200 durable Release resolver; no implicit full compilation")
