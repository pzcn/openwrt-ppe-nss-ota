#!/usr/bin/env python3
"""Aurora: noarch native APK, version stamping and package ownership contracts."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from aurora import (
    REQUIRED, COMMIT, VERSION, PACKAGE_NAME, PACKAGE_VERSION,
    build_apk, stage_contents, check_layout, substitute_version,
)

assert len(COMMIT) == 40 and VERSION == "1.4.0"
assert PACKAGE_NAME == "luci-theme-aurora" and PACKAGE_VERSION == "1.4.0-r1"
assert substitute_version('data-version="{# PKG_VERSION #}"') == 'data-version="1.4.0"'
assert substitute_version('href="{{ media }}/main.css"') == 'href="{{ media }}/main.css?v=1.4.0"'
assert substitute_version('src="{{ resource }}/menu.js"') == 'src="{{ resource }}/menu.js?v=1.4.0"'

with TemporaryDirectory() as tmp:
    base = Path(tmp)
    source = base / "theme"
    payload = base / "staged"
    for rel in REQUIRED:
        file = source / rel
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('data-version="{# PKG_VERSION #}"')
    check_layout(source)
    written = stage_contents(source, payload)
    assert len(written) == len(REQUIRED)
    assert (payload / "www/luci-static/aurora/main.css").is_file()
    assert (payload / "www/luci-static/resources/menu-aurora.js").is_file()
    header = payload / "usr/share/ucode/luci/template/themes/aurora/header.ut"
    assert header.read_text() == 'data-version="1.4.0"'
    assert (payload / "usr/share/licenses/luci-theme-aurora/LICENSE").is_file()
    assert not (payload / "etc/uci-defaults/30_luci-theme-aurora").exists()
    try:
        stage_contents(source, payload)
    except ValueError:
        pass
    else:
        raise AssertionError("Aurora files overwrote existing APK payload")

    builder = base / "builder"
    local = builder / "packages"
    host_apk = builder / "staging_dir/host/bin/apk"
    local.mkdir(parents=True)
    host_apk.parent.mkdir(parents=True)
    host_apk.write_text("#!/bin/sh\nexit 0\n")
    host_apk.chmod(0o755)
    def fake_mkpkg(argv, check):
        assert check and argv[0] == str(host_apk) and argv[1] == "mkpkg"
        assert "--files" in argv and "--output" in argv
        details = [argv[i + 1] for i, word in enumerate(argv[:-1]) if word == "--info"]
        for item in (
            "name:luci-theme-aurora", "version:1.4.0-r1",
            "arch:noarch", "depends:luci-base", "license:Apache-2.0"
        ):
            assert item in details, details
        result = Path(argv[argv.index("--output") + 1])
        assert result.parent == local
        root = Path(argv[argv.index("--files") + 1])
        assert (root / "www/luci-static/aurora/main.css").is_file()
        assert (root / "usr/share/ucode/luci/template/themes/aurora/header.ut").is_file()
        assert not (root / "etc/uci-defaults/30_luci-theme-aurora").exists()
        result.write_bytes(b"MOCK-APK-V3" * 160)
    with patch("aurora.check_source", side_effect=check_layout), \
         patch("aurora.subprocess.run", side_effect=fake_mkpkg) as fake:
        result = build_apk(source, builder)
        assert fake.call_count == 1
    assert result["fast_build_installation"] == "imagebuilder-local-noarch-apk"
    assert result["architecture"] == "noarch"
    assert result["filename"] == "luci-theme-aurora-1.4.0-r1.apk"
    assert len(result["sha256"]) == 64
    assert (local / result["filename"]).is_file()
    try:
        with patch("aurora.check_source", side_effect=check_layout):
            build_apk(source, builder)
    except ValueError:
        pass
    else:
        raise AssertionError("Aurora APK rebuild reused previous payload")

    asset = source / "htdocs/luci-static/aurora/main.css"
    asset.unlink()
    asset.symlink_to(source / "LICENSE")
    try:
        check_layout(source)
    except ValueError:
        pass
    else:
        raise AssertionError("Unsafe theme symlink was accepted")
print("Aurora native noarch APK, version stamping, filesystem ownership: PASS")
