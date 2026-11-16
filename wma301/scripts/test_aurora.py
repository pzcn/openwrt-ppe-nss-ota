#!/usr/bin/env python3
"""Offline Aurora source/layout and LuCI-template packaging regression tests."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from aurora import REQUIRED, COMMIT, VERSION, stage_contents, check_layout, substitute_version

assert len(COMMIT) == 40 and VERSION == "1.4.0"
assert substitute_version('data-version="{# PKG_VERSION #}"') == 'data-version="1.4.0"'
assert substitute_version('href="{{ media }}/main.css"') == 'href="{{ media }}/main.css?v=1.4.0"'
assert substitute_version('src="{{ resource }}/menu.js"') == 'src="{{ resource }}/menu.js?v=1.4.0"'

with TemporaryDirectory() as tmp:
    source = Path(tmp) / "theme"
    overlay = Path(tmp) / "overlay"
    for rel in REQUIRED:
        file = source / rel
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('data-version="{# PKG_VERSION #}"')
    check_layout(source)
    written = stage_contents(source, overlay)
    assert len(written) == len(REQUIRED)
    assert (overlay / "www/luci-static/aurora/main.css").is_file()
    assert (overlay / "www/luci-static/resources/menu-aurora.js").is_file()
    header = overlay / "usr/share/ucode/luci/template/themes/aurora/header.ut"
    assert header.read_text() == 'data-version="1.4.0"'
    assert (overlay / "usr/share/licenses/luci-theme-aurora/LICENSE").is_file()
    assert not (overlay / "etc/uci-defaults/30_luci-theme-aurora").exists()
    try:
        stage_contents(source, overlay)
    except ValueError:
        pass
    else:
        raise AssertionError("Aurora files overwrote existing overlay content")
    asset = source / "htdocs/luci-static/aurora/main.css"
    asset.unlink()
    asset.symlink_to(source / "LICENSE")
    try:
        check_layout(source)
    except ValueError:
        pass
    else:
        raise AssertionError("Unsafe theme symlink was accepted")
print("Pinned Aurora theme layout, version stamping, overlay isolation: PASS")
