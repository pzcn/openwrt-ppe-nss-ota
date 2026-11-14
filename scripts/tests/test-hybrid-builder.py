#!/usr/bin/env python3
"""Offline tests for the hybrid Builder plan, official closure and identity."""
import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import hybrid_builder as h  # noqa: E402
import immortalwrt_builder as ib  # noqa: E402
import immortalwrt_sdk as sdk  # noqa: E402

SHA = lambda c: c * 40  # noqa: E731


def block(src, build_deps="", pkgs=()):
    out = [f"Source-Makefile: {src}/Makefile"]
    if build_deps:
        out.append("Build-Depends: " + build_deps)
    out.append("")
    for name, deps, extra in pkgs:
        out += [f"Package: {name}", "Version: 1", "Depends: " + deps,
                "Provides: @" + name + "-any"] + list(extra)
        out += ["Description:  multi", "line text: with colons", "@@", ""]
    return "\n".join(out)


PACKAGEINFO = "\n".join((
    block("package/kernel/linux", pkgs=[("kmod-fs-f2fs", "+kmod-lib-crc32c", ()),
                                         ("kmod-lib-crc32c", "", ()),
                                         ("kmod-sched-cake", "", ())]),
    block("package/network/utils/fullconenat-nft", pkgs=[("kmod-nft-fullcone", "+kmod-nft-nat", ())]),
    block("package/kernel/nft", pkgs=[("kmod-nft-nat", "", ())]),
    block("package/base-files", "usign/host ucert/host",
          [("base-files", "+libc +netifd +SIGNED_PACKAGES:usign +!SELINUX:procd +SELINUX:procd-selinux",
            ())]),
    block("package/libs/toolchain", pkgs=[("libc", "+libgcc", ()), ("libgcc", "", ())]),
    block("package/system/usign", pkgs=[("usign", "+libubox", ())]),
    block("package/system/ucert", pkgs=[("ucert", "", ())]),
    block("package/libs/libubox", "lua", [("libubox", "+libc", ("ABI-Version: 20261103",))]),
    block("package/network/config/netifd", pkgs=[("netifd", "+libubox", ())]),
    block("package/system/procd", pkgs=[("procd", "+libubox", ()), ("procd-selinux", "", ())]),
    block("package/feeds/packages/sqm-scripts", pkgs=[("sqm-scripts", "+tc +kmod-sched-cake +uci-firewall", ())]),
    block("package/feeds/packages/tc", pkgs=[("tc-tiny", "", ())]),
    block("package/feeds/luci/luci-app-qca-ppe-qos", "lua/host luci-base/host LUCI_CSSTIDY:csstidy/host",
          [("luci-app-qca-ppe-qos", "+libc +qca-ppe-qos", ())]),
    block("package/network/config/qca-ppe-qos", pkgs=[("qca-ppe-qos", "+libc +tc", ())]),
    block("package/utils/ppe-help", pkgs=[("ppe-help", "+libc", ())]),
    block("package/luci-theme-aurora", "lua/host luci-base/host", [("luci-theme-aurora", "+luci-base", ())]),
    block("package/luci-app-sing-box", "lua/host luci-base/host",
          [("luci-app-sing-box", "+luci-base +sing-box", ())]),
    block("package/utils/lua", pkgs=[("lua", "", ())]),
    block("package/feeds/luci/luci-base", pkgs=[("luci-base", "+libc +libubox", ())]),
    block("package/feeds/luci/csstidy", pkgs=[("csstidy", "", ("Build-Only: 1",))]),
    block("package/feeds/nss/nss-firmware", pkgs=[("nss-firmware-ipq60xx", "+libc", ())]),
    block("package/firmware/ipq-wifi", pkgs=[("ipq-wifi-jdcloud_re-ss-01", "", ())]),
    block("package/feeds/packages/sing-box", pkgs=[("sing-box", "+kmod-inet-diag", ())]),
    block("package/system/apk", pkgs=[("apk-openssl", "+libopenssl", ())]),
))
SELECTED = ["kmod-fs-f2fs", "kmod-lib-crc32c", "kmod-sched-cake", "kmod-nft-fullcone", "kmod-nft-nat",
            "base-files", "libc", "libgcc", "usign", "netifd", "procd", "libubox", "sqm-scripts",
            "luci-app-qca-ppe-qos", "qca-ppe-qos", "ppe-help", "luci-theme-aurora",
            "luci-app-sing-box", "luci-base", "nss-firmware-ipq60xx", "sing-box", "csstidy", "apk-openssl"]
