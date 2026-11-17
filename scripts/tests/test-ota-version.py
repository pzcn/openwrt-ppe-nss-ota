#!/usr/bin/env python3
"""Offline regressions: official Snapshot revision, provenance and Beijing time."""
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

root = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("ota_version", root / "scripts/ota_version.py")
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)

# November 15, 2026 11:25 UTC = November 15, 2026 19:25 Beijing.
epoch = int(datetime(2026, 11, 15, 11, 25, tzinfo=timezone.utc).timestamp())
arthur = module.make_tag("arthur", epoch, "r43172-4765b657")
mx = module.make_tag("mx4200v1", epoch, "r42542-e695009c15")
assert arthur == "imm-re-ss-01-SNAPSHOT-r43172-202611151925", arthur
assert "imm-arthur-" not in arthur
assert mx == "imm-mx4200v1-SNAPSHOT-r42542-202611151925", mx
wma = module.make_tag("wma301", epoch, "r42542-e695009c15")
assert wma == "imm-wma301-SNAPSHOT-r42542-202611151925", wma
wma21 = module.make_tag("wma301v21", epoch, "r42542-e695009c15")
assert wma21 == "imm-wma301v21-SNAPSHOT-r42542-202611151925", wma21
assert arthur.split("-")[-1] == mx.split("-")[-1] == wma.split("-")[-1]
assert module.short_revision("r42542") == "r42542"

# UTC day boundary must be Shanghai local time; no YYMM string.
next_day = int(datetime(2026, 11, 15, 17, 1, tzinfo=timezone.utc).timestamp())
assert module.make_tag("arthur", next_day, "r43172").endswith("202611160101")
december = int(datetime(2026, 11, 30, 16, 0, tzinfo=timezone.utc).timestamp())
assert module.make_tag("mx4200v1", december, "r42542") == \
    "imm-mx4200v1-SNAPSHOT-r42542-202612010000"

with tempfile.TemporaryDirectory() as d:
    temp = Path(d)
    lock = temp / "snapshot-lock.json"
    lock.write_text(json.dumps({
        "schema": 2, "target": "qualcommax/ipq807x",
        "snapshot_version": "r42542-e695009c15",
    }))
    assert module.select_revision(device="mx4200v1", snapshot_lock=lock) == "r42542"
    try:
        module.select_revision(device="arthur", snapshot_lock=lock)
    except ValueError:
        pass
    else:
        raise AssertionError("Accepted MX signed Snapshot lock for Arthur")

    builder = temp / "builder-metadata.json"
    base = {
        "schema": 1, "channel": "re-ss-01-immortal-imagebuilder",
        "profile": "jdcloud_re-ss-01",
        "immortalwrt_commit": "4765b657625ec5bbda74b44400465fe043802b30",
    }
    builder.write_text(json.dumps({
        **base, "build_mode": "hybrid",
        "official_snapshot": {"snapshot_version": "r42542-e695009c15"}
    }))
    assert module.select_revision(device="arthur", builder_metadata=builder) == "r42542"
    builder.write_text(json.dumps({**base, "build_mode": "full"}))
    upstream = {
        "ahead_by": 43172, "behind_by": 0, "status": "ahead",
        "merge_base": module.REVISION_BASE,
    }
    def compare(**overrides):
        payload = json.dumps({**upstream, **overrides})
        return subprocess.CompletedProcess(args=["gh"], returncode=0, stdout=payload)

    with patch.object(module.subprocess, "run", return_value=compare()) as mock_run:
        assert module.select_revision(device="arthur", builder_metadata=builder) == "r43172"
        mock_run.assert_called_once()
        assert module.REVISION_BASE in mock_run.call_args.args[0][2]
        assert base["immortalwrt_commit"] in mock_run.call_args.args[0][2]

    # Incorrect ancestry / API JSON must fail closed, not invent a revision.
    for override in ({"ahead_by": None}, {"behind_by": 1},
                     {"merge_base": "f" * 40}, {"status": "diverged"}):
        with patch.object(module.subprocess, "run",
                          return_value=compare(**override)):
            try:
                module.select_revision(device="arthur", builder_metadata=builder)
            except ValueError:
                pass
            else:
                raise AssertionError(f"Accepted untrusted GitHub compare {override}")
    with patch.object(module.subprocess, "run", side_effect=OSError("offline")):
        try:
            module.select_revision(device="arthur", builder_metadata=builder)
        except ValueError:
            pass
        else:
            raise AssertionError("Used made-up revision when source lookup failed")

for rev in ("SNAPSHOT2611", "25.12", "rabc", "r42542+foo",
            "r42542-nothex", "r0", "", None):
    try:
        module.make_tag("mx4200v1", epoch, rev)
    except ValueError:
        pass
    else:
        raise AssertionError(f"Accepted nonofficial revision: {rev}")

for args in [("none", epoch, "r42542"), ("arthur", 0, "r43172"),
             ("arthur", 1.5, "r43172")]:
    try:
        module.make_tag(*args)
    except ValueError:
        pass
    else:
        raise AssertionError(f"Invalid OTA tag args accepted: {args}")

print("PASS official Snapshot provenance, tags, and Beijing calendar boundaries")
