#!/usr/bin/env python3
"""Offline checks for official Snapshot lock, content digests and race detection."""
import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "snapshot", ROOT / "scripts/resolve-immortalwrt-snapshot.py")
snap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snap)

SOURCE = "e695009c15" + "e" * 30
KMOD_ABI = "6.18.1-1-" + "a" * 32


def sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def put_index(folder: Path, relative: str, blob: bytes) -> str:
    path = folder / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(blob)
    return sha(blob) + " *" + relative


def rewrite_sums(folder: Path, entries: list[str]) -> None:
    (folder / "sha256sums").write_text("\n".join(entries) + "\n")


def fixture(root: Path, *, kernel_abi: str = KMOD_ABI) -> tuple[Path, Path]:
    target = root / "targets/qualcommax/ipq60xx"
    arch = root / "packages/aarch64_cortex-a53"
    target.mkdir(parents=True)
    arch.mkdir(parents=True)
    feeds = (
        "src-git packages https://github.com/immortalwrt/packages.git^" + "a" * 40 + "\n"
        "src-git luci https://github.com/immortalwrt/luci.git^" + "b" * 40 + "\n"
        "src-git routing https://github.com/openwrt/routing.git^" + "c" * 40 + "\n"
        "src-git telephony https://github.com/openwrt/telephony.git^" + "d" * 40 + "\n"
    )
    archfeeds = (
        "src-git-full base https://github.com/immortalwrt/immortalwrt.git^" + "e" * 40 + "\n"
        + feeds
    )
    files = {
        "version.buildinfo": b"r42542-e695009c15\n",
        "feeds.buildinfo": feeds.encode(),
        "config.buildinfo": (
            b"CONFIG_TARGET_qualcommax=y\n"
            b"CONFIG_TARGET_qualcommax_ipq60xx=y\n"
            b"CONFIG_TARGET_DEVICE_qualcommax_ipq60xx_DEVICE_jdcloud_re-ss-01=y\n"
        ),
    }
    target_entries = [put_index(target, name, blob) for name, blob in files.items()]
    target_entries += [
        put_index(target, "packages/packages.adb", b"binary target apk index"),
        put_index(target, f"kmods/{kernel_abi}/packages.adb", b"binary kmod index"),
        put_index(target, "packages/sample-1.0-r1.apk", b"tarred target apk"),
        put_index(target, "packages/libc-1.2.6-r5.apk", b"official libc"),
    ]
    for kind in ("imagebuilder", "sdk", "toolchain"):
        target_entries.append(
            "1" * 64 + " *immortalwrt-" + kind +
            "-qualcommax-ipq60xx_gcc-14.4.0_musl.Linux-x86_64.tar.zst")
    rewrite_sums(target, target_entries)
    arch_entries = [put_index(arch, "feeds.conf", archfeeds.encode())]
    for name in snap.ARCH_REPOS:
        arch_entries.append(put_index(arch, f"{name}/packages.adb", name.encode()))
    arch_entries.append(put_index(arch, "packages/demo-1.2~git-r1.apk", b"arch apk"))
    rewrite_sums(arch, arch_entries)
    commits = root / "github-commits"
    commits.mkdir(parents=True, exist_ok=True)
    (commits / "e695009c15.json").write_text(json.dumps({"sha": SOURCE}))
    return target, arch


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    target, arch = fixture(root)
    first = snap.resolve(root)
    assert first == snap.resolve(root), "A lock must be deterministic"
    assert first["schema"] == 2
    assert first["target"] == "qualcommax/ipq60xx"
    assert first["target_commit"] == SOURCE
    assert first["target_commit_prefix"] == "e695009c15"
    assert first["official_kernel_abi"] == KMOD_ABI
    assert first["compatibility"]["ppe_port_kernel_line_matches"]
    assert not first["compatibility"]["checksum_signature_verified"]
    assert first["package_counts"] == {"target_apks": 2, "arch_apks": 1}
    assert first["libc_version"] == "1.2.6-r5"
    assert set(first["package_indexes"]["architecture"]) == set(snap.ARCH_REPOS)
    assert set(first["assets"]) == {"imagebuilder", "sdk", "toolchain"}
    assert snap.classify(first, first) == "unchanged"
    assert snap.classify(None, first) == "kernel-or-target"

    # Arch package content changed, despite identical source-feed revisions.
    new_entry = put_index(arch, "packages/demo-1.2~git-r1.apk", b"recompiled arch apk")
    lines = (arch / "sha256sums").read_text().splitlines()
    rewrite_sums(arch, [new_entry if s.endswith("*packages/demo-1.2~git-r1.apk")
                         else s for s in lines])
    arch_change = snap.resolve(root)
    assert snap.classify(first, arch_change) == "packages-only"
    assert arch_change["kernel_fingerprint"] == first["kernel_fingerprint"]
    assert arch_change["packages_fingerprint"] != first["packages_fingerprint"]

    # Mutating an index without updating the advertised hashes must fail.
    (arch / "base/packages.adb").write_bytes(b"altered unsigned package index")
    try:
        snap.resolve(root)
    except ValueError as exc:
        assert "package index hash changed" in str(exc)
    else:
        raise AssertionError("Accepted a tampered APK index")
    put_index(arch, "base/packages.adb", b"base")

    (target / "version.buildinfo").write_text("r42543-fffffffffff\n")
    try:
        snap.resolve(root)
    except ValueError as exc:
        assert "Checksum mismatch" in str(exc)
    else:
        raise AssertionError("Accepted a changed target revision without checksum update")

    clean_root = root / "clean"
    clean, _ = fixture(clean_root)
    (clean / "sha256sums").write_text((clean / "sha256sums").read_text().replace(
        " *version.buildinfo", " *../version.buildinfo"))
    try:
        snap.resolve(clean_root)
    except ValueError as exc:
        assert "Unsafe checksum path" in str(exc)
    else:
        raise AssertionError("Accepted checksum path traversal")

    # A kernel ABI mismatch is an explicit P2 hard blocker.
    incompatible = root / "old-kernel"
    fixture(incompatible, kernel_abi="6.12.94-1-" + "c" * 32)
    legacy = snap.resolve(incompatible)
    assert not legacy["compatibility"]["ppe_port_kernel_line_matches"]
    assert snap.classify(first, legacy) == "kernel-or-target"

    # Simulate Snapshot rotating while the resolver reads target + arch files.
    original_fetch = snap.fetch
    reads = [0]
    def rotating_fetch(url: str, *, fixture: Path | None = None):
        if url.endswith("/sha256sums") and "/targets/" in url:
            reads[0] += 1
            if reads[0] >= 2:
                return b"updated by a concurrently publishing buildbot"
        return original_fetch(url, fixture=fixture)
    snap.fetch = rotating_fetch
    try:
        snap.resolve(incompatible)
    except ValueError as exc:
        assert "changed during resolution" in str(exc)
    else:
        raise AssertionError("Accepted a rotating Snapshot")
    finally:
        snap.fetch = original_fetch

    # GitHub's expanded commit is checked against the official short SHA.
    wrong = incompatible / "github-commits/e695009c15.json"
    wrong.write_text(json.dumps({"sha": "f" * 40}))
    try:
        snap.resolve(incompatible)
    except ValueError as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("Accepted a source commit from another revision")

    assert len(snap.parse_feeds(
        b"src-git packages https://example.org/x.git^" + b"a" * 40 + b"\n"
        b"src-git luci https://example.org/y.git^" + b"b" * 40 + b"\n"
        b"src-git routing https://example.org/z.git^" + b"c" * 40 + b"\n"
        b"src-git telephony https://example.org/t.git^" + b"d" * 40 + b"\n"
    )) == 4

print("PASS snapshot target/arch package indexes, full commit, ABI gate and race detection")
