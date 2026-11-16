#!/usr/bin/env python3
"""Check that both build paths omit OTA runtime assets by default."""
from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from stage_files import is_ota_file, stage_files

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "files"
ota_files = {
    p.relative_to(SOURCE).as_posix()
    for p in SOURCE.rglob("*")
    if p.is_file() and is_ota_file(p.relative_to(SOURCE))
}
assert len(ota_files) == 6, ota_files

with TemporaryDirectory() as folder:
    root = Path(folder)
    with patch.dict(os.environ, {"WMA301_ENABLE_OTA": "false"}):
        staged = stage_files(SOURCE, root / "disabled")
    assert not ota_files.intersection(staged)
    assert all(not (root / "disabled" / p).exists() for p in ota_files)
    assert (root / "disabled/etc/uci-defaults/95-luci-preferences").is_file()
    with patch.dict(os.environ, {"WMA301_ENABLE_OTA": "true"}):
        staged = stage_files(SOURCE, root / "enabled")
    assert ota_files <= set(staged)
    assert all((root / "enabled" / p).is_file() for p in ota_files)

print("WMA301 overlay: OTA files disabled by default; opt-in preserves all files: PASS")
