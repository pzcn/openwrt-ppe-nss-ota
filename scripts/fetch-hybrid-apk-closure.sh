#!/usr/bin/env bash
# Fetch one recursive userspace package closure with official IB's APK v3.
# Requires inspect-hybrid-official-ib.sh to extract that exact official IB.
set -Eeuo pipefail
ROOT="${GITHUB_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
LOCK="${1:?Expected snapshot-lock.json}"
LOCK="$(realpath "$LOCK")"
OUT="${2:?Expected output directory}"
OUT="$(mkdir -p "$OUT" && cd "$OUT" && pwd)"
shift 2
[[ "$#" -ge 1 ]] || { echo "Specify at least one userspace package"; exit 1; }
WORK="${RUNNER_TEMP:-/tmp}/hybrid-ib-inspect"
mapfile -t dirs < <(find "$WORK/extracted" -mindepth 1 -maxdepth 1 -type d -name '*imagebuilder*')
[[ "${#dirs[@]}" -eq 1 ]] || { echo "::error::Missing pinned official IB"; exit 1; }
IB="${dirs[0]}"
APK="$IB/staging_dir/host/bin/apk"
[[ -x "$APK" && -s "$IB/keys/immortalwrt-snapshots.pem" ]] || {
  echo "::error::Official apk solver or Snapshot public key not found"; exit 1;
}
[[ "$(jq -er .schema "$LOCK")" == 2 ]] || exit 1
TARGET_URL="$(jq -er .target_url "$LOCK")"
ARCH_URL="$(jq -er .architecture_url "$LOCK")"
[[ "$TARGET_URL" == "https://downloads.immortalwrt.org/snapshots/targets/qualcommax/ipq60xx" ]] || exit 1
[[ "$ARCH_URL" == "https://downloads.immortalwrt.org/snapshots/packages/aarch64_cortex-a53" ]] || exit 1
repos=(-X "$TARGET_URL/packages/packages.adb")
for feed in base packages luci routing telephony; do
  repos+=(-X "$ARCH_URL/$feed/packages.adb")
done
for pkg in "$@"; do
  [[ "$pkg" =~ ^[a-z0-9][a-z0-9+._-]*$ ]] || {
    echo "::error::Unsafe requested package name"; exit 1;
  }
  [[ "$pkg" != kernel && "$pkg" != kmod-* ]] || {
    echo "::error::Never fetch a foreign official kernel or kmod"; exit 1;
  }
  case "$pkg" in
    sqm-scripts|qca-ppe-qos|ppe-help|luci-app-qca-ppe-qos|luci-theme-aurora|luci-app-sing-box)
      echo "::error::Must build local patched package"; exit 1 ;;
  esac
done
# apk fetch does not initialize package indexes by itself. Stage a
# scratch-root cache with the official ImageBuilder public keys, run an
# explicit apk update, then fetch the complete dependency closure.
APKROOT="$OUT/apkroot"
mkdir -p "$OUT/apks" "$APKROOT/etc/apk/keys" "$APKROOT/var/cache/apk" "$APKROOT/lib/apk/db"
cp "$IB/keys/"*.pem "$APKROOT/etc/apk/keys/"
# apk3 update/fetch require an initialized database; an empty directory
# alone is insufficient. --usermode creates it as the unprivileged runner.
if ! "$APK" --root "$APKROOT" --arch aarch64_cortex-a53 \
  --repositories-file /dev/null add --initdb --usermode \
  > "$OUT/apk-initdb.log" 2>&1; then
  tail -n 100 "$OUT/apk-initdb.log" >&2
  echo "::error::Could not initialize scratch APK database"; exit 1
fi
echo "APK scratch-root database layout:"
find "$APKROOT" -maxdepth 5 -type f -printf "  %P\n" | head -n 35
common=(
  --root "$APKROOT" --arch aarch64_cortex-a53
  --keys-dir etc/apk/keys --cache-dir var/cache/apk
  --repositories-file /dev/null --timeout 75 --no-progress
  "${repos[@]}"
)
echo "::group::Native APK 3 update of pinned official repositories"
if ! "$APK" "${common[@]}" update > "$OUT/apk-update.log" 2>&1; then
  tail -n 140 "$OUT/apk-update.log" >&2
  echo "::error::Official index update failed"; exit 1
fi
tail -n 40 "$OUT/apk-update.log"
echo "::endgroup::"
echo "::group::Native APK 3 recursive dependency fetch"
if ! "$APK" "${common[@]}" \
   fetch --recursive --output "$OUT/apks" "$@" \
   > "$OUT/apk-fetch.log" 2>&1; then
  tail -n 140 "$OUT/apk-fetch.log" >&2
  echo "::error::Native package solver failed; no firmware will be published"; exit 1
fi
tail -n 40 "$OUT/apk-fetch.log"
echo "::endgroup::"
python3 "$ROOT/scripts/hybrid-verify-apk-closure.py" \
  --lock "$LOCK" --download-dir "$OUT/apks" \
  --output "$OUT/closure-manifest.json" --requested "$@"
echo "Verified recursive closure count: $(jq -er .count "$OUT/closure-manifest.json")"
echo "Test only: no custom kernel ABI or flashable Builder approved."
