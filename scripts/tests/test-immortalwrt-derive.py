#!/usr/bin/env python3
"""Offline tests for package-only Builder/SDK derivation and lineage."""
import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from immortalwrt_derive import sanitize, derive_metadata, REMOVED
from immortalwrt_builder import metadata as make_builder, release_tag
from immortalwrt_sdk import SDK_CHANNEL, SDK_TARGET, FEEDS, feed_fingerprint
from immortalwrt_sdk import verify_files, write_json
from immortalwrt_builder import sha256, check_metadata

with TemporaryDirectory() as temp:
    root = Path(temp)
    ib = root / "imagebuilder"
    sdk = root / "sdk"
    (ib / "packages").mkdir(parents=True)
    (sdk / "feeds/luci/applications/luci-app-homeproxy").mkdir(parents=True)
    (sdk / "tmp").mkdir()
    (ib / "Makefile").write_text("all:\n\t@true\n")
    (sdk / "Makefile").write_text("all:\n\t@true\n")
    for name in ("luci-app-homeproxy", "luci-i18n-homeproxy-zh-cn",
                 "luci-app-sing-box", "sing-box"):
        (ib / "packages" / f"{name}-1.0-r1.apk").write_bytes(b"apk" * 80)
    (sdk / "feeds/luci/applications/luci-app-homeproxy/Makefile").write_text("bad")
    (sdk / "tmp/.packageinfo").write_text("Package: luci-app-homeproxy\n")
    (sdk / ".config").write_text(
        "CONFIG_PACKAGE_luci-app-homeproxy=y\n"
        "CONFIG_PACKAGE_luci-app-sing-box=y\n"
    )
    (ib / ".config").write_text("CONFIG_PACKAGE_luci-app-homeproxy=y\n")
    old_packages = root / "old-packages.txt"
    old_packages.write_text(
        ("sing-box\nluci-app-homeproxy\nluci-i18n-homeproxy-zh-cn\n") * 3
    )
    add = root / "add.txt"
    add.write_text("sing-box\nluci-app-sing-box\n")
    output_packages = root / "imagebuilder-packages.txt"
    sanitize(argparse.Namespace(
        imagebuilder=ib, sdk=sdk, parent_packages=old_packages,
        add=add, output_packages=output_packages
    ))
    assert output_packages.read_text().splitlines() == [
        "luci-app-sing-box", "sing-box"
    ]
    assert not (sdk / "feeds/luci/applications/luci-app-homeproxy").exists()
    assert not (sdk / "tmp/.packageinfo").exists()
    assert not list(ib.rglob("*homeproxy*"))
    assert "CONFIG_PACKAGE_luci-app-homeproxy=y" not in (sdk / ".config").read_text()

    add.write_text("luci-app-sing-box\nluci-app-homeproxy\n")
    try:
        sanitize(argparse.Namespace(
            imagebuilder=ib, sdk=sdk, parent_packages=old_packages,
            add=add, output_packages=output_packages
        ))
    except ValueError:
        pass
    else:
        raise AssertionError("Derived Builder accepted forbidden HomeProxy")
    add.write_text("sing-box\nluci-app-sing-box\n")
    # The real Builder package manifest is much larger than 100 bytes.
    output_packages.write_text(
        output_packages.read_text() +
        "".join(f"original-package-{i}\n" for i in range(12))
    )

    # Verify inherited exact feed commits and source ABI, with new archive
    # checksums and immutable, different Builder and SDK provenance.
    parent_ib = root / "immortalwrt-imagebuilder-qualcommax-ipq60xx.Linux-x86_64.tar.zst"
    parent_sdk = root / "immortalwrt-sdk-qualcommax-ipq60xx.Linux-x86_64.tar.zst"
    ib_out = root / "new" / parent_ib.name
    sdk_out = root / "new" / parent_sdk.name
    ib_out.parent.mkdir()
    overlay = root / "base-overlay.tar.gz"
    for file in (parent_ib, parent_sdk, overlay, ib_out, sdk_out):
        file.write_bytes((file.name + " checksum test ").encode() * 30)
    old_meta = root / "builder-metadata.json"
    imm, ppe, base = "a" * 40, "b" * 40, "c" * 40
    feeds = {name: str(i + 4) * 40 for i, name in enumerate(FEEDS)}
    fingerprint = feed_fingerprint(feeds)
    make_builder(argparse.Namespace(
        immortal=imm, ppe=ppe, base=base, feeds=fingerprint,
        archive=parent_ib, overlay=overlay, packages=old_packages,
        output=old_meta
    ))
    parent = json.loads(old_meta.read_text())
    parent["fingerprint"] = "f" * 64  # simulate an earlier full-build recipe
    parent["tag"] = release_tag(
        imm, ppe, base, parent["fingerprint"], parent["package_fingerprint"],
        fingerprint
    )
    write_json(old_meta, parent)
    lock_file = root / "sdk-feeds.lock.json"
    lock = dict(schema=1, channel=SDK_CHANNEL, builder_tag=parent["tag"],
                immortalwrt_commit=imm, feeds=feeds,
                feeds_fingerprint=fingerprint)
    write_json(lock_file, lock)
    old_sdk_meta = root / "sdk-metadata.json"
    sdk_doc = dict(
        schema=1, channel=SDK_CHANNEL, target=SDK_TARGET, profile=parent["profile"],
        builder_tag=parent["tag"], builder_metadata_sha256=sha256(old_meta),
        immortalwrt_commit=imm, ppe_nss_commit=ppe, base_overlay_commit=base,
        feeds_fingerprint=fingerprint, toolchain="source",
        archive=parent_sdk.name, archive_sha256=sha256(parent_sdk),
        feed_lock=lock_file.name, feed_lock_sha256=sha256(lock_file)
    )
    write_json(old_sdk_meta, sdk_doc)
    new_builder_meta = ib_out.parent / "builder-metadata.json"
    new_sdk_meta = ib_out.parent / "sdk-metadata.json"
    new_feed_lock = ib_out.parent / "sdk-feeds.lock.json"
    derive_metadata(argparse.Namespace(
        parent_builder_metadata=old_meta, parent_builder_archive=parent_ib,
        parent_sdk_metadata=old_sdk_meta, parent_sdk_archive=parent_sdk,
        parent_feed_lock=lock_file, archive=ib_out, sdk_archive=sdk_out,
        overlay=overlay, parent_packages=old_packages, packages=output_packages,
        builder_metadata=new_builder_meta, sdk_metadata=new_sdk_meta,
        feed_lock=new_feed_lock
    ))
    new, legacy = check_metadata(new_builder_meta)
    assert not legacy and new["tag"] != parent["tag"]
    assert new["derived_from_builder"] == parent["tag"]
    assert new["derivation"] == "package-only-no-kernel-rebuild"
    assert verify_files(new_sdk_meta, new_builder_meta, sdk_out, new_feed_lock)
    assert json.loads(new_feed_lock.read_text())["feeds"] == feeds
    assert json.loads(new_sdk_meta.read_text())["derived_from_builder"] == parent["tag"]
    sdk_out.write_bytes(b"damaged")
    try:
        verify_files(new_sdk_meta, new_builder_meta, sdk_out, new_feed_lock)
    except ValueError:
        pass
    else:
        raise AssertionError("Derived SDK accepted a corrupted archive")

script = (ROOT / "scripts/derive-immortalwrt-builder.sh").read_text()
workflow = (ROOT / ".github/workflows/builder-incremental.yml").read_text()
assert "rebuild-missing-apks.sh" in script
assert 'immortalwrt_derive.py" sanitize' in script
assert 'immortalwrt_derive.py" metadata' in script
assert not any(line.lstrip().startswith(("make -j", "make download"))
               for line in script.splitlines())
assert "actions/cache@v4" in workflow and ".build-cache/sdk-apks" in workflow
assert "builder_tag" in workflow and "firmware-immortalwrt.yml" in workflow
assert "scripts/derive-immortalwrt-builder.sh" in workflow
assert "gh release create" in workflow
print("PASS package-only Builder/SDK reissue, HomeProxy pruning and ABI lineage")
