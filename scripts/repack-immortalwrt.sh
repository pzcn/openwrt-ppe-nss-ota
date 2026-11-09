#!/usr/bin/env bash
# Repackage a firmware from the ABI-matched standalone ImmortalWrt NSS ImageBuilder.
set -Eeuo pipefail
trap 'echo "::error::ImmortalWrt ImageBuilder repack failed at line $LINENO: $BASH_COMMAND" >&2' ERR

ROOT="${GITHUB_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
WORK="${RUNNER_TEMP:-/tmp}/immortal-image-repack"
OUT="${IMMORTAL_OUT_DIR:-$ROOT/out-immortal}"
PUBLISH_RELEASE="${PUBLISH_RELEASE:-false}"
REPO="${GITHUB_REPOSITORY:-pzcn/openwrt-ppe-nss-ota}"
META="${BUILDER_META:?Set BUILDER_META to the downloaded builder-metadata.json}"
ARCHIVE="${BUILDER_ARCHIVE:?Set BUILDER_ARCHIVE to the matching ImageBuilder .tar.zst}"
BASE_OVERLAY="${BASE_OVERLAY:?Set BASE_OVERLAY to the matching base-overlay.tar.gz}"
PACKAGES_FILE="${BUILDER_PACKAGES:?Set BUILDER_PACKAGES to the matching imagebuilder-packages.txt}"
mkdir -p "$WORK" "$OUT"

python3 "$ROOT/scripts/immortalwrt_builder.py" verify \
  --metadata "$META" --archive "$ARCHIVE" --overlay "$BASE_OVERLAY" \
  --packages "$PACKAGES_FILE"
IMM_SHA="$(jq -er '.immortalwrt_commit' "$META")"
PPE_SHA="$(jq -er '.ppe_nss_commit' "$META")"
BUILDER_TAG="$(jq -er '.tag' "$META")"
SOURCE_REV="$(git -C "$ROOT" rev-parse --short=8 HEAD)"
BUILD_NUMBER="$(date -u +%s)"
TAG="imm-ppe-nss-${IMM_SHA:0:8}-${PPE_SHA:0:8}-g${SOURCE_REV}-b$BUILD_NUMBER"
IMAGE="immortalwrt-qualcommax-ipq60xx-jdcloud_re-ss-01-squashfs-sysupgrade.bin"
MANIFEST="immortalwrt-qualcommax-ipq60xx-jdcloud_re-ss-01.manifest"

mkdir -p "$WORK/builder" "$WORK/overlay" "$WORK/images"
tar -I zstd -xf "$ARCHIVE" -C "$WORK/builder"
mapfile -t IB_DIRS < <(find "$WORK/builder" -mindepth 1 -maxdepth 1 -type d -name '*imagebuilder*')
[[ "${#IB_DIRS[@]}" -eq 1 ]] || { echo "::error::Unexpected ImageBuilder archive layout" >&2; exit 1; }
IB="${IB_DIRS[0]}"
test -f "$IB/Makefile"

# Combine the PPE base files with user customizations and fresh OTA metadata.
tar -xzf "$BASE_OVERLAY" -C "$WORK/overlay"
rsync -a "$ROOT/files/" "$WORK/overlay/"
rm -f "$WORK/overlay/www/luci-static/resources/view/system/ppe-update.js" \
      "$WORK/overlay/usr/share/luci/menu.d/luci-app-ppe-update.json" \
      "$WORK/overlay/etc/uci-defaults/94-custom-world" \
      "$WORK/overlay/etc/ppe-release" \
      "$WORK/overlay/etc/config/fstab" \
      "$WORK/overlay/etc/uci-defaults/96-migrate-legacy-extroot"
# Exclude the optional Dr.COM app from matched Builder and user files.
sh "$ROOT/scripts/exclude-drcom-from-firmware.sh" "$WORK/overlay"
# Refuse an old Builder without the matching eMMC config-preservation hook.
test -s "$WORK/overlay/lib/upgrade/platform.sh"
grep -Fq 'platform_copy_config()' "$WORK/overlay/lib/upgrade/platform.sh"
grep -Fq 'emmc_copy_config' "$WORK/overlay/lib/upgrade/platform.sh"
I18N_DIR="$WORK/overlay/usr/lib/lua/luci/i18n"
mkdir -p "$I18N_DIR"
python3 "$ROOT/scripts/build_luci_i18n.py" \
  --input "$ROOT/config/translations/qca-ppe-qos.zh-cn.json" \
  --output "$I18N_DIR/qca-ppe-qos.zh-cn.lmo" --min-entries 61
