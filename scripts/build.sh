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
MONITOR_REV=ppe-nss-native2
OTA_REV=custom-ota5
I18N_REV=zhcn-lmo1
DRCOM_REV=campus-drcom12
WORK="$RUNNER_TEMP/firmware-build"
mkdir -p "$WORK/ib" "$GITHUB_WORKSPACE/out"
TAG="$UPSTREAM_TAG"
if [[ -z "$TAG" ]]; then
  TAG="$(gh release view --repo "$UPSTREAM_REPO" --json tagName --jq '.tagName')"
fi
[[ "$TAG" == ppe-nss-* ]] || { echo "::error::Unexpected upstream tag: $TAG"; exit 1; }
# A source change must produce a distinct firmware even if upstream is unchanged.
# The same source and upstream tag still share a release on scheduled runs.
SOURCE_REV="$(git -C "$GITHUB_WORKSPACE" rev-parse --short=8 HEAD)"
[[ "$SOURCE_REV" =~ ^[0-9a-f]{8,}$ ]] || { echo "::error::Invalid source commit"; exit 1; }
RELEASE_TAG="ota-$TAG-$AURORA_TAG-$STORAGE_FIX_REV-$MONITOR_REV-$OTA_REV-$I18N_REV-$DRCOM_REV-g$SOURCE_REV"
if [[ "$GITHUB_EVENT_NAME" == workflow_dispatch ]]; then
  RELEASE_TAG="$RELEASE_TAG-$GITHUB_RUN_NUMBER"
fi
if gh release view "$RELEASE_TAG" --repo "$GITHUB_REPOSITORY" >/dev/null 2>&1; then
  echo "Already published for source $SOURCE_REV: $RELEASE_TAG"
  exit 0
fi

gh release download "$TAG" --repo "$UPSTREAM_REPO" -p "imagebuilder-$GROUP.tar.zst" -p "files-$GROUP.tar.gz" -D "$WORK"
tar -C "$WORK/ib" --strip-components=1 -xf "$WORK/imagebuilder-$GROUP.tar.zst"
mkdir -p "$WORK/ib/files"
tar -C "$WORK/ib/files" -xzf "$WORK/files-$GROUP.tar.gz"
cp -a "$GITHUB_WORKSPACE/files/." "$WORK/ib/files/"
# Add the missing custom LuCI translations as native .lmo catalogs, without
# overwriting the upstream application's JavaScript or untranslated locales.
I18N_DIR="$WORK/ib/files/usr/lib/lua/luci/i18n"
mkdir -p "$I18N_DIR"
python3 "$GITHUB_WORKSPACE/scripts/build_luci_i18n.py" \
  --input "$GITHUB_WORKSPACE/config/translations/qca-ppe-qos.zh-cn.json" \
  --output "$I18N_DIR/qca-ppe-qos.zh-cn.lmo" --min-entries 61
python3 "$GITHUB_WORKSPACE/scripts/build_luci_i18n.py" \
  --input "$GITHUB_WORKSPACE/config/translations/ppe-update.zh-cn.json" \
  --output "$I18N_DIR/ppe-update.zh-cn.lmo" --min-entries 2
test -s "$I18N_DIR/qca-ppe-qos.zh-cn.lmo"
test -s "$I18N_DIR/ppe-update.zh-cn.lmo"

