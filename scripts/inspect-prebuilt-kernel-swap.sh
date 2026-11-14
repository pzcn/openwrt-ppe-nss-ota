#!/usr/bin/env bash
# Read-only experiment: FIT kernel from Julius, official ImmortalWrt RE-SS-01
# userland. No sysupgrade is built or published from this inspection.
set -Eeuo pipefail
trap 'echo "::error::Kernel swap inspection failed at line '"$LINENO"'" >&2' ERR

ROOT="${GITHUB_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
LOCK="${1:?Expected official snapshot-lock.json}"
OUT="${2:-$ROOT/out-julius-swap}"
LOCK="$(realpath "$LOCK")"
mkdir -p "$OUT"
OUT="$(realpath "$OUT")"
WORK="${RUNNER_TEMP:-/tmp}/immortal-julius-swap"
mkdir -p "$WORK"

OFFICIAL_ROOT="https://downloads.immortalwrt.org/snapshots/targets/qualcommax/ipq60xx"
JULIUS_TAG="ppe-nss-20261107T141109Z-42380319235"
JULIUS_URL="https://github.com/JuliusBairaktaris/Qualcommax_NSS_Builder/releases/download/$JULIUS_TAG"
OFFICIAL_FILE="immortalwrt-qualcommax-ipq60xx-jdcloud_re-ss-01-squashfs-sysupgrade.bin"
JULIUS_FILE="openwrt-qualcommax-ipq60xx-jdcloud_re-ss-01-squashfs-sysupgrade.bin"

for cmd in curl jq python3 sha256sum unsquashfs dumpimage; do
  command -v "$cmd" >/dev/null || { echo "::error::Missing $cmd"; exit 1; }
done
jq -e --arg url "$OFFICIAL_ROOT" \
  '.schema == 2 and .target == "qualcommax/ipq60xx" and .target_url == $url' \
  "$LOCK" >/dev/null

download() {
  local url="$1" output="$2"
  echo "Fetching: $url"
  curl --fail --location --retry 3 --retry-delay 3 \
    --connect-timeout 20 --max-time 240 --silent --show-error \
    "$url" -o "$output"
  [[ -s "$output" ]] || { echo "::error::Empty asset: $url"; exit 1; }
}
indexed_sha() {
  local index="$1" filename="$2"
  awk -v want="$filename" '
    NF == 2 {
      name=$2
      sub(/^\*/, "", name)
      if (name == want) {
        if ($1 !~ /^[0-9a-f]+$/ || length($1) != 64) exit 2
        print $1
      }
    }' "$index"
}
verify_file() {
  local file="$1" sha="$2"
  [[ "$sha" =~ ^[a-f0-9]{64}$ ]] || { echo "::error::Missing SHA256: $file"; exit 1; }
  printf '%s  %s\n' "$sha" "$file" | sha256sum -c --status ||
    { echo "::error::Checksum failed: $file"; exit 1; }
}

# Target SHA256 index is already pinned by the Snapshot resolver.
download "$OFFICIAL_ROOT/sha256sums" "$WORK/immortalwrt-sha256sums"
EXPECTED="$(jq -er '.target_checksums_sha256' "$LOCK")"
verify_file "$WORK/immortalwrt-sha256sums" "$EXPECTED"
IMM_SHA="$(indexed_sha "$WORK/immortalwrt-sha256sums" "$OFFICIAL_FILE")"
download "$OFFICIAL_ROOT/$OFFICIAL_FILE" "$WORK/$OFFICIAL_FILE"
verify_file "$WORK/$OFFICIAL_FILE" "$IMM_SHA"

# Julius publishes separate 1 GiB and 512 MiB configs. Resolve the variant
# from the checksum manifest that actually contains the RE-SS-01 firmware.
JULIUS_SHA=""
JULIUS_PROFILE=""
for profile in 1g 512m; do
  index="$WORK/julius-$profile-sha256sums"
  download "$JULIUS_URL/sha256sums-ipq60xx-$profile.txt" "$index"
  digest="$(indexed_sha "$index" "$JULIUS_FILE")"
  if [[ -n "$digest" ]]; then
    if [[ -n "$JULIUS_SHA" && "$JULIUS_SHA" != "$digest" ]]; then
      echo "::error::Ambiguous Julius RE-SS-01 hashes across variants"; exit 1
    fi
    JULIUS_SHA="$digest"
    JULIUS_PROFILE="$profile"
  fi
done
[[ -n "$JULIUS_SHA" ]] || {
  echo "::error::No RE-SS-01 checksum in Julius 1g or 512m manifests"; exit 1;
}
download "$JULIUS_URL/$JULIUS_FILE" "$WORK/$JULIUS_FILE"
verify_file "$WORK/$JULIUS_FILE" "$JULIUS_SHA"

