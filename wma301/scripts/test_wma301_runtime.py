#!/usr/bin/env python3
"""Mock network + sysupgrade: ensure OTA is WMA301-only and flash stays opt-in."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from wma301_ota import BOARD, IMAGE, LAYOUT, PROFILE, REPO, stamp

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "files/usr/sbin/wma301-ota"
assert shutil.which("jq"), "CI needs jq for OTA JSON parsing"

with TemporaryDirectory() as tmp:
    root = Path(tmp)
    (root / "bin").mkdir()
    (root / "fixtures").mkdir()
    board = root / "board_name"
    board.write_text(BOARD + "\n")
    marker = root / "etc"
    ota = stamp(marker, 12344, "a" * 40, "b" * 64)
    payload = (root / "fixtures/firmware.itb")
    payload.write_bytes(b"FAKE-OTA-FIT" * 110_000)
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    run = 12345
    tag = f"wma301-ota-r{run}"
    index = [
        {"tag_name": tag, "draft": False, "prerelease": False,
         "published_at": "2026-11-13T08:00:00Z",
         "assets": [{"name": "ota.json"}, {"name": IMAGE}]},
        # Publication time is not the firmware version; prefer larger run ID.
        {"tag_name": "wma301-ota-r12343", "draft": False, "prerelease": False,
         "published_at": "2026-11-13T09:00:00Z",
         "assets": [{"name": "ota.json"}, {"name": IMAGE}]},
        {"tag_name": "wma301-ota-r12346", "draft": True, "prerelease": False,
         "assets": [{"name": "ota.json"}, {"name": IMAGE}]},
        {"tag_name": "wma301-ota-testing-r99999", "draft": False,
         "prerelease": False, "assets": [{"name": "ota.json"}, {"name": IMAGE}]},
    ]
    (root / "fixtures/releases.json").write_text(json.dumps(index))
    remote = {"schema": 3, "repository": REPO,
              "tag": tag, "build": run, "board": BOARD, "profile": PROFILE,
              "layout": LAYOUT, "image": IMAGE, "image_sha256": digest,
              "image_size": payload.stat().st_size, "auto_upgrade": False}
    (root / "fixtures/ota.json").write_text(json.dumps(remote))

    fakecurl = root / "bin/curl"
    fakecurl.write_text("""#!/bin/sh
dest=''
url=''
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) dest="$2"; shift 2 ;;
    https://*) url="$1"; shift ;;
    *) shift ;;
  esac
done
case "$url" in
  *'/releases?per_page=100') src="$OTA_FIXTURES/releases.json" ;;
  */ota.json) src="$OTA_FIXTURES/ota.json" ;;
  *.itb) src="$OTA_FIXTURES/firmware.itb" ;;
  *) exit 20 ;;
esac
cp "$src" "$dest"
""")
    fakeuci = root / "bin/uci"
    fakeuci.write_text("""#!/bin/sh
case "$*" in
  *wma301-ota.main.enable_flash*) echo 0 ;;
  *) exit 1 ;;
esac
""")
    upgrade = root / "bin/sysupgrade"
    upgrade.write_text("""#!/bin/sh
if [ "$1" != "-T" ]; then
  echo "UNSAFE: flash command was invoked" >&2
  exit 111
fi
echo "-T $2" >>"$OTA_TEST_LOG"
exit 0
""")
    for item in (fakecurl, fakeuci, upgrade):
        item.chmod(0o755)
    env = dict(os.environ, PATH=str(root / "bin") + os.pathsep + os.environ["PATH"],
               OTA_FIXTURES=str(root / "fixtures"),
               OTA_TEST_LOG=str(root / "upgrade.log"),
               WMA301_OTA_WORK=str(root / "work"),
               WMA301_OTA_RELEASE=str(marker / "etc/wma301-ota-release"),
               WMA301_OTA_BOARD=str(board))
    def call(*args: str):
        return subprocess.run(["sh", str(BACKEND), *args], env=env,
                              text=True, capture_output=True)
    result = call("status")
    assert result.returncode == 0, result.stderr
    status = json.loads(result.stdout)
    assert status["update"] is True and status["downloaded"] is False, status
    assert status["flash_enabled"] is False and status["auto"] is False, status
    assert status["latest"] == tag and "channel" not in status
    result = call("download")
    assert result.returncode == 0, result.stderr
    assert "-T " in (root / "upgrade.log").read_text()
    result = call("status")
    assert json.loads(result.stdout)["downloaded"] is True, result.stdout
    result = call("start")
    assert result.returncode != 0 and "not enabled" in result.stderr
    # If GitHub metadata is for another board or release tag it is rejected.
    remote["board"] = "jdcloud,re-ss-01"
    (root / "fixtures/ota.json").write_text(json.dumps(remote))
    result = call("status")
    assert json.loads(result.stdout)["update"] is False
    assert "does not match" in json.loads(result.stdout)["error"]
    remote["board"] = BOARD
    remote["tag"] = "wma301-ota-r99999"
    (root / "fixtures/ota.json").write_text(json.dumps(remote))
    result = call("status")
    assert "does not match" in json.loads(result.stdout)["error"]
    # No real /sbin/sysupgrade ever ran (stub accepts -T only).
    assert "UNSAFE" not in (root / "upgrade.log").read_text()
print("WMA301 OTA mocked single feed, SHA256, download, device guard, no auto-flash: PASS")
