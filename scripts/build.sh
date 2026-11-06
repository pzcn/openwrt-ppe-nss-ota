#!/usr/bin/env bash
set -euo pipefail
UPSTREAM_REPO=JuliusBairaktaris/Qualcommax_NSS_Builder
# Upstream currently publishes jdcloud_re-ss-01 only in this group.
# The ipq60xx-1g group does not contain this device profile.
GROUP=ipq60xx-512m
PROFILE=jdcloud_re-ss-01
AURORA_TAG=v1.4.0
AURORA_APK=luci-theme-aurora-1.4.0-r20260920.apk
STORAGE_FIX_REV=f2fsrootfsdata1
WORK="$RUNNER_TEMP/firmware-build"
mkdir -p "$WORK/ib" "$GITHUB_WORKSPACE/out"
TAG="$UPSTREAM_TAG"
if [[ -z "$TAG" ]]; then
  TAG="$(gh release view --repo "$UPSTREAM_REPO" --json tagName --jq '.tagName')"
fi
[[ "$TAG" == ppe-nss-* ]] || { echo "::error::Unexpected upstream tag: $TAG"; exit 1; }
RELEASE_TAG="ota-$TAG-$AURORA_TAG-$STORAGE_FIX_REV"
if [[ "$GITHUB_EVENT_NAME" == workflow_dispatch ]]; then
  RELEASE_TAG="$RELEASE_TAG-$GITHUB_RUN_NUMBER"
elif gh release view "$RELEASE_TAG" --repo "$GITHUB_REPOSITORY" >/dev/null 2>&1; then
  echo "Already published: $RELEASE_TAG"
  exit 0
fi

gh release download "$TAG" --repo "$UPSTREAM_REPO" -p "imagebuilder-$GROUP.tar.zst" -p "files-$GROUP.tar.gz" -D "$WORK"
tar -C "$WORK/ib" --strip-components=1 -xf "$WORK/imagebuilder-$GROUP.tar.zst"
mkdir -p "$WORK/ib/files"
tar -C "$WORK/ib/files" -xzf "$WORK/files-$GROUP.tar.gz"
cp -a "$GITHUB_WORKSPACE/files/." "$WORK/ib/files/"
chmod +x "$WORK/ib/files/etc/uci-defaults/"*

# Leave rootfs_data to stock fstools; p27 must be a separate data filesystem.
FSTAB="$WORK/ib/files/etc/config/fstab"
test -s "$FSTAB"
grep -Fq "option device '/dev/mmcblk0p27'" "$FSTAB"
grep -Fq "option target '/mnt/storage'" "$FSTAB"
grep -Fq "option fstype 'ext4'" "$FSTAB"
if grep -Eq "option[[:space:]]+target[[:space:]]+['\"]/(overlay)?['\"]" "$FSTAB"; then
  echo "::error::The ROM fstab must not select extroot"
  exit 1
fi
sh -n "$WORK/ib/files/etc/uci-defaults/96-migrate-legacy-extroot"
grep -qx 'kmod-fs-f2fs' "$GITHUB_WORKSPACE/config/add.txt"
grep -qx 'f2fs-tools' "$GITHUB_WORKSPACE/config/add.txt"

URL="https://github.com/eamonxg/luci-theme-aurora/releases/download/$AURORA_TAG/$AURORA_APK"
curl -fL --retry 3 --connect-timeout 20 "$URL" -o "$WORK/$AURORA_APK"
test -s "$WORK/$AURORA_APK"
sha256sum "$WORK/$AURORA_APK" > "$GITHUB_WORKSPACE/out/aurora-sha256.txt"
cp "$WORK/$AURORA_APK" "$WORK/ib/packages/"

