#!/usr/bin/env bash
# Shared OTA builder for MX4200 v1: same Python schema/backend as Arthur.
# prepare OVERLAY OUT IMM_SHA PPE_SHA
# metadata OUT IMM_SHA PPE_SHA
set -Eeuo pipefail
ROOT="${GITHUB_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
ACTION="${1:?prepare or metadata}"
[[ "$ACTION" == prepare || "$ACTION" == metadata ]] || exit 2
if [[ "$ACTION" == prepare ]]; then
  OVERLAY="${2:?Overlay required}"
  OUT="${3:?Output directory required}"
  IMM="${4:?ImmortalWrt commit required}"
  PPE="${5:?PPE/NSS commit required}"
else
  OUT="${2:?Output directory required}"
  IMM="${3:?ImmortalWrt commit required}"
  PPE="${4:?PPE/NSS commit required}"
fi
[[ "$IMM" =~ ^[a-f0-9]{40}$ && "$PPE" =~ ^[a-f0-9]{40}$ ]] || {
  echo "::error::OTA requires exact upstream source SHAs"; exit 1;
}
SOURCE="$(git -C "$ROOT" rev-parse HEAD)"
[[ "$SOURCE" =~ ^[a-f0-9]{40}$ ]]
IDENTITY="$OUT/mx4200v1-ota-identity.json"
PREFIX="immortalwrt-qualcommax-ipq807x-linksys_mx4200v1"

if [[ "$ACTION" == prepare ]]; then
  BUILD="${MX_OTA_BUILD:-$(date -u +%s)}"
  [[ "$BUILD" =~ ^[0-9]+$ ]] && (( BUILD > 0 )) || {
    echo "::error::MX OTA build must be positive integer"; exit 1;
  }
  TAG="imm-mx4200v1-${IMM:0:8}-${PPE:0:8}-g${SOURCE:0:8}-b$BUILD"
  mkdir -p "$OUT"
  python3 "$ROOT/scripts/immortalwrt_ota.py" prepare \
    --device mx4200v1 --overlay "$OVERLAY" --tag "$TAG" --build "$BUILD"
  [[ -s "$OVERLAY/etc/immortal-ppe-ota-release" ]]
  grep -Fq 'linksys,mx4200v1' "$OVERLAY/usr/sbin/ppe-update"
  grep -Fq 'mx4200v1-immortal-ppe-nss' "$OVERLAY/usr/sbin/ppe-update"
  # Confirm the shared OTA UI and proxy selector are present, not an obsolete label.
  grep -Fq '在线固件更新' "$OVERLAY/www/luci-static/resources/view/system/flash.js"
  grep -Fq 'GitHub 代理' "$OVERLAY/www/luci-static/resources/view/system/flash.js"
  sh -n "$OVERLAY/usr/sbin/ppe-update"
  jq -n --arg tag "$TAG" --arg imm "$IMM" --arg ppe "$PPE" \
    --arg source "$SOURCE" --argjson build "$BUILD" \
    '{schema:1,device:"mx4200v1",tag:$tag,build:$build,
      immortalwrt_commit:$imm,ppe_nss_commit:$ppe,source_commit:$source}' > "$IDENTITY"
  echo "Prepared MX4200 OTA $TAG (no release published)"
else
  [[ -s "$IDENTITY" ]]
  jq -e --arg imm "$IMM" --arg ppe "$PPE" --arg source "$SOURCE" '
    .schema == 1 and .device == "mx4200v1" and
    .immortalwrt_commit == $imm and .ppe_nss_commit == $ppe and
    .source_commit == $source
  ' "$IDENTITY" >/dev/null
  TAG="$(jq -er .tag "$IDENTITY")"
  BUILD="$(jq -er .build "$IDENTITY")"
  python3 "$ROOT/scripts/immortalwrt_ota.py" metadata \
    --device mx4200v1 --tag "$TAG" --build "$BUILD" \
    --immortal-commit "$IMM" --ppe-commit "$PPE" \
    --image "$OUT/$PREFIX-squashfs-sysupgrade.bin" \
    --manifest "$OUT/$PREFIX.manifest" \
    --source-commit "$SOURCE" \
    --sing-box-core "$OUT/sing-box-core.json" --output "$OUT/ota.json"
  jq -e --arg tag "$TAG" '.channel == "mx4200v1-immortal-ppe-nss" and
    .board == "linksys,mx4200v1" and .tag == $tag and
    .image_sha256 != "" and .manifest_sha256 != ""' "$OUT/ota.json" >/dev/null
  echo "Verified MX4200 OTA metadata $TAG (manual test artifact)"
fi
