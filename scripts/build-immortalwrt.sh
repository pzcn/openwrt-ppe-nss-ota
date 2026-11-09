#!/usr/bin/env bash
# Full-source build: ImmortalWrt + OpenWrt PPE/NSS Wi-Fi port + RE-SS-01 customizations.
set -Eeuo pipefail
trap 'echo "::error::ImmortalWrt build failed at line $LINENO: $BASH_COMMAND" >&2' ERR

ROOT="${GITHUB_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
WORK="${RUNNER_TEMP:-/tmp}/immortal-ppe-nss"
OUT="$ROOT/out-immortal"
IMM="$WORK/immortalwrt"
PPE="$WORK/ppe-nss"
BUILDER="$WORK/ppe-builder"
PUBLISH_RELEASE="${PUBLISH_RELEASE:-false}"
IMMORTAL_REF="${IMMORTAL_REF:-master}"
PPE_REF="${PPE_REF:-ppe-nss}"
RUN_NUMBER="${GITHUB_RUN_NUMBER:-1}"
ATTEMPT="${GITHUB_RUN_ATTEMPT:-1}"
mkdir -p "$WORK" "$OUT"

for n in "$RUN_NUMBER" "$ATTEMPT"; do
  [[ "$n" =~ ^[0-9]+$ ]] || { echo "Invalid run number" >&2; exit 1; }
done
(( ATTEMPT < 10 )) || { echo "Unexpected run attempt" >&2; exit 1; }
BUILD_NUMBER=$(( RUN_NUMBER * 10 + ATTEMPT ))
SOURCE_REV="$(git -C "$ROOT" rev-parse --short=8 HEAD)"

clone() {
  local url="$1" ref="$2" dest="$3"
  git clone --quiet --depth 1 --single-branch --branch "$ref" "$url" "$dest"
}
clone https://github.com/immortalwrt/immortalwrt.git "$IMMORTAL_REF" "$IMM"
clone https://github.com/JuliusBairaktaris/openwrt-ppe-nss.git "$PPE_REF" "$PPE"
clone https://github.com/JuliusBairaktaris/Qualcommax_NSS_Builder.git main "$BUILDER"
IMM_SHA="$(git -C "$IMM" rev-parse HEAD)"
PPE_SHA="$(git -C "$PPE" rev-parse HEAD)"
TAG="imm-ppe-nss-${IMM_SHA:0:8}-${PPE_SHA:0:8}-g$SOURCE_REV-b$RUN_NUMBER-a$ATTEMPT"
printf 'ImmortalWrt=%s\nPPE/NSS=%s\nCustom=%s\n' "$IMM_SHA" "$PPE_SHA" "$SOURCE_REV" | tee "$OUT/source-commits.txt"

export IMM_SOURCE_DIR="$IMM" PPE_SOURCE_DIR="$PPE"
bash "$ROOT/scripts/port-ppe-nss-to-immortalwrt.sh"

# Keep official ImmortalWrt packages/LuCI, adding only the PPE/NSS firmware
# feed and Julius' QoS LuCI application.
cd "$IMM"
cp feeds.conf.default feeds.conf
# The upstream video feed is unnecessary for this router image and currently
# introduces unrelated Qt5 Kconfig recursive dependency errors.
sed -i '/^src-git video /d' feeds.conf
printf '\nsrc-git nss https://github.com/JuliusBairaktaris/nss-packages.git;ppe-nss\n' >> feeds.conf
./scripts/feeds update -a
# Upstream currently includes unrelated packages with circular Kconfig chains.
# Neither is used by this router; exclude only these optional package definitions
# before re-indexing feeds, retaining official sources for all required packages.
# fwknopd <-> luci-app-fwknopd / FWKNOPD_GPG
# squeezelite-custom <-> SQUEEZELITE_WMA_ALAC
rm -rf "$IMM/feeds/packages/net/fwknop" \
       "$IMM/feeds/packages/sound/squeezelite" \
       "$IMM/feeds/luci/applications/luci-app-fwknopd"
./scripts/feeds update -i packages

# Use the same pinned hardware SQM backend as the existing PPE release.
patch -p1 -d "$IMM/feeds/packages" < \
  "$BUILDER/patches/feeds/ppe-nss/packages/0001-sqm-scripts-pin-the-fork-that-carries-hw_ppe.patch"

git clone --quiet --depth 1 --filter=blob:none --sparse --branch luci-app-ppe-qos \
  https://github.com/JuliusBairaktaris/luci.git "$WORK/ppe-luci"
