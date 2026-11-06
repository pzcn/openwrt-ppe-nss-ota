#!/usr/bin/env python3
"""Compile a simple LuCI gettext catalog into .lmo (no extra dependencies).

The binary format matches LuCI's po2lmo.c: padded UTF-8 values, a sorted
index of (SuperFastHash(msgid), plural_index + 1, offset, size) in big-endian
uint32, then the uint32 offset of the index. This compiler intentionally
accepts only singular, non-context translations, which is all this project
needs. It never alters the applications' JS or other language catalogs.

Reference: openwrt/luci/modules/luci-base/src/{po2lmo.c,lib/lmo.c}
"""
from __future__ import annotations

import argparse
import json
import re
import struct
from pathlib import Path

M32 = 0xFFFFFFFF
FORMATS = re.compile(r"%(?:\d+\$)?[-+0-9.#]*[sd]")


def sfh_hash(data: bytes) -> int:
    """LuCI's SuperFastHash, including signed trailing chars."""
    n = len(data)
    if n == 0:
        return 0
    value = n
    pos = 0

    def word(offset: int) -> int:
        return data[offset] | (data[offset + 1] << 8)

    def signed(byte: int) -> int:
        return byte - 256 if byte >= 128 else byte

    for _ in range(n >> 2):
        value = (value + word(pos)) & M32
        temp = ((word(pos + 2) << 11) ^ value) & M32
        value = ((value << 16) ^ temp) & M32
        pos += 4
        value = (value + (value >> 11)) & M32

    rem = n & 3
    if rem == 3:
        value = (value + word(pos)) & M32
        value ^= (value << 16) & M32
        value ^= (signed(data[pos + 2]) << 18) & M32
        value = (value + (value >> 11)) & M32
    elif rem == 2:
        value = (value + word(pos)) & M32
        value ^= (value << 11) & M32
        value = (value + (value >> 17)) & M32
    elif rem == 1:
        value = (value + signed(data[pos])) & M32
        value ^= (value << 10) & M32
        value = (value + (value >> 1)) & M32

    value ^= (value << 3) & M32
    value = (value + (value >> 5)) & M32
    value ^= (value << 4) & M32
    value = (value + (value >> 17)) & M32
    value ^= (value << 25) & M32
    value = (value + (value >> 6)) & M32
    return value & M32


def validate(entries: dict[str, str], minimum: int) -> None:
    if not isinstance(entries, dict) or len(entries) < minimum:
        raise ValueError(f"Expected >= {minimum} translations; got {len(entries) if isinstance(entries, dict) else 0}")
    for key, value in entries.items():
        if not isinstance(key, str) or not key or not isinstance(value, str) or not value.strip():
            raise ValueError(f"Empty or invalid msgid/msgstr: {key!r}")
        if FORMATS.findall(key) != FORMATS.findall(value):
            raise ValueError(f"Translation changed format placeholders for {key!r}")
        if len(key.encode("utf-8")) >= 4096:
            raise ValueError(f"Message ID too large: {key[:40]!r}")


def compile_lmo(entries: dict[str, str]) -> bytes:
    """Produce a valid LuCI LMO containing only non-identical translations."""
    data = bytearray()
    index = []
    seen = set()

    for original, localized in entries.items():
        msgid = original.encode("utf-8")
        msgstr = localized.encode("utf-8")
        key_hash = sfh_hash(msgid)
        if key_hash in seen:
            raise ValueError(f"Hash collision or duplicate message: {original!r}")
        seen.add(key_hash)
        if key_hash == sfh_hash(msgstr):
            continue
        offset = len(data)
        data.extend(msgstr)
        data.extend(b"\x00" * (-len(data) % 4))
        index.append((key_hash, 1, offset, len(msgstr)))

    if not index:
        raise ValueError("No translated entries to write")
    index.sort(key=lambda e: e[0])
    data_offset = len(data)
    for row in index:
        data.extend(struct.pack(">4I", *row))
    data.extend(struct.pack(">I", data_offset))
    return bytes(data)


def lookup(lmo: bytes, original: str) -> str | None:
    """Small decoder used by CI to verify binary hash lookups."""
    offset = struct.unpack(">I", lmo[-4:])[0]
    if offset > len(lmo) - 4 or (len(lmo) - 4 - offset) % 16:
        raise ValueError("Invalid LMO index offset")
    key_hash = sfh_hash(original.encode("utf-8"))
    for pos in range(offset, len(lmo) - 4, 16):
        kid, plural, start, size = struct.unpack(">4I", lmo[pos:pos + 16])
        if kid == key_hash:
            if plural != 1 or start + size > offset:
                raise ValueError("Malformed LMO catalog")
            return lmo[start:start + size].decode("utf-8")
    return None


def build(source: Path, output: Path, minimum: int) -> int:
    entries = json.loads(source.read_text(encoding="utf-8"))
    validate(entries, minimum)
    compiled = compile_lmo(entries)
    for original, localized in entries.items():
        if localized != original and lookup(compiled, original) != localized:
            raise ValueError(f"LMO verification failed for {original!r}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(compiled)
    return len(entries)


def main() -> None:
    p = argparse.ArgumentParser(description="Build LuCI zh-cn LMO catalog")
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--min-entries", type=int, default=1)
    args = p.parse_args()
    count = build(args.input, args.output, args.min_entries)
    print(f"Generated {args.output} ({count} translated keys)")


if __name__ == "__main__":
    main()
