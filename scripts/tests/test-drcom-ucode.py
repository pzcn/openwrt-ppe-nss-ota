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
with tempfile.TemporaryDirectory() as directory:
    script = Path(directory) / "check-drcom.uc"
    script.write_text(functions + "\n" + suite, encoding="utf-8")
    subprocess.run([sys.argv[1], str(script)], check=True)
