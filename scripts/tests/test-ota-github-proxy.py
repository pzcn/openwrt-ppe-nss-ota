#!/usr/bin/env python3
"""No-network tests: GitHub proxy rewriting, fallback, and unsafe URL rejection."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
UPDATER = ROOT / "files/usr/sbin/ppe-update"

subprocess.run(["sh", "-n", str(UPDATER)], check=True)
script = r'''
. "$PPE_UPDATE_SCRIPT"
uci() {
    case "$3" in
        ppe-update.main.github_proxy) printf '%s\n' "$PROXY_MODE" ;;
        ppe-update.main.github_proxy_url) printf '%s\n' "$CUSTOM_PROXY" ;;
        *) return 1 ;;
    esac
}
curl() { return 1; } # no external requests, even on failed stub fetch
fetch "$ORIGINAL" "$WORK/output"
'''
api = "https://api.github.com/repos/pzcn/openwrt-ppe-nss-ota/releases?per_page=100"
image = "https://github.com/pzcn/openwrt-ppe-nss-ota/releases/download/test/fw.bin"
candidates = {
    "ghfast": "https://ghfast.top",
    "ghproxy": "https://ghproxy.net",
    "gh_proxy": "https://gh-proxy.com",
    "custom": "https://my-proxy.example/gh",
}


def probe(mode, url, *, custom="", fail_direct=False, fail_proxy=False, ok=True):
    with tempfile.TemporaryDirectory() as d:
        env = dict(os.environ)
        env.update({
            "PPE_UPDATE_SCRIPT": str(UPDATER),
            "PPE_UPDATE_LIB": "1",
            "PPE_WORK": d,
            "PPE_STATE": str(Path(d) / "state"),
            "FETCH_LOG": str(Path(d) / "requested.txt"),
            "PROXY_MODE": mode,
            "CUSTOM_PROXY": custom,
            "ORIGINAL": url,
            "FAIL_DIRECT": "1" if fail_direct else "0",
            "FAIL_PROXY": "1" if fail_proxy else "0",
        })
        mock_fetch = Path(d) / "uclient-fetch"
        mock_fetch.write_text("""#!/bin/sh
printf '%s\n' "$6" >> "$FETCH_LOG"
if [ "$FAIL_DIRECT" = 1 ] && [ "$6" = "$ORIGINAL" ]; then
    exit 1
fi
if [ "$FAIL_PROXY" = 1 ] && [ "$6" != "$ORIGINAL" ]; then
    exit 1
fi
printf 'test content' > "$5"
""")
        mock_fetch.chmod(0o755)
        env["PATH"] = d + os.pathsep + env.get("PATH", "")
        result = subprocess.run(
            ["sh", "-c", script], env=env, capture_output=True, text=True)
        requests = (Path(d) / "requested.txt")
        requested = requests.read_text().splitlines() if requests.exists() else []
        assert (result.returncode == 0) == ok, (mode, url, result.stderr)
        return requested


assert probe("direct", image) == [image]
assert probe("direct", api) == [api]

for mode, base in candidates.items():
    custom = candidates["custom"] if mode == "custom" else ""
    assert probe(mode, image, custom=custom) == [base + "/" + image]
    assert probe(mode, image, custom=custom, fail_proxy=True) == [
        base + "/" + image, image
    ]
    assert probe(mode, api, custom=custom) == [api]
    assert probe(mode, api, custom=custom, fail_direct=True) == [
        api, base + "/" + api
    ]
    # The proxy is never used for non-GitHub hosts.
    other = "https://example.org/another-file.bin"
    assert probe(mode, other, custom=custom) == [other]

# Bad custom URLs are rejected before any fetch, rather than creating
# an insecure request or allowing shell/control-character injection.
for bad in ("http://proxy.example", "https://user:password@proxy.example",
            "https://proxy.example/?token=secret", "https://proxy.example/#x",
            "https://proxy.example\nhttps://other.example", "ftp://example.org",
            "https://", "https://proxy.example/;$(touch /tmp/bad)"):
    assert probe("custom", image, custom=bad, ok=False) == [], bad

assert probe("nonexistent", image, ok=False) == []
assert "sysupgrade -T" in UPDATER.read_text()
assert "image SHA256 mismatch" in UPDATER.read_text()
print("PASS: direct/preset/custom GitHub proxies, API/asset routing, fallback, validation")
