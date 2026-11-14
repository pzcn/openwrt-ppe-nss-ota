#!/usr/bin/env bash
# Hybrid Builder, refresh mode: no compilation at all.
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
SDK_ARCHIVE="$PARENT/$(jq -er '.archive' "$SDK_META")"
for file in "$META" "$SDK_META" "$FEED_LOCK" "$IB_ARCHIVE" "$SDK_ARCHIVE" \
  "$PARENT/base-overlay.tar.gz" "$PARENT/imagebuilder-packages.txt" \
  "$PARENT/local-plan.json" "$PARENT/official-apks.json" "$PARENT/official-toolchain-status.txt"; do
  test -s "$file" || { echo "::error::Parent Builder lacks $(basename "$file")" >&2; exit 1; }
done
python3 "$ROOT/scripts/immortalwrt_builder.py" verify --metadata "$META" \
  --archive "$IB_ARCHIVE" --overlay "$PARENT/base-overlay.tar.gz" \
  --packages "$PARENT/imagebuilder-packages.txt"
python3 "$ROOT/scripts/immortalwrt_sdk.py" verify --metadata "$SDK_META" \
  --builder-metadata "$META" --archive "$SDK_ARCHIVE" --feed-lock "$FEED_LOCK"
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
[[ "$IDENTITY" != "$(jq -er '.hybrid.identity' "$META")" ]] || {
  echo "::error::Nothing changed since $PARENT_TAG" >&2; exit 1;
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
NEW_IB="$OUT/$(basename "$IB_ARCHIVE")"
tar -I 'zstd -T0 -12' -cf "$NEW_IB" -C "$WORK" "$(basename "$IB")"
hybrid_check_archive_keys "$NEW_IB"
cp "$SDK_ARCHIVE" "$OUT/"
NEW_SDK="$OUT/$(basename "$SDK_ARCHIVE")"
cp "$PARENT/base-overlay.tar.gz" "$PARENT/official-toolchain-status.txt" "$OUT/"
mark repack "$T3"

# ---------------------------------------------------------------------------
# 4. Metadata: same kernel lineage, new snapshot/feeds/package selection
# ---------------------------------------------------------------------------
FEEDS_FINGERPRINT="$("${HB[@]}" fingerprint feeds --lock "$LOCK" --nss "$NSS_SHA" --ppe-luci "$PPE_LUCI_SHA")"
jq -n --argjson lock "$(cat "$LOCK")" --arg nss "$NSS_SHA" --arg luci "$PPE_LUCI_SHA" \
  '{packages: $lock.arch_feeds.packages.commit, luci: $lock.arch_feeds.luci.commit,
    routing: $lock.arch_feeds.routing.commit, telephony: $lock.arch_feeds.telephony.commit,
    nss: $nss, ppe_qos_luci: $luci}' > "$WORK/feeds.json"
hybrid_info "$WORK/hybrid-info.json" "$IDENTITY" "$KERNEL_IDENTITY" \
  "$(jq -er '.hybrid.kernel_built_at' "$META")" \
  "$(jq -r '.hybrid.kernel_parent // .tag' "$META")" "$KEYRING_SHA"
cd "$ROOT"
python3 scripts/immortalwrt_builder.py metadata --mode hybrid --snapshot-lock "$LOCK" \
  --hybrid-info "$WORK/hybrid-info.json" \
  --immortal "$IMM_SHA" --ppe "$PPE_SHA" --base "$BASE_SHA" --feeds "$FEEDS_FINGERPRINT" \
  --archive "$NEW_IB" --overlay "$OUT/base-overlay.tar.gz" \
  --packages "$OUT/imagebuilder-packages.txt" --output "$OUT/builder-metadata.json"
[[ "$(jq -r .tag "$OUT/builder-metadata.json")" != "$PARENT_TAG" ]]
python3 scripts/immortalwrt_sdk.py reissue --parent-metadata "$SDK_META" \
  --builder-metadata "$OUT/builder-metadata.json" --archive "$NEW_SDK" \
  --feeds "$WORK/feeds.json" --feed-lock "$OUT/sdk-feeds.lock.json" \
  --output "$OUT/sdk-metadata.json"
{
  grep -v '^Official snapshot=\|^Feeds=' "$PARENT/source-commits.txt" 2>/dev/null || true
  echo "Official snapshot=$(jq -er '.snapshot_version' "$LOCK")"
  echo "Feeds=$FEEDS_FINGERPRINT"
  echo "Refreshed from=$PARENT_TAG"
} > "$OUT/source-commits.txt"
cp "$LOCK" "$OUT/snapshot-lock.json"

# ---------------------------------------------------------------------------
# 5. Smoke test: build the real firmware image from the refreshed Builder
# ---------------------------------------------------------------------------
T4="$(date +%s)"
BUILDER_META="$OUT/builder-metadata.json" BUILDER_ARCHIVE="$NEW_IB" \
BASE_OVERLAY="$OUT/base-overlay.tar.gz" BUILDER_PACKAGES="$OUT/imagebuilder-packages.txt" \
IMMORTAL_OUT_DIR="$OUT/ib-smoke" PUBLISH_RELEASE=false \
  bash scripts/repack-immortalwrt.sh
test -s "$OUT/ib-smoke/immortalwrt-qualcommax-ipq60xx-jdcloud_re-ss-01-squashfs-sysupgrade.bin"
mark smoke-test "$T4"
mark total "$T0"
hybrid_summary "$OUT" "Hybrid Builder (userland refresh of $PARENT_TAG)"
echo "Refreshed hybrid Builder: $(jq -r .tag "$OUT/builder-metadata.json")"
