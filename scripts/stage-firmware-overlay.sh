#!/bin/sh
# Firmware-only file selection. This file is NOT an ImageBuilder core input.
# Keep optional app inclusion/exclusion decisions outside the Builder ABI.
set -eu
[ "$#" -eq 1 ] || { echo "usage: $0 FIRMWARE_OVERLAY" >&2; exit 2; }
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
sh "$SCRIPT_DIR/exclude-drcom-from-firmware.sh" "$1"