# Validate Dr.COM Web portal app and its narrow RPC permissions.
DRCOM_FILES="$WORK/ib/files"
test -s "$DRCOM_FILES/etc/config/drcom"
test -s "$DRCOM_FILES/usr/libexec/drcom-web"
test -s "$DRCOM_FILES/usr/libexec/drcom-schedule"
test -s "$DRCOM_FILES/etc/init.d/drcom"
test -s "$DRCOM_FILES/usr/share/rpcd/ucode/luci.drcom"
test -s "$DRCOM_FILES/www/luci-static/resources/view/network/drcom-native.js"
chmod +x "$DRCOM_FILES/usr/libexec/drcom-web" "$DRCOM_FILES/usr/libexec/drcom-schedule" "$DRCOM_FILES/etc/init.d/drcom"
sh -n "$DRCOM_FILES/usr/libexec/drcom-web"
sh -n "$DRCOM_FILES/usr/libexec/drcom-schedule"
sh -n "$DRCOM_FILES/etc/init.d/drcom"
sh -n "$DRCOM_FILES/etc/uci-defaults/97-drcom-credentials-permissions"
sh -n "$DRCOM_FILES/etc/uci-defaults/98-drcom-clear-unused-legacy-url"
python3 -m json.tool "$DRCOM_FILES/usr/share/luci/menu.d/luci-app-drcom.json" >/dev/null
python3 -m json.tool "$DRCOM_FILES/usr/share/rpcd/acl.d/luci-app-drcom.json" >/dev/null
node --check "$DRCOM_FILES/www/luci-static/resources/view/network/drcom-native.js"
grep -Fq "return { 'luci.drcom': methods };" "$DRCOM_FILES/usr/share/rpcd/ucode/luci.drcom"
grep -Fq 'data-urlencode = "DDDDD=%s"' "$DRCOM_FILES/usr/libexec/drcom-web"
grep -Fq 'data-urlencode = "upass=%s"' "$DRCOM_FILES/usr/libexec/drcom-web"
grep -Fq "ubus call network.interface.wan status" "$DRCOM_FILES/usr/libexec/drcom-web"
grep -Fq -- '--interface "if!$WAN_DEVICE"' "$DRCOM_FILES/usr/libexec/drcom-web"
grep -Fq "nslookup -type=A" "$DRCOM_FILES/usr/libexec/drcom-web"
grep -Fq -- '--resolve "$CURL_RESOLVE"' "$DRCOM_FILES/usr/libexec/drcom-web"
grep -Fq "'class': 'cbi-map'" "$DRCOM_FILES/www/luci-static/resources/view/network/drcom-native.js"
grep -Fq "const verify = cursor();" "$DRCOM_FILES/usr/share/rpcd/ucode/luci.drcom"
grep -Fq "backend_revision: 'drcom-rpc9'" "$DRCOM_FILES/usr/share/rpcd/ucode/luci.drcom"
grep -Fq "reject: true" "$DRCOM_FILES/www/luci-static/resources/view/network/drcom-native.js"
grep -Fq "chmod('/etc/config/drcom', 0o600)" "$DRCOM_FILES/usr/share/rpcd/ucode/luci.drcom"
grep -Fq "open(filepath, 'wx', 0o600)" "$DRCOM_FILES/usr/share/rpcd/ucode/luci.drcom"
grep -Fq "option login_url ''" "$DRCOM_FILES/etc/config/drcom"
grep -Fq "option logout_url ''" "$DRCOM_FILES/etc/config/drcom"
! grep -Fq 'gate.lnu.edu.cn' "$DRCOM_FILES/etc/config/drcom"
! grep -Fq 'gate.lnu.edu.cn' "$DRCOM_FILES/usr/share/rpcd/ucode/luci.drcom"
grep -Fq '0 0 * * * /usr/libexec/drcom-web auto' "$DRCOM_FILES/usr/libexec/drcom-schedule"
grep -Fq "option auto '0'" "$DRCOM_FILES/etc/config/drcom"
grep -Fq 'save_urls:' "$DRCOM_FILES/usr/share/rpcd/ucode/luci.drcom"
grep -Fq 'set_auto:' "$DRCOM_FILES/usr/share/rpcd/ucode/luci.drcom"
chmod +x "$WORK/ib/files/etc/uci-defaults/"*
# Keep upstream /etc/ppe-release untouched for the NSS kernel package feed.
# A distinct ROM metadata file identifies ONLY this custom GitHub OTA channel.
test "$GITHUB_REPOSITORY" = 'pzcn/openwrt-ppe-nss-ota'
case "$GITHUB_RUN_NUMBER" in '' | *[!0-9]*) echo "::error::Invalid build number"; exit 1 ;; esac
cat > "$WORK/ib/files/etc/pzcn-ota-release" <<EOF
OTA_TAG='$RELEASE_TAG'
OTA_BUILD='$GITHUB_RUN_NUMBER'
OTA_CHANNEL='re-ss-01-custom'
EOF
test -s "$WORK/ib/files/usr/sbin/ppe-update"
chmod +x "$WORK/ib/files/usr/sbin/ppe-update"
sh -n "$WORK/ib/files/usr/sbin/ppe-update"
grep -Fq "RELEASE_API='https://api.github.com/repos/pzcn/openwrt-ppe-nss-ota/releases/latest'" "$WORK/ib/files/usr/sbin/ppe-update"
grep -Fq 'PZCN_RELEASE' "$WORK/ib/files/usr/sbin/ppe-update"
grep -Fq 'sysupgrade -T' "$WORK/ib/files/usr/sbin/ppe-update"
python3 -m json.tool "$WORK/ib/files/usr/share/rpcd/acl.d/luci-app-ppe-update.json" >/dev/null
grep -Fq "otaScheduleWidget()" "$WORK/ib/files/www/luci-static/resources/view/system/flash.js"
test -s "$WORK/ib/files/www/luci-static/resources/view/system/flash.js"
node --check "$WORK/ib/files/www/luci-static/resources/view/system/flash.js"
test ! -e "$WORK/ib/files/usr/share/luci/menu.d/luci-app-ppe-update.json"
grep -Fq "在线固件更新" "$WORK/ib/files/www/luci-static/resources/view/system/flash.js"
grep -Fq "handleSysupgradeConfirm" "$WORK/ib/files/www/luci-static/resources/view/system/flash.js"
grep -Fq "handleBackup(ev)" "$WORK/ib/files/www/luci-static/resources/view/system/flash.js"
grep -Fq 'if [ "$policy" = auto ]; then' "$WORK/ib/files/usr/sbin/ppe-update"
grep -Fq 'sysupgrade -T "$WORK/$IMAGE"' "$WORK/ib/files/usr/sbin/ppe-update"


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
grep -qx 'luci-i18n-sqm-zh-cn' "$GITHUB_WORKSPACE/config/add.txt"
grep -qx 'luci-i18n-bcp38-zh-cn' "$GITHUB_WORKSPACE/config/add.txt"
grep -qx 'curl' "$GITHUB_WORKSPACE/config/add.txt"
grep -qx 'jsonfilter' "$GITHUB_WORKSPACE/config/add.txt"

