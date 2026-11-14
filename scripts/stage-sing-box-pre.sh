#!/usr/bin/env bash
# Opt-in: place verified official AArch64 musl core directly in firmware.
set -Eeuo pipefail
ROOT="${GITHUB_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
VERSION="${SING_BOX_PRE_VERSION:-}"
[[ -n "$VERSION" ]] || exit 0
[[ "$VERSION" == "1.15.0-alpha.13" ]] || {
  echo "::error::Unsupported sing-box pre-release: $VERSION" >&2
  exit 1
}
STAGE="${1:?Firmware FILES directory required}"
OUT="${2:?Firmware artifact directory required}"
[[ -d "$STAGE" ]] || exit 1
FILE="${RUNNER_TEMP:-/tmp}/sing-box-1.15.0-alpha.13-linux-arm64-musl.tar.gz"
if [[ ! -s "$FILE" ]]; then
  curl -fL --retry 4 --retry-delay 3 --connect-timeout 20 --max-time 300 \
    "https://github.com/SagerNet/sing-box/releases/download/v1.15.0-alpha.13/sing-box-1.15.0-alpha.13-linux-arm64-musl.tar.gz" \
    -o "$FILE"
fi
python3 "$ROOT/scripts/sing_box_pre.py" --archive "$FILE" --overlay "$STAGE" \
  --metadata "$OUT/sing-box-core.json"
echo "Official sing-box 1.15.0-alpha.13 staged in firmware SquashFS"
