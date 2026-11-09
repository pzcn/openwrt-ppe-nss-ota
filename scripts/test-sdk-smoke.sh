#!/usr/bin/env bash
# Compile one trivial target APK inside the *published* SDK staging layout.
# This validates not just tarball contents but external-toolchain usability.
set -Eeuo pipefail
ARCHIVE="${1:?Expected SDK tar.zst archive}"
TEST_ROOT="${2:?Expected temporary SDK smoke workspace}"
test -s "$ARCHIVE"
mkdir -p "$TEST_ROOT"
tar -I zstd -xf "$ARCHIVE" -C "$TEST_ROOT"
mapfile -t sdks < <(find "$TEST_ROOT" -mindepth 1 -maxdepth 1 -type d -name '*sdk*')
[[ "${#sdks[@]}" -eq 1 ]] || { echo "::error::Unexpected SDK archive layout" >&2; exit 1; }
SDK="${sdks[0]}"
test -f "$SDK/Makefile"

PACKAGE_DIR="$SDK/package/imm-sdk-smoke"
mkdir -p "$PACKAGE_DIR/src"
cat > "$PACKAGE_DIR/src/smoke.c" <<'C'
#include <stdio.h>
int main(void) { puts("sdk toolchain ok"); return 0; }
C
cat > "$PACKAGE_DIR/Makefile" <<'MAKE'
include $(TOPDIR)/rules.mk

PKG_NAME:=imm-sdk-smoke
PKG_VERSION:=1.0.0
PKG_RELEASE:=1
PKG_LICENSE:=MIT
include $(INCLUDE_DIR)/package.mk

define Package/imm-sdk-smoke
  SECTION:=utils
  CATEGORY:=Utilities
  TITLE:=SDK toolchain smoke test
endef

define Build/Prepare
	mkdir -p $(PKG_BUILD_DIR)
	cp ./src/smoke.c $(PKG_BUILD_DIR)/smoke.c
endef

define Build/Compile
	$(TARGET_CC) $(TARGET_CFLAGS) -o $(PKG_BUILD_DIR)/imm-sdk-smoke $(PKG_BUILD_DIR)/smoke.c $(TARGET_LDFLAGS)
endef

define Package/imm-sdk-smoke/install
	$(INSTALL_DIR) $(1)/usr/bin
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/imm-sdk-smoke $(1)/usr/bin/imm-sdk-smoke
endef

$(eval $(call BuildPackage,imm-sdk-smoke))
MAKE

(
  cd "$SDK"
  export GIT_AUTHOR_NAME="ImmortalWrt SDK CI"
  export GIT_AUTHOR_EMAIL="ci@example.invalid"
  export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME"
  export GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"
  printf 'CONFIG_PACKAGE_imm-sdk-smoke=y\n' >> .config
  make defconfig
  grep -Fxq 'CONFIG_PACKAGE_imm-sdk-smoke=y' .config || {
    echo "::error::SDK failed to select smoke package" >&2
    exit 1
  }
  make -j"$(nproc)" package/imm-sdk-smoke/compile V=s
)
APK="$(find "$SDK/bin" -type f -name 'imm-sdk-smoke-*.apk' -print -quit)"
test -n "$APK" && test -s "$APK" || {
  echo "::error::SDK did not produce a valid APK with its bundled toolchain" >&2
  exit 1
}
BINARY="$(find "$SDK/build_dir" -type f -name 'imm-sdk-smoke' -print -quit)"
if [[ -n "$BINARY" ]] && command -v file >/dev/null 2>&1; then
  file "$BINARY" | grep -Eiq 'ARM aarch64|ARM64' || {
    echo "::error::SDK compiler produced a non-AArch64 test binary" >&2
    exit 1
  }
fi
echo "PASS matched SDK compiled a tiny AArch64 APK: $(basename "$APK")"