CONFIG = "\n".join([f"CONFIG_PACKAGE_{n}=y" for n in SELECTED]
                   + ["CONFIG_PACKAGE_ipq-wifi-jdcloud_re-ss-01=m", "CONFIG_SIGNED_PACKAGES=y",
                      "# CONFIG_SELINUX is not set", "CONFIG_PACKAGE_tc-tiny=n"])


def expect_error(fn, text):
    try:
        fn()
    except ValueError as exc:
        assert text in str(exc), exc
        return
    raise AssertionError("expected ValueError: " + text)


# --- Kconfig parsing -------------------------------------------------------
sym = {"A": "y", "B": "n", "C": "m"}
for expr, value in (("A", True), ("!A", False), ("A&&C", True), ("A&&B", False),
                    ("(B||C)&&!B", True), ("!(A||B)", False)):
    assert h.kconfig_true(expr, sym) is value, expr
expect_error(lambda: h.kconfig_true("(A", sym), "Kconfig condition")
assert h.kernel_config_lines(
    "CONFIG_KERNEL_BUILD_USER=\"buildbot\"\nCONFIG_KERNEL_CGROUPS=y\n# CONFIG_KERNEL_KALLSYMS is not set\n"
    "CONFIG_ALL_KMODS=y\n") == ["CONFIG_KERNEL_CGROUPS=y", "# CONFIG_KERNEL_KALLSYMS is not set"]
assert h.abi_name({"libfoo2": {"abi": "7"}}, "libfoo2") == "libfoo2-7"
assert h.abi_name({"libubox": {"abi": "1"}}, "libubox") == "libubox1"

sources, packages = h.parse_packageinfo(PACKAGEINFO)
assert sources["package/base-files"]["build_depends"] == ["usign/host", "ucert/host"]
assert packages["csstidy"]["build_only"] and packages["libubox"]["abi"] == "20261103"

# --- Local plan -------------------------------------------------------------
symbols = h.parse_symbols(CONFIG)
plan = h.local_plan(sources, packages, symbols)
local = {p["name"]: p for p in plan["local_packages"]}
assert set(plan["local_kmods"]) == {"kmod-fs-f2fs", "kmod-lib-crc32c", "kmod-sched-cake",
                                    "kmod-nft-fullcone", "kmod-nft-nat"}
assert "kernel" in local and "package/kernel/linux/compile" in plan["kernel_compile_targets"]
assert "package/network/utils/fullconenat-nft/compile" in plan["kernel_compile_targets"]
assert set(plan["userland_compile_targets"]) == {
    "package/base-files/compile", "package/libs/toolchain/compile", "package/feeds/packages/sqm-scripts/compile",
    "package/feeds/luci/luci-app-qca-ppe-qos/compile", "package/network/config/qca-ppe-qos/compile",
    "package/utils/ppe-help/compile", "package/luci-theme-aurora/compile",
    "package/luci-app-sing-box/compile", "package/feeds/nss/nss-firmware/compile"}
assert set(plan["host_compile_targets"]) == {
    "package/system/usign/host/compile", "package/system/ucert/host/compile",
    "package/utils/lua/host/compile", "package/feeds/luci/luci-base/host/compile",
    "package/feeds/luci/csstidy/host/compile"}
# Conditional dependencies follow this .config; plain names for NO_DEPS builds.
assert local["base-files"]["depends"] == ["libc", "netifd", "usign", "procd"]
assert local["base-files"]["provides"] == ["base-files-any"]
roots = set(plan["image_roots"])
assert {"ipq-wifi-jdcloud_re-ss-01", "sing-box", "libubox", "luci-base"} <= roots
assert "apk-openssl" in roots  # target package manager, not host-only
assert not roots & {"csstidy", "sqm-scripts", "libc", "kmod-fs-f2fs"}
missing = SELECTED.copy()
missing.remove("ppe-help")
expect_error(lambda: h.local_plan(sources, packages, h.parse_symbols(
    "\n".join(f"CONFIG_PACKAGE_{n}=y" for n in missing))), "ppe-help")
