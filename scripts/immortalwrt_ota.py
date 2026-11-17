#!/usr/bin/env python3
"""Prepare an independent ImmortalWrt PPE/NSS OTA channel and its release metadata."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import time

REPOSITORY = "pzcn/openwrt-ppe-nss-ota"
CHANNEL = "re-ss-01-immortal-ppe-nss"
GROUP = "ipq60xx-512m"
PROFILE = "jdcloud_re-ss-01"
BOARD = "jdcloud,re-ss-01"
IMAGE = "immortalwrt-qualcommax-ipq60xx-jdcloud_re-ss-01-squashfs-sysupgrade.bin"
MANIFEST = "immortalwrt-qualcommax-ipq60xx-jdcloud_re-ss-01.manifest"
TAG_PATTERN = re.compile(r"^imm-(?:re-ss-01|mx4200v1|wma301|wma301v21)-[a-zA-Z0-9._-]+$")
SHA_PATTERN = re.compile(r"^[a-f0-9]{40}$")

# The updater implementation and release index are shared; every device gets
# a unique, strictly checked OTA identity and its own release sequence.
DEVICES = {
    "arthur": {
        "channel": CHANNEL, "group": GROUP, "profile": PROFILE, "board": BOARD,
        "target": "qualcommax/ipq60xx", "image": IMAGE, "manifest": MANIFEST,
        "tag_prefix": "imm-re-ss-01-", "display": "RE-SS-01 PPE+NSS",
    },
    "mx4200v1": {
        "channel": "mx4200v1-immortal-ppe-nss", "group": "ipq807x-6m",
        "profile": "linksys_mx4200v1", "board": "linksys,mx4200v1",
        "target": "qualcommax/ipq807x",
        "image": "immortalwrt-qualcommax-ipq807x-linksys_mx4200v1-squashfs-sysupgrade.bin",
        "manifest": "immortalwrt-qualcommax-ipq807x-linksys_mx4200v1.manifest",
        "tag_prefix": "imm-mx4200v1-", "display": "MX4200 v1 PPE+NSS",
    },
    "wma301": {
        "channel": "wma301-immortal-filogic",
        "group": "filogic-mt7981-single-ubi",
        "profile": "tplink_wma301-v2", "board": "tplink,wma301-v2",
        "target": "mediatek/filogic",
        "image": "immortalwrt-mediatek-filogic-tplink_wma301-v2-squashfs-sysupgrade.itb",
        "manifest": "immortalwrt-mediatek-filogic-tplink_wma301-v2.manifest",
        "tag_prefix": "imm-wma301-", "display": "WMA301 v2.0",
        "layout": "oem-bl2-bl31-custom-bl33-single-ubi-v1",
    },
    "wma301v21": {
        "channel": "wma301v21-immortal-filogic",
        "group": "filogic-mt7981-single-ubi",
        "profile": "tplink_wma301-v2-1", "board": "tplink,wma301-v2-1",
        "target": "mediatek/filogic",
        "image": "immortalwrt-mediatek-filogic-tplink_wma301-v2-1-squashfs-sysupgrade.itb",
        "manifest": "immortalwrt-mediatek-filogic-tplink_wma301-v2-1.manifest",
        "tag_prefix": "imm-wma301v21-", "display": "WMA301 v2.1",
        "layout": "oem-bl2-bl31-custom-bl33-single-ubi-v1",
    },
}


def device_spec(device: str) -> dict:
    try:
        return DEVICES[device]
    except KeyError as exc:
        raise ValueError(f"Unknown OTA device: {device}") from exc



def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fd:
        for chunk in iter(lambda: fd.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def replace_once(source: str, before: str, after: str) -> str:
    count = source.count(before)
    if count != 1:
        raise ValueError(f"Expected one occurrence, found {count}: {before[:80]}")
    return source.replace(before, after)



def fingerprint_flash_view(overlay: Path, build: int) -> str:
    """Change the *module URL*, not just the OTA release tag.

    LuCI caches modules at module.js?v=<luci-base-pkg-version>. That query is
    unchanged when only the ImageBuilder FILES overlay changes. A stock
    flash.js may therefore stay cached after flashing new custom firmware.
    Keep the original route admin/system/flash and redirect its view action
    to a build- and content-fingerprinted copy using a late menu.d override.
    """
    if not isinstance(build, int) or build < 1:
        raise ValueError("Invalid OTA build number for LuCI cache identity")
    directory = overlay / "www/luci-static/resources/view/system"
    original = directory / "flash.js"
    if not original.is_file():
        raise ValueError(f"Missing customized LuCI flash view: {original}")

    content = original.read_bytes()
    digest = hashlib.sha256(content).hexdigest()[:16]
    module = f"system/flash-ota-b{build}-{digest}"
    target = directory / f"{module.split('/')[-1]}.js"

    # Avoid leaving stale copies in the ImageBuilder FILES overlay, without
    # ever removing the stock flash.js (fallback/debugging).
    for older in directory.glob("flash-ota-b*.js"):
        older.unlink()
    target.write_bytes(content)

    menu = overlay / "usr/share/luci/menu.d/zzzz-ota-flash-cache.json"
    menu.parent.mkdir(parents=True, exist_ok=True)
    # LuCI dispatcher merges menu.d entries in filename order. This late file
    # overrides ONLY the existing admin/system/flash action. It creates no
    # extra menu entry, retains the original ACL and keeps the original URL.
    menu.write_text(json.dumps({
        "admin/system/flash": {
            "action": {"type": "view", "path": module},
            "depends": {"acl": ["luci-mod-system-flash"]}
        }
    }, ensure_ascii=False, indent=2) + "\n")
    return module


def prepare(overlay: Path, tag: str, build: int, device: str = "arthur") -> None:
    spec = device_spec(device)
    if not TAG_PATTERN.fullmatch(tag) or not tag.startswith(spec["tag_prefix"]) or build < 1:
        raise ValueError("Invalid release tag/build")
    ota = overlay / "usr/sbin/ppe-update"
    source = ota.read_text()
    patches = [
        ('[ -r "${PPE_RELEASE:=/etc/ppe-release}" ] && . "$PPE_RELEASE"',
         f"GROUP='{spec['group']}'"),
        ('[ -r "${PZCN_RELEASE:=/etc/pzcn-ota-release}" ] && . "$PZCN_RELEASE"',
         '[ -r "${PZCN_RELEASE:=/etc/immortal-ppe-ota-release}" ] && . "$PZCN_RELEASE"'),
        ("RELEASE_API='https://api.github.com/repos/pzcn/openwrt-ppe-nss-ota/releases/latest'",
         "RELEASE_API='https://api.github.com/repos/pzcn/openwrt-ppe-nss-ota/releases?per_page=100'"),
        ("RELEASE_CHANNEL='re-ss-01-custom'",
         f"RELEASE_CHANNEL='{spec['channel']}'"),
        ("EXPECTED_IMAGE='openwrt-pzcn-qualcommax-ipq60xx-jdcloud_re-ss-01-squashfs-sysupgrade.bin'",
         f"EXPECTED_IMAGE='{spec['image']}'"),
        ("EXPECTED_MANIFEST='openwrt-pzcn-qualcommax-ipq60xx-jdcloud_re-ss-01.manifest'",
         f"EXPECTED_MANIFEST='{spec['manifest']}'"),
        ("LATEST=$(jsonfilter -i \"$WORK/github.json\" -e '@.tag_name')",
         """if ! jq -e 'type == "array"' "$WORK/github.json" >/dev/null 2>&1; then
    die "invalid GitHub Releases API response"
