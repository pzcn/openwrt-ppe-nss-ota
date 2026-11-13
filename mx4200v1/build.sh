#!/usr/bin/env bash
# Full-source TEST build for Linksys MX4200 v1, without changing Arthur builds.
# Produces factory/sysupgrade, matching ImageBuilder and SDK; no OTA/release.
set -Eeuo pipefail
trap 'echo "::error::MX4200 v1 build failed at line $LINENO: $BASH_COMMAND" >&2' ERR

ROOT="${GITHUB_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)/..}"
ROOT="$(cd "$ROOT" && pwd)"
WORK="${RUNNER_TEMP:-/tmp}/mx4200v1-source"
OUT="${MX4200V1_OUT:-$ROOT/out-mx4200v1}"
CACHE="$ROOT/.build-cache/mx4200v1"
DL="$CACHE/dl"
CCACHE="$CACHE/ccache"
GO_CACHE="$CACHE/go-build"
IMM="$WORK/immortalwrt"
PPE="$WORK/ppe-nss"
BUILDER="$WORK/base-builder"
IMMORTAL_REF="${IMMORTAL_REF:-master}"
PPE_REF="${PPE_REF:-ppe-nss}"

rm -rf "$WORK" "$OUT"
mkdir -p "$WORK" "$OUT" "$DL" "$CCACHE" "$GO_CACHE"
git clone --quiet --depth 1 --single-branch --branch "$IMMORTAL_REF" \
  https://github.com/immortalwrt/immortalwrt.git "$IMM"
git clone --quiet --depth 1 --single-branch --branch "$PPE_REF" \
  https://github.com/JuliusBairaktaris/openwrt-ppe-nss.git "$PPE"
git clone --quiet --depth 1 --single-branch --branch main \
  https://github.com/JuliusBairaktaris/Qualcommax_NSS_Builder.git "$BUILDER"

printf 'ImmortalWrt=%s\nPPE-NSS=%s\nBuilder=%s\nCustom=%s\n' \
  "$(git -C "$IMM" rev-parse HEAD)" \
  "$(git -C "$PPE" rev-parse HEAD)" \
  "$(git -C "$BUILDER" rev-parse HEAD)" \
  "$(git -C "$ROOT" rev-parse HEAD)" > "$OUT/source-commits.txt"

ln -s "$DL" "$IMM/dl"
ln -s "$CCACHE" "$IMM/.ccache"
CCACHE_DIR="$CCACHE" ccache --max-size 1600M

export IMM_SOURCE_DIR="$IMM" PPE_SOURCE_DIR="$PPE"
bash "$ROOT/mx4200v1/port-ppe-nss.sh"

cd "$IMM"
cp feeds.conf.default feeds.conf
sed -i '/^src-git video /d' feeds.conf
printf '\nsrc-git nss https://github.com/JuliusBairaktaris/nss-packages.git;ppe-nss\n' >> feeds.conf
./scripts/feeds update -a

# Match the Arthur builder's feed dependency workarounds.
rm -rf feeds/packages/net/fwknop \
       feeds/packages/sound/squeezelite \
       feeds/luci/applications/luci-app-fwknopd \
       feeds/luci/applications/luci-app-homeproxy
./scripts/feeds update -i packages
patch -p1 -d "$IMM/feeds/packages" < \
  "$BUILDER/patches/feeds/ppe-nss/packages/0001-sqm-scripts-pin-the-fork-that-carries-hw_ppe.patch"

git clone --quiet --depth 1 --filter=blob:none --sparse --branch luci-app-ppe-qos \
  https://github.com/JuliusBairaktaris/luci.git "$WORK/ppe-luci"
git -C "$WORK/ppe-luci" sparse-checkout set applications/luci-app-qca-ppe-qos
rm -rf "$IMM/feeds/luci/applications/luci-app-qca-ppe-qos"
cp -a "$WORK/ppe-luci/applications/luci-app-qca-ppe-qos" \
  "$IMM/feeds/luci/applications/"
./scripts/feeds update -i luci
./scripts/feeds install -a
test -e package/feeds/luci/luci-app-qca-ppe-qos

git clone --quiet --depth 1 --branch v1.4.0 \
  https://github.com/eamonxg/luci-theme-aurora.git package/luci-theme-aurora

# Apply only Julius' generic PPE defaults. Never copy Arthur's F2FS,
# eMMC sysupgrade platform.sh, firmware overlay, or OTA device identity.
mkdir -p files
rsync -a "$BUILDER/devices/common/files.ppe-nss/" files/