bad = PACKAGEINFO.replace("Build-Depends: lua/host luci-base/host LUCI_CSSTIDY", "Build-Depends: libnl LUCI_CSSTIDY")
expect_error(lambda: h.local_plan(*h.parse_packageinfo(bad), symbols), "target build dependency libnl")


# --- Official closure -------------------------------------------------------
def pkg(name, deps=(), provides=(), tags=(), version="1"):
    return {"name": name, "version": version, "depends": list(deps),
            "provides": list(provides), "tags": list(tags)}


def indexes(**extra):
    repos = {
        "target": [pkg("kernel"), pkg("base-files"), pkg("ipq-wifi-jdcloud_re-ss-01"),
                   pkg("libc"), pkg("procd", ["libubox20260721"])],
        "base": [pkg("libubox20260721", ["libc"], ["libubox"], ["openwrt:abiversion=20260721"]),
                 pkg("netifd", ["libubox20260721", "!netifd-legacy"]), pkg("usign", ["libubox20260721"]),
                 pkg("firewall4", ["kmod-nft-nat", "nftables"], ["uci-firewall"]),
                 pkg("firewall", ["kmod-ipt-nat"], ["uci-firewall"]), pkg("nftables"),
                 pkg("tc-full", provides=["tc"]), pkg("tc-tiny", provides=["tc"]),
                  pkg("apk-openssl", ["libopenssl"], provides=["apk"]), pkg("libopenssl")],
        "packages": [pkg("sing-box", ["kmod-inet-diag", "ca-bundle>=1"]), pkg("ca-bundle"),
                     pkg("sqm-scripts", version="0.9")],
        "luci": [pkg("luci-base", ["libubox", "rpcd"]), pkg("rpcd", ["libubox20260721"])],
        "routing": [pkg("unused")], "telephony": [pkg("unused2")],
    }
    for repo, items in extra.items():
        repos[repo] = repos[repo] + items
    return {r: h.parse_index_json(json.dumps({"packages": v}), r) for r, v in repos.items()}


plan["local_kmods"].append("kmod-inet-diag")
plan["local_packages"].append({"name": "kmod-inet-diag", "apk_name": "kmod-inet-diag",
                               "source": "package/kernel/linux", "depends": [], "provides": []})
res = h.closure(plan, indexes(base=[pkg("unrelated")]))
chosen = {p["name"]: p["repo"] for p in res["official"]}
assert not res["errors"] and not res["local_fallback"], res
# Local builds win, official kernel/kmods/base-files never enter the mirror.
assert not set(chosen) & {"kernel", "base-files", "libc", "sqm-scripts"}
assert chosen["apk-openssl"] == "base" and chosen["libopenssl"] == "base"
no_apk_index = indexes()
no_apk_index["base"] = [x for x in no_apk_index["base"] if x["name"] != "apk-openssl"]
assert "apk-openssl" in h.closure(plan, no_apk_index)["local_fallback"]
assert not any(n.startswith("kmod-") for n in chosen)
# Roots resolve through ABI base names; deps through exact ABI names.
assert chosen["libubox20260721"] == "base" and chosen["procd"] == "target"
assert {"sing-box", "ca-bundle", "luci-base", "rpcd", "ipq-wifi-jdcloud_re-ss-01"} <= set(chosen)
# Virtual tc: deterministic single provider; uci-firewall: never fw3's iptables.
assert res["virtual_choices"]["tc"] == "tc-full" and "tc-tiny" not in chosen
assert "firewall" not in chosen and "unrelated" not in chosen
# An official package needing a kmod we did not build is an error.
plan_no_diag = json.loads(json.dumps(plan))
plan_no_diag["local_kmods"].remove("kmod-inet-diag")
plan_no_diag["local_packages"] = [p for p in plan_no_diag["local_packages"] if p["name"] != "kmod-inet-diag"]
assert any("kmod-inet-diag" in e for e in h.closure(plan_no_diag, indexes())["errors"])
# A selected package missing upstream falls back to a local build.
plan_fb = json.loads(json.dumps(plan))
plan_fb["image_roots"].append("only-in-master")
assert h.closure(plan_fb, indexes())["local_fallback"] == ["only-in-master"]
# A dependency nobody provides is an error, not a silent omission.
broken = indexes()
broken["packages"] = h.parse_index_json(json.dumps({"packages": [
    pkg("sing-box", ["kmod-inet-diag", "libmissing"]), pkg("ca-bundle")]}), "packages")
