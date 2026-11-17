#!/usr/bin/env python3
"""Offline contracts for the WMA301 v2 home-page WAN port picker.

These tests intentionally avoid touching a real network: a four-port DSA
reassignment needs a device-side hardware and remote-access smoke test.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from stage_files import stage_files

ROOT = Path(__file__).resolve().parents[1]
script = ROOT / "files/usr/sbin/wma301-ports"
callback = ROOT / "files/usr/libexec/wma301-ports-dhcp-probe"
view = ROOT / "files/www/luci-static/resources/view/status/include/29_ports.js"
acl = ROOT / "files/usr/share/rpcd/acl.d/luci-app-wma301-ports.json"

for shfile in (script, callback, ROOT / "files/etc/init.d/wma301-ports",
               ROOT / "files/etc/uci-defaults/97-wma301-ports"):
    subprocess.run(["sh", "-n", str(shfile)], check=True)

if os.environ.get("NODE_AVAILABLE", "1") == "1":
    subprocess.run(["node", "--check", str(view)], check=True)

cfg = (ROOT / "files/etc/config/wma301-ports").read_text()
assert "option mode 'auto'" in cfg
assert "option active 'none'" in cfg

backend = script.read_text()
for mapping in ("1) echo lan1", "2) echo lan2", "3) echo lan3", "4) echo wan"):
    assert mapping in backend, mapping
assert 'uci -q set "network.wan.device=$target"' in backend
assert "network.$bridge.ports" in backend
assert "network.wan.proto=" not in backend, "port switching must not change WAN protocol"
assert "set_active" in backend and "scan()" in backend
assert "PROBE_SCRIPT=/usr/libexec/wma301-ports-dhcp-probe" in backend
assert "tplink,wma301-v2-1" in backend
assert 'ip link set dev "$p" nomaster' in backend, "DHCP discovery must isolate bridge ports"
assert "carrier" in backend and "previous=" in backend
assert "sleep 2  # carrier debounce" in backend

js = view.read_text()
assert "const nativePortGrid" in js, "reuse native LuCI tiles rather than reimplementing"
for api in ("getCarrier()", "getSpeed()", "getTXBytes()", "getRXBytes()"):
    assert api in js
assert "WAN 网口选择" in js
for item in ("自动识别（默认）", "固定网口 1", "固定网口 4"):
    assert item in js
assert "this.pendingWanMode" in js, "selection should survive status polling"

data = json.loads(acl.read_text())
permissions = data["luci-app-wma301-ports"]
assert "/usr/sbin/wma301-ports status" in permissions["read"]["file"]
for item in ("auto", "1", "2", "3", "4"):
    assert "/usr/sbin/wma301-ports set " + item in permissions["write"]["file"]

with TemporaryDirectory() as directory:
    root = Path(directory)
    staged = stage_files(ROOT / "files", root / "overlay")
    for path in (
        "usr/sbin/wma301-ports",
        "usr/libexec/wma301-ports-dhcp-probe",
        "etc/init.d/wma301-ports",
        "etc/uci-defaults/97-wma301-ports",
    ):
        assert path in staged
        assert ((root / "overlay" / path).stat().st_mode & 0o111), path
    assert "www/luci-static/resources/view/status/include/29_ports.js" in staged

    stubbin = root / "bin"
    stubbin.mkdir()
    stubuci = stubbin / "uci"
    stubuci.write_text("#!/bin/sh\ncase \"$*\" in *wma301-ports.main.mode*) echo auto ;; "
                       "*wma301-ports.main.active*) echo lan2 ;; esac\n")
    stubuci.chmod(0o755)
    env = dict(os.environ, PATH=str(stubbin) + os.pathsep + os.environ["PATH"])
    p = subprocess.run(["sh", str(script), "status"], env=env,
                       capture_output=True, text=True, check=True)
    state = json.loads(p.stdout)
    assert state == {"mode": "auto", "active": "lan2", "active_number": 2}, state

print("WMA301 WAN selector: shell, JS, ACL, overlay permissions, status: PASS")
