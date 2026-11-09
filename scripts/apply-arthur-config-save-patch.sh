#!/usr/bin/env bash
# Enable sysupgrade configuration backup for JDCloud Arthur RE-SS-01 only.
# This does not alter rootfs_data / overlay persistence after ordinary reboot.
set -Eeuo pipefail
OVERLAY="${1:?Pass the FILES overlay directory}"
REF=4765b657625ec5bbda74b44400465fe043802b30
EXPECTED_BLOB=e7bacdf1122768126537e59ba727d98e855fb794
SRC="https://raw.githubusercontent.com/immortalwrt/immortalwrt/$REF/target/linux/qualcommax/ipq60xx/base-files/lib/upgrade/platform.sh"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
curl --fail --location --silent --show-error --retry 3 --connect-timeout 15 --max-time 90 "$SRC" -o "$TMP"
ACTUAL_BLOB="$(git hash-object "$TMP")"
[[ "$ACTUAL_BLOB" == "$EXPECTED_BLOB" ]] || {
  echo "::error::Official ImmortalWrt platform.sh differs from the published Builder's pinned source" >&2
  exit 1
}
! grep -Fq 'platform_copy_config()' "$TMP" || {
  echo "::error::Unexpected upstream platform_copy_config() already exists" >&2
  exit 1
}
OUTPUT="$OVERLAY/lib/upgrade/platform.sh"
install -D -m 0644 "$TMP" "$OUTPUT"
cat >> "$OUTPUT" <<'PATCH'

# Preserve the sysupgrade backup on the new eMMC rootfs partition on Arthur.
# Only jdcloud,re-ss-01 is in scope for the A/B comparison.
platform_copy_config() {
	case "$(board_name)" in
	jdcloud,re-ss-01)
		emmc_copy_config
		;;
	esac
}
PATCH
sh -n "$OUTPUT"
grep -Fq 'emmc_copy_config' "$OUTPUT"
echo "Applied the pinned Arthur sysupgrade configuration-preservation patch."
