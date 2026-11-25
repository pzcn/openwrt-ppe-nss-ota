#!/usr/bin/env python3
"""Offline verify of WMA301 initramfs FIT with a RAM-only DTB.

Validates the FIT payload/hash and board DTB; cannot prove a physical boot.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from fit_inspect import inspect, image_payload, parse_fit, text_prop
from verify import BOARDS, PARTS

EXPECTED_NAME = "immortalwrt-mediatek-filogic-tplink_wma301-v2-initramfs-recovery.itb"
MAX_SIZE = 30 * 1024 * 1024  # 0x46000000 TFTP load below typical 0x48000000 kernel load


def require(value: bool, reason: str) -> None:
    if not value:
        raise RuntimeError(reason)


def payload(binary: bytes, total: int, tree: dict, name: str) -> bytes:
    properties = tree.get("/images/" + name)
    require(properties is not None, f"missing FIT image {name}")
    contents, _, error = image_payload(properties, binary, total)
    require(contents is not None and error is None, f"invalid FIT image {name}: {error}")
    return contents


def inspect_ramboot(path: Path) -> dict:
    require(path.name == EXPECTED_NAME, f"unexpected recovery image name: {path.name}")
    require(path.stat().st_size <= MAX_SIZE,
            "recovery FIT exceeds 30 MiB RAM boot address budget")
    report = inspect(path)
    require(report["inspection_ok"], f"invalid FIT hashes or configuration: {report['problems']}")
    require(not report["signature_nodes_detected"], "unexpected FIT signature")

    blob = path.read_bytes()
    total, tree = parse_fit(blob)
    default = text_prop(tree.get("/configurations", {}).get("default"))
    require(isinstance(default, str) and default in report["configurations"],
            "FIT default configuration missing")
    cfg = tree["/configurations/" + default]
    require("loadables" not in cfg, "RAM FIT must not reference persistent rootfs loadables")
    for item in ("kernel", "fdt", "ramdisk"):
        require(item in cfg, "RAM FIT missing " + item)
        ref = text_prop(cfg[item])
        require(isinstance(ref, str), "invalid FIT reference " + item)
        minimum = 1000 if item == "fdt" else 100_000
        require(len(payload(blob, total, tree, ref)) > minimum,
                "empty FIT " + item)

    dtb = payload(blob, total, tree, text_prop(cfg["fdt"]))
    _, nodes = parse_fit(dtb)
    compatible = nodes.get("/", {}).get("compatible", b"").split(b"\0")
    require(all(name in compatible for name in BOARDS),
            "RAM recovery must support both WMA301 revisions")
    chosen = nodes.get("/chosen", {})
    args = chosen.get("bootargs-append", b"")
    require(b"root=/dev/ram0" in args and b"fit0" not in args,
            "RAM DTB must select ram0, not fit0")
    require("rootdisk" not in chosen, "RAM DTB still references NAND/UBI rootdisk")
    require(not any(v == b"linux,ubi\0" for props in nodes.values()
                    for k, v in props.items() if k == "compatible"),
            "RAM DTB still requests UBI auto-attach")
    labels = {props["label"][:-1].decode("ascii", "replace")
              for props in nodes.values() if "label" in props and
              props["label"].endswith(b"\0")}
    require(all(name in labels for name, _, _, _ in PARTS),
            "expected preserved WMA301 NAND partitions for diagnostics")

    output = {
        "file": path.name,
        "sha256": hashlib.sha256(blob).hexdigest(),
        "bytes": len(blob),
        "mode": "initramfs-ram-only",
        "compatible": [b.decode() for b in BOARDS],
        "bootargs": "root=/dev/ram0",
        "ubi_autoattach": False,
        "offline_validation": "PASS",
        "hardware_validation": "NOT_TESTED",
    }
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--upstream-sha", required=True)
    parser.add_argument("--local-sha", required=True)
    options = parser.parse_args()
    fits = sorted(options.images.glob("*tplink_wma301-v2*recovery.itb"))
    require(len(fits) == 1, f"expected exactly one WMA301 recovery FIT, found {len(fits)}")
    require(not list(options.images.glob("*tplink_wma301-v2*sysupgrade*")),
            "RAM-only build unexpectedly emitted a flashable sysupgrade image")
    record = inspect_ramboot(fits[0])
    options.output.mkdir(parents=True, exist_ok=True)
    out_file = options.output / EXPECTED_NAME
    out_file.write_bytes(fits[0].read_bytes())
    manifest = {"source": "immortalwrt/immortalwrt", "upstream_sha": options.upstream_sha,
                "local_sha": options.local_sha, "recovery": record,
                "warning": "Boot via U-Boot only; never sysupgrade this ITB. Physical boot untested."}
    (options.output / "manifest-ramboot.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (options.output / "SHA256SUMS").write_text(f"{record['sha256']}  {EXPECTED_NAME}\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
