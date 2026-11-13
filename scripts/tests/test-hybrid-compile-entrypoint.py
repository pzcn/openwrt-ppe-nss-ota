#!/usr/bin/env python3
"""Catch swallowed Bash functions, malformed regex quoting and duplicate phases."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
script = ROOT / "scripts/compile-hybrid-kernel.sh"
source = script.read_text()

assert source.count("phase() {") == 1, "phase function duplicated or missing"
expected = [
    "download", "host-tools", "toolchain", "linux-target",
    "kernel-packages", "mac80211", "nss-wifi", "qca-ppe-qos", "ppe-help",
]
actual = re.findall(r"^phase ([a-z-]+) ", source, flags=re.MULTILINE)
assert actual == expected, f"Unexpected compiler phases: {actual}"
assert "if grep -Eq '^CONFIG_(IB|IB_STANDALONE|SDK|BUILD_ALL_HOST_TOOLS)=y$' \\" in source
assert "if grep -Eq '^CONFIG_(ALL_KMODS|ALL_NONSHARED|PACKAGE_(sing-box|tailscale|ddns-go))=y$' \\" in source
assert "grep -Fqx 'toolchain=official-immortalwrt'" in source

for command in (["bash", "-n", str(script)],
                ["bash", str(script), "--self-test"]):
    finished = subprocess.run(command, capture_output=True, text=True, check=True)
    if "--self-test" in command:
        assert "PASS hybrid compile control flow" in finished.stdout

print("PASS P2 Bash compile entrypoint, single phase block, no swallowed functions")
