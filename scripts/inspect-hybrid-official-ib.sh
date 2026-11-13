#!/usr/bin/env bash
# Inspect the exact official snapshot ImageBuilder and its apk-tools binary.
# Read-only experiment; the extracted official ImageBuilder is never republished.
set -Eeuo pipefail
ROOT="${GITHUB_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
LOCK="${1:?Pass snapshot-lock.json}"
LOCK="$(realpath "$LOCK")"
OUT="${2:-$ROOT/out-hybrid-ib-inspect}"
WORK="${RUNNER_TEMP:-/tmp}/hybrid-ib-inspect"
mkdir -p "$OUT" "$WORK"
for c in jq zstd curl tar sha256sum; do command -v "$c" >/dev/null; done
jq -e '.schema == 2 and .target == "qualcommax/ipq60xx"' "$LOCK" >/dev/null
ARCHIVE="$(jq -er '.assets.imagebuilder.filename' "$LOCK")"
SHA="$(jq -er '.assets.imagebuilder.sha256' "$LOCK")"
URL="$(jq -er '.target_url' "$LOCK")/$ARCHIVE"
[[ "$ARCHIVE" =~ ^immortalwrt-imagebuilder-qualcommax-ipq60xx[A-Za-z0-9._+~-]*[.]tar[.]zst$ ]] || exit 1
[[ "$SHA" =~ ^[a-f0-9]{64}$ ]] || exit 1
[[ "$URL" == https://downloads.immortalwrt.org/snapshots/targets/qualcommax/ipq60xx/* ]] || exit 1
ARCHIVE_PATH="$WORK/$ARCHIVE"
curl -fL --retry 3 --connect-timeout 20 --max-time 240 "$URL" -o "$ARCHIVE_PATH"
echo "$SHA  $ARCHIVE_PATH" | sha256sum -c --status
mkdir -p "$WORK/extracted"
tar -I zstd -xf "$ARCHIVE_PATH" -C "$WORK/extracted"
mapfile -t IBDIRS < <(find "$WORK/extracted" -mindepth 1 -maxdepth 1 -type d -name '*imagebuilder*')
[[ "${#IBDIRS[@]}" -eq 1 ]] || { echo "::error::Unexpected official IB layout"; exit 1; }
IB="${IBDIRS[0]}"
test -s "$IB/Makefile"

{
  echo "Official IB: $ARCHIVE"
  echo "Snapshot: $(jq -er .snapshot_version "$LOCK")"
  echo "Archive SHA256: $SHA"
  echo "Package APKs embedded: $(find "$IB/packages" -maxdepth 1 -type f -name '*.apk' | wc -l)"
  echo "ImageBuilder top-level directories:"
  find "$IB" -mindepth 1 -maxdepth 1 -type d -printf '  %f\n' | sort
  echo "Possible apk executables:"
  find "$IB" -type f -name apk -print | head -n 20
  echo "Signing keys:"
  find "$IB" -type f \( -name '*.pem' -o -name '*.pub' \) -printf '%P\n' | head -n 20
} > "$OUT/ib-layout.txt"
cat "$OUT/ib-layout.txt"

TARGET_INDEX="$(jq -er '.package_indexes.target.filename' "$LOCK")"
TARGET_INDEX_SHA="$(jq -er '.package_indexes.target.sha256' "$LOCK")"
[[ "$TARGET_INDEX" == packages/packages.adb ]] || exit 1
curl -fL --retry 3 --max-time 90 \
  "$(jq -er .target_url "$LOCK")/$TARGET_INDEX" -o "$WORK/target-packages.adb"
echo "$TARGET_INDEX_SHA  $WORK/target-packages.adb" | sha256sum -c --status

APK_BIN=""
for p in "$IB/staging_dir/host/bin/apk" "$IB/staging_dir/hostpkg/bin/apk"; do
  if [[ -x "$p" ]]; then APK_BIN="$p"; break; fi
done
if [[ -z "$APK_BIN" ]]; then
  APK_BIN="$(find "$IB" -type f -name apk -perm /111 -print -quit)"
fi
[[ -n "$APK_BIN" ]] || {
  echo "::error::Official ImageBuilder does not contain an executable apk solver"; exit 1;
}
echo "Using host APK solver: $APK_BIN"
"$APK_BIN" --version | tee "$OUT/apk-version.txt"
"$APK_BIN" --help > "$OUT/apk-help.txt" 2>&1 || true
"$APK_BIN" fetch --help > "$OUT/apk-fetch-help.txt" 2>&1 || true
"$APK_BIN" adbdump "$WORK/target-packages.adb" \
  > "$OUT/target-packages-adbdump.txt" 2>&1 || {
    echo "::warning::Official apk-tools did not accept adbdump; recorded diagnostics."
  }
head -n 70 "$OUT/target-packages-adbdump.txt"
echo "Official ImageBuilder layout inspection complete. No images modified or published."
