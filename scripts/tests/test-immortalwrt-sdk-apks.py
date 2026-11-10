#!/usr/bin/env python3
"""Offline tests for missing-APK detection, ABI-pinned cache and install."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from immortalwrt_sdk_apks import (
    APK, cache_manifest, collect, install, missing_packages,
    package_in_directory, request_names, safe_apk_files, selection_sha,
    sdk_compile_targets,
)

with tempfile.TemporaryDirectory() as dirname:
    root = Path(dirname)
    ib = root / "imagebuilder"
    repo = ib / "packages"
    repo.mkdir(parents=True)
    add = root / "add.txt"
    remove = root / "remove.txt"
    add.write_text(
        "# optional extensions\n"
        "luci-app-autoreboot\n"
        "luci-app-new-thing # trailing comment\n"
        "libnew-dep\n"
    )
    remove.write_text("ip-tiny\n")
    (repo / "luci-app-autoreboot-1.0-r1.apk").write_bytes(b"already-compiled")
    assert request_names(add) == [
        "libnew-dep", "luci-app-autoreboot", "luci-app-new-thing"
    ]
    assert missing_packages(ib, add) == ["libnew-dep", "luci-app-new-thing"]
    assert package_in_directory(repo, "luci-app-autoreboot")
    assert not package_in_directory(repo, "luci-app-new")
    assert APK.fullmatch("luci-app-new-thing-2.1-r7.apk")
    assert not APK.fullmatch("../evil.apk")

    sdk_bin = root / "sdk" / "bin"
    out = sdk_bin / "packages" / "aarch64_cortex-a53" / "base"
    out.mkdir(parents=True)
    (out / "luci-app-new-thing-2.1-r7.apk").write_bytes(b"new-luci" * 32)
    (out / "libnew-dep-1.1-r1.apk").write_bytes(b"new-library" * 25)
    (out / "luci-app-autoreboot-1.0-r1.apk").write_bytes(b"already-compiled")
    identity = {
        "schema": 1,
        "builder_tag": "imm-builder-test",
        "sdk_archive_sha256": "a" * 64,
        "sdk_metadata_sha256": "b" * 64,
        "builder_metadata_sha256": "c" * 64,
        "feeds_fingerprint": "d" * 64,
        "package_selection_sha256": selection_sha(add, remove),
    }
    cache = root / "sdk-apk-cache"
    wanted = missing_packages(ib, add)
    collect(sdk_bin, ib, cache, identity, wanted)
    files = safe_apk_files(cache, identity, wanted)
    assert len(files) == 2, [f.name for f in files]
    assert sorted(f.name for f in files) == [
        "libnew-dep-1.1-r1.apk", "luci-app-new-thing-2.1-r7.apk"
    ]
    before = (repo / "luci-app-autoreboot-1.0-r1.apk").read_bytes()
    assert install(cache, ib, identity, wanted) == 2
    assert (repo / "luci-app-autoreboot-1.0-r1.apk").read_bytes() == before
    assert missing_packages(ib, add) == []
    assert install(cache, ib, identity, []) == 0

    # The exact same APK filenames from a different SDK release cannot enter.
    changed = dict(identity, sdk_archive_sha256="e" * 64)
    try:
        safe_apk_files(cache, changed, wanted)
    except ValueError:
        pass
    else:
        raise AssertionError("Accepted APK cache from another SDK")

    pkg = cache / files[0].name
    pkg.write_bytes(b"tampered")
    try:
        safe_apk_files(cache, identity, wanted)
    except ValueError:
        pass
    else:
        raise AssertionError("Accepted edited or corrupted compiled APK")

    # A malicious or misbehaving build cannot trick the cache installer into
    # reading outside its own output directory.
    data = json.loads(cache_manifest(cache).read_text())
    data["files"][0]["name"] = "../untrusted.apk"
    cache_manifest(cache).write_text(json.dumps(data))
    try:
        safe_apk_files(cache, identity, wanted)
    except ValueError:
        pass
    else:
        raise AssertionError("Accepted APK cache path traversal")
    add.write_text("No spaces, upperCASE\n")
    try:
        request_names(add)
    except ValueError:
        pass
    else:
        raise AssertionError("Allowed invalid requested APK name")

    # OpenWrt metadata maps binary names to their installed source directories.
    # One source can produce multiple binary APKs; build it only once.
    sdk_src = root / "sdk-src"
    (sdk_src / "tmp").mkdir(parents=True)
    sing = sdk_src / "package/feeds/sing_box/luci-app-sing-box"
    lib = sdk_src / "package/feeds/packages/libnew-dep"
    sing.mkdir(parents=True)
    lib.mkdir(parents=True)
    (sing / "Makefile").write_text("include $(TOPDIR)/rules.mk\n")
    (lib / "Makefile").write_text("include $(TOPDIR)/rules.mk\n")
    (sdk_src / "tmp/.packageinfo").write_text(
        "Source-Makefile: feeds/sing_box/luci-app-sing-box/Makefile\n"
        "Package: luci-app-sing-box\n"
        "Source-Makefile: feeds/packages/libs/libnew-dep/Makefile\n"
        "Package: libnew-dep\n"
        "Package: libnew-dep-extra\n"
        "Source-Makefile: feeds/packages/libs/nonexistent/Makefile\n"
        "Package: missing-source\n"
    )
    assert sdk_compile_targets(sdk_src, ["luci-app-sing-box"]) == [
        "package/feeds/sing_box/luci-app-sing-box/compile"
    ]
    assert sdk_compile_targets(sdk_src, [
        "luci-app-sing-box", "libnew-dep", "libnew-dep-extra"
    ]) == [
        "package/feeds/packages/libnew-dep/compile",
        "package/feeds/sing_box/luci-app-sing-box/compile",
    ]
    for bad in ("missing-source", "unknown-package", "../escape"):
        try:
            sdk_compile_targets(sdk_src, [bad])
        except ValueError:
            pass
        else:
            raise AssertionError(f"Unsafe or missing SDK package accepted: {bad}")

repack = (ROOT / "scripts/repack-immortalwrt.sh").read_text()
sdk = (ROOT / "scripts/rebuild-missing-apks.sh").read_text()
fw = (ROOT / ".github/workflows/firmware-immortalwrt.yml").read_text()
assert 'bash "$ROOT/scripts/rebuild-missing-apks.sh" "$IB" "$META"' in repack
assert 'python3 "$SDK_CHECK" verify' in sdk
assert 'scripts/feeds install -a' in sdk or './scripts/feeds install -a' in sdk
assert 'make -j"$(nproc)" "${MAKE_TARGETS[@]}" V=s' in sdk
assert 'make -j"$(nproc)" NO_DEPS=1 CONFIG_LUCI_JSMIN= CONFIG_LUCI_CSSTIDY= "${MAKE_TARGETS[@]}" V=s' in sdk
assert "CONFIG_SIGN_EACH_PACKAGE=y" in sdk
assert "openssl ecparam -name prime256v1 -genkey -noout -out private-key.pem" in sdk
assert "untrusted comment: Local SDK package key" in sdk
assert '"${MISSING[0]}" == luci-app-sing-box' in sdk
assert '"${#MISSING[@]}" -eq 1' in sdk
assert 'package/compile V=s' not in sdk
assert 'targets --sdk "$SDK" --packages "${MISSING[@]}"' in sdk
assert 'git -C "$dest" rev-parse HEAD' in sdk
assert 'SDK_APK_CACHE_DIR' in sdk
assert "test-immortalwrt-sdk-apks.py" in fw
assert "sdk-apks-v1-" in fw
assert "sdk-apks" in fw

subprocess.run(["bash", "-n", str(ROOT / "scripts/rebuild-missing-apks.sh")],
               check=True, capture_output=True)
print("PASS ABI-bound APK cache, missing package detection and safe repack integration")
