#!/usr/bin/env python3
"""Offline tests: complete mirror inventory and every APK file must be pinned."""
import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "hybrid_mirror_verify", ROOT / "scripts/verify-hybrid-official-mirror.py")
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def signed(doc: dict, key: str) -> dict:
    value = json.loads(json.dumps(doc))
    value[key] = sha(v.mirror_lib.canonical(value))
    return value

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp) / "apks"
    root.mkdir()
    filename = "etherwake-1.09-r2.apk"
    rel = "arch/packages/" + filename
    path = root / rel
    path.parent.mkdir(parents=True)
    path.write_bytes(b"official userland demo")
    lock = {"schema": 2, "lock_fingerprint": "a" * 64}
    planned = {
        "name": "etherwake", "source": "arch", "feed": "packages",
        "filename": filename, "sha256": sha(path.read_bytes())
    }
    audit = signed({
        "schema": 1,
        "status": "P3-dependency-audit-not-build-approved",
        "snapshot_lock_fingerprint": lock["lock_fingerprint"],
        "mirror_plan_content_pinned": True,
        "mirror_plan_missing_archives": [],
        "root_blockers": [], "unresolved": [],
        "mirror_plan": [planned],
    }, "audit_sha256")
    manifest = signed({
        "schema": 1,
        "status": "P3-untrusted-userland-mirror-test-only",
        "snapshot_lock_fingerprint": lock["lock_fingerprint"],
        "dependency_audit_sha256": audit["audit_sha256"],
        "download_sha256_verified": True,
        "download_count": 1,
        "full_candidate_closure_mirrored": True,
        "kernel_abi_verified": False,
        "publishable": False,
        "files": [{
            "name": "etherwake", "source": "arch", "feed": "packages",
            "filename": filename, "relative_path": rel,
            "sha256": planned["sha256"]
        }],
    }, "manifest_sha256")

    def rejected(a, m, expected: str) -> None:
        try:
            v.check(lock, a, m, root)
        except ValueError as err:
            assert expected in str(err), str(err)
        else:
            raise AssertionError("Unsafe mirror accepted: " + expected)

    ok = v.check(lock, audit, manifest, root)
    assert ok["verified_apks"] == 1
    assert ok["total_bytes"] == len(b"official userland demo")
    assert ok["full_candidate_closure_mirrored"]
    assert not ok["publishable"]
    assert not ok["kernel_abi_verified"]

    path.write_bytes(b"tampered APK")
    rejected(audit, manifest, "corrupted")
    path.write_bytes(b"official userland demo")

    extra = root / "arch/base/foreign-1.0-r1.apk"
    extra.parent.mkdir(parents=True)
    extra.write_bytes(b"foreign")
    rejected(audit, manifest, "untracked")
    extra.unlink()

    path.unlink()
    path.symlink_to(Path(tmp) / "outside")
    rejected(audit, manifest, "Symlink")
    path.unlink()
    path.write_bytes(b"official userland demo")

    fake = json.loads(json.dumps(manifest))
    fake["files"][0]["sha256"] = "f" * 64
    fake = signed({k: val for k, val in fake.items()
                   if k != "manifest_sha256"}, "manifest_sha256")
    rejected(audit, fake, "provenance")

    partial = json.loads(json.dumps(manifest))
    partial["full_candidate_closure_mirrored"] = False
    partial = signed({k: val for k, val in partial.items()
                      if k != "manifest_sha256"}, "manifest_sha256")
    rejected(audit, partial, "partial")
    assert v.check(lock, audit, partial, root, require_full=False)["verified_apks"] == 1

    changed = json.loads(json.dumps(audit))
    changed["snapshot_lock_fingerprint"] = "b" * 64
    changed = signed({k: val for k, val in changed.items()
                      if k != "audit_sha256"}, "audit_sha256")
    rejected(changed, manifest, "Snapshot")

print("PASS full official mirror integrity, tampering, symlinks and partial closure gates")