python3 "$ROOT/scripts/build_luci_i18n.py" \
  --input "$ROOT/config/translations/ppe-update.zh-cn.json" \
  --output "$I18N_DIR/ppe-update.zh-cn.lmo" --min-entries 2
python3 "$ROOT/scripts/immortalwrt_ota.py" prepare \
  --overlay "$WORK/overlay" --tag "$TAG" --build "$BUILD_NUMBER"
for script in \
  "$WORK/overlay/usr/sbin/ppe-update" \
  "$WORK/overlay/etc/init.d/ppe-update"; do
  sh -n "$script"
done
node --check "$WORK/overlay/www/luci-static/resources/view/system/flash.js"

# No official snapshot kmods: only packages compiled for the identical ABI.
PACKAGES="$(tr '\n' ' ' < "$PACKAGES_FILE")"
test -n "$PACKAGES"
# Newly requested plugins can be added if the matching Builder has their APKs.
# Missing APKs fail in ImageBuilder, never silently drop user packages.
while IFS= read -r entry || [[ -n "$entry" ]]; do
  entry="${entry%%#*}"
  for pkg in $entry; do
    [[ "$pkg" =~ ^[a-z0-9][a-z0-9+._-]*$ ]] || {
      echo "::error::Invalid requested package: $pkg" >&2
      exit 1
    }
    if [[ " $PACKAGES " != *" $pkg "* ]]; then
      PACKAGES+=" $pkg"
    fi
  done
done < "$ROOT/config/add.txt"
# Preserve the source firmware's package exclusions, including ip-tiny.
while IFS= read -r entry || [[ -n "$entry" ]]; do
  entry="${entry%%#*}"
  for pkg in $entry; do
    [[ "$pkg" =~ ^[a-z0-9][a-z0-9+._-]*$ ]] || {
      echo "::error::Invalid excluded package: $pkg" >&2
      exit 1
    }
    PACKAGES+=" -$pkg"
  done
done < "$ROOT/config/remove.txt"
(
  cd "$IB"
  make image PROFILE=jdcloud_re-ss-01 PACKAGES="$PACKAGES" \
    FILES="$WORK/overlay" BIN_DIR="$WORK/images"
)

IMAGE_PATH="$(find "$WORK/images" -type f -name "$IMAGE" -print -quit)"
test -n "$IMAGE_PATH" && test -s "$IMAGE_PATH"
MANIFEST_PATH="$(find "$WORK/images" -type f -name "$MANIFEST" -print -quit)"
if [[ -z "$MANIFEST_PATH" ]]; then
  MANIFEST_PATH="$(find "$WORK/images" -type f -name '*ipq60xx.manifest' -print -quit)"
fi
test -n "$MANIFEST_PATH" && test -s "$MANIFEST_PATH"

cp "$IMAGE_PATH" "$OUT/$IMAGE"
cp "$MANIFEST_PATH" "$OUT/$MANIFEST"
sha256sum "$OUT/$IMAGE" "$OUT/$MANIFEST" > "$OUT/sha256sums"
python3 "$ROOT/scripts/immortalwrt_ota.py" metadata \
  --tag "$TAG" --build "$BUILD_NUMBER" \
  --immortal-commit "$IMM_SHA" --ppe-commit "$PPE_SHA" \
  --image "$OUT/$IMAGE" --manifest "$OUT/$MANIFEST" \
  --builder-tag "$BUILDER_TAG" --source-commit "$(git -C "$ROOT" rev-parse HEAD)" \
  --output "$OUT/ota.json"
cp "$META" "$OUT/builder-metadata.json"

if [[ "$PUBLISH_RELEASE" == true ]]; then
  [[ "$REPO" == pzcn/openwrt-ppe-nss-ota ]] || {
    echo "::error::Refusing to publish from an unexpected repository" >&2
    exit 1
  }
  cat > "$OUT/release-notes.md" <<EOF
# ImmortalWrt + PPE/NSS customized RE-SS-01

- ImmortalWrt source: $IMM_SHA
- Julius PPE/NSS source: $PPE_SHA
- ABI-matched reusable ImageBuilder: $BUILDER_TAG
- Customized source: $SOURCE_REV
- Image: $IMAGE
- F2FS overlay (p18) and separate ext4 storage (p27).

All packages come from the matching standalone builder.
The ImmortalWrt OTA channel remains independent of OpenWrt.
EOF
  gh release create "$TAG" --repo "$REPO" --latest=false \
    --title "RE-SS-01 ImmortalWrt PPE+NSS ($BUILD_NUMBER)" \
    --notes-file "$OUT/release-notes.md" \
    "$OUT/$IMAGE" "$OUT/$MANIFEST" "$OUT/ota.json" \
    "$OUT/sha256sums" "$OUT/builder-metadata.json"
fi
