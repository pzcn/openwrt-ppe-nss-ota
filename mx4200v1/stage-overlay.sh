#!/usr/bin/env bash
# Strip Julius' ppe-update feature from MX4200 v1 only.
set -Eeuo pipefail
DEST="${1:?Usage: stage-overlay.sh <existing-overlay-directory>}"
[[ -d "$DEST" && "$DEST" != / ]] || { echo "Invalid MX4200 overlay: $DEST" >&2; exit 1; }
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
for path in \
  etc/config/ppe-update \
  etc/init.d/ppe-update \
  etc/uci-defaults/zz-ppe-update \
  lib/upgrade/keep.d/ppe-update \
  usr/sbin/ppe-update \
  usr/share/luci/menu.d/luci-app-ppe-update.json \
  usr/share/rpcd/acl.d/luci-app-ppe-update.json \
  www/luci-static/resources/view/system/ppe-update.js; do
  rm -f -- "$DEST/$path"
  [[ ! -e "$DEST/$path" ]] || { echo "Unable to exclude $path" >&2; exit 1; }
done
install -D -m 0755 "$ROOT/mx4200v1/files/etc/uci-defaults/99-remove-ppe-update" \
  "$DEST/etc/uci-defaults/99-remove-ppe-update"
install -D -m 0755 "$ROOT/files/etc/uci-defaults/95-sing-box-tun-user" \
  "$DEST/etc/uci-defaults/95-sing-box-tun-user"
echo "MX4200 overlay: no PPE update UI/service; sing-box defaults staged"