IB="$WORK/ib"
sed -i 's/^CONFIG_IB_STANDALONE=y$/# CONFIG_IB_STANDALONE is not set/' "$IB/.config"
arch="$(sed -n 's/^CONFIG_TARGET_ARCH_PACKAGES="\([^"]*\)"/\1/p' "$IB/.config")"
board="$(sed -n 's/^CONFIG_TARGET_BOARD="\([^"]*\)"/\1/p' "$IB/.config")"
subtarget="$(sed -n 's/^CONFIG_TARGET_SUBTARGET="\([^"]*\)"/\1/p' "$IB/.config")"
test -n "$arch" && test -n "$board" && test -n "$subtarget"
for feed in base packages luci routing telephony video; do
  echo "@snapshot https://downloads.openwrt.org/snapshots/packages/$arch/$feed/packages.adb" >> "$IB/repositories"
done
echo "@snapshot https://downloads.openwrt.org/snapshots/targets/$board/$subtarget/packages/packages.adb" >> "$IB/repositories"

# Allow the known, explicitly downloaded local third-party APK during assembly.
# No trust key is installed on the target device.
sed -i 's/--cache-dir $(DL_DIR)/--allow-untrusted --cache-dir $(DL_DIR)/' "$IB/Makefile"
grep -q -- '--allow-untrusted --cache-dir' "$IB/Makefile"

python3 "$GITHUB_WORKSPACE/scripts/resolve_packages.py" --tag "$TAG" --group "$GROUP" --profile "$PROFILE" > "$WORK/packages.txt"
PACKAGES="$(cat "$WORK/packages.txt")"
cd "$IB"
make image PROFILE="$PROFILE" PACKAGES="$PACKAGES" FILES=files EXTRA_IMAGE_NAME=pzcn BIN_DIR="$GITHUB_WORKSPACE/out" 2>&1 | tee "$WORK/build.log"

cd "$GITHUB_WORKSPACE/out"
mapfile -t imgs < <(find . -maxdepth 1 -name '*-squashfs-sysupgrade.bin' -printf '%f\n')
test 1 -eq "$(find . -maxdepth 1 -name '*-squashfs-sysupgrade.bin' -printf '%f\n' | wc -l)"
IMAGE="$(find . -maxdepth 1 -name '*-squashfs-sysupgrade.bin' -printf '%f\n' | head -n 1)"
test -n "$IMAGE"
sha256sum "$IMAGE" > sha256sums
cp "$WORK/packages.txt" selected-packages.txt
MANIFEST="$(find . -maxdepth 1 -name '*.manifest' -printf '%f\n' | head -n 1)"
test -n "$MANIFEST"
for p in luci-theme-aurora luci-app-filemanager luci-app-ttyd luci-app-nlbwmon luci-app-statistics luci-app-wifihistory luci-app-irqbalance luci-app-lldpd luci-app-pbr luci-i18n-base-zh-cn luci-proto-wireguard kmod-wireguard kmod-nss-wifi-drv block-mount kmod-fs-ext4 e2fsprogs kmod-fs-f2fs f2fs-tools mkf2fs f2fsck; do
  grep -q "^$p " "$MANIFEST" || { echo "::error::Missing in manifest: $p"; exit 1; }
done
cat > "$WORK/notes.md" <<EOF
JDCloud RE-SS-01 customized PPE+NSS firmware.

Upstream release: $TAG
Aurora release: $AURORA_TAG
Storage fix revision: $STORAGE_FIX_REV

The standard OpenWrt rootfs_data overlay is used on the active rootfs partition's
space after SquashFS. Matching kmod-fs-f2fs, f2fs-tools and mkf2fs are included
for fstools to initialize that large space as F2FS on first boot, if unformatted.
CAUTION: first-boot initialization may format the unused tail of the active
rootfs partition (reported as p18); it does NOT format p27.
The original 64 GB eMMC's p27 ext4 partition is independent data storage,
mounted as /mnt/storage. No GPT or U-Boot modifications.
Legacy p27 extroot fstab settings are converted to /mnt/storage by a
first-boot UCI default when config files are retained across sysupgrade.

Uses upstream Linux/PPE/NSS/ath11k binaries, with selected LuCI apps and Chinese language packs.
Only sysupgrade, not factory/U-Boot. No Wi-Fi credentials are embedded.
The bundled ppe-update still targets upstream releases; upgrade this custom image from this repository.
EOF
gh release create "$RELEASE_TAG" --repo "$GITHUB_REPOSITORY" --title "RE-SS-01 PPE+NSS Aurora + F2FS rootfs_data ($TAG)" --notes-file "$WORK/notes.md" --latest "$IMAGE" sha256sums aurora-sha256.txt selected-packages.txt "$MANIFEST"
