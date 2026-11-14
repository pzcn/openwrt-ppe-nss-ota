#!/usr/bin/env bash
# Publish a verified hybrid Builder (full build or refresh) as a Release.
#
# Usage: publish-hybrid-builder.sh OUT_DIR PRERELEASE(true|false)
# A prerelease is invisible to the firmware workflow (it only picks
# non-prerelease imm-builder-* releases), so a new kernel waits for a
# hardware test; promote it by unticking "pre-release" on GitHub.
set -Eeuo pipefail
ROOT="${GITHUB_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
DIR="$(realpath "${1:?Builder output directory}")"
PRERELEASE="${2:?true or false}"
REPO="${GITHUB_REPOSITORY:-pzcn/openwrt-ppe-nss-ota}"
[[ "$REPO" == pzcn/openwrt-ppe-nss-ota ]] || { echo "::error::Unexpected repository" >&2; exit 1; }
[[ "$PRERELEASE" == true || "$PRERELEASE" == false ]]
# Builds from a non-default branch are test builds: never let the firmware
# workflow pick them up.
BRANCH="${GITHUB_REF_NAME:-main}"
if [[ "$BRANCH" != main ]]; then
  PRERELEASE=true
fi

META="$DIR/builder-metadata.json"
SDK_META="$DIR/sdk-metadata.json"
TAG="$(jq -er '.tag' "$META")"
[[ "$TAG" =~ ^imm-builder-[a-zA-Z0-9._-]+$ ]]
IB_ARCHIVE="$DIR/$(jq -er '.archive' "$META")"
SDK_ARCHIVE="$DIR/$(jq -er '.archive' "$SDK_META")"
python3 "$ROOT/scripts/immortalwrt_builder.py" verify --metadata "$META" \
  --archive "$IB_ARCHIVE" --overlay "$DIR/base-overlay.tar.gz" \
  --packages "$DIR/imagebuilder-packages.txt"
python3 "$ROOT/scripts/immortalwrt_sdk.py" verify --metadata "$SDK_META" \
  --builder-metadata "$META" --archive "$SDK_ARCHIVE" --feed-lock "$DIR/sdk-feeds.lock.json"

if gh release view "$TAG" -R "$REPO" >/dev/null 2>&1; then
  echo "::notice::$TAG already exists; keeping the immutable release."
  exit 0
fi
SNAPSHOT="$(jq -er '.official_snapshot.snapshot_version' "$META")"
IDENTITY="$(jq -er '.hybrid.identity' "$META")"
PARENT="$(jq -r '.hybrid.kernel_parent // empty' "$META")"
if [[ -n "$PARENT" ]]; then
  KIND="userland refresh (kernel from $PARENT)"
else
  KIND="full build (new kernel)"
fi
[[ "$BRANCH" != main ]] && KIND="$KIND, branch $BRANCH"
flags=(--latest=false)
[[ "$PRERELEASE" == true ]] && flags+=(--prerelease)
# The title carries the identity: the resolve job finds the newest hybrid
# Builder by it.
gh release create "$TAG" -R "$REPO" "${flags[@]}" \
  --title "Hybrid ImageBuilder + SDK $SNAPSHOT (id:${IDENTITY:0:16})" \
  --notes "Hybrid Builder, $KIND. Kernel, kmods, base-files and PPE/LuCI packages are compiled from ImmortalWrt master + PPE/NSS; every other APK is mirrored from the official ImmortalWrt snapshot $SNAPSHOT (signed index, per-package signature and SHA256). See snapshot-lock.json, local-plan.json and official-apks.json. Prereleases are ignored by the firmware workflow until promoted." \
  "$IB_ARCHIVE" "$DIR/base-overlay.tar.gz" "$DIR/imagebuilder-packages.txt" \
  "$META" "$SDK_ARCHIVE" "$SDK_META" "$DIR/sdk-feeds.lock.json" \
  "$DIR/source-commits.txt" "$DIR/official-toolchain-status.txt" \
  "$DIR/snapshot-lock.json" "$DIR/local-plan.json" "$DIR/official-apks.json" \
  "$DIR/imagebuilder.manifest"
echo "Published $TAG ($KIND, prerelease=$PRERELEASE)"
if [[ "$PRERELEASE" == false ]]; then
  gh workflow run firmware-immortalwrt.yml -R "$REPO" --ref main -f "builder_tag=$TAG" ||
    echo "::warning::Firmware dispatch failed; the daily firmware run will pick up $TAG."
fi
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  echo "Published \`$TAG\` — $KIND, prerelease=$PRERELEASE" >> "$GITHUB_STEP_SUMMARY"
fi
