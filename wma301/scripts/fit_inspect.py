#!/usr/bin/env python3
"""Inspect FIT/ITB structure, embedded/external payloads and image hashes offline.

This does not validate bootloader compatibility, authenticity or safe installation.
"""
import argparse
import hashlib
import json
import struct
import zlib
from pathlib import Path

MAGIC = 0xd00dfeed
BEGIN, END, PROP, NOP, FINISH = 1, 2, 3, 4, 9
MAX_SIZE = 192 * 1024 * 1024

def be32(raw, pos=0):
    if pos < 0 or pos + 4 > len(raw):
        raise ValueError("truncated big-endian integer")
    return struct.unpack_from(">I", raw, pos)[0]

def align4(value):
    return (value + 3) & ~3

def fdt_text(data, pos):
    if not 0 <= pos < len(data):
        raise ValueError("FDT string offset outside block")
    end = data.find(b"\0", pos)
    if end < 0:
        raise ValueError("unterminated FDT string")
    return data[pos:end].decode("utf-8", "replace")

def parse_fit(data):
    if len(data) < 40 or be32(data, 0) != MAGIC:
        raise ValueError("not a FIT image (FDT magic missing)")
    (total, struct_off, strings_off, _reserve, _ver, _last, _cpu,
     strings_len, struct_len) = struct.unpack_from(">9I", data, 4)
    if total < 40 or total > len(data):
        raise ValueError("invalid FDT total length")
    if (struct_off < 40 or struct_off + struct_len > total or
            strings_off + strings_len > total):
        raise ValueError("FDT structure/strings out of bounds")
    strings = data[strings_off:strings_off + strings_len]
    stack, nodes = [], {}
    pos, end = struct_off, struct_off + struct_len
    ended = False
    while pos + 4 <= end:
        token = be32(data, pos)
        pos += 4
        if token == BEGIN:
            name_end = data.find(b"\0", pos, end)
            if name_end < 0:
                raise ValueError("unterminated node name")
            stack.append(data[pos:name_end].decode("utf-8", "replace"))
            nodes.setdefault("/".join(stack) or "/", {})
            pos = align4(name_end + 1)
        elif token == END:
            if not stack:
                raise ValueError("unbalanced END_NODE")
            stack.pop()
        elif token == PROP:
            if not stack or pos + 8 > end:
                raise ValueError("truncated FDT property header")
            n, name_off = be32(data, pos), be32(data, pos + 4)
            pos += 8
            if pos + n > end:
                raise ValueError("FDT property exceeds structure")
            key = fdt_text(strings, name_off)
            nodes["/".join(stack) or "/"][key] = data[pos:pos + n]
            pos = align4(pos + n)
        elif token == NOP:
            continue
        elif token == FINISH:
            if stack:
                raise ValueError("unclosed FDT nodes")
            ended = True
            break
        else:
            raise ValueError("unknown FDT token %d" % token)
    if not ended:
        raise ValueError("FDT_END token missing")
    return total, nodes

def text_prop(raw, numeric=False):
    if raw is None:
        return None
    if numeric:
        return '0x%x' % be32(raw)
    if raw.endswith(b"\0") and all(x == 0 or 32 <= x < 127 for x in raw):
        return raw.rstrip(b"\0").decode("ascii", "replace")
    if len(raw) == 4:
        return "0x%x" % be32(raw)
    return raw.hex() if len(raw) <= 32 else "%d binary bytes" % len(raw)

def hash_check(algo, payload, expected):
    if payload is None:
        return {"algorithm": algo, "status": "missing-payload"}
    if algo == "crc32":
        actual = struct.pack(">I", zlib.crc32(payload) & 0xffffffff)
    elif algo in ("sha1", "sha256", "sha384", "sha512", "md5"):
        actual = hashlib.new(algo, payload).digest()
    else:
        return {"algorithm": algo, "status": "unsupported"}
    return {"algorithm": algo, "status": "pass" if actual == expected else "FAIL",
            "expected": expected.hex(), "computed": actual.hex()}

def image_payload(props, data, total):
    embedded = props.get("data")
    if embedded is not None:
        return embedded, "embedded", None
    if "data-position" in props or "data-offset" in props:
        n = props.get("data-size")
        if n is None or len(n) != 4:
            return None, "external", "external payload missing 32-bit data-size"
        size = be32(n)
        if "data-position" in props:
            address = be32(props["data-position"])
        else:
            address = total + be32(props["data-offset"])
        if address > len(data) or size > len(data) - address:
            return None, "external", "external payload exceeds file size"
        return data[address:address + size], "external", None
    return None, "absent", "image has no data or external reference"

def inspect(path):
    data = Path(path).read_bytes()
    if len(data) > MAX_SIZE:
        raise ValueError("file exceeds 64 MiB read-only inspection limit")
    total, nodes = parse_fit(data)
    images, configs, problems = {}, {}, []
    for node, props in nodes.items():
        parts = node.strip("/").split("/")
        if len(parts) == 2 and parts[0] == "images":
            name = parts[1]
            payload, kind, error = image_payload(props, data, total)
            images[name] = {
                "properties": {
                    k: text_prop(props.get(k), numeric=k in ("load", "entry")) for k in
                    ("type", "arch", "os", "compression", "load", "entry", "description")
                    if k in props
                },
                "data_size": len(payload) if payload is not None else None,
                "payload_kind": kind, "checks": [],
            }
            if error:
                problems.append(name + ": " + error)
        if len(parts) == 2 and parts[0] == "configurations":
            configs[parts[1]] = {
                k: text_prop(v) for k, v in props.items()
                if k in ("kernel", "fdt", "ramdisk", "description", "loadables")
            }
    for node, props in nodes.items():
        parts = node.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "images" and parts[1] in images:
            if parts[2].startswith("hash"):
                parent = nodes.get("/images/" + parts[1], {})
                payload, _, _ = image_payload(parent, data, total)
                algo = text_prop(props.get("algo"))
                digest = props.get("value")
                if not algo or digest is None:
                    images[parts[1]]["checks"].append(
                        {"algorithm": algo, "status": "incomplete-hash-node"})
                else:
                    images[parts[1]]["checks"].append(hash_check(algo, payload, digest))
    if not images:
        problems.append("FIT has no images")
    if not configs:
        problems.append("FIT has no configurations")
    for name, image in images.items():
        if not image["checks"]:
            problems.append(name + ": no image hash nodes")
    signatures = sorted(p for p in nodes if p.split("/")[-1].startswith("signature"))
    default = text_prop(nodes.get("/configurations", {}).get("default"))
    if default is not None and default not in configs:
        problems.append("default FIT config not present")
    for confname, conf in configs.items():
        for key in ("kernel", "fdt", "ramdisk"):
            if conf.get(key) and conf[key] not in images:
                problems.append(confname + ": references missing " + key + " image")
    checks = [c for im in images.values() for c in im["checks"]]
    return {
        "file": str(path), "file_size": len(data), "fit_totalsize": total,
        "images": images, "configurations": configs, "default_configuration": default,
        "signature_nodes_detected": signatures,
        "failed_hashes": sum(c["status"] == "FAIL" for c in checks),
        "indeterminate_hashes": sum(c["status"] not in ("pass", "FAIL") for c in checks),
        "problems": problems,
        "inspection_ok": not problems and all(c["status"] == "pass" for c in checks),
        "disclaimer": "An integrity pass does not establish image authenticity, stock boot compatibility, or safe NAND installation.",
    }

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("itb", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = inspect(args.itb)
    result = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(result + "\n", encoding="utf-8")
    print(result)
    if not report["inspection_ok"]:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
