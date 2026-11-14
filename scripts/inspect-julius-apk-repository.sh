#!/usr/bin/env bash
# Inspect the same-release Julius ImageBuilder's APK repository metadata.
# No packages installed and no flashable images are generated.
set -Eeuo pipefail
ROOT="${GITHUB_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
OUT="${1:-$ROOT/out-julius-swap}"
OUT="$(realpath "$OUT")"
WORK="${RUNNER_TEMP:-/tmp}/immortal-julius-swap"
REPORT="$OUT/swap-compatibility-report.json"
[[ -s "$REPORT" ]] || { echo "::error::Run FIT/rootfs inspection first"; exit 1; }
ASSET="$(jq -er .donor_prebuilt_imagebuilder "$REPORT")"
SHA="$(jq -er .donor_prebuilt_imagebuilder_sha256 "$REPORT")"
[[ "$ASSET" =~ ^imagebuilder-ipq60xx-(1g|512m)[.]tar[.]zst$ ]] || exit 1
[[ "$SHA" =~ ^[a-f0-9]{64}$ ]] || exit 1
ARCHIVE="$WORK/$ASSET"
[[ -s "$ARCHIVE" ]] || exit 1
printf '%s  %s\n' "$SHA" "$ARCHIVE" | sha256sum -c --status || exit 1
mkdir -p "$WORK/donor-ib-extracted"
echo "::group::Unpack SHA256-pinned Julius ImageBuilder"
tar --no-same-owner --no-same-permissions -I zstd \
  -xf "$ARCHIVE" -C "$WORK/donor-ib-extracted"
echo "::endgroup::"
mapfile -t DIRS < <(find "$WORK/donor-ib-extracted" -mindepth 1 -maxdepth 1 -type d -name '*imagebuilder*')
[[ "${#DIRS[@]}" -eq 1 ]] || { echo "::error::Unexpected donor IB directory"; exit 1; }
IB="${DIRS[0]}"
[[ -s "$IB/Makefile" && -d "$IB/packages" ]] || {
  echo "::error::Donor IB missing Makefile/packages"; exit 1;
}
APK="$IB/staging_dir/host/bin/apk"
[[ -x "$APK" ]] || { echo "::error::No donor native apk3 executable"; exit 1; }
"$APK" --version > "$OUT/julius-apk-version.txt"
printf 'ImageBuilder path: %s\n' "$IB" > "$OUT/julius-repo-layout.txt"
{
  echo "Host APK: $("$APK" --version)"
  echo "Prebuilt APK count: $(find "$IB/packages" -maxdepth 1 -type f -name '*.apk' | wc -l)"
  echo "Root APK index files:"
  find "$IB/packages" -maxdepth 2 -type f \
    \( -name '*.adb' -o -name '*.gz' -o -name '*.tar' \) \
    -printf '  %P (%s B)\n' | sort
  echo "ImageBuilder signing keys:"
  find "$IB" -maxdepth 3 -type f \
    \( -name '*.pem' -o -name '*.pub' \) \
    -printf '  %P\n' | sort
  echo "Package kernel and selected kmod APKs:"
  find "$IB/packages" -maxdepth 1 -type f \
    \( -name 'kernel-*.apk' -o -name 'kmod-fs-f2fs-*.apk' \
       -o -name 'kmod-nss-wifi-drv-*.apk' \
       -o -name 'kmod-wireguard-*.apk' \) \
    -printf '  %f\n' | sort
} >> "$OUT/julius-repo-layout.txt"
cat "$OUT/julius-repo-layout.txt"
DONOR_INDEX="$IB/packages/packages.adb"
if [[ -s "$DONOR_INDEX" ]]; then
  "$APK" adbdump "$DONOR_INDEX" > "$OUT/julius-packages-adbdump.txt"
  grep -E '^  - name: (kernel|kmod-fs-f2fs|kmod-wireguard|kmod-nss-wifi-drv|base-files|libc|busybox)$' \
    "$OUT/julius-packages-adbdump.txt" || true
  echo "Donor package index decoded."
else
  echo "::warning::Donor IB has APK payloads but no packages/packages.adb; a new signed local repository may be needed."
  printf '%s\n' "missing donor native package index" \
    > "$OUT/julius-packages-index-absent.txt"
fi
echo "Repository discovery complete. No APK solver approval, no firmware."
