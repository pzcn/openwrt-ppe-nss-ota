#!/usr/bin/env bash
# Publish the immutable, verified WMA301 artifact using the shared firmware
# workflow's release permissions. No recompilation or firmware modification.
set -Eeuo pipefail
REPO="pzcn/openwrt-ppe-nss-ota"
SOURCE_RUN="44028887027"
SOURCE_SHA="e01cd20e6df0f4818623538bf67d98e412dccf7a"
IMAGE="immortalwrt-mediatek-filogic-tplink_wma301-v2-squashfs-sysupgrade.itb"
MANIFEST="immortalwrt-mediatek-filogic-tplink_wma301-v2.manifest"

[[ "$GITHUB_REPOSITORY" == "$REPO" && "$GITHUB_REF" == refs/heads/main ]] || {
  echo "::error::WMA301 stable release requires the main repository and branch"
  exit 1
}
gh api "repos/$REPO/actions/runs/$SOURCE_RUN" >"$RUNNER_TEMP/wma-run.json"
jq -e --arg sha "$SOURCE_SHA" '
  .status == "completed" and .conclusion == "success" and
  .head_branch == "main" and .head_sha == $sha and
  .name == "WMA301 | Official ImageBuilder + unified OTA"
' "$RUNNER_TEMP/wma-run.json" >/dev/null

mkdir -p "$RUNNER_TEMP/wma-artifact"
gh run download "$SOURCE_RUN" -R "$REPO" --name WMA301_VERIFIED_UNIFIED_OTA \
  --dir "$RUNNER_TEMP/wma-artifact"
cd "$RUNNER_TEMP/wma-artifact"
[[ -s "dist/SHA256SUMS" && -s "dist/manifest.json" &&
   -s "official-provenance.json" && -s "out-wma301-ota/sha256sums" ]]
(cd dist && sha256sum -c SHA256SUMS)
cd out-wma301-ota
sha256sum -c sha256sums
[[ -s "$IMAGE" && -s "$MANIFEST" ]]
TAG="$(jq -er '.tag' ota.json)"
[[ "$TAG" =~ ^imm-wma301-SNAPSHOT-r[0-9]+-[0-9]{12}$ ]] || {
  echo "::error::Unexpected WMA301 OTA tag: $TAG"; exit 1;
}
jq -e --arg source "$SOURCE_SHA" --arg tag "$TAG" \
    --arg image "$IMAGE" --arg manifest "$MANIFEST" '
  .schema == 1 and .repository == "pzcn/openwrt-ppe-nss-ota" and
  .channel == "wma301-immortal-filogic" and .tag == $tag and
  .source_commit == $source and .board == "tplink,wma301-v2" and
  .profile == "tplink_wma301-v2" and .target == "mediatek/filogic" and
  .group == "filogic-mt7981-single-ubi" and
  .layout == "oem-bl2-bl31-custom-bl33-single-ubi-v1" and
  .image == $image and .manifest == $manifest
' ota.json >/dev/null
jq -e --arg sha "$SOURCE_SHA" '
  .build == "official-imagebuilder-fast" and
  .device == "tplink,wma301-v2" and .local_sha == $sha and
  .output.fit_hashes == "pass" and
  .output.mode == "squashfs-persistent" and
  .output.dts.compatible == "tplink,wma301-v2" and
  .output.dts.factory_info_protected == true
' manifest.json >/dev/null
cmp manifest.json ../dist/manifest.json
cmp official-provenance.json ../official-provenance.json
jq -e '
  .installed_theme.name == "luci-theme-aurora" and
  .installed_theme.version == "1.4.0-r1" and
  .installed_theme.install_method == "imagebuilder-local-native-apk"
' manifest.json >/dev/null
test -s "luci-theme-aurora-1.4.0-r1.apk"
printf '%s  %s\n' "$(jq -r '.installed_theme.sha256' manifest.json)" \
  luci-theme-aurora-1.4.0-r1.apk | sha256sum -c -
for package in autocore cpufreq luci-app-cpufreq luci-i18n-cpufreq-zh-cn default-settings-chn; do
  grep -Eq "^$package - [^[:space:]]+" "$MANIFEST" || {
    echo "::error::Missing WMA301 package: $package"; exit 1;
  }
done
if grep -Eiq '^(sing-box|tailscale|luci-app-tailscale-community|luci-app-ddns-go|luci-app-sing-box|luci-app-ppe-qos|luci-app-ppe-nss-monitor|kmod-qca-nss[^[:space:]]*)[[:space:]]' "$MANIFEST"; then
  echo "::error::Forbidden WMA301 package in firmware"
  exit 1
fi
if gh release view "$TAG" -R "$REPO" >/dev/null 2>&1; then
  echo "WMA301 stable release already exists: $TAG"
  exit 0
fi
cat >"$RUNNER_TEMP/wma301-release-notes.md" <<'NOTES'
WMA301 v2.0 / MT7981 · ImmortalWrt master Linux 6.18

**Official stable OTA Release (not prerelease).**
Updated LuCI OTA supports real-time transfer progress, speed and installation
stages, diagnostic errors and automatic reboot/reconnect guidance.
Manual upgrades and optional scheduled automatic updates use the same backend
as Arthur and MX4200 (automatic update is off by default).

Verified by CI: FIT, DTS, SHA256, package manifest, upstream provenance
and single-UBI device/layout identity. **Physical hardware validation is not
implied by CI.** This firmware is only for WMA301 v2.0 that already uses the
121 MiB single-UBI four-volume layout. It is not compatible with stock A/B
partition layouts or WMA301 v2.1. Preserve recovery and U-Boot before upgrading.

Includes native Aurora, autocore temperature reporting, cpufreq and
default-settings-chn. Excludes sing-box, Tailscale, DDNS-Go and Qualcomm
NSS/PPE-specific components.
NOTES
gh release create "$TAG" -R "$REPO" --target "$SOURCE_SHA" --latest=false \
  --title "WMA301 v2.0 | ImmortalWrt 6.18 ($TAG)" \
  --notes-file "$RUNNER_TEMP/wma301-release-notes.md" \
  "$IMAGE" "$MANIFEST" ota.json sha256sums manifest.json \
  official-provenance.json luci-theme-aurora-1.4.0-r1.apk
gh release view "$TAG" -R "$REPO" --json tagName,isPrerelease,assets \
  --jq '{tag:.tagName,prerelease:.isPrerelease,assets:(.assets|map(.name))}'