python3 "$ROOT/scripts/probe-prebuilt-kernel-swap.py" \
  --immortalwrt "$WORK/$OFFICIAL_FILE" \
  --julius "$WORK/$JULIUS_FILE" \
  --extract-dir "$WORK/extracted" \
  --output "$OUT/image-layout.json"

for name in immortalwrt julius; do
  dumpimage -l "$WORK/extracted/$name.fit" > "$OUT/$name-fit.txt"
  unsquashfs -s "$WORK/extracted/$name.squashfs" > "$OUT/$name-squashfs.txt"
  grep -Fq 'config@cp03-c2' "$OUT/$name-fit.txt" || {
    echo "::error::$name FIT missing RE-SS-01 config@cp03-c2 DTB"; exit 1;
  }
  # Extract only the files needed for this comparison. Full OpenWrt
  # rootfs contains /dev/console character devices, which an unprivileged
  # GitHub runner cannot recreate; extracting those is unnecessary here.
  unsquashfs -no-progress -no-xattrs -d "$WORK/$name-rootfs" \
    "$WORK/extracted/$name.squashfs" \
    lib/modules etc/openwrt_release > "$OUT/$name-unpack.log"
  test -d "$WORK/$name-rootfs/lib/modules"
  find "$WORK/$name-rootfs/lib/modules" -mindepth 1 -maxdepth 1 -type d \
    -printf '%f\n' | sort > "$OUT/$name-module-versions.txt"
  find "$WORK/$name-rootfs/lib/modules" -type f \
    \( -name '*.ko' -o -name '*.ko.gz' -o -name '*.ko.zst' \) \
    -printf '%P\n' | sort > "$OUT/$name-modules.txt"
  if [[ -f "$WORK/$name-rootfs/etc/openwrt_release" ]]; then
    cp "$WORK/$name-rootfs/etc/openwrt_release" "$OUT/$name-openwrt_release.txt"
  fi
  echo "$name module versions:"
  cat "$OUT/$name-module-versions.txt"
  echo "$name module count: $(wc -l < "$OUT/$name-modules.txt")"
done

IMM_KVERS="$(paste -sd, "$OUT/immortalwrt-module-versions.txt")"
JULIUS_KVERS="$(paste -sd, "$OUT/julius-module-versions.txt")"
IMM_MODULE_COUNT="$(wc -l < "$OUT/immortalwrt-modules.txt")"
JULIUS_MODULE_COUNT="$(wc -l < "$OUT/julius-modules.txt")"
F2FS_DONOR="$(grep -Ec '(^|/)f2fs\.ko(\.|$)' "$OUT/julius-modules.txt" || true)"
WIREGUARD_DONOR="$(grep -Ec '(^|/)wireguard\.ko(\.|$)' "$OUT/julius-modules.txt" || true)"
NSS_DONOR="$(grep -Ec '(^|/)nss.wifi.drv\.ko(\.|$)|(^|/)nss-wifi-drv\.ko(\.|$)' "$OUT/julius-modules.txt" || true)"
jq --arg release "$JULIUS_TAG" \
   --arg memory_profile "$JULIUS_PROFILE" \
   --arg immortalwrt_sha "$IMM_SHA" \
   --arg julius_sha "$JULIUS_SHA" \
   --arg immortalwrt_kversions "$IMM_KVERS" \
   --arg julius_kversions "$JULIUS_KVERS" \
   --argjson immortalwrt_modules "$IMM_MODULE_COUNT" \
   --argjson julius_modules "$JULIUS_MODULE_COUNT" \
   --argjson donor_f2fs "$F2FS_DONOR" \
   --argjson donor_wireguard "$WIREGUARD_DONOR" \
   --argjson donor_nss "$NSS_DONOR" \
  '. + {
    source_release:$release,
    donor_memory_profile:$memory_profile,
    official_firmware_sha256:$immortalwrt_sha,
    donor_firmware_sha256:$julius_sha,
    official_kernel_module_directories:$immortalwrt_kversions,
    donor_kernel_module_directories:$julius_kversions,
    official_module_file_count:$immortalwrt_modules,
    donor_module_file_count:$julius_modules,
    donor_f2fs_module_found:($donor_f2fs>0),
    donor_wireguard_module_found:($donor_wireguard>0),
    donor_nss_wifi_module_found:($donor_nss>0),
    must_replace_official_modules:true,
    immortalwrt_rootfs_retained:true,
    ready_to_flash:false,
    publishable:false
  }' "$OUT/image-layout.json" > "$OUT/swap-compatibility-report.json"

echo "::notice::RE-SS-01 FIT/rootfs inspection complete (no firmware produced)"
jq '{same_layout,julius_kernel_fits_target_partition,
     official_kernel_module_directories,donor_kernel_module_directories,
     official_module_file_count,donor_module_file_count,
     donor_memory_profile,donor_f2fs_module_found,donor_nss_wifi_module_found,
     ready_to_flash}' "$OUT/swap-compatibility-report.json"
