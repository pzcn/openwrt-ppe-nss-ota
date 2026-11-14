#!/usr/bin/env bash
# Hybrid userland refresh: reuse the immutable parent IB/SDK and publish
# only a verified set of official APKs plus the new image manifest.
#
# Reuse the previous hybrid Builder's ImageBuilder + SDK (kernel, kmods,
# base-files, libc and custom packages unchanged) and replace only the
# mirrored official userland with the closure of the new official snapshot
# and the current add.txt/remove.txt. Used when the kernel side is identical
# (same PPE/NSS sources, recipe, compiler and libc).
#
# Usage: refresh-hybrid-builder.sh PARENT_ASSET_DIR
# Environment: SNAPSHOT_LOCK (required), EXPECTED_KERNEL_IDENTITY (optional).
set -Eeuo pipefail
trap 'echo "::error::Hybrid refresh failed at line $LINENO: $BASH_COMMAND" >&2' ERR

ROOT="${GITHUB_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
# shellcheck source=hybrid-common.sh
source "$ROOT/scripts/hybrid-common.sh"
PARENT="$(realpath "${1:?Pass the directory with the parent Builder release assets}")"
WORK="${RUNNER_TEMP:-/tmp}/immortal-hybrid-refresh"
OUT="${HYBRID_OUT_DIR:-$ROOT/out-hybrid}"
LOCK="$(realpath "${SNAPSHOT_LOCK:?Set SNAPSHOT_LOCK to snapshot-lock.json}")"
rm -rf "$WORK"
mkdir -p "$WORK" "$OUT"
: > "$OUT/timings.tsv"
mark() { printf '%s\t%s\n' "$1" "$(( $(date +%s) - $2 ))" >> "$OUT/timings.tsv"; }
T0="$(date +%s)"
hybrid_check_lock "$LOCK"

# ---------------------------------------------------------------------------
# 1. Verified parent
# ---------------------------------------------------------------------------
META="$PARENT/builder-metadata.json"
SDK_META="$PARENT/sdk-metadata.json"
FEED_LOCK="$PARENT/sdk-feeds.lock.json"
IB_ARCHIVE="$PARENT/$(jq -er '.archive' "$META")"
for file in "$META" "$SDK_META" "$FEED_LOCK" "$IB_ARCHIVE" \
  "$PARENT/base-overlay.tar.gz" "$PARENT/imagebuilder-packages.txt" \
  "$PARENT/local-plan.json" "$PARENT/official-apks.json" "$PARENT/official-toolchain-status.txt"; do
  test -s "$file" || { echo "::error::Parent Builder lacks $(basename "$file")" >&2; exit 1; }
done
python3 "$ROOT/scripts/immortalwrt_builder.py" verify --metadata "$META" \
  --archive "$IB_ARCHIVE" --overlay "$PARENT/base-overlay.tar.gz" \
  --packages "$PARENT/imagebuilder-packages.txt"
jq -e --arg tag "$(jq -er .tag "$META")" \
  --arg sha "$(sha256sum "$META" | cut -d" " -f1)" \
  '.builder_tag == $tag and .builder_metadata_sha256 == $sha and \
   (.archive_sha256 | test("^[0-9a-f]{64}$"))' "$SDK_META" >/dev/null
jq -e --arg tag "$(jq -er .tag "$META")" \
  '.builder_tag == $tag and .schema == 1' "$FEED_LOCK" >/dev/null
jq -e '.build_mode == "hybrid" and (.hybrid | type == "object")' "$META" >/dev/null || {
  echo "::error::Parent is not a hybrid Builder" >&2; exit 1;
}
PARENT_TAG="$(jq -er '.tag' "$META")"
IMM_SHA="$(jq -er '.immortalwrt_commit' "$META")"
PPE_SHA="$(jq -er '.ppe_nss_commit' "$META")"
BASE_SHA="$(jq -er '.base_overlay_commit' "$META")"
NSS_SHA="$(jq -er '.feeds.nss' "$FEED_LOCK")"
PPE_LUCI_SHA="$(jq -er '.feeds.ppe_qos_luci' "$FEED_LOCK")"
KEYRING_SHA="$(jq -er '.hybrid.keyring_commit' "$META")"
PARENT_KERNEL_IDENTITY="$(jq -er '.hybrid.kernel_identity' "$META")"
# The kernel side of the parent must be exactly what this snapshot needs.
KERNEL_IDENTITY="$("${HB[@]}" kernel-identity --lock "$LOCK" --ppe "$PPE_SHA" --base "$BASE_SHA" \
  --nss "$NSS_SHA" --ppe-luci "$PPE_LUCI_SHA")"
