#!/usr/bin/env bash
# Publish verified test-only pre-release firmware. Distinct tags mean neither
# device's stable OTA will ever auto-discover these experimental images.
set -Eeuo pipefail
ROOT="${GITHUB_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
DEVICE="${1:?arthur or mx4200v1}"
DOWNLOAD="${2:?downloaded Actions artifact directory}"
[[ -d "$DOWNLOAD" ]]
[[ "$DEVICE" == arthur || "$DEVICE" == mx4200v1 ]] || exit 1
[[ "${GITHUB_REPOSITORY:-}" == "pzcn/openwrt-ppe-nss-ota" ]] || exit 1
[[ "${GITHUB_SHA:-}" =~ ^[0-9a-f]{40}$ ]] || exit 1
TAG="preview-singbox-${DEVICE}-1.15.0-alpha.13-g${GITHUB_SHA:0:12}"
if [[ "$DEVICE" == arthur ]]; then
  BOARD=jdcloud,re-ss-01
  CHANNEL=re-ss-01-immortal-ppe-nss
  IMAGE=immortalwrt-qualcommax-ipq60xx-jdcloud_re-ss-01-squashfs-sysupgrade.bin
  MANIFEST=immortalwrt-qualcommax-ipq60xx-jdcloud_re-ss-01.manifest
else
  BOARD=linksys,mx4200v1
  CHANNEL=mx4200v1-immortal-ppe-nss
  IMAGE=immortalwrt-qualcommax-ipq807x-linksys_mx4200v1-squashfs-sysupgrade.bin
  FACTORY=immortalwrt-qualcommax-ipq807x-linksys_mx4200v1-squashfs-factory.bin
  MANIFEST=immortalwrt-qualcommax-ipq807x-linksys_mx4200v1.manifest
  FWTOOL_META=immortalwrt-qualcommax-ipq807x-linksys_mx4200v1-squashfs-sysupgrade.metadata.json
fi
mapfile -t match < <(find "$DOWNLOAD" -type f -name "$IMAGE" -print)
[[ "${#match[@]}" -eq 1 ]] || { echo "::error::Ambiguous image artifact"; exit 1; }
DIR="$(dirname "${match[0]}")"
for name in "$IMAGE" "$MANIFEST" ota.json sing-box-core.json; do
  [[ -s "$DIR/$name" && ! -L "$DIR/$name" ]] || {
    echo "::error::Missing preview firmware asset: $name"; exit 1;
  }
done
jq -e --arg board "$BOARD" --arg channel "$CHANNEL" --arg image "$IMAGE" \
  --arg manifest "$MANIFEST" '
    .schema == 1 and .board == $board and .channel == $channel and
    .image == $image and .manifest == $manifest and
    .sing_box_core.version == "1.15.0-alpha.13" and
    .sing_box_core.placement == "firmware-squashfs" and
    .sing_box_core.architecture == "aarch64" and
    .sing_box_core.asset_sha256 == "38508bd270d78bbc1838e459d2f1b3b0cab5d3658592d8f1f4e383c40935d757"
  ' "$DIR/ota.json" >/dev/null
jq -e '
   .schema == 1 and .version == "1.15.0-alpha.13" and
   .placement == "firmware-squashfs" and
   .asset_sha256 == "38508bd270d78bbc1838e459d2f1b3b0cab5d3658592d8f1f4e383c40935d757" and
   (.binary_sha256 | test("^[0-9a-f]{64}$"))
' "$DIR/sing-box-core.json" >/dev/null
cmp -s <(jq -cS '.sing_box_core' "$DIR/ota.json") \
  <(jq -cS '.' "$DIR/sing-box-core.json") || {
  echo "::error::OTA metadata core and staged binary provenance disagree"; exit 1;
}
[[ "$(sha256sum "$DIR/$IMAGE" | cut -d' ' -f1)" == "$(jq -er .image_sha256 "$DIR/ota.json")" ]] || exit 1
[[ "$(sha256sum "$DIR/$MANIFEST" | cut -d' ' -f1)" == "$(jq -er .manifest_sha256 "$DIR/ota.json")" ]] || exit 1
[[ "$(stat -c %s "$DIR/$IMAGE")" == "$(jq -er .image_size "$DIR/ota.json")" ]] || exit 1
assets=("$DIR/$IMAGE" "$DIR/$MANIFEST" "$DIR/ota.json" "$DIR/sing-box-core.json")
for extra in sha256sums builder-metadata.json snapshot-lock.json repack-metadata.json \
             mx4200v1-ota-identity.json "$FACTORY" "$FWTOOL_META"; do
  [[ -n "$extra" && -s "$DIR/$extra" ]] && assets+=("$DIR/$extra")
done
if [[ "$DEVICE" == mx4200v1 ]]; then
  [[ -s "$DIR/$FACTORY" && -s "$DIR/$FWTOOL_META" ]] || exit 1
  jq -e '
    .metadata_version == "1.1" and
    ((.supported_devices // .new_supported_devices // []) |
    index("linksys,mx4200v1") != null)
  ' "$DIR/$FWTOOL_META" >/dev/null
fi
echo "PASS $DEVICE: verified sing-box core alpha.13 and image metadata"
if [[ "${PREVIEW_VERIFY_ONLY:-false}" == true ]]; then
  exit 0
fi
if gh release view "$TAG" -R "$GITHUB_REPOSITORY" >/dev/null 2>&1; then
  echo "Immutable preview Release already exists: $TAG"
  exit 0
fi
gh release create "$TAG" -R "$GITHUB_REPOSITORY" \
  --target "$GITHUB_SHA" --prerelease --latest=false \
  --title "$DEVICE test firmware - sing-box v1.15.0-alpha.13" \
  --notes "EXPERIMENTAL: Official sing-box v1.15.0-alpha.13 (AArch64 musl) embedded directly in firmware SquashFS and verified by upstream asset SHA256. The LuCI manager remains v0.4.7. APK metadata may still show the original sing-box feed package version. This prerelease is NOT part of the stable OTA channel. Boot, upgrade, config compatibility and fallback have not been hardware tested; do not flash the wrong device." \
  "${assets[@]}"
echo "Published experimental $DEVICE preview: $TAG"
