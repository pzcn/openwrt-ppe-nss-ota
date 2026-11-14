#!/usr/bin/env python3
"""Tests for pre-finalization service links, module indexes and APK scripts."""
import importlib.util
import io
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "swap_root_finalize", ROOT / "scripts/audit-swap-boot-finalization.py")
mod = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(mod)

with tempfile.TemporaryDirectory() as name:
    d = Path(name)
    official, donor, mixed = (d / n for n in ("stock", "donor", "mixed"))
    for root in (official, donor, mixed):
        (root / "etc/rc.d").mkdir(parents=True)
        (root / "etc/init.d").mkdir(parents=True)
        (root / "lib/modules/6.18.60").mkdir(parents=True)
        (root / "lib/apk/db").mkdir(parents=True)
        (root / "etc/init.d/network").write_text("#!/bin/sh\n")
    (official / "etc/rc.d/S20network").symlink_to("../init.d/network")
    (donor / "etc/rc.d/S20network").symlink_to("../init.d/network")
    (donor / "etc/rc.d/S50nss-wifi").symlink_to("../init.d/nss-wifi")
    (official / "lib/modules/6.18.60/modules.dep").write_text("test.ko:\n")
    (donor / "lib/modules/6.18.60/modules.alias").write_text("alias test test\n")
    archive = mixed / "lib/apk/db/scripts.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        body = b"#!/bin/sh\n"
        entry = tarfile.TarInfo("base-files.post-install")
        entry.size = len(body)
        tar.addfile(entry, io.BytesIO(body))
    result = mod.report(mod.snapshot(official), mod.snapshot(donor),
                        mod.snapshot(mixed))
    assert result["stock_rc_symlink_count"] == 1
    assert result["julius_rc_symlink_count"] == 2
    assert result["mixed_rc_symlink_count"] == 0
    assert result["missing_stock_service_links_before_finalization"] == ["S20network"]
    assert result["missing_julius_service_links_before_finalization"] == [
        "S20network", "S50nss-wifi"]
    assert result["module_index_expected_in_stock"]
    assert result["module_index_expected_in_donor"]
    assert result["mix_contains_apk_post_install_scripts"]
    assert result["mixed"]["apk_postinstall"]["post_install_script_count"] == 1
    assert not result["publishable"]
    (mixed / "etc/rc.d/S20network").symlink_to("../init.d/network")
    result = mod.report(mod.snapshot(official), mod.snapshot(donor),
                        mod.snapshot(mixed))
    assert result["missing_stock_service_links_before_finalization"] == []
    (mixed / "etc/rc.d/S20network").unlink()
    (mixed / "etc/rc.d/S20network").symlink_to("bad-target")
    result = mod.report(mod.snapshot(official), mod.snapshot(donor),
                        mod.snapshot(mixed))
    assert result["differing_stock_service_links_before_finalization"] == ["S20network"]

print("PASS baseline service enablement and APK script archive inventory")
