#!/usr/bin/env python3
"""Static integration regression checks for native LuCI views / Dr.COM URLs.

No router or external campus network required. UI moved to distinct view URLs
so an old static resource cache cannot make a new firmware look unchanged.
"""
import json
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[2]
overlay = root / "files"

monitor = overlay / "www/luci-static/resources/view/status/ppe-nss-monitor-native.js"
campus = overlay / "www/luci-static/resources/view/network/drcom-native.js"
backend = (overlay / "usr/share/rpcd/ucode/luci.drcom").read_text()
transport = (overlay / "usr/libexec/drcom-web").read_text()
default = (overlay / "etc/config/drcom").read_text()

for src in (monitor, campus):
    assert src.is_file(), f"Missing LuCI native view: {src}"
    subprocess.run(["node", "--check", str(src)], check=True)
    code = src.read_text()
    assert "'class': 'cbi-map'" in code
    assert "'class': 'cbi-section'" in code
    assert "'class': 'table'" in code
    assert "luci-static/resources/" not in code
    assert "stylesheet" not in code
    assert "background:" not in code

for filename, menu in (
    ("view/status/ppe-nss-monitor-native.js", "luci-app-ppe-nss-monitor.json"),
    ("view/network/drcom-native.js", "luci-app-drcom.json"),
):
    key = json.loads((overlay / "usr/share/luci/menu.d" / menu).read_text())
    item = next(iter(key.values()))
    assert item["action"]["path"] == filename.removeprefix("view/").removesuffix(".js")
assert "gate.lnu.edu.cn" not in default
assert "gate.lnu.edu.cn" not in backend
assert "gate.lnu.edu.cn" not in transport
assert "option login_url ''" in default
assert "option logout_url ''" in default
assert "return { ok: true, login_url: saved.login_url, logout_url: saved.logout_url," in backend
assert "const verify = cursor();" in backend
assert "verify.get('drcom', 'main', key)" in backend
assert "return getConfig().then(" in campus.read_text()
assert "result.login_url !== target.login" in campus.read_text()
assert "c.login_url !== target.login" in campus.read_text()
assert "--interface \"if!$WAN_DEVICE\"" in transport
assert "option auto '0'" in default
print("PASS: native LuCI views and persisted Dr.COM URL readback checks")
