#!/usr/bin/env python3
"""Pin an official sing-box alpha binary directly in firmware SquashFS FILES.

Not a runtime overlayfs upgrade. The existing sing-box APK database version
remains unchanged because the firmware overrides its executable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import struct
import tarfile

VERSION = "1.15.0-alpha.13"
ASSET = f"sing-box-{VERSION}-linux-arm64-musl.tar.gz"
ARCHIVE_SHA256 = "38508bd270d78bbc1838e459d2f1b3b0cab5d3658592d8f1f4e383c40935d757"
MAX_ARCHIVE = 64 * 1024 * 1024
MAX_BINARY = 120 * 1024 * 1024


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validated_core(archive: Path, expected: str) -> bytes:
    if not archive.is_file() or archive.is_symlink() or not (0 < archive.stat().st_size <= MAX_ARCHIVE):
        raise ValueError("Untrusted or oversized sing-box prerelease archive")
    if sha256(archive) != expected:
        raise ValueError("Official sing-box asset SHA256 mismatch")
    members = []
    with tarfile.open(archive, mode="r:gz") as tar:
        for entry in tar.getmembers():
            parts = PurePosixPath(entry.name)
            if parts.is_absolute() or ".." in parts.parts or "\\" in entry.name:
                raise ValueError("Unsafe upstream archive path")
            if parts.name == "sing-box":
                if not entry.isfile() or entry.size <= 0 or entry.size > MAX_BINARY:
                    raise ValueError("Unsafe sing-box executable type/size")
                if len(parts.parts) != 2 or not parts.parts[0].startswith("sing-box-"):
                    raise ValueError("Unexpected upstream archive executable path")
                members.append(entry)
        if len(members) != 1:
            raise ValueError("Expected exactly one official sing-box binary")
        stream = tar.extractfile(members[0])
        if stream is None:
            raise ValueError("Cannot read binary from upstream archive")
        binary = stream.read(MAX_BINARY + 1)
    if len(binary) != members[0].size or len(binary) > MAX_BINARY:
        raise ValueError("Truncated or oversized executable")
    if binary[:4] != b"\x7fELF" or binary[4] != 2 or binary[5] != 1:
        raise ValueError("Executable must be little-endian ELF64")
    if struct.unpack_from("<H", binary, 18)[0] != 183:
        raise ValueError("Executable must be AArch64")
    return binary


def stage(archive: Path, overlay: Path, metadata: Path, expected: str = ARCHIVE_SHA256) -> dict:
    binary = validated_core(archive, expected)
    if overlay.is_symlink() or not overlay.is_dir():
        raise ValueError("Invalid firmware staging directory")
    exe = overlay / "usr/bin/sing-box"
    if exe.is_symlink():
        raise ValueError("Refusing symlinked sing-box destination")
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(binary)
    exe.chmod(0o755)
    details = {
        "schema": 1, "version": VERSION, "release": f"v{VERSION}",
        "source": "SagerNet/sing-box official pre-release",
        "asset": ASSET, "asset_sha256": expected,
        "binary_sha256": hashlib.sha256(binary).hexdigest(),
        "architecture": "aarch64", "placement": "firmware-squashfs",
        "apk_note": "The firmware overrides the executable; the base APK metadata retains its feed version.",
    }
    content = json.dumps(details, indent=2, sort_keys=True) + "\n"
    record = overlay / "etc/sing-box-core.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(content)
    metadata.parent.mkdir(parents=True, exist_ok=True)
    metadata.write_text(content)
    if sha256(exe) != details["binary_sha256"]:
        raise ValueError("Staged core SHA256 mismatch")
    return details


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(stage(args.archive, args.overlay, args.metadata), indent=2))


if __name__ == "__main__":
    main()
