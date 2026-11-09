#!/bin/sh
# Dr.COM is optional; keep its source under files/, exclude from firmware.
set -eu
[ "$#" -eq 1 ] || { echo "usage: $0 FIRMWARE_OVERLAY" >&2; exit 2; }
OVERLAY="$1"
for entry in \
  etc/config/drcom \
  etc/init.d/drcom \
  etc/uci-defaults/97-drcom-credentials-permissions \
  etc/uci-defaults/98-drcom-clear-unused-legacy-url \
  usr/libexec/drcom-schedule \
  usr/libexec/drcom-web \
  usr/share/luci/menu.d/luci-app-drcom.json \
  usr/share/rpcd/acl.d/luci-app-drcom.json \
  usr/share/rpcd/ucode/luci.drcom \
  www/luci-static/resources/view/network/drcom-native.js
do
    rm -f "$OVERLAY/$entry"
done
