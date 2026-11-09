#!/usr/bin/env python3
"""Dr.COM source files are preserved, but firmware overlays omit the app."""
from pathlib import Path
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
filter_script = root / "scripts/exclude-drcom-from-firmware.sh"
build = (root / "scripts/build-immortalwrt.sh").read_text()
repack = (root / "scripts/repack-immortalwrt.sh").read_text()

sources = [
    "etc/config/drcom",
    "etc/init.d/drcom",
    "etc/uci-defaults/97-drcom-credentials-permissions",
    "etc/uci-defaults/98-drcom-clear-unused-legacy-url",
    "usr/libexec/drcom-schedule",
    "usr/libexec/drcom-web",
    "usr/share/luci/menu.d/luci-app-drcom.json",
    "usr/share/rpcd/acl.d/luci-app-drcom.json",
    "usr/share/rpcd/ucode/luci.drcom",
    "www/luci-static/resources/view/network/drcom-native.js",
]
assert 'sh "$ROOT/scripts/stage-firmware-overlay.sh" "$IMM/files"' in build
assert 'sh "$ROOT/scripts/stage-firmware-overlay.sh" "$WORK/overlay"' in repack
stage_script = root / "scripts/stage-firmware-overlay.sh"
assert 'sh "$SCRIPT_DIR/exclude-drcom-from-firmware.sh" "$1"' in stage_script.read_text()
assert "drcom" not in build.lower()
subprocess.run(["sh", "-n", str(filter_script)], check=True)
subprocess.run(["sh", "-n", str(stage_script)], check=True)

for name in sources:
    assert (root / "files" / name).is_file(), "Source missing from repository: " + name
    assert name in filter_script.read_text(), "File not filtered: " + name
with tempfile.TemporaryDirectory() as d:
    overlay = Path(d)
    for name in sources:
        dest = overlay / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / "files" / name, dest)
    keep = overlay / "usr/sbin/ppe-update"
    keep.parent.mkdir(parents=True, exist_ok=True)
    keep.write_text("keep")
    for _ in range(2):
        subprocess.run(["sh", str(stage_script), str(overlay)], check=True)
    assert all(not (overlay / name).exists() for name in sources)
    assert keep.read_text() == "keep"
assert "Dr.COM, F2FS/ext4" not in build
print("PASS Dr.COM kept in source; excluded from full and repacked firmware")
