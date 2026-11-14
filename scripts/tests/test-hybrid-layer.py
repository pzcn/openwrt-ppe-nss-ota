#!/usr/bin/env python3
"""Offline layer-contract tests: provenance, package integrity and safe install."""
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import hybrid_layer as layer  # noqa: E402
import immortalwrt_builder as builder  # noqa: E402


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write_json(path: Path, doc: dict) -> None:
    path.write_text(json.dumps(doc, indent=2) + "\n")


def expect_fail(func, text: str) -> None:
    try:
        func()
    except (ValueError, KeyError, OSError, tarfile.TarError) as exc:
        assert text in str(exc), exc
    else:
        raise AssertionError(f"Unexpected success; expected: {text}")


def make_archive(path: Path, files: dict[str, bytes],
                 extra: tuple[str, bytes] | None = None,
                 symlink: bool = False) -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        folder = tarfile.TarInfo("packages/")
        folder.type = tarfile.DIRTYPE
        tar.addfile(folder)
        for name, data in files.items():
            info = tarfile.TarInfo("packages/" + name)
            if symlink:
                info.type = tarfile.SYMTYPE
                info.linkname = "/etc/passwd"
                tar.addfile(info)
            else:
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        if extra:
            info = tarfile.TarInfo(extra[0])
            info.size = len(extra[1])
            tar.addfile(info, io.BytesIO(extra[1]))
    subprocess.run(["zstd", "-q", "-f", "-o", str(path)],
                   input=buffer.getvalue(), check=True, capture_output=True)


