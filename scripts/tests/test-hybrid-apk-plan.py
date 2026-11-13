#!/usr/bin/env python3
"""Offline regression for safe official userland APK reuse planning."""
import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "hybrid_apk", ROOT / "scripts/hybrid-official-apk-plan.py")
planner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(planner)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


with tempfile.TemporaryDirectory() as tempdir:
    root = Path(tempdir)
    fixture = root / "fixture"
    target = fixture / "targets/qualcommax/ipq60xx"
    arch = fixture / "packages/aarch64_cortex-a53"
    target.mkdir(parents=True)
    arch.mkdir(parents=True)

    def asset(directory, rel, blob):
        file = directory / rel
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(blob)
        return sha(blob)

    source_target = {
        "packages/jq-1.8.1-r1.apk": asset(target, "packages/jq-1.8.1-r1.apk", b"jq binary"),
        "packages/kernel-6.18.55-1.apk": "a" * 64,
        "kmods/6.18.55-1-" + "b" * 32 + "/kmod-wireguard-1.apk": "c" * 64,
    }
    source_arch = {
        "packages/tailscale-1.90.0-r1.apk": asset(
            arch, "packages/tailscale-1.90.0-r1.apk", b"tailscale"),
        "base/ubus-2026.10-r1.apk": asset(arch, "base/ubus-2026.10-r1.apk", b"ubus"),
        "luci/luci-app-cpufreq-1.5-r1.apk": asset(
            arch, "luci/luci-app-cpufreq-1.5-r1.apk", b"luci"),
    }
    checksum_target = "".join(f"{v} *{k}\n" for k, v in source_target.items()).encode()
    checksum_arch = "".join(f"{v} *{k}\n" for k, v in source_arch.items()).encode()
    asset(target, "sha256sums", checksum_target)
    asset(arch, "sha256sums", checksum_arch)

    lock = {
        "schema": 2, "target": planner.snapshot.TARGET,
        "architecture": planner.snapshot.ARCH,
        "target_url": planner.snapshot.ROOT + "/targets/qualcommax/ipq60xx",
        "architecture_url": planner.snapshot.ROOT + "/packages/aarch64_cortex-a53",
        "target_checksums_sha256": sha(checksum_target),
        "arch_checksums_sha256": sha(checksum_arch),
        "lock_fingerprint": "1" * 64,
        "kernel_fingerprint": "2" * 64,
        "packages_fingerprint": "3" * 64,
    }

    t, a = planner.verified_indexes(lock, fixture=fixture)
    requested = planner.parse_names("""
        # custom firmware
        jq tailscale luci-app-cpufreq
        kernel kmod-wireguard
        qca-ppe-qos luci-app-sing-box
        ubus special-missing
    """)
    excluded = planner.parse_names("ubus\n")
    inv = planner.plan(lock, t, a, requested, excluded)
    m = {e["name"]: e for e in inv["packages"]}
    assert inv["status"] == "P3-inventory-only-not-build-approved"
    assert not inv["dependency_closure_verified"]
    assert "ubus" not in m
    assert m["kernel"]["status"] == "local-kernel"
    assert m["kmod-wireguard"]["status"] == "local-kernel"
    assert m["qca-ppe-qos"]["status"] == "local-custom"
    assert m["luci-app-sing-box"]["status"] == "local-custom"
    assert m["special-missing"]["status"] == "missing"
    assert m["jq"]["status"] == "official-candidate"
    assert m["tailscale"]["source"] == "arch"
    assert m["luci-app-cpufreq"]["feed"] == "luci"
    assert inv == planner.plan(lock, t, a, requested, excluded)

    manifest = planner.copy_verified_package(
        m["jq"], root / "downloads", fixture=fixture)
    assert manifest["sha256"] == sha(b"jq binary")
    assert (root / "downloads/target/packages/jq-1.8.1-r1.apk").read_bytes() == b"jq binary"
    entry = dict(m["jq"])
    entry["url"] = "https://malicious.example.org/jq.apk"
    try:
        planner.copy_verified_package(entry, root / "downloads", fixture=fixture)
    except ValueError as exc:
        assert "URL" in str(exc)
    else:
        raise AssertionError("Accepted an unapproved download host")
    try:
        planner.copy_verified_package(m["kernel"], root / "downloads", fixture=fixture)
    except ValueError:
        pass
    else:
        raise AssertionError("Allowed official kernel import")
    asset(target, "packages/jq-1.8.1-r1.apk", b"changed while mirror downloads")
    try:
        planner.copy_verified_package(m["jq"], root / "downloads", fixture=fixture)
    except ValueError as exc:
        assert "sha256" in str(exc)
    else:
        raise AssertionError("Accepted tampered APK downloaded from official URL")
    (arch / "sha256sums").write_bytes(b"changed official index")
    try:
        planner.verified_indexes(lock, fixture=fixture)
    except ValueError as exc:
        assert "changed" in str(exc)
    else:
        raise AssertionError("Accepted a rotating package repository")

    # Duplicate names are not chosen automatically across independent feeds.
    extra = dict(a)
    extra["base/tailscale-1.90.0-r1.apk"] = "e" * 64
    dup = planner.plan(lock, t, extra, ["tailscale"], [])
    assert dup["packages"][0]["status"] == "ambiguous"
    for illegal in ("../kmod-hijack", "x;rm", "kmod/root"):
        try:
            planner.parse_names(illegal)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Unsafe package selection accepted: {illegal}")

print("PASS hybrid official APK inventory and content-pinned safe download")
