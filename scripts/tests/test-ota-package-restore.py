#!/usr/bin/env python3
"""Offline OTA package restoration checks: ROM/world delta and legacy quarantine."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
UPDATER = ROOT / "files/usr/sbin/ppe-update"


def invoke(command: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["sh", "-c", '. "$PPE_UPDATE_SCRIPT"\n' + command],
                          env=env, text=True, capture_output=True, check=True)


with TemporaryDirectory() as base:
    home = Path(base)
    work = home / "work"
    state = home / "state"
    work.mkdir()
    state.mkdir()
    rom = home / "rom-world"
    world = home / "world"
    manifest = work / "manifest"
    rom.write_text(
        "base-files\ncollectd\ncollectd-mod-network\n"
        "btrfs-progs\nkmod-fs-btrfs\nlibubox20261103\n"
        "luci\nluci-app-filemanager\nip-tiny\n"
    )
    world.write_text(
        "base-files\ncollectd\ncollectd-mod-network\n"
        "btrfs-progs\nkmod-fs-btrfs\nlibubox20261103\n"
        "luci\nluci-app-filemanager\n"
        "luci-app-my-tool@testing>=1.0\n"
        "luci-i18n-my-tool-zh-cn\n"
        "already-bundled\n"
        "kmod-user-extra\nlibubox20270401\n"
        "libstdcpp6\n!ip-tiny\n"
    )
    manifest.write_text("base-files\nluci\nalready-bundled\n")
    env = dict(os.environ,
               PPE_UPDATE_SCRIPT=str(UPDATER), PPE_UPDATE_LIB="1",
               PPE_WORK=str(work), PPE_STATE=str(state),
               PPE_APK_WORLD=str(world), PPE_APK_ROM_WORLD=str(rom))
    # The old algorithm would have included collectd, Btrfs and stale libc
    # packages merely because the NEW image no longer has those packages.
    result = invoke("extras", env)
    selected = set(result.stdout.splitlines())
    assert selected == {
        "!ip-tiny", "luci-app-my-tool", "luci-i18n-my-tool-zh-cn",
        "libstdcpp6",
    }, (selected, result.stderr)

    # Do not invent removals: deleting a stock package from writable world
    # is not proof that its absence should be forced in the new image.
    world.write_text(world.read_text().replace("!ip-tiny\n", ""))
    result = invoke("extras", env)
    assert "!ip-tiny" not in result.stdout.splitlines()

    # Without the old immutable ROM baseline, safe differentiation is
    # impossible; the updater must not treat the entire world as custom.
    env_missing = dict(env, PPE_APK_ROM_WORLD=str(home / "missing"))
    result = invoke('if extras >"$WORK/bad-extras"; then exit 9; fi', env_missing)
    assert not (work / "bad-extras").read_text(), result.stdout

    # Legacy queues are ambiguous. Archive them BEFORE touching the package
    # feeds, do not repeatedly attempt to reinstall every stale dependency.
    (state / "packages").write_text(
        "collectd\ncollectd-mod-network\nbtrfs-progs\n"
        "libubox20261103\nluci-app-my-tool\n"
    )
    apk_called = home / "apk-called"
    env["PPE_APK_CALLED"] = str(apk_called)
    invoke("""
lock() { return 0; }
apk() { echo "$*" >>"$PPE_APK_CALLED"; return 0; }
cmd_restore
""", env)
    assert not (state / "packages").exists()
    legacy = (state / "packages.legacy")
    assert legacy.is_file()
    assert set(legacy.read_text().splitlines()) == {
        "collectd", "collectd-mod-network", "btrfs-progs",
        "libubox20261103", "luci-app-my-tool",
    }
    assert not apk_called.exists(), "Legacy list reached apk add/update"

    # A second unknown legacy queue is merged into the archived copy.
    (state / "packages").write_text("collectd\nold-other-lib\n")
    invoke("archive_legacy_queue", env)
    assert "old-other-lib" in legacy.read_text().splitlines()

    # A v2 queue contains an embedded format header which survives sysupgrade
    # together with the package file; this one is eligible for recovery.
    (state / "packages").write_text(
        "# ppe-update-extras-v2\nluci-app-my-tool\n"
    )
    invoke("""
lock() { return 0; }
apk() { echo "$*" >>"$PPE_APK_CALLED"; return 0; }
cmd_restore
""", env)
    assert not (state / "packages").exists()
    assert apk_called.read_text().splitlines() == [
        "update", "add luci-app-my-tool",
    ], apk_called.read_text()
    assert "old-other-lib" in legacy.read_text()

    # A mixed v2 list must keep its header when a remaining package fails.
    (state / "packages").write_text(
        "# ppe-update-extras-v2\nluci-app-needed\nluci-app-missing\n"
    )
    invoke("""
lock() { return 0; }
apk() {
    [ "$1" = update ] && return 0
    [ "$#" -eq 2 ] && [ "$2" = luci-app-needed ]
}
(cmd_restore) || :
""", env)
    assert (state / "packages").read_text().splitlines() == [
        "# ppe-update-extras-v2", "luci-app-missing",
    ], (state / "packages").read_text()

    # Status responses summarize archived legacy lists without embedding
    # the obsolete full list as a live restore queue.
    out = invoke("""
uci() { echo 0; }
lookup() { LATEST=demo; LATEST_TIME=1; SIZE=2000000; IMAGE=image; }
newer() { return 1; }
extras() { :; }
BOARD=board
OTA_TAG=old
OTA_BUILD=1
GROUP=group
cmd_status
""", env)
    data = json.loads(out.stdout)
    assert data["legacy_count"] == 6, data
    assert data["pending"] == "luci-app-missing ", data

print("PASS: OTA restores only explicit user additions, quarantines legacy queues")
