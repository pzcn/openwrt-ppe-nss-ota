#!/usr/bin/env bash
# Rebuild MX4200 v1 factory/sysupgrade from an existing, verified Hybrid IB.
# Never compile a new kernel, kmods, toolchain or SDK; never release/flash OTA.
#
# Usage: repack-hybrid.sh BUILDER_ARTIFACT_DIR FIRMWARE_ARTIFACT_DIR DIAGNOSTICS_DIR
# BASE_RUN_ID and BASE_SOURCE_SHA identify the run that produced the IB.
set -Eeuo pipefail
trap 'echo "::error::MX4200 fast repack failed at line $LINENO: $BASH_COMMAND" >&2' ERR

ROOT="${GITHUB_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
WORK="${RUNNER_TEMP:-/tmp}/mx4200v1-fast-repack"
OUT="${MX4200V1_REPACK_OUT:-$ROOT/out-mx4200v1-fast-repack}"
BUILDER="$(realpath "${1:?Builder artifact directory is required}")"
PREVIOUS="$(realpath "${2:?Prior firmware artifact directory is required}")"
DIAGNOSTICS="$(realpath "${3:?Diagnostic artifact directory is required}")"
BASE_RUN_ID="${BASE_RUN_ID:-}"
BASE_BUILDER_TAG="${BASE_BUILDER_TAG:-}"
BASE_SOURCE_SHA="${BASE_SOURCE_SHA:?MX4200 Builder resolver must supply BASE_SOURCE_SHA}"

# The IB is tied to the original kernel recipe. Repack-only changes to packages
# and userspace files are allowed; a new kernel config/port needs a new Builder.
[[ "$BASE_SOURCE_SHA" =~ ^[a-f0-9]{40}$ ]] || exit 1
# Old short-lived artifacts identify their numeric run; durable releases use
# an immutable Builder tag. Never fabricate a run ID for Release-backed images.
if [[ -n "$BASE_BUILDER_TAG" ]]; then
  [[ "$BASE_BUILDER_TAG" =~ ^mx4200-builder-[0-9a-f]{24}$ && -z "$BASE_RUN_ID" ]] || exit 1
else
  [[ "$BASE_RUN_ID" =~ ^[1-9][0-9]*$ ]] || exit 1
fi
git -C "$ROOT" cat-file -e "${BASE_SOURCE_SHA}^{commit}"
if ! git -C "$ROOT" diff --quiet "$BASE_SOURCE_SHA" HEAD -- \
    mx4200v1/source.config mx4200v1/port-ppe-nss.sh \
    mx4200v1/packages.txt mx4200v1/remove.txt; then
  echo "::error::MX4200 kernel, port, or package closure changed since Builder source; rebuild MX-only Hybrid Builder or create a verified APK layer." >&2
  exit 1
fi

mkdir -p "$WORK/imagebuilder" "$WORK/overlay" "$OUT"
mapfile -t archives < <(find "$BUILDER" -type f -name '*imagebuilder*.tar.zst' -print)
[[ "${#archives[@]}" -eq 1 ]] || { echo "::error::Need exactly one MX ImageBuilder archive"; exit 1; }
IB_ARCHIVE="${archives[0]}"
IB_NAME="$(basename "$IB_ARCHIVE")"
[[ "$IB_NAME" == immortalwrt-imagebuilder-qualcommax-ipq807x* ]]
# GitHub Actions artifact ZIPs preserve out-mx4200v1-hybrid/ prefixes.
# Locate by verified singleton filenames instead of assuming a flat unzip.
find_single() {
  local folder="$1" name="$2"
  local -a matches=()
  mapfile -t matches < <(find "$folder" -type f -name "$name" -print)
  [[ "${#matches[@]}" -eq 1 ]] || {
    echo "::error::Need exactly one $name under $folder"; exit 1;
  }
  printf '%s\n' "${matches[0]}"
}
BASE_OVERLAY="$(find_single "$BUILDER" base-overlay.tar.gz)"
BASE_LOCK="$(find_single "$BUILDER" snapshot-lock.json)"
BASE_META="$(find_single "$DIAGNOSTICS" mx4200v1-hybrid-metadata.json)"
BASE_SHA_FILE="$(find_single "$PREVIOUS" sha256sums)"
DIAGNOSTICS="$(dirname "$BASE_META")"
for file in "$IB_ARCHIVE" "$BASE_OVERLAY" "$BASE_LOCK" "$BASE_META" "$BASE_SHA_FILE"; do
  [[ -s "$file" ]] || { echo "::error::Missing immutable parent asset $file"; exit 1; }
done
jq -e --arg archive "$IB_NAME" '
  .schema == 1 and .target == "qualcommax/ipq807x" and
  .profile == "linksys_mx4200v1" and .imagebuilder == $archive and
  .hardware_tested == false and .publishable == false
