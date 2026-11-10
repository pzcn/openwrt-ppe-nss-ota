#!/usr/bin/env bash
# Reissue a HomeProxy-free ImageBuilder + SDK from a verified release.
# There is deliberately no make download or make package/compile here.
set -Eeuo pipefail
trap 'echo "::error::Incremental Builder failed at line $LINENO: $BASH_COMMAND" >&2' ERR
ROOT="${GITHUB_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
INPUT="${1:?Pass directory containing verified parent Builder release assets}"
OUT="${2:-$ROOT/out-incremental-builder}"
WORK="${RUNNER_TEMP:-/tmp}/immortal-builder-incremental"
mkdir -p "$WORK/ib" "$WORK/sdk" "$OUT"

META="$INPUT/builder-metadata.json"
SDK_META="$INPUT/sdk-metadata.json"
FEED_LOCK="$INPUT/sdk-feeds.lock.json"
OVERLAY="$INPUT/base-overlay.tar.gz"
PACKAGES="$INPUT/imagebuilder-packages.txt"
IB_ARCHIVE="$INPUT/$(jq -er '.archive' "$META")"
SDK_ARCHIVE="$INPUT/$(jq -er '.archive' "$SDK_META")"
for file in "$META" "$SDK_META" "$FEED_LOCK" "$OVERLAY" "$PACKAGES" "$IB_ARCHIVE" "$SDK_ARCHIVE"; do
  test -s "$file" || { echo "::error::Missing Builder asset: $file" >&2; exit 1; }
done
python3 "$ROOT/scripts/immortalwrt_builder.py" verify \
  --metadata "$META" --archive "$IB_ARCHIVE" \
  --overlay "$OVERLAY" --packages "$PACKAGES"
python3 "$ROOT/scripts/immortalwrt_sdk.py" verify \
  --metadata "$SDK_META" --builder-metadata "$META" \
  --archive "$SDK_ARCHIVE" --feed-lock "$FEED_LOCK"

tar -I zstd -xf "$IB_ARCHIVE" -C "$WORK/ib"
tar -I zstd -xf "$SDK_ARCHIVE" -C "$WORK/sdk"
mapfile -t ibs < <(find "$WORK/ib" -mindepth 1 -maxdepth 1 -type d -name '*imagebuilder*')
mapfile -t sdks < <(find "$WORK/sdk" -mindepth 1 -maxdepth 1 -type d -name '*sdk*')
[[ "${#ibs[@]}" -eq 1 && "${#sdks[@]}" -eq 1 ]] || {
  echo "::error::Unexpected parent ImageBuilder/SDK layout" >&2; exit 1;
}
IB="${ibs[0]}"
SDK="${sdks[0]}"
test -s "$IB/Makefile" && test -s "$SDK/Makefile"

# Use the parent metadata and exactly matching SDK APK cache BEFORE modifying
# the archives. Previously compiled sing-box LuCI is cached by that identity.
bash "$ROOT/scripts/rebuild-missing-apks.sh" "$IB" "$META"

python3 "$ROOT/scripts/immortalwrt_derive.py" sanitize \
  --imagebuilder "$IB" --sdk "$SDK" \
  --parent-packages "$PACKAGES" --add "$ROOT/config/add.txt" \
  --output-packages "$OUT/imagebuilder-packages.txt"

IB_OUT="$OUT/$(basename "$IB_ARCHIVE")"
SDK_OUT="$OUT/$(basename "$SDK_ARCHIVE")"
tar -I 'zstd -T0 -3' -cf "$IB_OUT" -C "$WORK/ib" "$(basename "$IB")"
tar -I 'zstd -T0 -3' -cf "$SDK_OUT" -C "$WORK/sdk" "$(basename "$SDK")"
cp "$OVERLAY" "$OUT/base-overlay.tar.gz"
for extra in source-commits.txt official-toolchain-status.txt; do
  if [[ -s "$INPUT/$extra" ]]; then cp "$INPUT/$extra" "$OUT/$extra"; fi
done

python3 "$ROOT/scripts/immortalwrt_derive.py" metadata \
  --parent-builder-metadata "$META" \
  --parent-builder-archive "$IB_ARCHIVE" \
  --parent-sdk-metadata "$SDK_META" \
  --parent-sdk-archive "$SDK_ARCHIVE" \
  --parent-feed-lock "$FEED_LOCK" \
  --archive "$IB_OUT" --sdk-archive "$SDK_OUT" \
  --overlay "$OUT/base-overlay.tar.gz" \
  --parent-packages "$PACKAGES" \
  --packages "$OUT/imagebuilder-packages.txt" \
  --builder-metadata "$OUT/builder-metadata.json" \
  --sdk-metadata "$OUT/sdk-metadata.json" \
  --feed-lock "$OUT/sdk-feeds.lock.json"

# Also verify tar contents, not just its extracted source tree.
for archive in "$IB_OUT" "$SDK_OUT"; do
  if tar -I zstd -tf "$archive" |
    grep -Eiq '(^|/)(luci-app-homeproxy|luci-i18n-homeproxy-zh-cn)(/|$|-[^/]+[.]apk$)'; then
    echo "::error::HomeProxy package remains in derived archive: $archive" >&2
    exit 1
  fi
done
echo "New ABI-matched Builder: $(jq -er '.tag' "$OUT/builder-metadata.json")"
echo "No kernel, NSS or compiler object was rebuilt."
