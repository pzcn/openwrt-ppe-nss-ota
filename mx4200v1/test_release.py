#!/usr/bin/env python3
"""Offline, no-GitHub validation for MX-only immutable Builder/OTA releases."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "mx4200v1/publish-release.sh"
WORKFLOW = ROOT / ".github/workflows/mx4200v1-publish.yml"

assert "gh release create" in SCRIPT.read_text()
assert "--prerelease --latest=false" in SCRIPT.read_text()
assert "Only main may publish" in SCRIPT.read_text()
assert 'tag == $tag' in SCRIPT.read_text()
assert "workflow_dispatch:" in WORKFLOW.read_text()
assert "confirm_publish:" in WORKFLOW.read_text()
assert "mx4200v1-hybrid-*" in WORKFLOW.read_text()
assert "merge-multiple: true" in WORKFLOW.read_text()


def put(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def json_put(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, indent=2) + "\n")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def invoke(kind: str, path: Path, valid: bool = True):
    env = dict(os.environ, MX_VERIFY_ONLY="true")
    res = subprocess.run(["bash", str(SCRIPT), kind, str(path)],
                         env=env, capture_output=True, text=True)
    if valid:
        assert res.returncode == 0, (res.returncode, res.stderr)
        assert "verified" in res.stdout
    else:
        assert res.returncode != 0, (kind, res.stdout)
    return res


with tempfile.TemporaryDirectory(prefix="mx4200-release-test-") as temp:
    base = Path(temp)
    builder = base / "builder"
    builder.mkdir()
    ib = "immortalwrt-imagebuilder-qualcommax-ipq807x.Linux-x86_64.tar.zst"
    sdk = "immortalwrt-sdk-qualcommax-ipq807x_gcc-test.Linux-x86_64.tar.zst"
    meta = {
        "schema": 1, "target": "qualcommax/ipq807x",
        "profile": "linksys_mx4200v1",
        "identity": "a" * 64, "kernel_identity": "b" * 64,
        "immortalwrt_commit": "c" * 40, "ppe_nss_commit": "d" * 40,
        "hardware_tested": False, "publishable": False,
        "imagebuilder": ib, "sdk": sdk,
    }
    json_put(builder / "mx4200v1-hybrid-metadata.json", meta)
    json_put(builder / "snapshot-lock.json", {
        "schema": 2, "target": "qualcommax/ipq807x",
        "architecture": "aarch64_cortex-a53",
    })
    json_put(builder / "official-apks.json", {"mirror": []})
    json_put(builder / "local-plan.json", {"local_packages": []})
    for name in (ib, sdk, "base-overlay.tar.gz", "local-apks.txt",
                 "imagebuilder-packages.txt", "source-commits.txt"):
        put(builder / name, ("verified archive:" + name).encode())
    with (builder / "sha256sums").open("w") as out:
        for p in builder.iterdir():
            if p.is_file() and p.name != "sha256sums":
                out.write(f"{sha(p)}  {p.name}\n")
    invoke("builder", builder)

    # Foreign target and altered archive are never published.
    bad = dict(meta, target="qualcommax/ipq60xx")
    json_put(builder / "mx4200v1-hybrid-metadata.json", bad)
    invoke("builder", builder, False)
    json_put(builder / "mx4200v1-hybrid-metadata.json", meta)
    with (builder / ib).open("ab") as out:
        out.write(b"tampered")
    invoke("builder", builder, False)

    firmware = base / "firmware"
    firmware.mkdir()
    prefix = "immortalwrt-qualcommax-ipq807x-linksys_mx4200v1"
    img = prefix + "-squashfs-sysupgrade.bin"
    factory = prefix + "-squashfs-factory.bin"
    manifest = prefix + ".manifest"
    fwmeta = prefix + "-squashfs-sysupgrade.metadata.json"
    put(firmware / img, b"sysupgrade" * 120_000)
    put(firmware / factory, b"factory" * 150_000)
    put(firmware / manifest, b"base-files - 1.0\nkernel - 6.18\n")
    json_put(firmware / fwmeta, {
        "metadata_version": "1.1", "compat_version": "1.0",
        "supported_devices": ["linksys,mx4200v1"],
    })
    json_put(firmware / "snapshot-lock.json", {
        "schema": 2, "target": "qualcommax/ipq807x",
        "architecture": "aarch64_cortex-a53",
    })
    tag = "imm-mx4200v1-abcdef01-12345678-g00112233-b123456"
    ota = {
        "schema": 1, "channel": "mx4200v1-immortal-ppe-nss",
        "repository": "pzcn/openwrt-ppe-nss-ota",
        "board": "linksys,mx4200v1", "profile": "linksys_mx4200v1",
        "group": "ipq807x-6m", "target": "qualcommax/ipq807x",
        "tag": tag, "build": 123456,
        "image": img, "manifest": manifest,
        "image_sha256": sha(firmware / img), "image_size": (firmware / img).stat().st_size,
        "manifest_sha256": sha(firmware / manifest),
    }
    json_put(firmware / "ota.json", ota)
    json_put(firmware / "mx4200v1-ota-identity.json", {
        "schema": 1, "device": "mx4200v1", "tag": tag,
    })
    with (firmware / "sha256sums").open("w") as out:
        for p in firmware.iterdir():
            if p.is_file() and p.name != "sha256sums":
                out.write(f"{sha(p)}  {p.name}\n")
    invoke("firmware", firmware)

    # OTA never recognizes Arthur board identity or a tampered image.
    bad = dict(ota, board="jdcloud,re-ss-01")
    json_put(firmware / "ota.json", bad)
    invoke("firmware", firmware, False)
    json_put(firmware / "ota.json", ota)
    with (firmware / img).open("ab") as out:
        out.write(b"tampered")
    invoke("firmware", firmware, False)

print("PASS: MX4200 v1 immutable Builder and OTA prerelease contracts")
