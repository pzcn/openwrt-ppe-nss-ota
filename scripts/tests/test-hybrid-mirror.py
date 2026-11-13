#!/usr/bin/env python3
"""Offline tests: P3 pinned APK mirror cannot fetch foreign ABI or stale data."""
import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "p3_mirror", ROOT / "scripts/mirror-hybrid-official-apks.py")
mirror = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mirror)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def add(folder: Path, name: str, data: bytes) -> str:
    dest = folder / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return sha(data)


with tempfile.TemporaryDirectory() as workspace:
    root = Path(workspace)
    fixture = root / "official"
    target = fixture / "targets/qualcommax/ipq60xx"
    arch = fixture / "packages/aarch64_cortex-a53"
    index_a = {
        "packages/small-1.0-r1.apk":
            add(target, "packages/small-1.0-r1.apk", b"small official APK"),
    }
    index_b = {
        "packages/alpha-2.0-r1.apk":
            add(arch, "packages/alpha-2.0-r1.apk", b"arch official APK"),
    }

    def sums(values):
        return "".join(sha + " *" + name + "\n"
                       for name, sha in sorted(values.items())).encode()

    lock = {
        "schema": 2,
        "lock_fingerprint": "b" * 64,
        "target_url": mirror.inventory.snapshot.ROOT +
                      "/targets/qualcommax/ipq60xx",
        "architecture_url": mirror.inventory.snapshot.ROOT +
                            "/packages/aarch64_cortex-a53",
        "target_checksums_sha256": add(target, "sha256sums", sums(index_a)),
        "arch_checksums_sha256": add(arch, "sha256sums", sums(index_b)),
    }

    def entry(source, feed, name, version, index):
        filename = f"{name}-{version}.apk"
        rel = f"{feed}/{filename}"
        return {
            "name": name, "version": version, "feed": feed,
            "source": source, "filename": filename, "path": rel,
            "sha256": index[rel],
            "url": (lock["target_url"] if source == "target" else
                    lock["architecture_url"]) + "/" + rel,
            "status": "official-candidate",
        }

    assets = [entry("target", "packages", "small", "1.0-r1", index_a),
              entry("arch", "packages", "alpha", "2.0-r1", index_b)]
    doc = {
        "schema": 1,
        "status": "P3-dependency-audit-not-build-approved",
        "snapshot_lock_fingerprint": lock["lock_fingerprint"],
        "mirror_plan_content_pinned": True,
        "mirror_plan_missing_archives": [],
        "root_blockers": [],
        "unresolved": [],
        "candidate_closure_size": len(assets),
        "mirror_plan": assets,
    }
    doc["audit_sha256"] = sha(mirror.canonical(doc))
    target_map, arch_map = mirror.inventory.verified_indexes(lock, fixture=fixture)
    assert len(mirror.check_audit(doc, lock, target_map, arch_map)) == 2
    out = root / "out"
    one = mirror.mirror(doc, lock, out, ["small"], fixture=fixture)
    assert one["download_count"] == 1
    assert not one["full_candidate_closure_mirrored"]
    assert not one["publishable"]
    assert not one["kernel_abi_verified"]
    assert (out / "target/packages/small-1.0-r1.apk").read_bytes() == b"small official APK"
    both = mirror.mirror(doc, lock, out, ["small", "alpha"],
                         fixture=fixture, jobs=2)
    assert both["download_count"] == 2
    assert both["full_candidate_closure_mirrored"]
    assert sorted(x["name"] for x in both["files"]) == ["alpha", "small"]

    changed = json.loads(json.dumps(doc))
    changed["mirror_plan"][0]["url"] = "https://evil.invalid/small.apk"
    changed["audit_sha256"] = sha(mirror.canonical({
        k: v for k, v in changed.items() if k != "audit_sha256"}))
    try:
        mirror.check_audit(changed, lock, target_map, arch_map)
    except ValueError as error:
        assert "URL" in str(error)
    else:
        raise AssertionError("Accepted a foreign download host")

    changed = json.loads(json.dumps(doc))
    changed["mirror_plan"][0]["name"] = "kmod-tun"
    changed["audit_sha256"] = sha(mirror.canonical({
        k: v for k, v in changed.items() if k != "audit_sha256"}))
    try:
        mirror.check_audit(changed, lock, target_map, arch_map)
    except ValueError as error:
        assert "Forbidden" in str(error)
    else:
        raise AssertionError("Accepted a foreign kernel module")

    changed = json.loads(json.dumps(doc))
    changed["candidate_closure_size"] = 3
    try:
        mirror.check_audit(changed, lock, target_map, arch_map)
    except ValueError:
        pass
    else:
        raise AssertionError("Accepted forged audit cardinality")

    add(arch, "packages/alpha-2.0-r1.apk", b"tampered package")
    try:
        mirror.mirror(doc, lock, out, ["alpha"], fixture=fixture)
    except ValueError as error:
        assert "sha256" in str(error)
    else:
        raise AssertionError("Accepted damaged official APK")
    add(arch, "packages/alpha-2.0-r1.apk", b"arch official APK")

    (arch / "sha256sums").write_text("rotated by buildbot")
    try:
        mirror.mirror(doc, lock, out, ["small"], fixture=fixture)
    except ValueError as error:
        assert "changed" in str(error)
    else:
        raise AssertionError("Accepted rotated official snapshot")

print("PASS Hybrid P3 mirror: pinning, offline downloads, source checks, local ABI exclusion")