assert any("libmissing" in e for e in h.closure(plan, broken)["errors"])

lock = {"target_url": "https://t", "architecture_url": "https://a"}
sel = [{"name": "procd", "version": "1", "repo": "target"},
       {"name": "ca-bundle", "version": "1", "repo": "packages"}]
mirror = h.mirror_plan(sel, lock, {"packages/procd-1.apk": "a" * 64},
                       {"packages/ca-bundle-1.apk": "b" * 64})
assert mirror[0]["url"] == "https://t/packages/procd-1.apk" and mirror[1]["sha256"] == "b" * 64
expect_error(lambda: h.mirror_plan(sel, lock, {}, {}), "absent from the locked sha256sums")
assert h.parse_sums(f"{'c' * 64} *base/x-1.apk\n") == {"base/x-1.apk": "c" * 64}

# --- Feeds, fingerprints and identity --------------------------------------
LOCK = {
    "schema": 2, "target": "qualcommax/ipq60xx", "snapshot_version": "r42542-e695009c15",
    "target_commit": SHA("e"), "lock_fingerprint": "1" * 64,
    "kernel_fingerprint": "2" * 64, "packages_fingerprint": "3" * 64,
    "assets": {"toolchain": {"filename": "immortalwrt-toolchain-qualcommax-ipq60xx_gcc-14.4.0_musl.Linux-x86_64.tar.zst",
                             "sha256": "9" * 64}},
    "libc_version": "1.2.6-r5",
    "arch_feeds": {
        "base": {"url": "https://github.com/immortalwrt/immortalwrt.git", "commit": SHA("0")},
        "packages": {"url": h.FEED_URLS["packages"], "commit": SHA("1")},
        "luci": {"url": h.FEED_URLS["luci"], "commit": SHA("2")},
        "routing": {"url": h.FEED_URLS["routing"], "commit": SHA("3")},
        "telephony": {"url": h.FEED_URLS["telephony"], "commit": SHA("4")},
    },
}
conf = h.feeds_conf(LOCK, SHA("5"))
assert f"src-git packages {h.FEED_URLS['packages']}^{SHA('1')}" in conf
assert conf.endswith(f"src-git nss {h.NSS_FEED_URL}^{SHA('5')}\n") and "base" not in conf
wrong = json.loads(json.dumps(LOCK))
wrong["arch_feeds"]["luci"]["url"] = "https://example.com/luci.git"
expect_error(lambda: h.feeds_conf(wrong, SHA("5")), "Unexpected luci feed URL")
expect_error(lambda: h.feeds_conf(LOCK, "main"), "full SHA")
fp = h.feeds_fingerprint(LOCK, SHA("5"), SHA("6"))
assert fp == sdk.feed_fingerprint({"packages": SHA("1"), "luci": SHA("2"), "routing": SHA("3"),
                                   "telephony": SHA("4"), "nss": SHA("5"), "ppe_qos_luci": SHA("6")})
core, packages_fp = h.core_fingerprint(), ib.package_fingerprint()
ident = h.identity(LOCK, SHA("a"), SHA("b"), SHA("c"), SHA("d"), core, packages_fp)
assert ident == h.identity(LOCK, SHA("a"), SHA("b"), SHA("c"), SHA("d"), core, packages_fp)
assert ident != h.identity(LOCK, SHA("f"), SHA("b"), SHA("c"), SHA("d"), core, packages_fp)
newer = json.loads(json.dumps(LOCK))
newer["packages_fingerprint"] = "4" * 64
assert ident != h.identity(newer, SHA("a"), SHA("b"), SHA("c"), SHA("d"), core, packages_fp)
assert core != ib.fingerprint(mode="full") and core == ib.fingerprint(mode="hybrid")

# --- Kernel identity and the skip / refresh / full decision -----------------
import datetime as dt  # noqa: E402