' "$BASE_META" >/dev/null
jq -e '.schema == 2 and .target == "qualcommax/ipq807x" and .architecture == "aarch64_cortex-a53"' \
  "$BASE_LOCK" >/dev/null

# Source run records SHA256 for the exact IB and overlay. The action artifact
# already provides transport integrity, but these checks bind the two copies.
check_parent_sum() {
  local path="$1" filename digest actual
  filename="$(basename "$path")"
  digest="$(awk -v name="$filename" '$2 == name {print $1}' "$BASE_SHA_FILE")"
  [[ "$digest" =~ ^[a-f0-9]{64}$ ]] || { echo "::error::No recorded SHA256 for $filename"; exit 1; }
  actual="$(sha256sum "$path" | cut -d' ' -f1)"
  [[ "$actual" == "$digest" ]] || { echo "::error::Parent artifact modified: $filename"; exit 1; }
}
check_parent_sum "$IB_ARCHIVE"
check_parent_sum "$BASE_OVERLAY"
check_parent_sum "$BASE_LOCK"

tar -I zstd -xf "$IB_ARCHIVE" -C "$WORK/imagebuilder"
mapfile -t roots < <(find "$WORK/imagebuilder" -mindepth 1 -maxdepth 1 -type d -name '*imagebuilder*' -print)
[[ "${#roots[@]}" -eq 1 ]] || { echo "::error::Unexpected IB layout"; exit 1; }
IB="${roots[0]}"
FWTOOL="$IB/staging_dir/host/bin/fwtool"
[[ -s "$IB/Makefile" && -x "$FWTOOL" && -d "$IB/packages" ]] || {
  echo "::error::MX ImageBuilder missing Makefile, host fwtool, or offline APKs"; exit 1;
}
# No cross-target borrow: must use this MX4200 v1's FIT built for the same ABI.
mapfile -t fits < <(find "$IB/build_dir" -type f \
  -path '*/linux-qualcommax_ipq807x/linksys_mx4200v1-uImage.itb' -print)
[[ "${#fits[@]}" -eq 1 && -s "${fits[0]}" ]] || {
  echo "::error::Matching MX4200 v1 FIT is absent"; exit 1;
}
(( $(stat -c '%s' "${fits[0]}") <= 6144 * 1024 )) || {
  echo "::error::MX4200 FIT exceeds 6144 KiB"; exit 1;
}
python3 "$ROOT/scripts/fit_configs.py" "${fits[0]}" | grep -Eq '^config@[^[:space:]]+$'

# Update ONLY the userspace overlay, preserve Linksys NAND/UBI/dual-slot.
tar -xzf "$BASE_OVERLAY" -C "$WORK/overlay"
bash "$ROOT/mx4200v1/stage-overlay.sh" "$WORK/overlay"
bash "$ROOT/scripts/stage-sing-box-pre.sh" "$WORK/overlay" "$OUT"
[[ ! -e "$WORK/overlay/lib/upgrade/platform.sh" ]] || {
  echo "::error::Refusing to override upstream Linksys NAND/UBI upgrade code"; exit 1;
}
IMM_SHA="$(jq -er '.immortalwrt_commit' "$BASE_META")"
PPE_SHA="$(jq -er '.ppe_nss_commit' "$BASE_META")"
bash "$ROOT/mx4200v1/ota-artifacts.sh" prepare "$WORK/overlay" "$OUT" "$IMM_SHA" "$PPE_SHA"

export HYBRID_TARGET=qualcommax/ipq807x
export HYBRID_IMAGE_PROFILE=linksys_mx4200v1
export HYBRID_IMAGE_CONFIG="$ROOT/mx4200v1/source.config"
export HYBRID_IMAGE_ADD="$ROOT/mx4200v1/packages.txt"
export HYBRID_IMAGE_REMOVE="$ROOT/mx4200v1/remove.txt"
# Non-kernel additions can be assembled only if already available in this IB.
source "$ROOT/scripts/hybrid-common.sh"
REQUEST="$(hybrid_image_request)"
[[ -n "$REQUEST" ]]
echo "MX4200 IB: $IB_NAME; build request: $REQUEST"
make -C "$IB" -j"$(nproc)" image PROFILE=linksys_mx4200v1 \
  STRIP_ABI=1 PACKAGES="$REQUEST" FILES="$WORK/overlay"

PREFIX="immortalwrt-qualcommax-ipq807x-linksys_mx4200v1"
TARGET="$IB/bin/targets/qualcommax/ipq807x"
FACTORY="$TARGET/$PREFIX-squashfs-factory.bin"
SYSUPGRADE="$TARGET/$PREFIX-squashfs-sysupgrade.bin"
for file in "$FACTORY" "$SYSUPGRADE"; do
  [[ -s "$file" ]] || { echo "::error::ImageBuilder failed to produce $(basename "$file")"; exit 1; }
