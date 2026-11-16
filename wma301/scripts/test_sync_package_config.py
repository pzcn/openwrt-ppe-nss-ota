#!/usr/bin/env python3
"""Test shared official/whole-source package selection and exclusions."""
from pathlib import Path
from tempfile import TemporaryDirectory

from sync_package_config import apply, check

with TemporaryDirectory() as td:
    path = Path(td)
    pkg = path / "packages.txt"
    cfg = path / ".config"
    pkg.write_text("luci\nluci-app-wol\n-luci-app-homeproxy\n")
    cfg.write_text("CONFIG_TARGET_mediatek=y\nCONFIG_PACKAGE_luci=n\n"
                   "CONFIG_PACKAGE_luci-app-homeproxy=y\n")
    apply(pkg, cfg)
    content = cfg.read_text()
    assert content.count("CONFIG_PACKAGE_luci=y") == 1
    assert "CONFIG_PACKAGE_luci-app-wol=y" in content
    assert "# CONFIG_PACKAGE_luci-app-homeproxy is not set" in content
    assert "CONFIG_TARGET_mediatek=y" in content
    check(pkg, cfg)
    cfg.write_text(content.replace("CONFIG_PACKAGE_luci-app-wol=y",
                                   "# CONFIG_PACKAGE_luci-app-wol is not set"))
    try:
        check(pkg, cfg)
    except ValueError:
        pass
    else:
        raise AssertionError("missing selected package went undetected")
    pkg.write_text("luci\n-luci\n")
    try:
        apply(pkg, cfg)
    except ValueError:
        pass
    else:
        raise AssertionError("conflicting selections accepted")
print("Full source shared package selection: PASS")