kcore = h.kernel_core_fingerprint()
kid = h.kernel_identity(LOCK, SHA("a"), SHA("b"), SHA("c"), SHA("d"), kcore)
# A new snapshot with the same compiler + libc keeps the kernel side...
next_snapshot = json.loads(json.dumps(newer))
next_snapshot["assets"]["toolchain"]["sha256"] = "8" * 64
next_snapshot["arch_feeds"]["luci"]["commit"] = SHA("7")
assert h.kernel_identity(next_snapshot, SHA("a"), SHA("b"), SHA("c"), SHA("d"), kcore) == kid
# ...but a new PPE commit, recipe, compiler or libc does not.
assert h.kernel_identity(LOCK, SHA("f"), SHA("b"), SHA("c"), SHA("d"), kcore) != kid
assert h.kernel_identity(LOCK, SHA("a"), SHA("b"), SHA("c"), SHA("d"), "0" * 64) != kid
libc = json.loads(json.dumps(LOCK))
libc["libc_version"] = "1.2.7-r1"
assert h.kernel_identity(libc, SHA("a"), SHA("b"), SHA("c"), SHA("d"), kcore) != kid
gcc = json.loads(json.dumps(LOCK))
gcc["assets"]["toolchain"]["filename"] = gcc["assets"]["toolchain"]["filename"].replace("14.4.0", "15.1.0")
assert h.kernel_identity(gcc, SHA("a"), SHA("b"), SHA("c"), SHA("d"), kcore) != kid
assert set(h.KERNEL_CORE_FILES) < set(h.HYBRID_CORE_FILES)
assert "scripts/hybrid_builder.py" not in h.KERNEL_CORE_FILES  # logic fixes need no kernel rebuild

now = dt.datetime(2026, 11, 14, tzinfo=dt.timezone.utc)
parent = {"tag": "imm-builder-parent", "hybrid": {
    "identity": "a" * 64, "kernel_identity": kid, "kernel_built_at": "2026-11-10T00:00:00Z"}}
assert h.decide("a" * 64, kid, parent, now)[0] == "skip"
assert h.decide("b" * 64, kid, parent, now)[0] == "refresh"
assert h.decide("b" * 64, "c" * 64, parent, now)[0] == "full"
assert h.decide("b" * 64, kid, None, now)[0] == "full"
assert h.decide("b" * 64, kid, {"tag": "imm-builder-full-source"}, now)[0] == "full"
assert h.decide("a" * 64, kid, parent, now, force_full=True)[0] == "full"
old = json.loads(json.dumps(parent))
old["hybrid"]["kernel_built_at"] = "2026-10-01T00:00:00Z"
mode, reason = h.decide("b" * 64, kid, old, now)
assert mode == "full" and "days old" in reason
assert h.decide("b" * 64, kid, old, now, max_age_days=60)[0] == "refresh"

# --- Refresh plan -------------------------------------------------------------
rp = h.refresh_plan(plan, ["tailscale", "luci-app-wol", "sqm-scripts", "kmod-fs-f2fs"], ["sing-box"])
assert rp["local_packages"] == plan["local_packages"]
assert {"tailscale", "luci-app-wol"} <= set(rp["image_roots"])
assert "sing-box" not in rp["image_roots"] and "sqm-scripts" not in rp["image_roots"]
expect_error(lambda: h.refresh_plan(plan, ["kmod-usb-net-rtl8152"], []), "cannot add kernel modules")
assert h.package_names("a b # c\n\n# x\nd\n") == ["a", "b", "d"]
expect_error(lambda: h.package_names("bad;name\n"), "Bad package name")