with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    base = root / "builder-metadata.json"
    base_official = root / "parent-official.json"
    official = root / "official-apks.json"
    snapshot = root / "snapshot-lock.json"
    packages = root / "imagebuilder-packages.txt"
    archive = root / layer.ARCHIVE_NAME
    metadata = root / "layer-metadata.json"
    sha = lambda ch: ch * 40
    hex64 = lambda ch: ch * 64

    core, pkgs, feeds = hex64("a"), hex64("b"), hex64("c")
    ib_tag = builder.release_tag(sha("1"), sha("2"), sha("3"), core, pkgs, feeds)
    ib_tag += "-s" + "d" * 8
    base_doc = {
        "schema": 1, "channel": builder.CHANNEL,
        "profile": builder.PROFILE, "packaging": "standalone",
        "build_mode": "hybrid", "tag": ib_tag,
        "fingerprint": core, "package_fingerprint": pkgs,
        "feeds_fingerprint": feeds,
        "immortalwrt_commit": sha("1"), "ppe_nss_commit": sha("2"),
        "base_overlay_commit": sha("3"),
        "archive": "builder.tar.zst", "archive_sha256": hex64("1"),
        "overlay": "overlay.tar.gz", "overlay_sha256": hex64("2"),
        "packages": "packages.txt", "packages_sha256": hex64("3"),
        "hybrid": {
            "identity": hex64("4"), "kernel_identity": hex64("5"),
            "kernel_built_at": "2026-11-13T00:00:00Z",
            "kernel_parent": None, "keyring_commit": sha("6"),
        },
        "official_snapshot": {"lock_fingerprint": hex64("d")},
    }
    write_json(base, base_doc)
    write_json(base_official, {"mirrored": ["old-1.apk"],
                               "mirror": [{"filename": "old-1.apk", "sha256": hex64("7")}]})
    payload = {"foo-2026.11~abc-r1.apk": b"official signed package" * 100,
               "bar-2.apk": b"new official package" * 100}
    records = [{"filename": name, "sha256": sha_bytes(data)}
               for name, data in payload.items()]
    write_json(official, {"mirrored": sorted(payload), "mirror": records,
                          "local_fallback": [], "errors": []})
    write_json(snapshot, {"schema": 2, "snapshot_version": "r42542-test",
                          "lock_fingerprint": hex64("f")})
    packages.write_text("foo\nbar\nkernel\n")
    make_archive(archive, payload)

    doc = layer.create(base, base_official, archive, official, packages,
                       snapshot, hex64("e"), metadata)
    assert doc["tag"] == layer.tag_for(ib_tag, hex64("e"))
    assert doc["base_builder_tag"] == ib_tag
    assert [x["filename"] for x in doc["mirrored"]] == sorted(payload)
    assert doc["remove"] == ["old-1.apk"]
    assert layer.check_header(base, metadata) == doc
    assert layer.verify(base, base_official, metadata, archive, official,
                        packages, snapshot) == doc

    imagebuilder = root / "imagebuilder"
    (imagebuilder / "packages").mkdir(parents=True)
    (imagebuilder / "Makefile").write_text("all:\n\t@true\n")
    (imagebuilder / "packages/old-1.apk").write_bytes(b"parent official")
    (imagebuilder / "packages/local-1.apk").write_bytes(b"local kmod")
    (imagebuilder / "packages/packages.adb").write_bytes(b"stale index")
    layer.verify(base, base_official, metadata, archive, official,
                 packages, snapshot, imagebuilder)
    assert not (imagebuilder / "packages/old-1.apk").exists()
    assert not (imagebuilder / "packages/packages.adb").exists()
    assert (imagebuilder / "packages/local-1.apk").read_bytes() == b"local kmod"
    for name, data in payload.items():
        assert (imagebuilder / "packages" / name).read_bytes() == data

    bad = dict(doc, remove=["local-1.apk"])
    write_json(metadata, bad)
    expect_fail(lambda: layer.verify(base, base_official, metadata, archive,
                                     official, packages, snapshot),
                "outside parent mirrors")
    write_json(metadata, doc)

    other = dict(base_doc, hybrid=dict(base_doc["hybrid"],
                                      kernel_identity=hex64("9")))
    write_json(base, other)
    expect_fail(lambda: layer.check_header(base, metadata), "not bound")
    write_json(base, base_doc)

    with archive.open("ab") as fd:
        fd.write(b"tampered")
    expect_fail(lambda: layer.verify(base, base_official, metadata, archive,
                                     official, packages, snapshot),
                "asset integrity mismatch")
    make_archive(archive, payload)

    make_archive(archive, payload, extra=("packages/../escape.apk", b"bad"))
    changed = dict(doc, archive_sha256=builder.sha256(archive))
    write_json(metadata, changed)
    expect_fail(lambda: layer.verify(base, base_official, metadata, archive,
                                     official, packages, snapshot),
                "Unknown, duplicate or unsafe")
    make_archive(archive, payload, symlink=True)
    changed["archive_sha256"] = builder.sha256(archive)
    write_json(metadata, changed)
    expect_fail(lambda: layer.verify(base, base_official, metadata, archive,
                                     official, packages, snapshot),
                "Unsafe layer archive entry")
    write_json(metadata, doc)

# Workflow/static contracts
full = (ROOT / ".github/workflows/builder-immortalwrt-hybrid.yml").read_text()
firmware = (ROOT / ".github/workflows/firmware-immortalwrt.yml").read_text()
refresh = (ROOT / "scripts/refresh-hybrid-builder.sh").read_text()
publish = (ROOT / "scripts/publish-hybrid-layer.sh").read_text()
repack = (ROOT / "scripts/repack-immortalwrt.sh").read_text()
assert 'scripts/publish-hybrid-layer.sh' in full
assert '--parent out-parent/identity.json' in full
assert 'out-parent/builder-metadata.json out-parent/identity.json' in full
assert 'hybrid-userland-packages.tar.zst' in refresh and 'sdk-metadata.json' in full
assert 'cp "$SDK_ARCHIVE"' not in refresh and "tar -I 'zstd -T0 -12'" not in refresh
assert 'scripts/hybrid_layer.py" install' in repack
assert "layer_tag" in firmware and 'imm-layer-' in firmware
assert 'gh release create "$TAG"' in publish and 'publish-hybrid-builder.sh' not in publish
assert 'Only main can publish immutable userland-layer tags' in publish
assert "github.ref == 'refs/heads/main' && (github.event_name" in full
print("PASS thin hybrid userland layer verified + installed without repacking IB/SDK")
