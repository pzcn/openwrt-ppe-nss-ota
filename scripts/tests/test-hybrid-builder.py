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
    block("package/system/apk", pkgs=[("apk-openssl", "", ())]),
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
assert not roots & {"csstidy", "apk-openssl", "sqm-scripts", "libc", "kmod-fs-f2fs"}
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
                 pkg("tc-full", provides=["tc"]), pkg("tc-tiny", provides=["tc"])],
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

# --- Builder metadata in hybrid mode ---------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)
    for name in ("ib.tar.zst", "overlay.tar.gz", "packages.txt"):
        (t / name).write_bytes(b"x" * 200)
    (t / "lock.json").write_text(json.dumps(LOCK))
    import argparse
    args = argparse.Namespace(immortal=SHA("a"), ppe=SHA("b"), base=SHA("c"), feeds=fp,
                              archive=t / "ib.tar.zst", overlay=t / "overlay.tar.gz",
                              packages=t / "packages.txt", output=t / "meta.json",
                              mode="hybrid", snapshot_lock=t / "lock.json")
    ib.metadata(args)
    doc, legacy = ib.check_metadata(t / "meta.json")
    assert not legacy and doc["build_mode"] == "hybrid"
    assert doc["official_snapshot"]["snapshot_version"] == "r42542-e695009c15"
    assert doc["official_snapshot"]["arch_feeds"]["luci"] == SHA("2")
    assert doc["fingerprint"] == core and doc["tag"].startswith("imm-builder-aaaaaaaa-")
    full_tag = ib.tag(SHA("a"), SHA("b"), SHA("c"), feeds=fp)
    assert doc["tag"] != full_tag
    args.snapshot_lock = None
    expect_error(lambda: ib.metadata(args), "official snapshot lock")
    args.mode, args.snapshot_lock = "full", t / "lock.json"
    expect_error(lambda: ib.metadata(args), "official snapshot lock")

print("PASS hybrid plan, official closure, mirror pins, feeds, identity and metadata")
