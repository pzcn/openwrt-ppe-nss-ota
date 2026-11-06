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
monitor_view = monitor.read_text(encoding="utf-8")
monitor_rpc = (overlay / "usr/share/rpcd/ucode/luci.ppe-nss-monitor").read_text(encoding="utf-8")
assert "监控状态" not in monitor_view
assert "最近 24 次采样" not in monitor_view
assert "togglePause" not in monitor_view
assert "manualRefresh" not in monitor_view
assert "poll.add(this._poller, 8)" in monitor_view
assert "E('h3', '加速引擎')" in monitor_view
assert "E('h3', '连接统计')" in monitor_view
assert "E('summary', '内核诊断')" in monitor_view
assert "c.unload();" not in monitor_rpc
assert "c.unload(pkg);" in monitor_rpc
assert "c.unload('firewall');" in monitor_rpc

assert "option login_url ''" in default
assert "option logout_url ''" in default
assert "backend_revision: 'drcom-rpc12'" in backend
assert "code: 'uci_commit'" in backend
assert "code: 'uci_mismatch'" in backend
assert "code: 'backend_exception_' + stage" in backend
assert "const verify = cursor();" in backend
assert "unload();" not in backend
assert "backend_exception_' + stage" in backend
assert "verify.get('drcom', 'main', key)" in backend
assert "for (let key in keys(changes))" in backend
assert "for (let key, value in changes)" not in backend
assert "return getConfig().then(" in campus.read_text()
assert "result.login_url !== target.login" in campus.read_text()
assert "field('认证地址', n.portalUrl)" in campus.read_text()
assert "n.logoutUrl" not in campus.read_text()
assert "buildPortalUrls" in campus.read_text()
assert "save_credentials" in backend
assert "save_credentials" in json.loads((overlay / "usr/share/rpcd/acl.d/luci-app-drcom.json").read_text())["luci-app-drcom"]["write"]["ubus"]["luci.drcom"]
assert "saveCredentials(target.login, target.logout, user, secret)" in campus.read_text()
assert "保存认证信息" in campus.read_text()
assert "drcom-remember" not in campus.read_text()
assert "••••••••（已保存）" in campus.read_text()
flash = (overlay / "www/luci-static/resources/view/system/flash.js").read_text()
assert "otaScheduleWidget()" in flash
assert "object: 'uci'" in flash
assert "method: 'commit'" in flash
assert "params: [ 'config' ]" in flash
assert "commitOtaConfig('ppe-update')" in flash
assert "uci.save()" in flash
assert "uci.unload('ppe-update')" in flash
assert "uci.load('ppe-update')" in flash
assert "保存后的配置与填写内容不一致" in flash
assert "uci.apply()" not in flash
assert "row('启用自动更新', auto)" in flash
assert "启用无人值守更新" not in flash
assert "'checked': uci.get('ppe-update', 'main', 'auto') == '1' ? '' : null" in flash
assert "'selected': (uci.get('ppe-update', 'main', 'hour') || '4') == String(i) ? '' : null" in flash
assert "'checked': config.auto ? '' : null" in campus.read_text()
assert "'启用0点自动认证'" in campus.read_text()
assert "'每天零点认证'" not in campus.read_text()
assert "发现新版本，已开启自动更新" in flash
assert "发现新版本，可立即手动升级" in flash
assert "发现新版本，可手动升级" not in flash
assert "view.otaRefresh().catch(function() {});" in flash
assert "'当前已是最新版本'" in flash
assert "'当前已是最新版本。'" not in flash
assert "this._otaInstallButton.disabled = isReadonlyView || st.update !== true;" in flash
assert "this._otaInstallButton.disabled = true;" in flash
assert "return this._otaInstallButton;" in flash
assert "'click': ui.createHandlerFn(this, 'otaAskInstall')" in flash
assert "L.url('admin/system/ppe-update')" not in flash
assert not (overlay / "usr/share/luci/menu.d/luci-app-ppe-update.json").exists()
assert "c.login_url !== target.login" in campus.read_text()
assert "reject: true" in campus.read_text()
assert campus.read_text().count("reject: true") == 7
assert "backend_revision !== 'drcom-rpc12'" in campus.read_text()
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
assert 'rm -f "$WORK/ib/files/www/luci-static/resources/view/system/ppe-update.js"' in build_script
assert '"$WORK/ib/files/usr/share/luci/menu.d/luci-app-ppe-update.json"' in build_script
assert 'Build failed at line $LINENO' in build_script
notes = build_script.split('cat > "$WORK/notes.md" <<EOF', 1)[1].split("\nEOF", 1)[0]
assert "pzcn" not in notes.lower()
assert "不会" not in notes
assert "在线固件更新" in notes
print("PASS: native LuCI, versioned RPC, concise user-facing copy and URL readback")
