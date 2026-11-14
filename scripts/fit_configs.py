#!/usr/bin/env python3
"""List the /configurations nodes of a FIT image (stdlib only, no dtc needed)."""
import struct
import sys

BEGIN, END, PROP, NOP, FDT_END = 1, 2, 3, 4, 9


def configurations(blob: bytes) -> list[str]:
    magic, total, off_struct = struct.unpack_from(">III", blob, 0)
    if magic != 0xD00DFEED or total > len(blob):
        raise ValueError("not a flattened device tree / FIT image")
    pos, path, found = off_struct, [], []
    while True:
        (tok,) = struct.unpack_from(">I", blob, pos)
        pos += 4
        if tok == BEGIN:
            end = blob.index(b"\0", pos)
            name = blob[pos:end].decode()
            pos = (end + 4) & ~3
            if path == ["", "configurations"]:
                found.append(name)
            path.append(name)
        elif tok == END:
            path.pop()
        elif tok == PROP:
            length, _ = struct.unpack_from(">II", blob, pos)
            pos = (pos + 8 + length + 3) & ~3
        elif tok == NOP:
            continue
        elif tok == FDT_END:
            return found
        else:
            raise ValueError(f"bad FDT token {tok}")


if __name__ == "__main__":
    try:
        with open(sys.argv[1], "rb") as f:
            print("\n".join(configurations(f.read())))
    except (OSError, ValueError, IndexError, struct.error) as exc:
        print(f"fit_configs: {exc}", file=sys.stderr)
        sys.exit(1)
