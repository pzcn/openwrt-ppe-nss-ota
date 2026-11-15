#!/usr/bin/env python3
"""Select the latest persistent MX4200 Builder Release; never initiate a rebuild.

Main pushes may run before the initial MX Builder has been published. In that
case skip the MX image job with a clear notice. Explicit manual repacks fail.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

def run(*argv):
    return subprocess.run(argv, check=True, text=True, capture_output=True).stdout.strip()

def main():
    repo = os.environ.get("GITHUB_REPOSITORY", "pzcn/openwrt-ppe-nss-ota")
    event = os.environ.get("GITHUB_EVENT_NAME", "workflow_dispatch")
    releases = json.loads(run("gh", "api", f"repos/{repo}/releases?per_page=100"))
    candidates = sorted((r for r in releases if not r.get("draft")
                         and r.get("prerelease")
                         and re.fullmatch(r"mx4200-builder-[0-9a-f]{24}", r.get("tag_name", ""))),
                        key=lambda r: r.get("published_at") or "", reverse=True)
    for release in candidates:
        tag = release["tag_name"]
        try:
            metadata = json.loads(run("gh", "api",
                f"repos/{repo}/releases/{release['id']}/assets"))
            # A matching long-lived archive and its corresponding source SHA
            # must both exist; do not fall back to ephemeral Actions artifacts.
            names = {a["name"] for a in metadata}
            required = {"mx4200v1-hybrid-metadata.json", "base-overlay.tar.gz",
                        "snapshot-lock.json", "sha256sums", "local-apks.txt"}
            if not required <= names or not any("imagebuilder" in n and n.endswith(".tar.zst") for n in names):
                continue
            blob = run("gh", "release", "download", tag, "-R", repo,
                       "-p", "mx4200v1-hybrid-metadata.json", "-O", "-")
            meta = json.loads(blob)
            source = meta.get("source_commit", "")
            if not re.fullmatch(r"[0-9a-f]{40}", source):
                continue
            if meta.get("target") != "qualcommax/ipq807x" or meta.get("profile") != "linksys_mx4200v1":
                continue
            if subprocess.run(["git", "merge-base", "--is-ancestor", source, "HEAD"]).returncode:
                continue
            if subprocess.run(["git", "diff", "--quiet", source, "HEAD", "--",
                               "mx4200v1/source.config", "mx4200v1/port-ppe-nss.sh",
                               "mx4200v1/packages.txt", "mx4200v1/remove.txt"]).returncode:
                continue
            with Path(os.environ["GITHUB_OUTPUT"]).open("a") as out:
                out.write(f"available=true\\ntag={tag}\\nsource_commit={source}\\n")
            print(f"Reuse immutable MX4200 Builder: {tag} at {source}")
            return
        except (subprocess.CalledProcessError, KeyError, ValueError, json.JSONDecodeError) as exc:
            print(f"Skipping invalid MX4200 Builder {tag}: {exc}", file=sys.stderr)
    msg = "No compatible persistent MX4200 Builder Release. Run the manual MX4200 Hybrid full build first. No automatic compile."
    if event == "workflow_dispatch":
        raise SystemExit(msg)
    print("::notice::" + msg)
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as out:
        out.write("available=false\\n")

if __name__ == "__main__":
    main()