fi
LATEST=$(jq -r --arg image "$EXPECTED_IMAGE" --arg manifest "$EXPECTED_MANIFEST" '
    [.[] | select(.draft == false and .prerelease == false and
                  (.tag_name | startswith("__OTA_TAG_PREFIX__")))
         | select(any(.assets[]?; .name == "ota.json"))
         | select(any(.assets[]?; .name == $image))
         | select(any(.assets[]?; .name == $manifest))]
    | sort_by(.published_at // "") | last | .tag_name // empty
' "$WORK/github.json") ||
    die "failed to parse GitHub firmware release index"
[ -n "$LATEST" ] || die "no ImmortalWrt firmware release is published on this channel" """),
        ('\tota-ppe-nss-*) ;;', f'\t{spec["tag_prefix"]}*) ;;'),
        ('\tppe-nss-*) ;;', '\timmortal-*) ;;'),
        ("EXPECTED_BOARD=\'jdcloud,re-ss-01\'", f"EXPECTED_BOARD=\'{spec['board']}\'"),
        ("EXPECTED_PROFILE=\'jdcloud_re-ss-01\'", f"EXPECTED_PROFILE=\'{spec['profile']}\'"),
        ("EXPECTED_GROUP=\'ipq60xx-512m\'", f"EXPECTED_GROUP=\'{spec['group']}\'"),
    ]
    for before, after in patches:
        source = replace_once(source, before, after)
    source = source.replace("__OTA_TAG_PREFIX__", spec["tag_prefix"])
    if device in ("wma301", "wma301v21"):
        # WMA301 uses the same manual and scheduled OTA policy as other boards.
        # Keep the NAND/UBI preflight and layout matching before sysupgrade.
        source = replace_once(
            source, '\tsysupgrade -T "$WORK/$IMAGE" >"$WORK/validation.log" 2>&1 ||',
            '\t/usr/libexec/ppe-update-wma301-preflight || '
            'die "WMA301 single-UBI safety preflight failed"\n'
            '\tsysupgrade -T "$WORK/$IMAGE" >"$WORK/validation.log" 2>&1 ||')
        source = replace_once(
            source, '\t[ "$(meta image)" = "$EXPECTED_IMAGE" ] &&',
            '\t[ "$(meta layout)" = '
            '"oem-bl2-bl31-custom-bl33-single-ubi-v1" ] || '
            'die "WMA301 OTA layout mismatch"\n'
            '\t[ "$(meta image)" = "$EXPECTED_IMAGE" ] &&')
    if "sysupgrade -T" not in source or "cmd_auto()" not in source:
        raise ValueError("OTA backend lost firmware validation/automatic update")
    ota.write_text(source)
    ota.chmod(0o755)

    release = overlay / "etc/immortal-ppe-ota-release"
    release.parent.mkdir(parents=True, exist_ok=True)
    release.write_text(
        f"OTA_TAG={shlex.quote(tag)}\n"
        f"OTA_BUILD={build}\n"
        f"OTA_CHANNEL={shlex.quote(spec['channel'])}\n"
    )
    fingerprint_flash_view(overlay, build)


def metadata(tag: str, build: int, upstream: str, ppe: str, image: Path,
             manifest: Path, output: Path, builder_tag: str = "",
             source_commit: str = "", layer_tag: str = "",
             device: str = "arthur", sing_box_core: Path | None = None) -> None:
    spec = device_spec(device)
    if not TAG_PATTERN.fullmatch(tag) or not tag.startswith(spec["tag_prefix"]) or build < 1:
        raise ValueError("Invalid tag/build")
    if not SHA_PATTERN.fullmatch(upstream):
        raise ValueError("Expected 40-character upstream source SHA")
    if device in ("wma301", "wma301v21"):
        if ppe:
            raise ValueError("WMA301 cannot carry a Qualcomm PPE/NSS source SHA")
    elif not SHA_PATTERN.fullmatch(ppe):
        raise ValueError("Expected 40-character PPE/NSS source SHA")
    if image.name != spec["image"] or manifest.name != spec["manifest"]:
        raise ValueError("Unexpected image or manifest basename")
    if not image.is_file() or image.stat().st_size < 1_000_000:
        raise ValueError("Missing or unusually small firmware image")
    if not manifest.is_file() or manifest.stat().st_size < 100:
        raise ValueError("Missing package manifest")
    if device in ("wma301", "wma301v21") and (builder_tag or layer_tag or sing_box_core is not None):
        raise ValueError("WMA301 cannot carry Qualcomm Builder, layer or sing-box metadata")
    if builder_tag and not re.fullmatch(r"imm-builder-[a-zA-Z0-9._-]+", builder_tag):
        raise ValueError("Invalid ImageBuilder tag")
    if source_commit and not SHA_PATTERN.fullmatch(source_commit):
        raise ValueError("Invalid firmware source commit")
    if layer_tag and not re.fullmatch(r"imm-layer-[0-9a-f]{24}", layer_tag):
        raise ValueError("Invalid userland layer tag")
    doc = {
        "schema": 1,
        "channel": spec["channel"],
        "repository": REPOSITORY,
        "tag": tag,
        "build": build,
        "epoch": int(time.time()),
        "board": spec["board"],
        "profile": spec["profile"],
        "group": spec["group"],
        "target": spec["target"],
        "upstream_tag": f"immortal-{upstream[:12]}",
        "immortalwrt_commit": upstream,
        "image": spec["image"],
        "image_size": image.stat().st_size,
        "image_sha256": sha256(image),
        "manifest": spec["manifest"],
        "manifest_sha256": sha256(manifest),
    }
    if ppe:
        doc["ppe_nss_commit"] = ppe
    if "layout" in spec:
        doc["layout"] = spec["layout"]
    if builder_tag:
        doc["builder_tag"] = builder_tag
    if source_commit:
        doc["source_commit"] = source_commit
    if layer_tag:
        doc["layer_tag"] = layer_tag
    if sing_box_core is not None and sing_box_core.is_file():
        details = json.loads(sing_box_core.read_text())
        if (not isinstance(details, dict) or
            details.get("version") != "1.15.0-alpha.13" or
            details.get("architecture") != "aarch64" or
            details.get("placement") != "firmware-squashfs" or
            not re.fullmatch(r"[a-f0-9]{64}", details.get("binary_sha256", ""))):
            raise ValueError("Invalid pinned sing-box pre-release metadata")
        doc["sing_box_core"] = details
    output.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="action", required=True)
    a = subs.add_parser("prepare")
    a.add_argument("--overlay", type=Path, required=True)
    a.add_argument("--device", choices=tuple(DEVICES), default="arthur")
    a.add_argument("--tag", required=True)
    a.add_argument("--build", type=int, required=True)
    b = subs.add_parser("metadata")
    b.add_argument("--tag", required=True)
    b.add_argument("--build", type=int, required=True)
    b.add_argument("--immortal-commit", required=True)
    b.add_argument("--ppe-commit", default="")
    b.add_argument("--image", type=Path, required=True)
    b.add_argument("--manifest", type=Path, required=True)
    b.add_argument("--output", type=Path, required=True)
    b.add_argument("--device", choices=tuple(DEVICES), default="arthur")
    b.add_argument("--builder-tag", default="")
    b.add_argument("--source-commit", default="")
    b.add_argument("--layer-tag", default="")
    b.add_argument("--sing-box-core", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.overlay, args.tag, args.build, args.device)
    else:
        metadata(args.tag, args.build, args.immortal_commit, args.ppe_commit,
                 args.image, args.manifest, args.output,
                 args.builder_tag, args.source_commit, args.layer_tag, args.device,
                 args.sing_box_core)


if __name__ == "__main__":
    main()
