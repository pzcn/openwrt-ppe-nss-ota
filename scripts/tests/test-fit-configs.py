#!/usr/bin/env python3
import importlib.util
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("fit", ROOT / "scripts/fit_configs.py")
fit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fit)


def node(name, *children, props=()):
    raw = name.encode() + b"\0"
    out = struct.pack(">I", 1) + raw + b"\0" * (-len(raw) % 4)
    for nameoff, data in props:
        out += struct.pack(">III", 3, len(data), nameoff) + data + b"\0" * (-len(data) % 4)
    for c in children:
        out += c
    return out + struct.pack(">I", 2)


def fdt(root):
    struct_blk = root + struct.pack(">I", 9) + struct.pack(">I", 4)  # END + trailing NOP
    strings = b"description\0default\0"
    off_struct = 40 + 16
    off_strings = off_struct + len(struct_blk)
    total = off_strings + len(strings)
    hdr = struct.pack(">10I", 0xD00DFEED, total, off_struct, off_strings, 40, 17, 16, 0,
                      len(strings), len(struct_blk))
    return hdr + b"\0" * 16 + struct_blk + strings


blob = fdt(node("", node("images", node("kernel-1", props=[(0, b"Linux\0")]),
                         node("fdt-1")),
                node("configurations", node("config@cp03-c2", props=[(0, b"x\0")]),
                     node("config@cp01-c1"), props=[(12, b"config@cp03-c2\0")])))
assert fit.configurations(blob) == ["config@cp03-c2", "config@cp01-c1"]
with tempfile.TemporaryDirectory() as tmp:
    f = Path(tmp) / "x.itb"
    f.write_bytes(blob)
    out = subprocess.run([sys.executable, str(ROOT / "scripts/fit_configs.py"), str(f)],
                         check=True, capture_output=True, text=True).stdout.split()
    assert out == ["config@cp03-c2", "config@cp01-c1"], out
    f.write_bytes(b"not a fit at all, just some bytes")
    assert subprocess.run([sys.executable, str(ROOT / "scripts/fit_configs.py"), str(f)],
                          capture_output=True).returncode == 1
for script in ("scripts/build-immortalwrt-hybrid.sh", "scripts/repack-immortalwrt.sh"):
    text = (ROOT / script).read_text()
    assert "fit_configs.py" in text and "fdtget" not in text, script
print("PASS FIT configuration listing without dtc")
