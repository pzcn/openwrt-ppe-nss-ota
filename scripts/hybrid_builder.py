#!/usr/bin/env python3
"""Hybrid Builder planning: local kernel/PPE packages + official userland APKs.

Division of labour (see docs/HYBRID-BUILDER.md):

* The kernel tree is ImmortalWrt master + the PPE/NSS port, the combination
  the full-source Builder already compiles. The kernel, every selected kmod,
  base-files, the toolchain libraries and the custom PPE/LuCI packages are
  compiled locally.
* Package feeds are pinned to the commits the official arch repositories
  were built from, and all other userland APKs are taken from the official
  ImmortalWrt snapshot, verified by signed index + SHA256.

Everything here is deterministic and stdlib-only, so it can be unit-tested
without a buildroot.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+._-]*$")
SRC_PATH = re.compile(r"^package/[A-Za-z0-9+._/-]+$")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ARCH_FEEDS = ("base", "packages", "luci", "routing", "telephony")
OFFICIAL_REPOS = ("target",) + ARCH_FEEDS
# Must equal the URLs the SDK rebuild path (rebuild-missing-apks.sh) fetches.
FEED_URLS = {
    "packages": "https://github.com/immortalwrt/packages.git",
    "luci": "https://github.com/immortalwrt/luci.git",
    "routing": "https://github.com/openwrt/routing.git",
    "telephony": "https://github.com/openwrt/telephony.git",
}
NSS_FEED_URL = "https://github.com/JuliusBairaktaris/nss-packages.git"
# Compiled locally even though official copies exist: they carry the PPE/OTA
# patches, are tied to this kernel/toolchain, or are not published upstream.
LOCAL_PACKAGES = frozenset((
    "base-files",
    "qca-ppe-qos", "ppe-help", "sqm-scripts",
    "luci-app-qca-ppe-qos", "luci-theme-aurora", "luci-app-sing-box",
))
# Not in buildroot metadata (BuildPackage is skipped under DUMP=1), but always
# produced by package/kernel/linux.
KERNEL_SOURCE = "package/kernel/linux"
# Whole sources compiled locally (every selected package they produce is local).
LOCAL_SOURCES = frozenset(("package/libs/toolchain",))
LOCAL_FEEDS = frozenset(("nss",))
# Sources that never belong in the image repository.
IGNORED_SOURCES = frozenset(("package/system/apk",))
HYBRID_CORE_FILES = (
    "scripts/build-immortalwrt-hybrid.sh",
    "scripts/hybrid_builder.py",
    "scripts/resolve-immortalwrt-snapshot.py",
    "scripts/reuse-official-toolchain.sh",
    "scripts/port-ppe-nss-to-immortalwrt.sh",
    "scripts/apply-immortalwrt-compat.sh",
    "config/immortalwrt-re-ss-01.config",
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


# --------------------------------------------------------------------------
# Kconfig / buildroot metadata
# --------------------------------------------------------------------------

def kernel_config_lines(buildinfo: str) -> list[str]:
    """Official CONFIG_KERNEL_* choices, so our kernel offers the same features.

    Build identity (user/domain) is deliberately not copied.
    """
    out = []
    for raw in buildinfo.splitlines():
        line = raw.strip()
        m = re.fullmatch(r"(?:# )?(CONFIG_KERNEL_[A-Za-z0-9_]+)(?:=.*| is not set)", line)
        if not m or m.group(1) in ("CONFIG_KERNEL_BUILD_USER", "CONFIG_KERNEL_BUILD_DOMAIN"):
            continue
        out.append(line)
    return out


def parse_symbols(text: str) -> dict[str, str]:
    """All enabled .config symbols (without the CONFIG_ prefix)."""
    symbols = {}
    for line in text.splitlines():
        m = re.fullmatch(r"CONFIG_([A-Za-z0-9+._-]+)=(.*)", line.strip())
        if m:
            symbols[m.group(1)] = m.group(2)
    return symbols


def parse_config(text: str) -> dict[str, str]:
    """Selected packages: name -> 'y' or 'm'."""
    return {name[len("PACKAGE_"):]: value for name, value in parse_symbols(text).items()
            if name.startswith("PACKAGE_") and value in ("y", "m")}


def kconfig_true(expr: str, symbols: dict[str, str]) -> bool:
    """Evaluate a Kconfig dependency condition such as '(A||B)&&!C'."""
    tokens = re.findall(r"\|\||&&|[!()]|[A-Za-z0-9_+.-]+", expr)
    if "".join(tokens) != expr.replace(" ", ""):
        raise ValueError(f"Unsupported Kconfig condition: {expr}")
    pos = 0

    def peek() -> str:
        return tokens[pos] if pos < len(tokens) else ""

    def take() -> str:
        nonlocal pos
        if pos >= len(tokens):
            raise ValueError(f"Truncated Kconfig condition: {expr}")
        pos += 1
        return tokens[pos - 1]

    def atom() -> bool:
        tok = take()
        if tok == "!":
            return not atom()
        if tok == "(":
            value = disjunction()
            if take() != ")":
                raise ValueError(f"Unbalanced Kconfig condition: {expr}")
            return value
        if not tok or tok in ("&&", "||", ")"):
            raise ValueError(f"Malformed Kconfig condition: {expr}")
        return symbols.get(tok, "n") in ("y", "m")

    def conjunction() -> bool:
        value = atom()
        while peek() == "&&":
            take()
            value = atom() and value
        return value

    def disjunction() -> bool:
        value = conjunction()
        while peek() == "||":
            take()
            value = conjunction() or value
        return value

    result = disjunction()
    if pos != len(tokens):
        raise ValueError(f"Trailing tokens in Kconfig condition: {expr}")
    return result


def parse_packageinfo(text: str) -> tuple[dict[str, dict], dict[str, dict]]:
    """Parse tmp/.packageinfo into (sources by path, packages by name)."""
    sources: dict[str, dict] = {}
    packages: dict[str, dict] = {}
    src: dict | None = None
    pkg: dict | None = None
    in_description = False
    for raw in text.splitlines():
        if in_description:
            if raw.strip() == "@@":
                in_description = False
                pkg = None
            continue
        if raw.startswith("Source-Makefile: "):
            path = raw.split(": ", 1)[1].strip()
            if not path.endswith("/Makefile"):
                raise ValueError(f"Unexpected Source-Makefile: {path}")
            path = path[: -len("/Makefile")]
            src = {"path": path, "name": path.rsplit("/", 1)[-1],
                   "build_depends": [], "packages": []}
            sources[path] = src
            pkg = None
            continue
        if src is None or ": " not in raw and not raw.endswith(":"):
            continue
        key, _, value = raw.partition(":")
        value = value.strip()
        if key == "Package":
            pkg = {"name": value, "source": src["path"], "depends": [],
                   "provides": [], "abi": "", "build_only": False}
            if value in packages:
                raise ValueError(f"Package defined twice: {value}")
            packages[value] = pkg
            src["packages"].append(value)
        elif pkg is None and key == "Build-Depends":
            src["build_depends"] = value.split()
        elif pkg is not None and key == "Depends":
            pkg["depends"] = value.split()
        elif pkg is not None and key == "Provides":
            pkg["provides"] = value.split()
        elif pkg is not None and key == "ABI-Version":
            pkg["abi"] = value
        elif pkg is not None and key == "Build-Only":
            pkg["build_only"] = value == "1"
        elif pkg is not None and key == "Description":
            in_description = True
    return sources, packages


def kconfig_dep_names(tokens: list[str], symbols: dict[str, str]) -> list[str]:
    """Runtime package names from buildroot Depends ('+x', '+COND:x', 'x').

    '@SYM' entries are pure Kconfig constraints. Conditional entries count
    only when their condition holds for this .config.
    """
    names = []
    for token in tokens:
        token = token.lstrip("+")
        if not token or token.startswith("@"):
            continue
        cond, _, dep = token.rpartition(":")
        if cond and not kconfig_true(cond, symbols):
            continue
        if PKG.fullmatch(dep):
            names.append(dep)
    return names


def source_lookup(sources: dict[str, dict], packages: dict[str, dict], name: str) -> str | None:
    """Resolve a buildroot dependency name (source dir or package) to a path."""
    matches = [p for p, s in sources.items() if s["name"] == name]
    if len(matches) == 1:
        return matches[0]
    if name in packages:
        return packages[name]["source"]
    if len(matches) > 1:
        # Prefer the in-tree copy over a duplicate under package/feeds.
        core = [p for p in matches if not p.startswith("package/feeds/")]
        if len(core) == 1:
            return core[0]
    return None


def abi_name(packages: dict[str, dict], name: str) -> str:
    """APK name as include/feeds.mk FormatABISuffix writes it."""
    pkg = packages.get(name)
    abi = pkg["abi"] if pkg and not name.startswith("kmod-") else ""
    if not abi:
        return name
    return name + ("-" if name[-1].isdigit() else "") + abi


def is_local_package(name: str, pkg: dict) -> bool:
    src = pkg["source"]
    feed = src.split("/")[2] if src.startswith("package/feeds/") else ""
    return (name in LOCAL_PACKAGES or name.startswith("kmod-")
            or src in LOCAL_SOURCES or feed in LOCAL_FEEDS)


def local_plan(sources: dict[str, dict], packages: dict[str, dict],
               symbols: dict[str, str], extra_local: set[str] = frozenset()) -> dict:
    """Decide which selected packages are compiled locally, and how."""
    selected = {name[len("PACKAGE_"):]: value for name, value in symbols.items()
                if name.startswith("PACKAGE_") and value in ("y", "m")}
    missing = sorted(n for n in LOCAL_PACKAGES if n not in selected)
    if missing:
        raise ValueError("Mandatory local packages are not selected: " + ", ".join(missing))
    local: dict[str, dict] = {}
    for name, value in selected.items():
        pkg = packages.get(name)
        if pkg is None or pkg["build_only"] or pkg["source"] in IGNORED_SOURCES:
            continue
        if is_local_package(name, pkg) or name in extra_local:
            local[name] = pkg
    # Sources that produce a kmod (or the kernel) are compiled with their normal
    # dependency chain: those are kernel objects, never official userland.
    if KERNEL_SOURCE not in sources:
        raise ValueError("Buildroot metadata lacks " + KERNEL_SOURCE)
    kernel_sources = sorted({p["source"] for n, p in local.items() if n.startswith("kmod-")}
                            | {KERNEL_SOURCE})
    userland_sources = sorted({p["source"] for p in local.values()} - set(kernel_sources))
    host_targets: set[str] = set()
    blockers = []
    for path in userland_sources:
        for token in sources[path]["build_depends"]:
            dep = token.rsplit(":", 1)[-1].lstrip("+")
            if dep.endswith("/host"):
                target = source_lookup(sources, packages, dep[: -len("/host")])
                if target is None:
                    blockers.append(f"{path}: unknown host build dependency {dep}")
                else:
                    host_targets.add(target + "/host/compile")
            else:
                # NO_DEPS userland builds must not secretly need target libraries.
                blockers.append(f"{path}: target build dependency {dep} needs a full dependency build")
    if blockers:
        raise ValueError("Local userland cannot be compiled without dependencies:\n  "
                         + "\n  ".join(blockers))
    local_names = sorted(local)
    return {
        "schema": 1,
        "kernel_compile_targets": [p + "/compile" for p in kernel_sources],
        "host_compile_targets": sorted(host_targets),
        "userland_compile_targets": [p + "/compile" for p in userland_sources],
        "local_packages": [
            {"name": n, "apk_name": abi_name(packages, n), "source": local[n]["source"],
             # Plain names: NO_DEPS builds have no staged pkginfo, so their
             # library dependencies carry no ABI suffix; official ABI
             # libraries also provide the plain name.
             "depends": kconfig_dep_names(local[n]["depends"], symbols),
             "provides": [x.lstrip("@") for x in local[n]["provides"]]}
            for n in local_names
        ] + [{"name": "kernel", "apk_name": "kernel", "source": KERNEL_SOURCE,
              "depends": [], "provides": []}],
        "local_kmods": [n for n in local_names if n.startswith("kmod-")],
        # Plain names: official libraries carry the snapshot's own ABI suffix.
        # 'm' too: per-device rootfs selects device packages (ipq-wifi-*) as m.
        "image_roots": sorted(
            n for n in selected
            if n in packages and not packages[n]["build_only"]
            and packages[n]["source"] not in IGNORED_SOURCES and n not in local
        ),
    }


# --------------------------------------------------------------------------
# Official APK indexes and dependency closure
# --------------------------------------------------------------------------

def atom_name(atom: str) -> str:
    """Name part of an apk dependency atom; '' for conflicts."""
    atom = atom.strip()
    if not atom or atom.startswith("!"):
        return ""
    name = re.split(r"[<>=~]", atom, maxsplit=1)[0].strip()
    if not PKG.fullmatch(name):
        raise ValueError(f"Unexpected dependency atom: {atom!r}")
    return name


def _atoms(value: object) -> list[str]:
    out = []
    for item in value or []:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict) and isinstance(item.get("name"), str):
            out.append(item["name"])
        else:
            raise ValueError(f"Unexpected dependency entry: {item!r}")
    return out


def parse_index_json(text: str, repo: str) -> list[dict]:
    """Parse `apk adbdump --format json packages.adb` output."""
    if repo not in OFFICIAL_REPOS:
        raise ValueError(f"Unknown official repository: {repo}")
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get("packages")
    if not isinstance(data, list) or not data:
        raise ValueError(f"Empty or malformed index: {repo}")
    out = []
    for raw in data:
        name, version = raw.get("name"), raw.get("version")
        if not isinstance(name, str) or not PKG.fullmatch(name) or not isinstance(version, str):
            raise ValueError(f"Malformed package entry in {repo}: {raw!r:.120}")
        base = name
        for tag in raw.get("tags") or []:
            if isinstance(tag, str) and tag.startswith("openwrt:abiversion="):
                abi = tag.split("=", 1)[1]
                if abi and name.endswith(abi):
                    base = name[: -len(abi)]
        out.append({"name": name, "base": base, "version": version, "repo": repo,
                    "depends": _atoms(raw.get("depends")),
                    "provides": [atom_name(a.lstrip("@")) for a in _atoms(raw.get("provides"))
                                 if atom_name(a.lstrip("@"))]})
    return out


def closure(plan: dict, indexes: dict[str, list[dict]]) -> dict:
    """Official APKs needed by the image roots, with local packages taking precedence."""
    if set(indexes) != set(OFFICIAL_REPOS):
        raise ValueError("Need exactly the target + five arch indexes")
    local_names = {p["apk_name"] for p in plan["local_packages"]}
    local_provides = set(local_names)
    for p in plan["local_packages"]:
        local_provides.update(atom_name(x) for x in p["provides"] if atom_name(x))

    local_plain = {p["name"] for p in plan["local_packages"]}
    by_name: dict[str, list[dict]] = {}
    by_base: dict[str, list[dict]] = {}
    by_provide: dict[str, list[dict]] = {}
    for repo in OFFICIAL_REPOS:
        for pkg in indexes[repo]:
            by_name.setdefault(pkg["name"], []).append(pkg)
            by_base.setdefault(pkg.get("base", pkg["name"]), []).append(pkg)
            for provided in pkg["provides"]:
                by_provide.setdefault(provided, []).append(pkg)

    def official(name: str, plain: bool = False) -> list[dict]:
        found = by_name.get(name, []) or (by_base.get(name, []) if plain else [])
        # A target-specific build wins over an arch duplicate of the same name.
        target = [p for p in found if p["repo"] == "target"]
        return target or found

    chosen: dict[str, dict] = {}
    wanted = set(plan["image_roots"]) | local_plain
    virtual_choices: dict[str, str] = {}
    errors: list[str] = []
    fallback: list[str] = []
    queue: deque[tuple[str, str]] = deque()

    def need(name: str, why: str) -> None:
        if not name or name in local_provides or (why == "image" and name in local_plain):
            return
        if name == "kernel" or name.startswith("kmod-"):
            errors.append(f"{why} needs {name}, which is not selected in the local kernel build")
            return
        candidates = official(name, plain=why == "image")
        if not candidates:
            # Virtual name: the image solver picks ONE provider. Prefer the
            # provider the configuration selected, else a deterministic one.
            providers = by_provide.get(name, [])
            preferred = [c for c in providers
                         if c.get("base", c["name"]) in wanted or c["name"] in chosen]
            if preferred:
                candidates = preferred
            elif providers:
                def viable(c: dict) -> bool:
                    kmods = (atom_name(d) for d in c["depends"])
                    return all(k in local_provides for k in kmods if k.startswith("kmod-"))
                candidates = [sorted(providers, key=lambda c: (
                    not viable(c), c["repo"] != "target", c["name"]))[0]]
                virtual_choices[name] = candidates[0]["name"]
        if not candidates:
            if why == "image":
                fallback.append(name)
            else:
                errors.append(f"{why} needs {name}, found neither locally nor in the official snapshot")
            return
        for pkg in candidates:
            if (pkg["name"] in local_names or pkg.get("base") in local_plain
                    or pkg["name"].startswith("kmod-") or pkg["name"] == "kernel"):
                continue
            if pkg["name"] not in chosen:
                chosen[pkg["name"]] = pkg
                queue.append((pkg["name"], pkg["repo"]))

    for root in plan["image_roots"]:
        need(root, "image")
    for local in plan["local_packages"]:
        for dep in local["depends"]:
            need(dep, local["name"])
    while queue:
        name, _ = queue.popleft()
        for atom in chosen[name]["depends"]:
            need(atom_name(atom), name)

    return {
        "official": [{"name": p["name"], "version": p["version"], "repo": p["repo"]}
                     for p in sorted(chosen.values(), key=lambda p: (p["repo"], p["name"]))],
        "virtual_choices": dict(sorted(virtual_choices.items())),
        "local_fallback": sorted(set(fallback)),
        "errors": sorted(set(errors)),
    }


def mirror_plan(selection: list[dict], lock: dict, target_sums: dict[str, str],
                arch_sums: dict[str, str]) -> list[dict]:
    out = []
    missing = []
    for item in selection:
        filename = f"{item['name']}-{item['version']}.apk"
        if item["repo"] == "target":
            rel, sums, base = "packages/" + filename, target_sums, lock["target_url"]
        else:
            rel, sums, base = item["repo"] + "/" + filename, arch_sums, lock["architecture_url"]
        sha = sums.get(rel)
        if not sha or not HEX64.fullmatch(sha):
            missing.append(rel)
            continue
        out.append({**item, "filename": filename, "url": base + "/" + rel, "sha256": sha})
    if missing:
        raise ValueError("Official APKs absent from the locked sha256sums: " + ", ".join(missing))
    return out


def parse_sums(text: str) -> dict[str, str]:
    sums = {}
    for line in text.splitlines():
        m = re.fullmatch(r"([0-9a-f]{64})\s+\*?(\S+)", line.strip())
        if m:
            sums[m.group(2)] = m.group(1)
    if not sums:
        raise ValueError("Empty sha256sums")
    return sums


# --------------------------------------------------------------------------
# Feeds, fingerprints and identity
# --------------------------------------------------------------------------

def feeds_conf(lock: dict, nss_sha: str) -> str:
    """Feeds pinned to the commits the official arch packages were built from."""
    if not GIT_SHA.fullmatch(nss_sha):
        raise ValueError("NSS feed must be pinned to a full SHA")
    feeds = lock["arch_feeds"]
    lines = []
    for name, url in FEED_URLS.items():
        entry = feeds.get(name)
        if not entry or not GIT_SHA.fullmatch(entry.get("commit", "")):
            raise ValueError(f"Snapshot lock lacks a pinned {name} feed")
        if entry["url"] != url:
            raise ValueError(f"Unexpected {name} feed URL in snapshot: {entry['url']}")
        lines.append(f"src-git {name} {url}^{entry['commit']}")
    lines.append(f"src-git nss {NSS_FEED_URL}^{nss_sha}")
    return "\n".join(lines) + "\n"


def feeds_fingerprint(lock: dict, nss_sha: str, ppe_luci_sha: str) -> str:
    """Same digest immortalwrt_sdk.feed_fingerprint computes from checkouts."""
    heads = [lock["arch_feeds"][f]["commit"] for f in ("packages", "luci", "routing", "telephony")]
    heads += [nss_sha, ppe_luci_sha]
    for head in heads:
        if not GIT_SHA.fullmatch(head):
            raise ValueError("Feed revision must be a full SHA")
    return hashlib.sha256("".join(h + "\n" for h in heads).encode("ascii")).hexdigest()


def core_fingerprint(root: Path = ROOT) -> str:
    digest = hashlib.sha256()
    for name in HYBRID_CORE_FILES:
        digest.update(name.encode() + b"\0" + (root / name).read_bytes() + b"\0")
    return digest.hexdigest()


def identity(lock: dict, ppe: str, base: str, nss: str, ppe_luci: str,
             core: str, packages: str) -> str:
    """What decides whether a new hybrid Builder is needed.

    ImmortalWrt master HEAD is intentionally absent: the kernel tree follows
    master, but a rebuild is only triggered by the official snapshot, the PPE
    sources or this repository's recipe/package list.
    """
    for value in (ppe, base, nss, ppe_luci):
        if not GIT_SHA.fullmatch(value):
            raise ValueError("Identity inputs must be full SHAs")
    for value in (core, packages):
        if not HEX64.fullmatch(value):
            raise ValueError("Identity fingerprints must be SHA256")
    return sha256_bytes(canonical({
        "snapshot": {
            "version": lock["snapshot_version"],
            "kernel_fingerprint": lock["kernel_fingerprint"],
            "packages_fingerprint": lock["packages_fingerprint"],
            "arch_feeds": lock["arch_feeds"],
        },
        "ppe": ppe, "base": base, "nss": nss, "ppe_luci": ppe_luci,
        "core": core, "packages": packages,
    }))


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def cmd_kernel_config(args: argparse.Namespace) -> None:
    lines = kernel_config_lines(args.buildinfo.read_text())
    print("\n".join(lines))


def cmd_feeds_conf(args: argparse.Namespace) -> None:
    sys.stdout.write(feeds_conf(_read_json(args.lock), args.nss))


def cmd_plan(args: argparse.Namespace) -> None:
    sources, packages = parse_packageinfo(args.packageinfo.read_text())
    extra = set(args.extra_local.read_text().split()) if args.extra_local else set()
    plan = local_plan(sources, packages, parse_symbols(args.config.read_text()), extra)
    args.output.write_text(json.dumps(plan, indent=2) + "\n")
    print(f"Local: {len(plan['local_packages'])} packages "
          f"({len(plan['local_kmods'])} kmods) from "
          f"{len(plan['kernel_compile_targets'])} kernel + "
          f"{len(plan['userland_compile_targets'])} userland sources; "
          f"{len(plan['image_roots'])} official image roots")


def cmd_closure(args: argparse.Namespace) -> None:
    plan = _read_json(args.plan)
    lock = _read_json(args.lock)
    indexes = {}
    for spec in args.index:
        repo, _, path = spec.partition("=")
        indexes[repo] = parse_index_json(Path(path).read_text(), repo)
    result = closure(plan, indexes)
    if result["errors"]:
        raise ValueError("Official userland does not fit the local kernel build:\n  "
                         + "\n  ".join(result["errors"]))
    result["mirror"] = mirror_plan(result["official"], lock,
                                   parse_sums(args.target_sums.read_text()),
                                   parse_sums(args.arch_sums.read_text()))
    del result["official"]
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Official APKs to mirror: {len(result['mirror'])}")
    if result["local_fallback"]:
        print("Not published officially, compile locally: " + " ".join(result["local_fallback"]))


def cmd_identity(args: argparse.Namespace) -> None:
    lock = _read_json(args.lock)
    print(identity(lock, args.ppe, args.base, args.nss, args.ppe_luci,
                   args.core or core_fingerprint(), args.packages))


def cmd_fingerprint(args: argparse.Namespace) -> None:
    if args.kind == "core":
        print(core_fingerprint())
    else:
        print(feeds_fingerprint(_read_json(args.lock), args.nss, args.ppe_luci))


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("kernel-config")
    s.add_argument("--buildinfo", type=Path, required=True)
    s.set_defaults(func=cmd_kernel_config)
    s = sub.add_parser("feeds-conf")
    s.add_argument("--lock", type=Path, required=True)
    s.add_argument("--nss", required=True)
    s.set_defaults(func=cmd_feeds_conf)
    s = sub.add_parser("plan")
    s.add_argument("--packageinfo", type=Path, required=True)
    s.add_argument("--config", type=Path, required=True)
    s.add_argument("--extra-local", type=Path)
    s.add_argument("--output", type=Path, required=True)
    s.set_defaults(func=cmd_plan)
    s = sub.add_parser("closure")
    s.add_argument("--plan", type=Path, required=True)
    s.add_argument("--lock", type=Path, required=True)
    s.add_argument("--index", action="append", required=True, help="repo=adbdump.json")
    s.add_argument("--target-sums", type=Path, required=True)
    s.add_argument("--arch-sums", type=Path, required=True)
    s.add_argument("--output", type=Path, required=True)
    s.set_defaults(func=cmd_closure)
    s = sub.add_parser("identity")
    s.add_argument("--lock", type=Path, required=True)
    for name in ("ppe", "base", "nss", "ppe-luci", "packages"):
        s.add_argument(f"--{name}", required=True)
    s.add_argument("--core")
    s.set_defaults(func=cmd_identity)
    s = sub.add_parser("fingerprint")
    s.add_argument("kind", choices=("core", "feeds"))
    s.add_argument("--lock", type=Path)
    s.add_argument("--nss")
    s.add_argument("--ppe-luci")
    s.set_defaults(func=cmd_fingerprint)
    args = p.parse_args(argv)
    try:
        args.func(args)
    except (ValueError, KeyError, OSError) as exc:
        print(f"hybrid_builder: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
