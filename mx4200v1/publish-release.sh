#!/usr/bin/env bash
# Publish an immutable, *pre-release* MX4200 v1 Builder or OTA firmware.
# Runtime OTA never sees prereleases; promotion to stable is an explicit
# hardware-validation decision made separately in the GitHub Release UI.
# Usage: publish-release.sh builder|firmware DIR
set -Eeuo pipefail
ROOT="${GITHUB_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
KIND="${1:?Expected builder or firmware}"
DIR="$(realpath "${2:?Expected the verified artifact directory}")"
REPO="${GITHUB_REPOSITORY:-pzcn/openwrt-ppe-nss-ota}"
[[ "$KIND" == builder || "$KIND" == firmware ]] || exit 2
[[ "$REPO" == pzcn/openwrt-ppe-nss-ota ]] || {
  echo "::error::Untrusted MX4200 Release repository"; exit 1;
}
[[ -d "$DIR" ]]
file() { [[ -s "$DIR/$1" && ! -L "$DIR/$1" ]] || { echo "::error::Missing $1"; exit 1; }; }
sha() { sha256sum "$1" | awk '{print $1}'; }
assert_sha() { # file expected hex
  [[ "$2" =~ ^[0-9a-f]{64}$ && "$(sha "$1")" == "$2" ]] || {
    echo "::error::SHA256 verification failed for $1"; exit 1;
  }
}
PREFIX="immortalwrt-qualcommax-ipq807x-linksys_mx4200v1"
IMAGE="$PREFIX-squashfs-sysupgrade.bin"
FACTORY="$PREFIX-squashfs-factory.bin"
MANIFEST="$PREFIX.manifest"
FW_META="$PREFIX-squashfs-sysupgrade.metadata.json"
TAG=""
ASSETS=()

if [[ "$KIND" == builder ]]; then
  META=mx4200v1-hybrid-metadata.json
  file "$META"; file sha256sums; file snapshot-lock.json
  file base-overlay.tar.gz; file local-apks.txt
  file imagebuilder-packages.txt; file official-apks.json
  file source-commits.txt
  jq -e '
    .schema == 1 and .target == "qualcommax/ipq807x" and
    .profile == "linksys_mx4200v1" and
    (.identity | test("^[0-9a-f]{64}$")) and
    (.kernel_identity | test("^[0-9a-f]{64}$")) and
    (.source_commit | test("^[0-9a-f]{40}$")) and
    (.immortalwrt_commit | test("^[0-9a-f]{40}$")) and
    (.ppe_nss_commit | test("^[0-9a-f]{40}$")) and
    (.hardware_tested == false) and (.publishable == false) and
    (.imagebuilder | startswith("immortalwrt-imagebuilder-qualcommax-ipq807x")) and
    (.sdk | startswith("immortalwrt-sdk-qualcommax-ipq807x"))
  ' "$DIR/$META" >/dev/null
  IB="$(jq -er .imagebuilder "$DIR/$META")"
  SDK="$(jq -er .sdk "$DIR/$META")"
  [[ "$IB" =~ ^immortalwrt-imagebuilder-qualcommax-ipq807x[A-Za-z0-9._+~-]*[.]tar[.]zst$ ]]
  [[ "$SDK" =~ ^immortalwrt-sdk-qualcommax-ipq807x[A-Za-z0-9._+~-]*[.]tar[.]zst$ ]]
  file "$IB"; file "$SDK"
  jq -e '.schema == 2 and .target == "qualcommax/ipq807x" and
          .architecture == "aarch64_cortex-a53"' "$DIR/snapshot-lock.json" >/dev/null
  # sha256sums from full Builder covers all archives and the exact test image.
  (cd "$DIR" && sha256sum --check --status sha256sums) || {
    echo "::error::Parent Builder integrity manifest failed"; exit 1;
  }
  TAG="mx4200-builder-$(jq -er '.identity[0:24]' "$DIR/$META")"
  ASSETS=("$IB" "$SDK" "$META" "sha256sums" "snapshot-lock.json"
          "base-overlay.tar.gz" "source-commits.txt" "local-apks.txt"
          "imagebuilder-packages.txt" "official-apks.json" "local-plan.json")
  TITLE="MX4200 v1 immutable Hybrid Builder (unflashed)"
  NOTES="MX4200 v1 qualcommax/ipq807x ABI-matched ImageBuilder and SDK. Device target, snapshot lock and all checksums verified. Prerelease is a reusable build artifact, NOT a tested or automatically installable firmware."