# The donor firmware only includes its default modules; investigate the
# matching *precompiled* ImageBuilder before declaring F2FS unavailable.
# This archive belongs to the same published donor kernel version/variant.
JULIUS_INDEX="$WORK/julius-$JULIUS_PROFILE-sha256sums"
JULIUS_IB="imagebuilder-ipq60xx-$JULIUS_PROFILE.tar.zst"
JULIUS_CONFIG="config-ipq60xx-$JULIUS_PROFILE.buildinfo"
# The per-profile sha256sums file covers firmware images, not the
# config/IB attachments. These exact SHA256 values are pinned from the
# published GitHub release asset digests, not invented from the manifest.
case "$JULIUS_PROFILE" in
  512m)
    IB_SHA="c2eebb7a7fc37c49843347bab75db758b8f0bd50c0c9aaa9e2af7f44452c412b"
    CONFIG_SHA="5859a5c79fbd14a638f41e520384de9c24bfca6a4ea3bc0c0988aad0ae9a5308"
    ;;
  1g)
    IB_SHA="7786d30f7957d6656ec560aa892d8e68e112412a6907339bbe0c6db53cd5ba1d"
    CONFIG_SHA="e7e2d61e68ed666d7cae4700a9ab5da953323fa71bf422e1709eae6ef5f1fa95"
    ;;
  *) echo "::error::Unexpected memory profile"; exit 1 ;;
esac
download "$JULIUS_URL/$JULIUS_CONFIG" "$WORK/$JULIUS_CONFIG"
verify_file "$WORK/$JULIUS_CONFIG" "$CONFIG_SHA"
grep -Ei '(^# )?CONFIG_.*(F2FS|WIREGUARD|NSS_WIFI|ATH11K_NSS)' \
  "$WORK/$JULIUS_CONFIG" > "$OUT/julius-kernel-config-relevant.txt" || true
download "$JULIUS_URL/$JULIUS_IB" "$WORK/$JULIUS_IB"
verify_file "$WORK/$JULIUS_IB" "$IB_SHA"
tar -I zstd -tf "$WORK/$JULIUS_IB" \
  > "$OUT/julius-imagebuilder-file-list.txt"
grep -Ei 'kmod-fs-f2fs|f2fs\.ko|kmod-nss-wifi|nss-wifi-drv|kmod-wireguard' \
  "$OUT/julius-imagebuilder-file-list.txt" \
  > "$OUT/julius-relevant-prebuilt-ib-files.txt" || true

F2FS_IB="$(grep -Ec "kmod-fs-f2fs.*[.]apk" "$OUT/julius-relevant-prebuilt-ib-files.txt" || true)"
NSS_IB="$(grep -Ec "kmod-nss-wifi-drv.*[.]apk" "$OUT/julius-relevant-prebuilt-ib-files.txt" || true)"
WG_IB="$(grep -Ec "kmod-wireguard.*[.]apk" "$OUT/julius-relevant-prebuilt-ib-files.txt" || true)"
jq --arg ib_name "$JULIUS_IB" --arg ib_sha "$IB_SHA" \
   --argjson ib_f2fs "$F2FS_IB" --argjson ib_nss "$NSS_IB" \
   --argjson ib_wireguard "$WG_IB" \
  '. + {donor_prebuilt_imagebuilder:$ib_name,
        donor_prebuilt_imagebuilder_sha256:$ib_sha,
        donor_imagebuilder_f2fs_apk_found:($ib_f2fs>0),
        donor_imagebuilder_nss_wifi_apk_found:($ib_nss>0),
        donor_imagebuilder_wireguard_apk_found:($ib_wireguard>0),
        ready_to_flash:false,publishable:false}' \
  "$OUT/swap-compatibility-report.json" > "$OUT/report-new.json"
mv "$OUT/report-new.json" "$OUT/swap-compatibility-report.json"
# The userland remains official ImmortalWrt only if the entire core APK
# dependency set is reconciled, not merely the kernel tar member.
ARCH_ROOT="https://downloads.immortalwrt.org/snapshots/packages/aarch64_cortex-a53"
download "$ARCH_ROOT/sha256sums" "$WORK/immortalwrt-arch-sha256sums"
verify_file "$WORK/immortalwrt-arch-sha256sums" \
  "$(jq -er '.arch_checksums_sha256' "$LOCK")"
python3 "$ROOT/scripts/compare-swap-userspace-packages.py" \
  --julius-imagebuilder-list "$OUT/julius-imagebuilder-file-list.txt" \
  --official-target-sums "$WORK/immortalwrt-sha256sums" \
  --official-arch-sums "$WORK/immortalwrt-arch-sha256sums" \
  --output "$OUT/core-userspace-version-comparison.json"
echo "Matching Julius prebuilt Builder package availability:"
cat "$OUT/julius-relevant-prebuilt-ib-files.txt"
echo "Read-only inspection complete. No kernel or firmware is published."
echo "All extracted rootfs files stay in ephemeral runner storage."
