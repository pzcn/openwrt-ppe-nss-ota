#!/usr/bin/env bash
# Publish an immutable verified official-APK layer, never republish IB or SDK.
# Usage: publish-hybrid-layer.sh OUTPUT_DIR PARENT_DIR PRERELEASE(true|false)
set -Eeuo pipefail
ROOT="${GITHUB_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
DIR="$(realpath "${1:?Output directory required}")"
PARENT="$(realpath "${2:?Parent Builder assets directory required}")"
PRE="${3:?Prerelease flag required}"
REPO="${GITHUB_REPOSITORY:-pzcn/openwrt-ppe-nss-ota}"
[[ "$REPO" == pzcn/openwrt-ppe-nss-ota && ( "$PRE" == true || "$PRE" == false ) ]] || exit 1
BRANCH="${GITHUB_REF_NAME:-main}"
[[ "$BRANCH" == main ]] || { echo "::error::Only main can publish immutable userland-layer tags" >&2; exit 1; }

META="$DIR/layer-metadata.json"
ARCHIVE="$DIR/hybrid-userland-packages.tar.zst"
python3 "$ROOT/scripts/hybrid_layer.py" verify \
  --base-metadata "$PARENT/builder-metadata.json" \
  --base-official "$PARENT/official-apks.json" \
  --metadata "$META" --archive "$ARCHIVE" \
  --official "$DIR/official-apks.json" \
  --packages "$DIR/imagebuilder-packages.txt" \
  --snapshot "$DIR/snapshot-lock.json"

TAG="$(jq -er .tag "$META")"
BASE="$(jq -er .base_builder_tag "$META")"
SNAPSHOT="$(jq -er .snapshot_version "$META")"
[[ "$TAG" =~ ^imm-layer-[a-f0-9]{24}$ ]]
[[ "$BASE" =~ ^imm-builder-[A-Za-z0-9._-]+$ ]]
if gh release view "$TAG" -R "$REPO" >/dev/null 2>&1; then
  echo "::notice::Keeping immutable existing userland layer $TAG"
  exit 0
fi
flags=(--latest=false)
[[ "$PRE" == true ]] && flags+=(--prerelease)
gh release create "$TAG" -R "$REPO" "${flags[@]}" \
  --title "Hybrid Userland Layer $SNAPSHOT (base: ${BASE:0:32})" \
  --notes "Verified official snapshot APK layer for immutable Builder $BASE. No ImageBuilder, SDK, kernel or kmod was rebuilt or republished. Includes exact parent APK removals and SHA256-bound package list. Firmware validates layer-metadata.json against its parent before installation." \
  "$META" "$ARCHIVE" "$DIR/official-apks.json" \
  "$DIR/imagebuilder-packages.txt" "$DIR/imagebuilder.manifest" \
  "$DIR/snapshot-lock.json" "$DIR/local-plan.json" "$DIR/source-commits.txt"
echo "Published thin APK layer $TAG against $BASE (prerelease=$PRE)"
if [[ "$PRE" == false ]]; then
  gh workflow run firmware-immortalwrt.yml -R "$REPO" --ref main \
    -f "builder_tag=$BASE" -f "layer_tag=$TAG" ||
    echo "::warning::Layer published; automatic firmware dispatch failed."
fi