[[ "$KERNEL_IDENTITY" == "$PARENT_KERNEL_IDENTITY" ]] || {
  echo "::error::Kernel side changed since $PARENT_TAG; a full hybrid build is required" >&2; exit 1;
}
[[ -z "${EXPECTED_KERNEL_IDENTITY:-}" || "$EXPECTED_KERNEL_IDENTITY" == "$KERNEL_IDENTITY" ]]
IDENTITY="$("${HB[@]}" identity --lock "$LOCK" --ppe "$PPE_SHA" --base "$BASE_SHA" \
  --nss "$NSS_SHA" --ppe-luci "$PPE_LUCI_SHA" \
  --packages "$(python3 "$ROOT/scripts/immortalwrt_builder.py" package-fingerprint)")"
[[ -z "${EXPECTED_IDENTITY:-}" || "$EXPECTED_IDENTITY" == "$IDENTITY" ]] || {
  echo "::error::Layer identity changed since workflow resolution" >&2; exit 1;
}

tar -I zstd -xf "$IB_ARCHIVE" -C "$WORK"
IB="$(find "$WORK" -mindepth 1 -maxdepth 1 -type d -name '*imagebuilder*' -print -quit)"
test -f "$IB/Makefile" && test -d "$IB/packages"
APK="$IB/staging_dir/host/bin/apk"
test -x "$APK"
mark parent "$T0"

# ---------------------------------------------------------------------------
# 2. New official closure for the reused local packages
# ---------------------------------------------------------------------------
T1="$(date +%s)"
KEYS="$WORK/official-keys"
hybrid_official_keys "$KEYRING_SHA" "$KEYS" "$WORK"
hybrid_official_indexes "$LOCK" "$APK" "$KEYS" "$WORK/official-indexes"
"${HB[@]}" refresh-plan --parent-plan "$PARENT/local-plan.json" \
  --add "$ROOT/config/add.txt" --remove "$ROOT/config/remove.txt" --output "$OUT/local-plan.json"
"${HB[@]}" closure --plan "$OUT/local-plan.json" --lock "$LOCK" "${HYBRID_INDEX_ARGS[@]}" \
  --output "$OUT/official-apks.json"
fallback="$(jq -r '.local_fallback[]' "$OUT/official-apks.json")"
[[ -z "$fallback" ]] || {
  echo "::error::Not published officially, needs a local build: $fallback" >&2; exit 1;
}
mark official-closure "$T1"

# ---------------------------------------------------------------------------
# 3. Swap the mirrored userland inside the ImageBuilder
# ---------------------------------------------------------------------------
T2="$(date +%s)"
while IFS= read -r file; do
  if [[ "$file" == */* || "$file" != *.apk ]]; then
    echo "::error::Bad parent mirror entry: $file" >&2; exit 1
  fi
  rm -f "$IB/packages/$file"
done < <(jq -r '.mirrored[]' "$PARENT/official-apks.json")
rm -f "$IB/packages/packages.adb" "$IB/packages/index.json"
"${HB[@]}" prune-local --plan "$OUT/local-plan.json" --dir "$IB/packages" | tail -n1
find "$IB/packages" -maxdepth 1 -type f -name '*.apk' -printf '%f\n' | sort > "$OUT/local-apks.txt"
while IFS= read -r name; do
  [[ -n "$(find "$IB/packages" -maxdepth 1 -type f -name "$name-[0-9]*.apk" -print -quit)" ]] || {
    echo "::error::Parent ImageBuilder lost local package $name" >&2; exit 1;
  }
done < <(jq -r '.local_packages[].apk_name' "$OUT/local-plan.json")
hybrid_mirror "$OUT/official-apks.json" "$IB/packages" "$APK" "$KEYS" "$WORK"
mark official-mirror "$T2"

T3="$(date +%s)"
# Resolve the manifest on a throwaway copy: a used ImageBuilder generates a
# local signing key whose public half firmware trusts. It must never ship.
cp -a "$IB" "$WORK/ib-manifest"
hybrid_ib_manifest "$WORK/ib-manifest" "$OUT" "$OUT/local-apks.txt"
rm -rf "$WORK/ib-manifest"
# Archive only official APK payloads; kernel, kmods, host tools and SDK are
# still referenced by immutable parent release and never re-tarred here.
NEW_LAYER="$OUT/hybrid-userland-packages.tar.zst"
mkdir -p "$WORK/layer/packages"
while IFS= read -r file; do
  [[ "$file" != */* && "$file" == *.apk && -s "$IB/packages/$file" ]] || {
    echo "::error::Bad verified official APK: $file" >&2; exit 1;
  }
  ln "$IB/packages/$file" "$WORK/layer/packages/$file"