cp "$ROOT/mx4200v1/source.config" .config
while IFS= read -r line || [[ -n "$line" ]]; do
  line="${line%%#*}"
  for package in $line; do
    [[ "$package" =~ ^[a-z0-9][a-z0-9+._-]*$ ]] || {
      echo "::error::Invalid package name: $package" >&2; exit 1;
    }
    printf 'CONFIG_PACKAGE_%s=y\n' "$package" >> .config
    # Translation-only selections must also request their parent LuCI apps.
    if [[ "$package" =~ ^luci-i18n-([a-z0-9_-]+)-zh-cn$ ]]; then
      app="${BASH_REMATCH[1]}"
      if [[ "$app" != base ]]; then
        printf 'CONFIG_PACKAGE_luci-app-%s=y\n' "$app" >> .config
      fi
    fi
  done
done < "$ROOT/mx4200v1/packages.txt"

# Persist Go compilation output rather than rebuilding Go modules on every run.
if command -v go >/dev/null 2>&1; then
  GO_ROOT="$(go env GOROOT)"
  printf 'CONFIG_GOLANG_EXTERNAL_BOOTSTRAP_ROOT="%s"\n' "$GO_ROOT" >> .config
  printf '# CONFIG_GOLANG_BUILD_BOOTSTRAP is not set\n' >> .config
  printf 'CONFIG_GOLANG_BUILD_CACHE_DIR="%s"\n' "$GO_CACHE" >> .config
fi

make defconfig 2>&1 | tee "$WORK/defconfig.log"
if grep -Fq 'error: recursive dependency detected!' "$WORK/defconfig.log"; then
  echo "::error::Upstream Kconfig dependency cycle." >&2
  exit 1
fi
for option in \
  CONFIG_TARGET_qualcommax_ipq807x=y \
  CONFIG_TARGET_DEVICE_qualcommax_ipq807x_DEVICE_linksys_mx4200v1=y \
  CONFIG_KERNEL_CC_STACKPROTECTOR_REGULAR=y \
  CONFIG_ATH11K_NSS_WIFI=y \
  CONFIG_PACKAGE_kmod-nss-wifi-drv=y \
  CONFIG_PACKAGE_qca-ppe-qos=y \
  CONFIG_PACKAGE_luci-theme-aurora=y \
  CONFIG_IB=y CONFIG_IB_STANDALONE=y CONFIG_SDK=y; do
  grep -Fqx "$option" .config || {
    echo "::error::Required MX4200 v1 configuration was dropped: $option" >&2
    exit 1
  }
done
if grep -Fqx 'CONFIG_TARGET_DEVICE_qualcommax_ipq807x_DEVICE_linksys_mx4200v2=y' .config; then
  echo "::error::v2 device selected in v1-only build" >&2
  exit 1
fi
while IFS= read -r line || [[ -n "$line" ]]; do
  line="${line%%#*}"
  for package in $line; do
    grep -Fqx "CONFIG_PACKAGE_$package=y" .config || {
      echo "::error::Required MX4200 v1 package unavailable: $package" >&2
      exit 1
    }
  done
done < "$ROOT/mx4200v1/packages.txt"

make download -j"$(nproc)"
make -j"$(nproc)" || make -j1 V=s

TARGET="$IMM/bin/targets/qualcommax/ipq807x"
PREFIX="immortalwrt-qualcommax-ipq807x-linksys_mx4200v1"
for image in "$PREFIX-squashfs-factory.bin" "$PREFIX-squashfs-sysupgrade.bin"; do
  test -s "$TARGET/$image" || {
    echo "::error::Expected MX4200 v1 image missing: $image" >&2
    exit 1
  }
  cp "$TARGET/$image" "$OUT/"
done
if find "$TARGET" -maxdepth 1 -name '*linksys_mx4200v2*' | grep -q .; then
  echo "::error::v2 image unexpectedly created by v1-only build" >&2
  exit 1
fi
MANIFEST="$TARGET/$PREFIX.manifest"
if [[ ! -s "$MANIFEST" ]]; then
  MANIFEST="$TARGET/immortalwrt-qualcommax-ipq807x.manifest"
fi
test -s "$MANIFEST"
cp "$MANIFEST" "$OUT/$PREFIX.manifest"

IB="$(find "$TARGET" -maxdepth 1 -type f -name '*imagebuilder*.tar.zst' -print -quit)"
SDK="$(find "$TARGET" -maxdepth 1 -type f -name '*sdk*.tar.zst' -print -quit)"
test -n "$IB" && test -s "$IB" || {
  echo "::error::Matching ImageBuilder not produced" >&2; exit 1;
}
test -n "$SDK" && test -s "$SDK" || {
  echo "::error::Matching SDK not produced" >&2; exit 1;
}
cp "$IB" "$SDK" "$OUT/"
(
  cd "$OUT"
  sha256sum "$PREFIX-squashfs-factory.bin" "$PREFIX-squashfs-sysupgrade.bin" \
    "$PREFIX.manifest" "$(basename "$IB")" "$(basename "$SDK")" > sha256sums
  sha256sum -c sha256sums
)
echo "MX4200 v1 test artifacts: $OUT"