git -C "$WORK/ppe-luci" sparse-checkout set applications/luci-app-qca-ppe-qos
rm -rf "$IMM/feeds/luci/applications/luci-app-qca-ppe-qos"
cp -a "$WORK/ppe-luci/applications/luci-app-qca-ppe-qos" "$IMM/feeds/luci/applications/"
# The first feeds update indexed LuCI before this extra application existed.
# Rebuild its local index, otherwise feeds install -a silently skips QoS LuCI.
./scripts/feeds update -i luci
grep -Fq 'luci-app-qca-ppe-qos' "$IMM/feeds/luci.index" || {
  echo "::error::PPE QoS LuCI application missing from feed index" >&2
  exit 1
}
./scripts/feeds install -a
test -e "$IMM/package/feeds/luci/luci-app-qca-ppe-qos" || {
  echo "::error::PPE QoS LuCI application was not installed from its feed" >&2
  exit 1
}

# Build pinned sources, not foreign-ABI release APKs.
clone https://github.com/eamonxg/luci-theme-aurora.git v1.4.0 "$IMM/package/luci-theme-aurora"
clone https://github.com/lauyv/luci-app-sing-box.git v0.4.7 "$IMM/package/luci-app-sing-box"
(
  cd "$IMM/package/luci-app-sing-box"
  command -v pnpm >/dev/null || npm install -g pnpm@10
  bash dashboard/build.sh
)

# Preserve the PPE/NSS QoS + system upgrade init pieces and the original
# custom LuCI, Dr.COM, Tailscale, sing-box, WOL, and storage layout.
mkdir -p "$IMM/files"
rsync -a "$BUILDER/devices/common/files.ppe-nss/" "$IMM/files/"
rsync -a "$ROOT/files/" "$IMM/files/"
rm -f "$IMM/files/www/luci-static/resources/view/system/ppe-update.js" \
      "$IMM/files/usr/share/luci/menu.d/luci-app-ppe-update.json" \
      "$IMM/files/etc/uci-defaults/94-custom-world" \
      "$IMM/files/etc/ppe-release"

# Translate the exact existing custom catalogs as native LuCI .lmo files.
I18N_DIR="$IMM/files/usr/lib/lua/luci/i18n"
mkdir -p "$I18N_DIR"
python3 "$ROOT/scripts/build_luci_i18n.py" \
  --input "$ROOT/config/translations/qca-ppe-qos.zh-cn.json" \
  --output "$I18N_DIR/qca-ppe-qos.zh-cn.lmo" --min-entries 61
python3 "$ROOT/scripts/build_luci_i18n.py" \
  --input "$ROOT/config/translations/ppe-update.zh-cn.json" \
  --output "$I18N_DIR/ppe-update.zh-cn.lmo" --min-entries 2
python3 "$ROOT/scripts/immortalwrt_ota.py" prepare \
  --overlay "$IMM/files" --tag "$TAG" --build "$BUILD_NUMBER"
for s in "$IMM/files/usr/sbin/ppe-update" \
         "$IMM/files/etc/init.d/ppe-update" \
         "$IMM/files/etc/init.d/drcom" \
         "$IMM/files/usr/libexec/drcom-web" \
         "$IMM/files/usr/libexec/drcom-schedule"; do
  sh -n "$s"
done
node --check "$IMM/files/www/luci-static/resources/view/system/flash.js"
node --check "$IMM/files/www/luci-static/resources/view/network/drcom-native.js"

# All user-requested packages are taken from ImmortalWrt's own source feeds.
# Kernel packages are compiled with this exact kernel; no OpenWrt snapshot APKs.
cp "$ROOT/config/immortalwrt-re-ss-01.config" "$IMM/.config"
append_packages() {
  local file="$1" value="$2" name line
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    for name in $line; do
      [[ "$name" =~ ^[a-z0-9][a-z0-9+._-]*$ ]] || { echo "Bad package: $name" >&2; exit 1; }
      printf 'CONFIG_PACKAGE_%s=%s\n' "$name" "$value" >> "$IMM/.config"
    done
  done < "$file"
}
append_packages "$ROOT/config/add.txt" y
append_packages "$ROOT/config/remove.txt" n

# LuCI translation packages do not automatically enable their application
# parents under Kconfig. Request the corresponding LuCI apps before
# defconfig, otherwise existing translations like bcp38-zh-cn are silently
# dropped even though the apps and their Chinese catalogs exist.
# 'base' is special: it belongs to luci-base rather than luci-app-base.
while IFS= read -r line || [[ -n "$line" ]]; do
  line="${line%%#*}"
  for p in $line; do
    if [[ "$p" =~ ^luci-i18n-([a-z0-9_-]+)-zh-cn$ ]]; then
      app="${BASH_REMATCH[1]}"
      if [[ "$app" != base ]]; then
        printf 'CONFIG_PACKAGE_luci-app-%s=y\n' "$app" >> "$IMM/.config"
      fi
    fi
  done
done < "$ROOT/config/add.txt"

# Kconfig can report recursive-dependency errors yet return status 0.
# Keep the diagnostic and fail instead of continuing with partial .config.
make defconfig 2>&1 | tee "$WORK/defconfig.log"
if grep -Fq 'error: recursive dependency detected!' "$WORK/defconfig.log"; then
  echo "::error::ImmortalWrt upstream feeds contain a Kconfig dependency cycle" >&2
  exit 1
