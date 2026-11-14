#!/usr/bin/env python3
"""Ephemeral SquashFS + TAR packaging smoke test for the mixed APK root.

NOT a flashable build.  APK install scripts were skipped upstream, the TAR
contains an intentionally invalid board CONTROL, no fwtool metadata is added,
and the image files are deleted before this script exits. Only JSON survives.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tarfile
import tempfile

HERE = Path(__file__).resolve().parent


def load_script(filename: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, HERE / filename)
    if not spec or not spec.loader:
        raise RuntimeError("Missing local validation module: " + filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = load_script("probe-prebuilt-kernel-swap.py", "swap_pack_probe")
audit = load_script("audit-swap-extracted-root.py", "swap_pack_audit")

# Deliberately NOT the actual RE-SS-01 board ID or regular sysupgrade prefix.
# A TAR with this CONTROL cannot pass normal device identity checks.
RESEARCH_PREFIX = "research-only-NOT-SYSUPGRADE"
RESEARCH_CONTROL = b"BOARD=research-invalid-not-a-real-device\nRESEARCH_ONLY=1\n"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def byte_manifest(base: Path) -> dict[str, tuple]:
    """Compare modules/autoload files and symlink targets before/after squashfs."""
    items: dict[str, tuple] = {}
    if not base.exists():
        raise ValueError("Missing package subtree: " + str(base))
    paths = [base, *sorted(base.rglob("*"))]
    for item in paths:
        rel = str(item.relative_to(base))
        mode = item.lstat().st_mode
        if stat.S_ISLNK(mode):
            items[rel] = ("symlink", os.readlink(item))
        elif stat.S_ISREG(mode):
            items[rel] = ("file", stat.S_IMODE(mode), sha256_file(item))
        elif stat.S_ISDIR(mode):
            items[rel] = ("dir", stat.S_IMODE(mode))
        else:
            raise ValueError("Unexpected special file in verified subtree: " + str(item))
    return items


def write_research_tar(kernel: Path, squashfs: Path, destination: Path) -> dict:
    """Test TAR/FIT/SquashFS layout without ever creating valid upgrade metadata."""
    fit = kernel.read_bytes()
    root = squashfs.read_bytes()
    if fit[:4] != probe.FIT_MAGIC:
        raise ValueError("Donor kernel has no FIT magic")
    if not (1024 < len(fit) <= probe.KERNEL_PARTITION_LIMIT):
        raise ValueError("Donor FIT exceeds RE-SS-01 kernel partition")
    if root[:4] != probe.SQUASHFS_MAGIC or len(root) > probe.MAX_ROOTFS_MEMBER:
        raise ValueError("Research rootfs missing SquashFS magic or oversized")
    entries = [
        ("CONTROL", RESEARCH_CONTROL),
        ("kernel", fit),
        ("root", root),
    ]
    with tarfile.open(destination, "w") as archive:
        for filename, body in entries:
            info = tarfile.TarInfo(RESEARCH_PREFIX + "/" + filename)
            info.size = len(body)
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            info.mtime = 0
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(body))
    unpacked_kernel, unpacked_root, parts = probe.read_sysupgrade_members(
        destination, "deliberately-invalid-research-tar")
    with tarfile.open(destination, "r:") as archive:
        control = archive.extractfile(RESEARCH_PREFIX + "/CONTROL")
        if control is None or control.read() != RESEARCH_CONTROL:
            raise ValueError("Research-only board marker not preserved")
    if unpacked_kernel != fit or unpacked_root != root:
        raise ValueError("Research TAR member bytes altered")
    # Only the tar member structure is comparable; this must NOT be described
    # as a valid sysupgrade image or a successful sysupgrade -T test.
    return {
        "research_tar_members_checked": parts["kernel_member"] and parts["rootfs_member"],
        "kernel_fit_sha256": hashlib.sha256(fit).hexdigest(),
        "rootfs_squashfs_sha256": hashlib.sha256(root).hexdigest(),
        "kernel_fit_bytes": len(fit),
        "rootfs_squashfs_bytes": len(root),
        "research_container_sha256": sha256_file(destination),
        "control_board_identity": "research-invalid-not-a-real-device",
    }


def run(root: Path, kernel: Path, plan: Path) -> dict:
    if not root.is_dir() or not kernel.is_file() or not plan.is_file():
        raise ValueError("Missing disposable root, donor FIT or pinned package plan")
    original = audit.inspect(root, json.loads(plan.read_text()))
    if not (original["exact_plan_pins_verified"]
            and original["module_tree_structure_verified"]
            and original["f2fs_boot_autoload_files"]):
        raise ValueError("Original scratch APK root failed required module/pin checks")
    if not (root / "var").is_symlink() or os.readlink(root / "var") != "tmp":
        raise ValueError("Stock /var -> tmp link was not installed")
    subtrees = ("lib/modules", "etc/modules-boot.d")
    originals = {p: byte_manifest(root / p) for p in subtrees}
    original_db = sha256_file(root / "lib/apk/db/installed")

    # All test images live in a temporary directory and are never uploaded.
    with tempfile.TemporaryDirectory(prefix="research-swap-pack-",
                                     dir=os.environ.get("RUNNER_TEMP")) as dirname:
        temp = Path(dirname)
        image = temp / "nonflashable-rootfs.squashfs"
        roundtrip = temp / "unpacked"
        research = temp / "not-a-firmware.research.tar"
        subprocess.run([
            "mksquashfs", str(root), str(image), "-noappend",
            "-comp", "xz", "-b", "262144", "-processors", "2",
            "-all-root", "-no-xattrs", "-no-progress",
        ], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["unsquashfs", "-s", str(image)], check=True,
                       stdout=subprocess.DEVNULL)
        subprocess.run([
            "unsquashfs", "-no-progress", "-no-xattrs",
            "-d", str(roundtrip), str(image),
            "lib/apk/db/installed", *subtrees, "var",
        ], check=True, stdout=subprocess.DEVNULL)
        if sha256_file(roundtrip / "lib/apk/db/installed") != original_db:
            raise ValueError("Installed APK DB changed after SquashFS round-trip")
        if not (roundtrip / "var").is_symlink() or os.readlink(roundtrip / "var") != "tmp":
            raise ValueError("/var stock symlink lost in SquashFS round-trip")
        for relative, original_manifest in originals.items():
            if byte_manifest(roundtrip / relative) != original_manifest:
                raise ValueError("SquashFS changed module/autoload content or permissions: "
                                 + relative)
        roundtrip_audit = audit.inspect(roundtrip, json.loads(plan.read_text()))
        if not (roundtrip_audit["exact_plan_pins_verified"]
                and roundtrip_audit["module_tree_structure_verified"]
                and roundtrip_audit["f2fs_boot_autoload_files"]):
            raise ValueError("Compressed-and-unpacked package/module audit failed")
        if original["apk_installed_package_count"] != roundtrip_audit["apk_installed_package_count"]:
            raise ValueError("Round-tripped installed APK count changed")
        container = write_research_tar(kernel, image, research)
        return {
            "schema": 1,
            "status": "ephemeral-nonflashable-mixed-rootfs-packaging-smoke-test",
            "source_installed_apks": original["apk_installed_package_count"],
            "exact_plan_versions_survived_roundtrip": True,
            "all_kernel_module_files_and_modes_survived_roundtrip": True,
            "early_f2fs_boot_files_survived_roundtrip": True,
            "stock_var_symlink_survived_roundtrip": True,
            "single_julius_module_tree": roundtrip_audit["kernel_module_directories"],
            "disposable_rootfs_file_roundtrip_passed": True,
            **container,
            "tar_has_intentionally_invalid_board_identity": True,
            "fwtool_metadata_added": False,
            "firmware_artifacts_retained": False,
            "package_scripts_executed": False,
            "kernel_runtime_abi_verified": False,
            "boot_or_sysupgrade_tested": False,
            "fullcone_nat_parity_verified": False,
            "production_ota_changed": False,
            "publishable": False,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rootfs", type=Path, required=True)
    parser.add_argument("--julius-fit", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.rootfs, args.julius_fit, args.plan)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("PASS research-only SquashFS/APK/module re-extraction and TAR member checks")
    print("The intentionally invalid research container was deleted. NOT FLASHABLE.")


if __name__ == "__main__":
    main()
