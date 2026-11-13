#!/usr/bin/env python3
"""Audit what OpenWrt ImageBuilder's prepare_rootfs still needs to finalize.

APK installs with --no-scripts are NORMAL for current OpenWrt ImageBuilder.
The build later unpacks APK post-install scripts and enables init.d service
symlinks. This experiment deliberately does not run any untrusted scripts.
It compares the published stock/donor SquashFS to the disposable APK root.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import tarfile
import tempfile
import subprocess


def init_links(root: Path) -> dict[str, str]:
    rc = root / "etc/rc.d"
    if not rc.exists():
        return {}
    if not rc.is_dir() or rc.is_symlink():
        raise ValueError("Malformed /etc/rc.d")
    result = {}
    for entry in sorted(rc.iterdir()):
        if not entry.is_symlink():
            raise ValueError("Unexpected /etc/rc.d non-symlink: " + entry.name)
        result[entry.name] = os.readlink(entry)
    return result


def module_metadata(root: Path) -> dict:
    top = root / "lib/modules"
    if not top.exists():
        return {"releases": [], "metadata": {}}
    if not top.is_dir():
        raise ValueError("Malformed /lib/modules")
    release_dirs = sorted(p for p in top.iterdir() if p.is_dir())
    files = ("modules.dep", "modules.alias", "modules.builtin", "modules.order")
    return {
        "releases": [p.name for p in release_dirs],
        "metadata": {p.name: {f: (p / f).is_file() for f in files}
                     for p in release_dirs},
    }


def script_archive(root: Path) -> dict:
    base = root / "lib/apk/db"
    archives = [base / name for name in ("scripts.tar.gz", "scripts.tar")]
    candidates = [a for a in archives if a.is_file()]
    if len(candidates) > 1:
        raise ValueError("Ambiguous APK script archives")
    if not candidates:
        return {"present": False, "post_install_script_count": 0,
                "other_script_count": 0, "post_install_script_names": [],
                "archive_format": None}
    archive = candidates[0]
    with tarfile.open(archive, "r:*") as tar:
        entries = tar.getmembers()
        names = []
        for item in entries:
            path = PurePosixPath(item.name)
            if path.is_absolute() or ".." in path.parts or not item.isfile():
                raise ValueError("Unexpected APK post-install archive entry")
            names.append(item.name)
    post_install = sorted(n for n in names if n.endswith(".post-install"))
    return {
        "present": True,
        "archive_format": archive.suffix,
        "post_install_script_count": len(post_install),
        "other_script_count": len(names) - len(post_install),
        "post_install_script_names": post_install,
    }


def snapshot(root: Path) -> dict:
    return {
        "rc_d_links": init_links(root),
        "module_metadata": module_metadata(root),
        "apk_postinstall": script_archive(root),
        "init_script_count": len(list((root / "etc/init.d").iterdir()))
        if (root / "etc/init.d").is_dir() else 0,
    }


def report(official: dict, donor: dict, mixed: dict) -> dict:
    official_rc = official["rc_d_links"]
    donor_rc = donor["rc_d_links"]
    mixed_rc = mixed["rc_d_links"]
    return {
        "schema": 1,
        "status": "imagebuilder-rootfs-finalization-needs-review",
        "official": official,
        "julius": donor,
        "mixed": mixed,
        "stock_rc_symlink_count": len(official_rc),
        "julius_rc_symlink_count": len(donor_rc),
        "mixed_rc_symlink_count": len(mixed_rc),
        "missing_stock_service_links_before_finalization":
            sorted(set(official_rc) - set(mixed_rc)),
        "missing_julius_service_links_before_finalization":
            sorted(set(donor_rc) - set(mixed_rc)),
        "differing_stock_service_links_before_finalization":
            sorted(n for n in official_rc.keys() & mixed_rc.keys()
                   if official_rc[n] != mixed_rc[n]),
        "module_index_expected_in_stock": any(
            row["modules.dep"] or row["modules.alias"]
            for row in official["module_metadata"]["metadata"].values()),
        "module_index_expected_in_donor": any(
            row["modules.dep"] or row["modules.alias"]
            for row in donor["module_metadata"]["metadata"].values()),
        "mix_contains_apk_post_install_scripts":
            mixed["apk_postinstall"]["post_install_script_count"] > 0,
        "imagebuilder_prepare_rootfs_executed": False,
        "service_enablement_executed": False,
        "runtime_abi_verified": False,
        "flashable_firmware_created": False,
        "publishable": False,
    }


def extract_reference(image: Path, dest: Path) -> None:
    subprocess.run(
        ["unsquashfs", "-no-progress", "-no-xattrs", "-d", str(dest),
         str(image), "etc/rc.d", "etc/init.d", "lib/modules",
         "lib/apk/db/scripts.tar.gz", "lib/apk/db/scripts.tar"],
        check=True, stdout=subprocess.DEVNULL,
    )


def analyze(official_image: Path, donor_image: Path, mixed_root: Path) -> dict:
    if not (official_image.is_file() and donor_image.is_file()
            and mixed_root.is_dir()):
        raise ValueError("Missing pinned reference SquashFS or disposable root")
    with tempfile.TemporaryDirectory(prefix="swap-finalization-audit-",
                                     dir=os.environ.get("RUNNER_TEMP")) as folder:
        official = Path(folder) / "official"
        donor = Path(folder) / "donor"
        extract_reference(official_image, official)
        extract_reference(donor_image, donor)
        return report(snapshot(official), snapshot(donor), snapshot(mixed_root))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--official-squashfs", type=Path, required=True)
    p.add_argument("--julius-squashfs", type=Path, required=True)
    p.add_argument("--mixed-rootfs", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    a = p.parse_args()
    result = analyze(a.official_squashfs, a.julius_squashfs, a.mixed_rootfs)
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("Official/donor/mixed /etc/rc.d links:",
          result["stock_rc_symlink_count"], result["julius_rc_symlink_count"],
          result["mixed_rc_symlink_count"])
    print("Original service links still absent before finalization:",
          len(result["missing_stock_service_links_before_finalization"]))
    print("APK post-install scripts pending:",
          result["mixed"]["apk_postinstall"]["post_install_script_count"])
    print("modules.dep / alias in original or donor:",
          result["module_index_expected_in_stock"],
          result["module_index_expected_in_donor"])
    print("No APK postinst scripts or ImageBuilder preparation executed.")


if __name__ == "__main__":
    main()