fi

# Kconfig silently omits unavailable packages. Refuse a deceptively
# successful image if a user-requested package or NSS option was dropped.
missing=()
verify_package() {
  local p="$1"
  if ! grep -Fqx "CONFIG_PACKAGE_$p=y" "$IMM/.config"; then
    echo "::error::Required package is unavailable: $p" >&2
    missing+=("$p")
  fi
}
while IFS= read -r line || [[ -n "$line" ]]; do
  line="${line%%#*}"
  for p in $line; do verify_package "$p"; done
done < "$ROOT/config/add.txt"
for p in kmod-nss-wifi-drv luci-theme-aurora luci-app-sing-box \
  qca-ppe-qos luci-app-qca-ppe-qos jq kmod-fs-f2fs; do
  verify_package "$p"
done
if (( ${#missing[@]} )); then
  printf 'Missing required packages (%d): %s\n' "${#missing[@]}" "${missing[*]}" >&2
  exit 1
fi
grep -Fqx 'CONFIG_ATH11K_NSS_WIFI=y' "$IMM/.config"
grep -Fqx 'CONFIG_TARGET_DEVICE_qualcommax_ipq60xx_DEVICE_jdcloud_re-ss-01=y' "$IMM/.config"

make download -j"$(nproc)"
make -j"$(nproc)" || make -j1 V=s

# The image's name is part of the independent OTA safety contract.
TARGET="$IMM/bin/targets/qualcommax/ipq60xx"
IMAGE="immortalwrt-qualcommax-ipq60xx-jdcloud_re-ss-01-squashfs-sysupgrade.bin"
MANIFEST="immortalwrt-qualcommax-ipq60xx-jdcloud_re-ss-01.manifest"
test -s "$TARGET/$IMAGE"
# Full-source builds may emit a board-wide manifest even for one device.
# Publish the single-device manifest under the stable per-device OTA name.
if [[ -s "$TARGET/$MANIFEST" ]]; then
  SOURCE_MANIFEST="$TARGET/$MANIFEST"
elif [[ -s "$TARGET/immortalwrt-qualcommax-ipq60xx.manifest" ]]; then
  SOURCE_MANIFEST="$TARGET/immortalwrt-qualcommax-ipq60xx.manifest"
else
  echo "::error::No target package manifest was produced" >&2
  exit 1
fi
cp "$TARGET/$IMAGE" "$OUT/"
cp "$SOURCE_MANIFEST" "$OUT/$MANIFEST"
cp "$IMM/.config" "$OUT/immortalwrt.config"
(
  cd "$OUT"
  sha256sum "$IMAGE" "$MANIFEST" > sha256sums
)
python3 "$ROOT/scripts/immortalwrt_ota.py" metadata \
  --tag "$TAG" --build "$BUILD_NUMBER" --immortal-commit "$IMM_SHA" \
  --ppe-commit "$PPE_SHA" --image "$OUT/$IMAGE" --manifest "$OUT/$MANIFEST" \
  --output "$OUT/ota.json"

# Publish only after a successful full compilation, manifest, and OTA metadata.
# Pull requests produce inspectable Actions artifacts but never update releases.
if [[ "$PUBLISH_RELEASE" == true ]]; then
  [[ "${GITHUB_REPOSITORY:-}" == pzcn/openwrt-ppe-nss-ota ]] || {
    echo "This release channel is reserved for the canonical repository" >&2; exit 1;
  }
  cat > "$OUT/release-notes.md" <<EOF
# ImmortalWrt + PPE/NSS + RE-SS-01 customizations

- ImmortalWrt master: $IMM_SHA
- PPE/NSS source: $PPE_SHA
- Customized config: $SOURCE_REV
- Board: JDCloud RE-SS-01 (ipq60xx 512 MiB profile; 1 GiB hardware supported)
- Packages: Dr.COM, F2FS/ext4 storage, PPE monitor/QoS, OTA, WireGuard,
  Tailscale, sing-box, Aurora, WOL and LuCI applications.
- Uses the independent \`$TAG\` channel and does not replace OpenWrt Releases/latest.

Experimental full-source build: verify wired PPE, Wi-Fi NSS, storage, and
sysupgrade on the device before enabling unattended OTA.
EOF
  gh release create "$TAG" --repo "$GITHUB_REPOSITORY" --latest=false \
    --title "RE-SS-01 ImmortalWrt PPE+NSS ($BUILD_NUMBER)" \
    --notes-file "$OUT/release-notes.md" \
    "$OUT/$IMAGE" "$OUT/$MANIFEST" "$OUT/ota.json" \
    "$OUT/sha256sums" "$OUT/source-commits.txt" "$OUT/immortalwrt.config"
fi