done
cp "$FACTORY" "$SYSUPGRADE" "$OUT/"
make -s -C "$IB" manifest PROFILE=linksys_mx4200v1 \
  STRIP_ABI=1 PACKAGES="$REQUEST" > "$OUT/$PREFIX.manifest"

# A readable trailer is mandatory: MX4200 v1 rejects sysupgrade without it.
FW_META="$OUT/$PREFIX-squashfs-sysupgrade.metadata.json"
"$FWTOOL" -i "$FW_META" "$OUT/$(basename "$SYSUPGRADE")"
jq -e '
  .metadata_version == "1.1" and (.compat_version | type == "string") and
  ((.supported_devices // .new_supported_devices // []) | index("linksys,mx4200v1") != null)
' "$FW_META" >/dev/null || {
  echo "::error::Invalid OpenWrt sysupgrade metadata for MX4200 v1"; exit 1;
}

for required in kmod-nss-wifi-drv qca-ppe-qos ppe-help luci-app-qca-ppe-qos \
    luci-theme-aurora sqm-scripts autocore luci-app-sing-box sing-box \
    kmod-inet-diag kmod-tun; do
  awk -v name="$required" '$1 == name {ok=1} END {exit !ok}' \
    "$OUT/$PREFIX.manifest" || { echo "::error::Missing $required"; exit 1; }
done
for bad in luci-app-homeproxy luci-app-diskman luci-app-statistics; do
  if awk -v name="$bad" '$1 == name {ok=1} END {exit !ok}' "$OUT/$PREFIX.manifest"; then
    echo "::error::Excluded package $bad returned"; exit 1;
  fi
done
if find "$TARGET" -maxdepth 1 -name '*linksys_mx4200v2*' | grep -q .; then
  echo "::error::Unexpected MX4200 v2 image"; exit 1;
fi

# Each installed kmod must come from the original local compilation, not the
# official Snapshot kernel or a different ABI. The parent diagnostic lists it.
LOCAL_APKS="$DIAGNOSTICS/local-apks.txt"
[[ -s "$LOCAL_APKS" ]] || { echo "::error::Parent kmod provenance list missing"; exit 1; }
while read -r apk; do
  grep -Fxq "$apk" "$LOCAL_APKS" || { echo "::error::Non-parent kmod: $apk"; exit 1; }
done < <(awk '$1 ~ /^kmod-/ { print $1 "-" $3 ".apk" }' "$OUT/$PREFIX.manifest")

bash "$ROOT/mx4200v1/ota-artifacts.sh" metadata "$OUT" "$IMM_SHA" "$PPE_SHA"
cp "$BASE_LOCK" "$OUT/snapshot-lock.json"
jq -n --argjson parent "$(cat "$BASE_META")" \
  --arg source "$(git -C "$ROOT" rev-parse HEAD)" \
  --arg base_source "$BASE_SOURCE_SHA" --arg base_run "$BASE_RUN_ID" \
  --arg builder_tag "$BASE_BUILDER_TAG" \
  --arg ib_sha "$(sha256sum "$IB_ARCHIVE" | cut -d' ' -f1)" \
  '{schema:1, channel:"mx4200v1-imagebuilder-repack-test",
    target:"qualcommax/ipq807x", profile:"linksys_mx4200v1",
    parent_run_id:(if $base_run == "" then null else $base_run end),
    parent_builder_tag:(if $builder_tag == "" then null else $builder_tag end),
    parent_source_commit:$base_source,
    parent_imagebuilder_sha256:$ib_sha, parent_hybrid:$parent,
    repack_source_commit:$source, compiled_kernel:false,
    reused_imagebuilder:true, hardware_tested:false,
    publishable:false}' > "$OUT/repack-metadata.json"
printf 'Parent Builder=%s\nParent run=%s\nParent SHA=%s\nSource SHA=%s\n' \
  "${BASE_BUILDER_TAG:-none}" "${BASE_RUN_ID:-none}" "$BASE_SOURCE_SHA" "$(git -C "$ROOT" rev-parse HEAD)" > "$OUT/source-commits.txt"
(
  cd "$OUT"
  sha256sum "$PREFIX-squashfs-factory.bin" "$PREFIX-squashfs-sysupgrade.bin" \
    "$PREFIX.manifest" "$PREFIX-squashfs-sysupgrade.metadata.json" \
    repack-metadata.json snapshot-lock.json ota.json mx4200v1-ota-identity.json > sha256sums
  sha256sum -c sha256sums
)
{
  echo "## MX4200 v1: firmware built from reused Hybrid ImageBuilder"
  echo "- Parent: ${BASE_BUILDER_TAG:-run $BASE_RUN_ID}"
  echo "- ImageBuilder reused: $IB_NAME"
  echo "- New kernel, kmods, toolchain or SDK compiled: **no**"
  echo "- MX4200 v1 factory/sysupgrade metadata: **verified**"
  echo "- On-device test: **not performed**"
} >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
echo "MX4200 v1 fast firmware artifacts ready in $OUT"
