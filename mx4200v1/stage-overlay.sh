#!/usr/bin/env bash
# MX4200 v1 firmware overlay: shared OTA UX/backend, device-specific upgrade.
# Reuse Arthur's OTA UI and shell backend; never import eMMC upgrade hooks.
set -Eeuo pipefail
DEST="${1:?Usage: stage-overlay.sh <existing-overlay-directory>}"
[[ -d "$DEST" && "$DEST" != / ]] || { echo "Invalid MX4200 overlay: $DEST" >&2; exit 1; }
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Match Arthur's common user-facing customizations: PPE/NSS monitoring,
# LuCI appearance/language, the updated flash/OTA page and shared helper
# scripts. Apply the SAME optional-app selection as Arthur. No kernel,
# eMMC/F2FS or Linksys platform.sh is copied from here.
rsync -a "$ROOT/files/" "$DEST/"
sh "$ROOT/scripts/exclude-drcom-from-firmware.sh" "$DEST"

# The old MX-only experiment removed this updater on first boot. Never
# include its stale cleanup script in a firmware that has shared OTA enabled.
rm -f -- "$DEST/etc/uci-defaults/99-remove-ppe-update"

# Older MX-only base-overlay archives intentionally deleted these service
# files. Stage reproducible, device-local copies to support fast repacking from
# those otherwise valid Builder assets, without any kernel rebuild.
for file in etc/config/ppe-update lib/upgrade/keep.d/ppe-update; do
  install -D -m 0644 "$ROOT/mx4200v1/files/$file" "$DEST/$file"
done
for file in etc/init.d/ppe-update etc/uci-defaults/zz-ppe-update; do
  install -D -m 0755 "$ROOT/mx4200v1/files/$file" "$DEST/$file"
done
install -D -m 0755 "$ROOT/files/usr/sbin/ppe-update" "$DEST/usr/sbin/ppe-update"
install -D -m 0644 "$ROOT/files/usr/share/rpcd/acl.d/luci-app-ppe-update.json" \
  "$DEST/usr/share/rpcd/acl.d/luci-app-ppe-update.json"
install -D -m 0644 "$ROOT/files/www/luci-static/resources/view/system/flash.js" \
  "$DEST/www/luci-static/resources/view/system/flash.js"

# The native LuCI backup/flash page includes OTA; only update its static label.
sed -i 's/RE-SS-01 PPE+NSS/MX4200 v1 PPE+NSS/g' \
  "$DEST/www/luci-static/resources/view/system/flash.js"

# No duplicate Julius updater menu.
rm -f -- "$DEST/www/luci-static/resources/view/system/ppe-update.js" \
  "$DEST/usr/share/luci/menu.d/luci-app-ppe-update.json"
install -D -m 0755 "$ROOT/files/etc/uci-defaults/95-sing-box-tun-user" \
  "$DEST/etc/uci-defaults/95-sing-box-tun-user"

# Keep unattended installation OFF for MX4200 pending verified dual-slot
# recovery and config preservation. Manual OTA remains fully available.
cat > "$DEST/etc/uci-defaults/98-mx4200v1-ota-manual-default" <<'EOF'
#!/bin/sh
if uci -q show ppe-update.main >/dev/null 2>&1; then
  uci -q set ppe-update.main.auto='0'
  uci -q commit ppe-update
fi
exit 0
EOF
chmod 0755 "$DEST/etc/uci-defaults/98-mx4200v1-ota-manual-default"

# Never ship Arthur's extroot/eMMC platform code to Linksys dual-slot NAND.
[[ ! -e "$DEST/lib/upgrade/platform.sh" ]] || {
  echo "::error::MX overlay attempted to override Linksys NAND/UBI platform.sh" >&2
  exit 1
}
echo "MX4200 overlay: shared OTA service + LuCI, native Linksys NAND/UBI intact"