else
  file ota.json; file mx4200v1-ota-identity.json
  for filename in "$IMAGE" "$FACTORY" "$MANIFEST" "$FW_META" snapshot-lock.json; do
    file "$filename"
  done
  jq -e --arg img "$IMAGE" --arg manifest "$MANIFEST" '
    .schema == 1 and
    .channel == "mx4200v1-immortal-ppe-nss" and
    .repository == "pzcn/openwrt-ppe-nss-ota" and
    .board == "linksys,mx4200v1" and
    .profile == "linksys_mx4200v1" and
    .group == "ipq807x-6m" and
    .target == "qualcommax/ipq807x" and
    (.tag | test("^imm-mx4200v1-[A-Za-z0-9._-]+$")) and
    (.build | type == "number" and . > 0) and
    .image == $img and .manifest == $manifest and
    (.image_sha256 | test("^[a-f0-9]{64}$")) and
    (.manifest_sha256 | test("^[a-f0-9]{64}$"))
  ' "$DIR/ota.json" >/dev/null
  jq -e '
    .metadata_version == "1.1" and
    (.compat_version | type == "string") and
    ((.supported_devices // .new_supported_devices // []) |
     index("linksys,mx4200v1") != null)
  ' "$DIR/$FW_META" >/dev/null
  jq -e --arg tag "$(jq -er .tag "$DIR/ota.json")" \
    '.schema == 1 and .device == "mx4200v1" and .tag == $tag' \
    "$DIR/mx4200v1-ota-identity.json" >/dev/null
  assert_sha "$DIR/$IMAGE" "$(jq -er .image_sha256 "$DIR/ota.json")"
  assert_sha "$DIR/$MANIFEST" "$(jq -er .manifest_sha256 "$DIR/ota.json")"
  [[ "$(stat -c %s "$DIR/$IMAGE")" == "$(jq -er .image_size "$DIR/ota.json")" ]]
  if [[ -s "$DIR/sha256sums" ]]; then
    for name in "$IMAGE" "$FACTORY" "$MANIFEST" "$FW_META" ota.json; do
      expected="$(awk -v n="$name" '$2 == n {print $1}' "$DIR/sha256sums")"
      assert_sha "$DIR/$name" "$expected"
    done
  fi
  TAG="$(jq -er .tag "$DIR/ota.json")"
  ASSETS=("$IMAGE" "$FACTORY" "$MANIFEST" "$FW_META" ota.json
          mx4200v1-ota-identity.json snapshot-lock.json)
  [[ ! -s "$DIR/sha256sums" ]] || ASSETS+=(sha256sums)
  TITLE="MX4200 v1 ImmortalWrt PPE/NSS OTA (hardware test required)"
  NOTES="MX4200 v1 only. Factory and sysupgrade images with verified metadata and SHA256, separate from Arthur's release channel. This is a prerelease; promote to stable ONLY after verified boot, LAN/WAN/Wi-Fi, retained settings, NAND dual-slot sysupgrade and recovery behavior. Automatic OTA remains off by default."
fi

if [[ "${MX_VERIFY_ONLY:-false}" == true ]]; then
  echo "MX4200 $KIND assets verified: $TAG (dry validation)"
  exit 0
fi

[[ "${GITHUB_REF_NAME:-}" == main && "${GITHUB_REF:-}" == refs/heads/main ]] || {
  echo "::error::Only main may publish MX4200 prereleases"; exit 1;
}
command -v gh >/dev/null
if gh release view "$TAG" -R "$REPO" >/dev/null 2>&1; then
  echo "::notice::Immutable MX4200 release already exists: $TAG"
  exit 0
fi
files=()
for name in "${ASSETS[@]}"; do
  file "$name"
  files+=("$DIR/$name")
done
RELEASE_UTC="$(date -u '+%Y-%m-%d %H:%M:%S UTC')"
RELEASE_CN="$(TZ=Asia/Shanghai date '+%Y-%m-%d %H:%M:%S CST (UTC+08:00)')"
NOTES="$NOTES

Published at: $RELEASE_UTC / $RELEASE_CN
GitHub created_at denotes the tag commit time; published_at is the actual release time."
release_flags=(--prerelease --latest=false)
if [[ "$KIND" == firmware && "${MX_RELEASE_STABLE:-false}" == true ]]; then
  # Only the explicitly marked stable publication from main can reach
  # device-scoped OTA. Retain all image, trailer, and SHA256 gates above.
  [[ "${GITHUB_EVENT_NAME:-}" == push &&
     "${GITHUB_REF:-}" == refs/heads/main &&
     "${GITHUB_EVENT_RELEASE_MARKER:-}" == release-official-r-20261115 ]] || {
    echo "::error::Stable MX release requires the one-time marked main push"; exit 1;
  }
  release_flags=(--latest=false)
  TITLE="MX4200 v1 ImmortalWrt PPE+NSS (stable)"
  NOTES="Official MX4200 v1 OTA firmware, CI-verified with device-specific metadata and SHA256; new hardware acceptance and recovery testing remain recommended. Automatic OTA is disabled by default."
fi
gh release create "$TAG" -R "$REPO" "${release_flags[@]}" \
  --target "${GITHUB_SHA:-$(git -C "$ROOT" rev-parse HEAD)}" \
  --title "$TITLE" --notes "$NOTES" "${files[@]}"
echo "Published MX4200 $KIND as $( [[ "$KIND" == firmware && "${MX_RELEASE_STABLE:-false}" == true ]] && echo stable || echo prerelease ) $TAG"
