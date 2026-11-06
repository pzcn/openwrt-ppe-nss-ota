#!/usr/bin/env python3
"""Run the Dr.COM URL validators in the native ucode VM (not Node.js)."""
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / "files/usr/share/rpcd/ucode/luci.drcom").read_text(encoding="utf-8")
start = source.index("function valid_url(url) {")
end = source.index("\nfunction config() {", start)
functions = source[start:end]

config_start = source.index("function config() {")
config_end = source.index("\nfunction run(action, payload) {", config_start)
config_functions = source[config_start:config_end]

save_start = source.index("\tsave_credentials: {")
save_end = source.index("\n\tlogin: {", save_start)
credential_method = source[save_start:save_end].strip().rstrip(",")

# Keep the tested functions identical to those installed on the router.
suite = r"""
const good_urls = [
    'http://192.168.15.1:8800/0.htm',
    'http://192.168.15.1:8800/F.htm',
    'http://gate.example.edu/0.htm',
    'http://gate.example.edu/F.htm?session=1',
    'https://portal.example.edu:443/path/0.htm?foo=bar&x=1',
    'http://10.1.2.3/login/0.htm'
];
for (let url in good_urls)
    if (!valid_url(url))
        die('Valid URL rejected: ' + url);

const bad_urls = [
    '', 'ftp://gate.example.edu/0.htm', 'http://',
    'http://user:pass@gate.example.edu/0.htm',
    'http://gate.example.edu:abc/0.htm',
    'http://gate.example.edu/0.htm#fragment',
    'http://gate.example.edu/0.htm <bad>',
    'http://gate.example.edu/0.htm\ninvalid',
    'http://gate.example.edu:999999/0.htm'
];
for (let url in bad_urls)
    if (valid_url(url))
        die('Invalid URL accepted: ' + url);
if (valid_url(42) || valid_url(null))
    die('Non-string URL accepted');
if (!valid_secret('password123', 256))
    die('Valid password rejected');
if (valid_secret('password\nother', 256) || valid_secret('', 256))
    die('Invalid password accepted');
print('PASS native ucode: Dr.COM portal URL and credential validators\n');
"""

# Native-ucode integration test: real validator and save_changes logic, with
# a mock cursor that persists data between calls. Never log test credentials.
save_suite = r"""
let disk = {
    login_url: '', logout_url: '', remember: '0', auto: '0'
};
function cursor() {
    let local = {};
    for (let key in keys(disk))
        local[key] = disk[key];
    return {
        load: function(name) { return name == 'drcom'; },
        get: function(pkg, section, key) { return local[key]; },
        set: function(pkg, section, key, value) {
            if (pkg != 'drcom' || section != 'main') return false;
            local[key] = value;
            return true;
        },
        commit: function(name) {
            if (name != 'drcom') return false;
            disk = local;
            return true;
        },
        unload: function(name) { return name == 'drcom'; }
    };
}
function chmod(path, mode) { return path == '/etc/config/drcom' && mode == 384; }
let handler = {
CREDENTIAL_METHOD
};
const url1 = 'http://10.0.0.1/0.htm';
const url2 = 'http://10.0.0.1/F.htm';
const secret = 'native-test-secret';
let saved = handler.save_credentials.call({
    args: { login_url: url1, logout_url: url2, username: 'student', password: secret }
});
if (!saved.ok || saved.username != 'student' || !saved.has_password)
    die('Native ucode credential save failed: ' + json(saved));
if (saved.password != null || disk.password != secret)
    die('Password missing from UCI or leaked in response');
if (index(json(saved), secret) != -1)
    die('Credential RPC response leaked password');
let config_read = config();
if (config_read.username != 'student' || config_read.password != secret || !config_read.remember)
    die('Stored credentials did not survive UCI readback');

let reused = handler.save_credentials.call({
    args: { login_url: 'http://10.0.0.2/0.htm', logout_url: 'http://10.0.0.2/F.htm',
            username: 'student', password: '' }
});
if (!reused.ok || disk.password != secret)
    die('Empty password did not preserve saved secret');

let invalid = handler.save_credentials.call({
    args: { login_url: url1, logout_url: url2, username: 'other', password: '' }
});
if (invalid.ok || invalid.code != 'invalid_password' || disk.username != 'student')
    die('Wrongly reused password after changing the username');
print('PASS native ucode: full credential save/readback and password preservation\n');
"""
save_suite = save_suite.replace("CREDENTIAL_METHOD", credential_method)

with tempfile.TemporaryDirectory() as directory:
    script = Path(directory) / "check-drcom.uc"
    script.write_text(
        functions + "\n" + config_functions + "\n" + suite + "\n" + save_suite,
        encoding="utf-8",
    )
    subprocess.run([sys.argv[1], str(script)], check=True)