done < <(jq -r '.mirrored[]' "$OUT/official-apks.json")
tar -I 'zstd -T0 -4' -cf "$NEW_LAYER" -C "$WORK/layer" packages
mark layer-archive "$T3"

cp "$LOCK" "$OUT/snapshot-lock.json"
python3 "$ROOT/scripts/hybrid_layer.py" create \
  --base-metadata "$META" --base-official "$PARENT/official-apks.json" \
  --archive "$NEW_LAYER" --official "$OUT/official-apks.json" \
  --packages "$OUT/imagebuilder-packages.txt" \
  --snapshot "$OUT/snapshot-lock.json" --identity "$IDENTITY" \
  --metadata "$OUT/layer-metadata.json"
{
  grep -v '^Official snapshot=\|^Feeds=' "$PARENT/source-commits.txt" 2>/dev/null || true
  echo "Official snapshot=$(jq -er '.snapshot_version' "$LOCK")"
  echo "Refreshed from=$PARENT_TAG"
} > "$OUT/source-commits.txt"
# ---------------------------------------------------------------------------
# 5. Smoke test: build the real firmware image from the refreshed Builder
# ---------------------------------------------------------------------------
T4="$(date +%s)"
BUILDER_META="$META" BUILDER_ARCHIVE="$IB_ARCHIVE" \
BASE_OVERLAY="$PARENT/base-overlay.tar.gz" BUILDER_PACKAGES="$PARENT/imagebuilder-packages.txt" \
HYBRID_LAYER_META="$OUT/layer-metadata.json" HYBRID_LAYER_ARCHIVE="$NEW_LAYER" \
HYBRID_LAYER_OFFICIAL="$OUT/official-apks.json" \
HYBRID_LAYER_PACKAGES="$OUT/imagebuilder-packages.txt" \
HYBRID_LAYER_SNAPSHOT="$OUT/snapshot-lock.json" \
HYBRID_PARENT_OFFICIAL="$PARENT/official-apks.json" \
IMMORTAL_OUT_DIR="$OUT/ib-smoke" PUBLISH_RELEASE=false \
  bash scripts/repack-immortalwrt.sh
test -s "$OUT/ib-smoke/immortalwrt-qualcommax-ipq60xx-jdcloud_re-ss-01-squashfs-sysupgrade.bin"
mark smoke-test "$T4"
mark total "$T0"
{
  echo "## Thin Hybrid userland layer $(jq -er .tag "$OUT/layer-metadata.json")"
  echo "- Base Builder: $PARENT_TAG (unchanged IB and SDK)"
  echo "- Official mirrored APKs: $(jq '.mirrored | length' "$OUT/layer-metadata.json")"
  echo "- Layer size: $(du -h "$NEW_LAYER" | cut -f1)"
  echo "- Real firmware smoke test: passed"
  echo ""
  echo "| Phase | Seconds |"
  echo "|---|---:|"
  awk -F"\t" '{ printf "| %s | %s |\n", $1, $2 }' "$OUT/timings.tsv"
} >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
echo "Verified thin userland layer: $(jq -er .tag "$OUT/layer-metadata.json")"
