#!/usr/bin/env python3
"""Regression for the real failure mode: cached stock Flash module on OTA repacks.

The old LuCI loader can retain 'system/flash.js?v=<luci-base version>' across
firmware upgrades because the base LuCI version stays unchanged. A changed
view *URL* must be requested, not just a changed file at the old URL.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "immortalwrt_ota", ROOT / "scripts/immortalwrt_ota.py")
ota = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(ota)


def requested_url(overlay: Path, base_version: str) -> str:
    menu_file = overlay / "usr/share/luci/menu.d/zzzz-ota-flash-cache.json"
    assert menu_file.name > "luci-mod-system.json"  # later glob merge
    menu = json.loads(menu_file.read_text())
    assert set(menu) == {"admin/system/flash"}, "must NOT add another menu"
    entry = menu["admin/system/flash"]
    assert entry["depends"]["acl"] == ["luci-mod-system-flash"]
    assert entry["action"]["type"] == "view"
    module = entry["action"]["path"]
    assert module.startswith("system/flash-ota-b")
    expected = overlay / "www/luci-static/resources/view" / (module + ".js")
    assert expected.is_file()
    assert b"renderOTAPanel()" in expected.read_bytes()
    return f"/luci-static/resources/view/{module}.js?v={base_version}"


with tempfile.TemporaryDirectory() as d:
    overlay = Path(d)
    view = overlay / "www/luci-static/resources/view/system/flash.js"
    view.parent.mkdir(parents=True)
    real_view = (ROOT / "files/www/luci-static/resources/view/system/flash.js").read_bytes()
    view.write_bytes(real_view)
    base_version = "26.293.12901~62f0fbb-1794627768"

    # A normal reload would otherwise hit the old browser's cached stock
    # module, because its base LuCI version and URL have not changed.
    old_url = f"/luci-static/resources/view/system/flash.js?v={base_version}"
    browser_cache = {old_url: b"stock Flash, no OTA controls"}

    first = ota.fingerprint_flash_view(overlay, 1794738025)
    assert first.endswith("-" + hashlib.sha256(real_view).hexdigest()[:16])
    first_url = requested_url(overlay, base_version)
    assert first_url not in browser_cache
    assert first_url != old_url
    assert view.read_bytes() == real_view

    # Repeating the same image inputs is deterministic.
    assert ota.fingerprint_flash_view(overlay, 1794738025) == first
    assert requested_url(overlay, base_version) == first_url

    # A new firmware build MUST change the browser URL even if the UI source
    # and installed luci-base package version remain identical.
    second = ota.fingerprint_flash_view(overlay, 1794739025)
    second_url = requested_url(overlay, base_version)
    assert second != first and second_url != first_url
    assert len(list(view.parent.glob("flash-ota-b*.js"))) == 1

    # Content edits must also bust cache, even within one build ID.
    view.write_bytes(real_view + b"\n// cache identity regression\n")
    third = ota.fingerprint_flash_view(overlay, 1794739025)
    assert third != second
    assert requested_url(overlay, base_version) != second_url

    # Never silently publish a firmware without the custom Flash UI.
    view.unlink()
    try:
        ota.fingerprint_flash_view(overlay, 1794739026)
    except ValueError as e:
        assert "Missing customized LuCI flash" in str(e)
    else:
        raise AssertionError("Missing Flash module was accepted")
print("PASS: changing OTA build/content changes LuCI module URL; no second menu")
