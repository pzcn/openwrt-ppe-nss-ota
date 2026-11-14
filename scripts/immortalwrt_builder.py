#!/usr/bin/env python3
"""Version and integrity metadata for the reusable ImmortalWrt NSS ImageBuilder."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
# Only source-build inputs belong here; overlay, plugin selections and
# metadata scripts can change without invalidating a compiled ImageBuilder.
CORE_RECIPE = "scripts/build-immortalwrt.sh"
FIRMWARE_ONLY_BEGIN = b"# BEGIN firmware-only overlay (excluded from Builder fingerprint)\n"
FIRMWARE_ONLY_END = b"# END firmware-only overlay\n"


def core_recipe_bytes(raw: bytes) -> bytes:
    """Exclude only the explicitly marked firmware-overlay staging block.

    Changes to kernel, feeds, NSS and compile commands outside these markers
    still invalidate the ABI-matched Builder. A missing/duplicate marker is
    a hard error; never accidentally hash the wrong script portion.
    """
    if raw.count(FIRMWARE_ONLY_BEGIN) != 1 or raw.count(FIRMWARE_ONLY_END) != 1:
        raise ValueError("Firmware-only overlay markers missing or duplicated")
    before, tail = raw.split(FIRMWARE_ONLY_BEGIN, 1)
    firmware_only, after = tail.split(FIRMWARE_ONLY_END, 1)
    if not firmware_only:
        raise ValueError("Empty firmware-only overlay section")
    return before + b"# firmware-only overlay omitted from core fingerprint\n" + after


CORE_FILES = (
    CORE_RECIPE,
    "scripts/reuse-official-toolchain.sh",
    "scripts/port-ppe-nss-to-immortalwrt.sh",
    "scripts/apply-immortalwrt-compat.sh",
    "config/immortalwrt-re-ss-01.config",
)
# Package selection is not a kernel ABI constraint, but rebuilding the
# package repository after a change requires a distinct immutable Release.
PACKAGE_FILES = ("config/add.txt", "config/remove.txt")
SHA = re.compile(r"^[a-f0-9]{40}$")
FP_SHA = re.compile(r"^[a-f0-9]{64}$")
PROFILE = "jdcloud_re-ss-01"
CHANNEL = "re-ss-01-immortal-imagebuilder"


MODES = ("full", "hybrid")


def fingerprint(root: Path = ROOT, mode: str = "full") -> str:
    """Core recipe digest. Hybrid Builders hash their own, separate recipe."""
    if mode == "hybrid":
        import hybrid_builder  # local module, same directory
        return hybrid_builder.core_fingerprint(root)
    if mode != "full":
        raise ValueError(f"Unknown Builder mode: {mode}")
    digest = hashlib.sha256()
    for name in CORE_FILES:
        data = (root / name).read_bytes()
        if name == CORE_RECIPE:
            data = core_recipe_bytes(data)
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(data)
        digest.update(b"\0")
    return digest.hexdigest()


def package_fingerprint(root: Path = ROOT) -> str:
    digest = hashlib.sha256()
    for name in PACKAGE_FILES:
        digest.update(name.encode("utf-8") + b"\0")
        digest.update((root / name).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def release_tag(immortal: str, ppe: str, base: str, core: str, packages: str,
                feeds: str) -> str:
    for value in (immortal, ppe, base):
        check_sha(value)
    if any(not FP_SHA.fullmatch(value) for value in (core, packages, feeds)):
        raise ValueError("Expected SHA256 fingerprints")
    return (f"imm-builder-{immortal[:8]}-{ppe[:8]}-{base[:8]}"
            f"-g{core[:12]}-p{packages[:8]}-f{feeds[:8]}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check_sha(value: str) -> None:
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ValueError("Expected a 40-character lowercase SHA")


def check_metadata(path: Path) -> tuple[dict, bool]:
    """Validate the Builder's own provenance, not the current Git checkout.

    The newest released Builder is the firmware toolchain. The repo may have
    changed LuCI pages, OTA scripts, overlays or even compiler recipes since
    that Builder was published. Those changes must not block repacking.
    """
    doc = json.loads(path.read_text())
    if doc.get("schema") != 1 or doc.get("channel") != CHANNEL:
        raise ValueError("Wrong builder channel or schema")
    if doc.get("profile") != PROFILE or doc.get("packaging") != "standalone":
        raise ValueError("Builder target or packaging mismatch")
    if doc.get("build_mode", "full") not in MODES:
        raise ValueError("Unknown Builder build mode")
    for key in ("immortalwrt_commit", "ppe_nss_commit", "base_overlay_commit"):
        check_sha(doc.get(key, ""))
    recorded_core = doc.get("fingerprint")
    if not isinstance(recorded_core, str) or not FP_SHA.fullmatch(recorded_core):
        raise ValueError("Builder metadata has an invalid recorded core fingerprint")

    packages = doc.get("package_fingerprint")
    feeds = doc.get("feeds_fingerprint")
    legacy = packages is None and feeds is None
    if legacy:
        # Before independently-versioned package and feed metadata, the tag
        # used only source SHAs and the recorded Builder core fingerprint.
        expected = (f"imm-builder-{doc['immortalwrt_commit'][:8]}"
                    f"-{doc['ppe_nss_commit'][:8]}"
                    f"-{doc['base_overlay_commit'][:8]}"
                    f"-g{recorded_core[:12]}")
    else:
        if (not isinstance(packages, str) or not FP_SHA.fullmatch(packages)
                or not isinstance(feeds, str) or not FP_SHA.fullmatch(feeds)):
            raise ValueError("Builder metadata has incomplete package/feed revisions")
        expected = release_tag(doc["immortalwrt_commit"], doc["ppe_nss_commit"],
                               doc["base_overlay_commit"], recorded_core,
                               packages, feeds)
        if doc.get("build_mode") == "hybrid":
            expected += hybrid_tag_suffix(doc.get("official_snapshot") or {})
            check_hybrid_info(doc.get("hybrid") or {})
    if doc.get("tag") != expected:
        raise ValueError("Builder release tag and recorded provenance do not match")
    for name in ("archive", "overlay", "packages"):
        if (not isinstance(doc.get(name), str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", doc[name])):
            raise ValueError(f"Invalid Builder asset name: {name}")
        checksum = doc.get(f"{name}_sha256")
        if not isinstance(checksum, str) or not FP_SHA.fullmatch(checksum):
            raise ValueError(f"Invalid Builder asset digest: {name}")
    return doc, legacy


def tag(immortal: str, ppe: str, base: str, root: Path = ROOT,
        feeds: str = "0" * 64, mode: str = "full") -> str:
    return release_tag(immortal, ppe, base, fingerprint(root, mode),
                       package_fingerprint(root), feeds)


def hybrid_tag_suffix(snapshot: dict) -> str:
    """Hybrid Builders are also versioned by the official snapshot they mirror.

    A refresh reuses the kernel tree, PPE and recipe of its parent, so without
    this suffix a new userland would collide with the parent's tag.
    """
    fp = snapshot.get("lock_fingerprint", "")
    if not FP_SHA.fullmatch(fp):
        raise ValueError("Hybrid Builder lacks its official snapshot lock fingerprint")
    return "-s" + fp[:8]


HYBRID_KEYS = ("identity", "kernel_identity", "kernel_built_at", "keyring_commit")


def check_hybrid_info(info: dict) -> dict:
    for key in ("identity", "kernel_identity"):
        if not FP_SHA.fullmatch(str(info.get(key, ""))):
            raise ValueError(f"Hybrid metadata has an invalid {key}")
    check_sha(info.get("keyring_commit", ""))
    stamp = str(info.get("kernel_built_at", ""))
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", stamp):
        raise ValueError("Hybrid metadata has an invalid kernel_built_at")
    parent = info.get("kernel_parent")
    if parent is not None and not re.fullmatch(r"imm-builder-[A-Za-z0-9._-]+", str(parent)):
        raise ValueError("Hybrid metadata has an invalid kernel_parent")
    return {key: info[key] for key in HYBRID_KEYS} | {"kernel_parent": parent}


def snapshot_provenance(lock_path: Path) -> dict:
    lock = json.loads(lock_path.read_text())
    if lock.get("schema") != 2 or lock.get("target") != "qualcommax/ipq60xx":
        raise ValueError("Not an ipq60xx official snapshot lock")
    out = {key: lock[key] for key in (
        "snapshot_version", "target_commit", "lock_fingerprint",
        "kernel_fingerprint", "packages_fingerprint")}
    out["arch_feeds"] = {k: v["commit"] for k, v in lock["arch_feeds"].items()}
    return out


def metadata(args: argparse.Namespace) -> None:
    for value in (args.immortal, args.ppe, args.base):
        check_sha(value)
    feeds = getattr(args, "feeds", "0" * 64)
    if not FP_SHA.fullmatch(feeds):
        raise ValueError("Invalid upstream feeds digest")
    for path in (args.archive, args.overlay, args.packages):
        if not path.is_file() or path.stat().st_size < 100:
            raise ValueError(f"Missing/empty builder artifact: {path}")
    mode = getattr(args, "mode", "full")
    lock = getattr(args, "snapshot_lock", None)
    if (mode == "hybrid") != (lock is not None):
        raise ValueError("A hybrid Builder (and only one) records its official snapshot lock")
    doc = {
        "schema": 1,
        "channel": CHANNEL,
        "profile": PROFILE,
        "packaging": "standalone",
        "build_mode": mode,
        "tag": tag(args.immortal, args.ppe, args.base, feeds=feeds, mode=mode),
        "fingerprint": fingerprint(mode=mode),
        "feeds_fingerprint": feeds,
        "package_fingerprint": package_fingerprint(),
        "immortalwrt_commit": args.immortal,
        "ppe_nss_commit": args.ppe,
        "base_overlay_commit": args.base,
        "archive": args.archive.name,
        "archive_sha256": sha256(args.archive),
        "overlay": args.overlay.name,
        "overlay_sha256": sha256(args.overlay),
        "packages": args.packages.name,
        "packages_sha256": sha256(args.packages),
    }
    if lock is not None:
        doc["official_snapshot"] = snapshot_provenance(lock)
        doc["tag"] += hybrid_tag_suffix(doc["official_snapshot"])
        info = getattr(args, "hybrid_info", None)
        if info is None:
            raise ValueError("A hybrid Builder records its identity and kernel lineage")
        doc["hybrid"] = check_hybrid_info(json.loads(info.read_text()))
    args.output.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")


def verify(args: argparse.Namespace) -> None:
    doc, legacy = check_metadata(args.metadata)
    for key, path, checksum in (
        ("archive", args.archive, "archive_sha256"),
        ("overlay", args.overlay, "overlay_sha256"),
        ("packages", args.packages, "packages_sha256"),
    ):
        if path.name != doc[key] or sha256(path) != doc[checksum]:
            raise ValueError(f"Builder artifact integrity mismatch: {key}")
    print(f"Verified ImageBuilder: {doc['tag']}"
          + (" (legacy metadata)" if legacy else ""))


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="action", required=True)
    f = sub.add_parser("fingerprint")
    f.add_argument("--mode", choices=MODES, default="full")
    sub.add_parser("package-fingerprint")
    t = sub.add_parser("tag")
    for name in ("immortal", "ppe", "base"):
        t.add_argument(f"--{name}", required=True)
    t.add_argument("--feeds", default="0" * 64)
    t.add_argument("--mode", choices=MODES, default="full")
    m = sub.add_parser("metadata")
    for name in ("immortal", "ppe", "base"):
        m.add_argument(f"--{name}", required=True)
    m.add_argument("--feeds", default="0" * 64)
    m.add_argument("--mode", choices=MODES, default="full")
    m.add_argument("--snapshot-lock", type=Path)
    m.add_argument("--hybrid-info", type=Path)
    m.add_argument("--archive", required=True, type=Path)
    m.add_argument("--overlay", required=True, type=Path)
    m.add_argument("--packages", required=True, type=Path)
    m.add_argument("--output", required=True, type=Path)
    c = sub.add_parser("check")
    c.add_argument("--metadata", required=True, type=Path)
    v = sub.add_parser("verify")
    for name in ("metadata", "archive", "overlay", "packages"):
        v.add_argument(f"--{name}", required=True, type=Path)
    args = p.parse_args()
    if args.action == "fingerprint":
        print(fingerprint(mode=args.mode))
    elif args.action == "package-fingerprint":
        print(package_fingerprint())
    elif args.action == "tag":
        print(tag(args.immortal, args.ppe, args.base, feeds=args.feeds, mode=args.mode))
    elif args.action == "metadata":
        metadata(args)
    elif args.action == "check":
        doc, legacy = check_metadata(args.metadata)
        print("Compatible Builder: " + doc["tag"]
              + (" (legacy metadata)" if legacy else ""))
    else:
        verify(args)


if __name__ == "__main__":
    main()