# Validate the custom LuCI status dashboard before publishing a firmware.
MONITOR_FILES="$WORK/ib/files"
test -s "$MONITOR_FILES/www/luci-static/resources/view/status/ppe-nss-monitor-native.js"
test -s "$MONITOR_FILES/usr/share/rpcd/ucode/luci.ppe-nss-monitor"
python3 -m json.tool "$MONITOR_FILES/usr/share/luci/menu.d/luci-app-ppe-nss-monitor.json" >/dev/null
python3 -m json.tool "$MONITOR_FILES/usr/share/rpcd/acl.d/luci-app-ppe-nss-monitor.json" >/dev/null
node --check "$MONITOR_FILES/www/luci-static/resources/view/status/ppe-nss-monitor-native.js"
grep -Fq "return { 'luci.ppe-nss-monitor': methods };" "$MONITOR_FILES/usr/share/rpcd/ucode/luci.ppe-nss-monitor"
grep -Fq '"get_status"' "$MONITOR_FILES/usr/share/rpcd/acl.d/luci-app-ppe-nss-monitor.json"

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
for p in luci-theme-aurora luci-app-filemanager luci-app-ttyd luci-app-nlbwmon luci-app-statistics luci-app-wifihistory luci-app-irqbalance luci-app-lldpd luci-app-pbr luci-i18n-base-zh-cn luci-i18n-sqm-zh-cn luci-i18n-bcp38-zh-cn luci-proto-wireguard kmod-wireguard kmod-nss-wifi-drv block-mount kmod-fs-ext4 e2fsprogs kmod-fs-f2fs f2fs-tools mkf2fs f2fsck curl jsonfilter; do
  grep -q "^$p " "$MANIFEST" || { echo "::error::Missing in manifest: $p"; exit 1; }
done
python3 "$GITHUB_WORKSPACE/scripts/write_ota_metadata.py" \
  --tag "$RELEASE_TAG" --build "$GITHUB_RUN_NUMBER" \
  --upstream "$TAG" --group "$GROUP" --profile "$PROFILE" \
  --image "$GITHUB_WORKSPACE/out/$IMAGE" \
  --manifest "$GITHUB_WORKSPACE/out/$MANIFEST" \
  --output "$GITHUB_WORKSPACE/out/ota.json"
python3 -m json.tool "$GITHUB_WORKSPACE/out/ota.json" >/dev/null
grep -Fq "$RELEASE_TAG" "$GITHUB_WORKSPACE/out/ota.json"
cat > "$WORK/notes.md" <<EOF
# RE-SS-01 PPE+NSS 固件

**上游版本：** $TAG
**Aurora 主题：** $AURORA_TAG

## 本版内容

- **状态 → PPE / NSS 硬件加速：** 连接统计、NSS 状态和内核诊断
- **网络 → 校园网认证：** 单一网关地址、账号密码、登录注销及每日 00:00 自动认证
- **系统 → 备份 / 升级 → 在线固件更新：** 检查版本、在线安装及自动更新设置
- **界面文案：** 使用 LuCI 原生风格，统一菜单和帮助文字

包含常用 LuCI 应用、简体中文语言包、PPE QoS 汉化、WireGuard 和 Aurora 主题。

## 存储

- p18：SquashFS + F2FS rootfs_data 可写层
- p27：ext4 数据分区，挂载到 /mnt/storage

**升级提示：** 建议先备份配置及重要文件。首次初始化时请确认 p18 数据状态。

## 版本标识

- 源代码提交：$SOURCE_REV
- 监控：$MONITOR_REV
- 校园网认证：$DRCOM_REV
- 在线更新：$OTA_REV
- 中文语言包：$I18N_REV
- 存储：$STORAGE_FIX_REV
EOF

gh release create "$RELEASE_TAG" --repo "$GITHUB_REPOSITORY" --title "RE-SS-01 PPE+NSS 固件 ($TAG)" --notes-file "$WORK/notes.md" --latest "$IMAGE" sha256sums aurora-sha256.txt selected-packages.txt "$MANIFEST" ota.json