# --- Deterministic mtimes for cached host tools ------------------------------
import os  # noqa: E402
import subprocess  # noqa: E402
with tempfile.TemporaryDirectory() as tmp:
    repo = Path(tmp)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "tools/a").mkdir(parents=True)
    (repo / "tools/a/Makefile").write_text("one\n")
    (repo / "tools/b").write_text("two\n")
    (repo / "other").write_text("x\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    assert h.normalize_mtimes(repo, ["tools"]) == 2
    first = (repo / "tools/a/Makefile").stat().st_mtime
    assert first < 1_300_000_000 and (repo / "other").stat().st_mtime > 1_700_000_000
    os.utime(repo / "tools/a/Makefile", (2_000_000_000, 2_000_000_000))
    h.normalize_mtimes(repo, ["tools"])
    assert (repo / "tools/a/Makefile").stat().st_mtime == first  # reproducible
    (repo / "tools/a/Makefile").write_text("changed\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    h.normalize_mtimes(repo, ["tools"])
    assert (repo / "tools/a/Makefile").stat().st_mtime != first  # content-sensitive

# --- Builder + SDK metadata in hybrid mode --------------------------------------
import argparse  # noqa: E402
with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)
    for name in ("ib.tar.zst", "ib2.tar.zst", "overlay.tar.gz", "packages.txt",
                 "immortalwrt-sdk-qualcommax-ipq60xx_gcc-14.4.0_musl.Linux-x86_64.tar.zst"):
        (t / name).write_bytes(name.encode() * 50)
    (t / "lock.json").write_text(json.dumps(LOCK))
    info = {"identity": "a" * 64, "kernel_identity": kid, "kernel_built_at": "2026-11-14T01:02:03Z",
            "kernel_parent": None, "keyring_commit": SHA("9")}
    (t / "info.json").write_text(json.dumps(info))
    args = argparse.Namespace(immortal=SHA("a"), ppe=SHA("b"), base=SHA("c"), feeds=fp,
                              archive=t / "ib.tar.zst", overlay=t / "overlay.tar.gz",
                              packages=t / "packages.txt", output=t / "meta.json",
                              mode="hybrid", snapshot_lock=t / "lock.json",
                              hybrid_info=t / "info.json")
    ib.metadata(args)
    doc, legacy = ib.check_metadata(t / "meta.json")
    assert not legacy and doc["build_mode"] == "hybrid" and doc["hybrid"] == info
    assert doc["official_snapshot"]["snapshot_version"] == "r42542-e695009c15"
    assert doc["official_snapshot"]["arch_feeds"]["luci"] == SHA("2")
    assert doc["fingerprint"] == core and doc["tag"].startswith("imm-builder-aaaaaaaa-")
    # Hybrid tags carry the snapshot, so a refresh never collides with its parent.
    assert doc["tag"] == ib.tag(SHA("a"), SHA("b"), SHA("c"), feeds=fp, mode="hybrid") + "-s11111111"
    tampered = dict(doc, hybrid=dict(info, kernel_built_at="yesterday"))
    (t / "bad.json").write_text(json.dumps(tampered))
    expect_error(lambda: ib.check_metadata(t / "bad.json"), "kernel_built_at")
    tampered = dict(doc, official_snapshot=dict(doc["official_snapshot"], lock_fingerprint="2" * 64))
    (t / "bad.json").write_text(json.dumps(tampered))
    expect_error(lambda: ib.check_metadata(t / "bad.json"), "do not match")
    for bad in (dict(vars(args), snapshot_lock=None), dict(vars(args), mode="full"),
                dict(vars(args), hybrid_info=None)):
        expect_error(lambda: ib.metadata(argparse.Namespace(**bad)), "")

    # SDK for the full build, then reissued unchanged for a refreshed Builder.
    sdk_archive = t / "immortalwrt-sdk-qualcommax-ipq60xx_gcc-14.4.0_musl.Linux-x86_64.tar.zst"
    feeds = {"packages": SHA("1"), "luci": SHA("2"), "routing": SHA("3"),
             "telephony": SHA("4"), "nss": SHA("5"), "ppe_qos_luci": SHA("6")}
    sdk.issue(t / "meta.json", sdk_archive, "official-immortalwrt", feeds, SHA("a"),
              t / "lock1.json", t / "sdk1.json")
    refreshed_lock = json.loads(json.dumps(next_snapshot))
    refreshed_lock["lock_fingerprint"] = "5" * 64
    (t / "lock2.json").write_text(json.dumps(refreshed_lock))
    fp2 = h.feeds_fingerprint(refreshed_lock, SHA("5"), SHA("6"))
    (t / "info2.json").write_text(json.dumps(dict(info, identity="b" * 64, kernel_parent=doc["tag"])))
    ib.metadata(argparse.Namespace(**dict(vars(args), feeds=fp2, archive=t / "ib2.tar.zst",
                                          output=t / "meta2.json", snapshot_lock=t / "lock2.json",
                                          hybrid_info=t / "info2.json")))
    child, _ = ib.check_metadata(t / "meta2.json")
    assert child["tag"] != doc["tag"] and child["tag"].endswith("-s55555555")
    assert child["hybrid"]["kernel_parent"] == doc["tag"]
    feeds2 = dict(feeds, luci=SHA("7"))
    (t / "feeds2.json").write_text(json.dumps(feeds2))
    subprocess.run([sys.executable, str(ROOT / "scripts/immortalwrt_sdk.py"), "reissue",
                    "--parent-metadata", str(t / "sdk1.json"), "--builder-metadata", str(t / "meta2.json"),
                    "--archive", str(sdk_archive), "--feeds", str(t / "feeds2.json"),
                    "--feed-lock", str(t / "lock2-sdk.json"), "--output", str(t / "sdk2.json")],
                   check=True, capture_output=True)
    sdk2 = sdk.verify_files(t / "sdk2.json", t / "meta2.json", sdk_archive, t / "lock2-sdk.json")
    assert sdk2["derived_from_builder"] == doc["tag"] and sdk2["archive_sha256"] == ib.sha256(sdk_archive)
    # A stale feed set (the parent's) cannot be bound to the refreshed Builder.
    expect_error(lambda: sdk.issue(t / "meta2.json", sdk_archive, "official-immortalwrt", feeds,
                                   SHA("a"), t / "x.json", t / "y.json"), "feeds do not match")

# --- Scripts and workflow contracts ---------------------------------------------
full_script = (ROOT / "scripts/build-immortalwrt-hybrid.sh").read_text()
refresh_script = (ROOT / "scripts/refresh-hybrid-builder.sh").read_text()
common = (ROOT / "scripts/hybrid-common.sh").read_text()
workflow = (ROOT / ".github/workflows/builder-immortalwrt-hybrid.yml").read_text()
publish = (ROOT / "scripts/publish-hybrid-builder.sh").read_text()
for script in (full_script, refresh_script):
    assert 'source "$ROOT/scripts/hybrid-common.sh"' in script
    assert "hybrid_official_indexes" in script and "hybrid_mirror" in script
    assert "hybrid_ib_manifest" in script and "repack-immortalwrt.sh" in script
    assert "\n! " not in script and "  ! " not in script  # `!` never trips set -e
assert "make " not in refresh_script.replace("make -C", "")  # refresh never compiles
assert 'cp -a "$IB" "$WORK/ib-manifest"' in refresh_script  # keys from the manifest run never ship
assert "hybrid_check_archive_keys" in refresh_script and "hybrid_check_archive_keys" in full_script
assert 'verify "${files[@]}"' in common and "--keys-dir" in common
# Index initialization must run before the first package index attempt.
assert common.index('make -C "$ib" -s _check_keys') < common.index('make -C "$ib" -s package_index')
assert "ImageBuilder staged $apk_count" in common
assert "imagebuilder-mkndx.log" in common
assert "for p in apk-openssl kernel base-files libc; do" in common
assert "normalize-mtimes --repo" in full_script and ".tools_*" in full_script
assert "refresh-hybrid-builder.sh" in workflow and "build-immortalwrt-hybrid.sh" in workflow
assert "needs.refresh.result == 'failure'" in workflow  # failed refresh falls back to full
assert "hybrid_builder.py decide" in workflow and "host_key" in workflow
assert "--prerelease" in publish and "firmware-immortalwrt.yml" in publish
assert 'startswith("Hybrid ImageBuilder")' in workflow and "Hybrid ImageBuilder + SDK" in publish
assert "schedule:" not in (ROOT / ".github/workflows/builder-immortalwrt.yml").read_text()
assert "push:" not in (ROOT / ".github/workflows/builder-incremental.yml").read_text()
hybrid_wf = (ROOT / ".github/workflows/builder-immortalwrt-hybrid.yml").read_text()
assert 'branches: [main, "feat/hybrid-**"]' in hybrid_wf
assert "contains(github.event.head_commit.message, '[full]')" in hybrid_wf
publish_sh = (ROOT / "scripts/publish-hybrid-builder.sh").read_text()
assert 'if [[ "$BRANCH" != main ]]; then\n  PRERELEASE=true' in publish_sh

print("PASS hybrid plan, closure, mirror, identities, skip/refresh/full, host cache, metadata, workflow")
