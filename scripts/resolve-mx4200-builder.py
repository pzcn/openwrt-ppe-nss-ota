#!/usr/bin/env python3
"""Select an intact MX4200 v1 Hybrid Builder, or require a new full build.

A successful Actions run is NOT enough: its complete, unexpired parent assets
must exist and the current target kernel recipe AND requested package closure
must match exactly. If the userland set changes, a full MX-only Hybrid build
is the safe fallback until MX gains a verified official-APK refresh layer.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

REQUIRED_ARTIFACTS = frozenset({
    "mx4200v1-hybrid-builder-sdk-test",
    "mx4200v1-hybrid-firmware-test",
    "mx4200v1-hybrid-diagnostics",
})
COMPATIBILITY_INPUTS = (
    "mx4200v1/source.config",
    "mx4200v1/port-ppe-nss.sh",
    "mx4200v1/packages.txt",
    "mx4200v1/remove.txt",
)
# Only skip a push when no firmware-producing input changed since the
# parent full build. Non-firmware tests and this resolver must not force a
# 100+ MiB repackage. Scheduled checks still run the image path.
FIRMWARE_INPUTS = (
    "mx4200v1", "config", "files", "scripts",
    ".github/workflows/mx4200v1-hybrid.yml",
    ".github/workflows/mx4200v1-fast-repack.yml",
    ":(exclude)scripts/resolve-mx4200-builder.py",
    ":(exclude)scripts/tests",
    ":(exclude)mx4200v1/README.md",
    ":(exclude,glob)mx4200v1/test*.py",
)
WORKFLOW_NAMES = frozenset({
    "Unified PPE/NSS - Arthur and MX4200 v1",
    "MX4200 v1 Hybrid - official Snapshot + local PPE NSS (test)",
})
SHA = re.compile(r"^[0-9a-f]{40}$")
# In a reusable GitHub Actions workflow, the overall run conclusion can be
# "failure" even though the target-specific Hybrid build job passed and its
# complete SHA256-backed artifacts were uploaded. Never discard that work.
MX_FULL_BUILD_JOB = (
    "Build ipq807x PPE/NSS and test MX4200 v1 factory/sysupgrade"
)


def completed_mx_build(jobs: dict) -> bool:
    """Verify the specific MX4200 full Builder job, not any unrelated job."""
    records = jobs.get("jobs", [])
    if not isinstance(records, list):
        return False
    return any(
        isinstance(job, dict)
        and (job.get("name") == MX_FULL_BUILD_JOB
             or job.get("name", "").endswith(" / " + MX_FULL_BUILD_JOB))
        and job.get("status") == "completed"
        and job.get("conclusion") == "success"
        for job in records
    )


def shell(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, text=True, capture_output=True, check=check)


def github_json(repository: str, endpoint: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Invalid GitHub repository")
    result = shell("gh", "api", f"repos/{repository}/{endpoint}")
    return json.loads(result.stdout)


def compatible_source(commit: str) -> bool:
    if not SHA.fullmatch(commit):
        return False
    # An older branch is reusable only if its source commit is in the current
    # history. This prevents unreviewed side branches from supplying a kernel.
    if shell("git", "merge-base", "--is-ancestor", commit, "HEAD",
             check=False).returncode != 0:
        return False
    return shell("git", "diff", "--quiet", commit, "HEAD", "--",
                 *COMPATIBILITY_INPUTS, check=False).returncode == 0


def unchanged_firmware_inputs(commit: str) -> bool:
    """A push with no changes to image inputs should reuse existing firmware."""
    return (SHA.fullmatch(commit) is not None
            and shell("git", "diff", "--quiet", commit, "HEAD", "--",
                      *FIRMWARE_INPUTS, check=False).returncode == 0)


def usable_artifacts(assets: dict) -> bool:
    entries = assets.get("artifacts", [])
    if not isinstance(entries, list):
        return False
    names = {
        obj.get("name") for obj in entries
        if isinstance(obj, dict) and
        obj.get("expired") is False and
        int(obj.get("size_in_bytes") or 0) > 0
    }
    return REQUIRED_ARTIFACTS <= names


def choose_parent(runs: list, fetch_assets, is_compatible,
                  fetch_jobs=None) -> tuple[int, str] | None:
    """Pure selector; all GitHub/API/git checks injectable for tests."""
    for run in runs:
        if not isinstance(run, dict):
            continue
        if run.get("name") not in WORKFLOW_NAMES:
            continue
        if (run.get("status") != "completed"
                or run.get("conclusion") not in ("success", "failure")):
            continue
        commit = run.get("head_sha", "")
        if not isinstance(commit, str) or not SHA.fullmatch(commit):
            continue
        run_id = run.get("id")
        if not isinstance(run_id, int) or run_id <= 0:
            continue
        if not is_compatible(commit):
            continue
        if not usable_artifacts(fetch_assets(run_id)):
            continue
        # A failed parent workflow is usable ONLY if its own MX4200 Builder
        # job completed successfully. The ImageBuilder repack subsequently
        # checks SHA256, target/profile and identical local kmod provenance.
        # Never reuse artifacts from a failed or cancelled Builder job.
        if run["conclusion"] == "failure":
            if fetch_jobs is None or not completed_mx_build(fetch_jobs(run_id)):
                continue
        return run_id, commit
    return None


def resolve(repository: str, mode: str, max_pages: int,
            event_name: str = "") -> dict[str, str]:
    if mode == "full":
        return {
            "mode": "full", "parent_run": "", "parent_sha": "",
            "reason": "explicit full rebuild requested",
        }

    for page in range(1, max_pages + 1):
        data = github_json(repository, f"actions/runs?per_page=100&page={page}")
        runs = data.get("workflow_runs", [])
        if not isinstance(runs, list):
            raise ValueError("GitHub workflow API returned no run list")

        parent = choose_parent(
            runs,
            lambda run_id: github_json(
                repository, f"actions/runs/{run_id}/artifacts?per_page=100"),
            compatible_source,
            lambda run_id: github_json(
                repository, f"actions/runs/{run_id}/jobs?per_page=100"),
        )
        if parent:
            run_id, source_sha = parent
            # The original Hybrid run also contains a fully assembled
            # MX4200 factory/sysupgrade image. Do not rebuild that identical
            # image just because this resolver, its tests or docs changed.
            if mode == "auto" and event_name == "push" and unchanged_firmware_inputs(source_sha):
                return {
                    "mode": "skip", "parent_run": str(run_id),
                    "parent_sha": source_sha,
                    "reason": f"firmware inputs unchanged since MX4200 build {run_id}",
                }
            return {
                "mode": "repack", "parent_run": str(run_id),
                "parent_sha": source_sha,
                "reason": f"compatible and complete MX4200 Hybrid Builder run {run_id} "
                          "(verified even if unrelated jobs marked parent workflow failed)",
            }
        if len(runs) < 100:
            break

    if mode == "repack":
        raise RuntimeError(
            "Explicit MX4200 repack requested, but no compatible, intact "
            "Hybrid Builder artifacts were found. Use mode=auto or full."
        )
    return {
        "mode": "full", "parent_run": "", "parent_sha": "",
        "reason": "no compatible complete MX4200 Builder; kernel or package "
                  "inputs changed, or prior artifacts expired",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=("auto", "repack", "full"), default="auto")
    parser.add_argument("--max-pages", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.max_pages <= 10:
        parser.error("max-pages must be 1..10")

    repository = os.environ.get("GITHUB_REPOSITORY", "pzcn/openwrt-ppe-nss-ota")
    result = resolve(repository, args.mode, args.max_pages,
                     event_name=os.environ.get("GITHUB_EVENT_NAME", ""))
    print(json.dumps(result, indent=2))
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a") as stream:
            for key, value in result.items():
                print(f"{key}={value}", file=stream)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a") as stream:
            print("### MX4200 Builder resolution", file=stream)
            print(f"- Mode: **{result['mode']}**", file=stream)
            print(f"- Reason: {result['reason']}", file=stream)
            if result["parent_run"]:
                print(f"- Parent run: {result['parent_run']}", file=stream)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"::error::Cannot resolve a safe MX4200 Builder: {exc}", file=sys.stderr)
        raise SystemExit(1)
