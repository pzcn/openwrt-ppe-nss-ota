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
assert "backend_revision: 'drcom-rpc9'" in backend
assert "code: 'uci_commit'" in backend
assert "code: 'uci_mismatch'" in backend
assert "code: 'backend_exception'" in backend
assert "const verify = cursor();" in backend
assert "verify.get('drcom', 'main', key)" in backend
assert "for (let key in keys(changes))" in backend
assert "for (let key, value in changes)" not in backend
assert "return getConfig().then(" in campus.read_text()
assert "result.login_url !== target.login" in campus.read_text()
assert "c.login_url !== target.login" in campus.read_text()
assert "reject: true" in campus.read_text()
assert campus.read_text().count("reject: true") == 7
assert "backend_revision !== 'drcom-rpc9'" in campus.read_text()
assert "RPC 未返回有效结果" in campus.read_text()
assert "--interface \"if!$WAN_DEVICE\"" in transport
assert "option auto '0'" in default
legacy = (overlay / "etc/uci-defaults/98-drcom-clear-unused-legacy-url").read_text()
assert "gate.lnu.edu.cn/0.htm" in legacy and "gate.lnu.edu.cn/F.htm" in legacy
for guard in ('[ -z "$username" ]', '[ -z "$password" ]', '[ "$remember" != 1 ]', '[ "$auto" != 1 ]'):
    assert guard in legacy, "Legacy migration must not clear remembered credentials"
subprocess.run(["sh", "-n", str(overlay / "etc/uci-defaults/98-drcom-clear-unused-legacy-url")], check=True)
# User-facing pages and documentation should use device/function names.
# Keep immutable GitHub owner URLs and old OTA asset names in the transport
# layer for backward compatibility with already installed firmware.
visible = [
    overlay / "www/luci-static/resources/view/status/ppe-nss-monitor-native.js",
    overlay / "www/luci-static/resources/view/network/drcom-native.js",
    overlay / "www/luci-static/resources/view/system/flash.js",
    overlay / "www/luci-static/resources/view/system/ppe-update.js",
    overlay / "usr/share/luci/menu.d/luci-app-ppe-update.json",
    root / "README.md",
    root / "docs/PPE-NSS-MONITOR.md",
    root / "docs/DRCOM-CAMPUS.md",
    root / "docs/CUSTOM-OTA.md",
]
for item in visible:
    content = item.read_text(encoding="utf-8").lower()
    assert "pzcn" not in content, f"Identity label in user-facing content: {item}"
    if item.name == "drcom-native.js":
        assert "注意事项" not in content
        assert "http 认证会明文传输密码" in content

    for phrase in ("不会", "不再", "不会回退", "不会修改"):
        assert phrase not in content, f"Defensive phrase {phrase}: {item}"
build_script = (root / "scripts/build.sh").read_text(encoding="utf-8")
notes = build_script.split('cat > "$WORK/notes.md" <<EOF', 1)[1].split("\nEOF", 1)[0]
assert "pzcn" not in notes.lower()
assert "不会" not in notes
assert "在线固件更新" in notes
print("PASS: native LuCI, versioned RPC, concise user-facing copy and URL readback")
