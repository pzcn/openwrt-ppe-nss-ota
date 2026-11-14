#!/usr/bin/env python3
"""Regression tests for source-aware RE-SS-01 firmware packaging."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "firmware_inputs", ROOT / "scripts/firmware_inputs.py")
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


with tempfile.TemporaryDirectory() as temp:
    repo = Path(temp)
    git(repo, "init", "-q")

    def write(path: str, content: str) -> None:
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def commit(message: str) -> str:
        git(repo, "add", "-A")
        git(repo, "-c", "user.name=CI", "-c", "user.email=ci@example.invalid",
            "-c", "commit.gpgsign=false", "commit", "-qm", message)
        return git(repo, "rev-parse", "HEAD")

    write("mx4200v1/build-hybrid.sh", "mx-a\n")
    write("scripts/hybrid_builder.py", "planner-a\n")
    write("scripts/repack-immortalwrt.sh", "image-a\n")
    write("config/add.txt", "one\n")
    first = commit("initial")
    write("mx4200v1/build-hybrid.sh", "mx-b\n")
    write("scripts/hybrid_builder.py", "planner-b\n")
    second = commit("only MX and shared Builder planning")
    assert mod.changed_paths(first, second, repo) == []
    assert not mod.relevant("scripts/tests/test-hybrid-builder.py")
    assert not mod.relevant("config/immortalwrt-re-ss-01.config")
    assert mod.relevant("files/etc/config/network")
    assert mod.relevant("config/translations/ppe-update.zh-cn.json")
    assert mod.relevant("scripts/immortalwrt_ota.py")
    write("files/usr/sbin/ppe-update", "updated OTA\n")
    third = commit("overlay changed")
    assert mod.changed_paths(second, third, repo) == ["files/usr/sbin/ppe-update"]
    write("config/add.txt", "one\ntwo\n")
    fourth = commit("package selection changed")
    assert mod.changed_paths(third, fourth, repo) == ["config/add.txt"]
    write("scripts/repack-immortalwrt.sh", "image-b\n")
    fifth = commit("image recipe changed")
    assert mod.changed_paths(fourth, fifth, repo) == ["scripts/repack-immortalwrt.sh"]
    (repo / "files/usr/sbin/ppe-update").unlink()
    sixth = commit("removed overlay")
    assert mod.changed_paths(fifth, sixth, repo) == ["files/usr/sbin/ppe-update"]
    assert mod.changed_paths(first, sixth, repo) == [
        "config/add.txt", "scripts/repack-immortalwrt.sh"]
    try:
        mod.changed_paths("invalid", "HEAD", repo)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid SHA accepted")
print("PASS firmware changes scoped to RE-SS-01 image inputs")
