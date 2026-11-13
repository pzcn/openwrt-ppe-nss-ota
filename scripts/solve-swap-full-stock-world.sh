#!/usr/bin/env bash
# Native apk3 dry-run for ALL 168 original installed ImmortalWrt package
# requirements (not just 11 core packages), swapping to Julius kernel/kmods.
# Two missing original modules are explicitly recorded; this is NOT approval.
set -Eeuo pipefail
ROOT="${GITHUB_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
OUT="$(realpath "${1:?Expected swap output directory}")"
WORK="${RUNNER_TEMP:-/tmp}/immortal-julius-swap"
DONOR_DIR="$WORK/donor-ib-extracted"
OFFICIAL_DIR="${RUNNER_TEMP:-/tmp}/hybrid-ib-inspect/extracted"
PLAN="$OUT/full-installed-world-swap-plan.json"
[[ -s "$PLAN" ]] || { echo "::error::No full-world installed-package plan"; exit 1; }
mapfile -t donor_matches < <(find "$DONOR_DIR" -mindepth 1 -maxdepth 1 -type d -name '*imagebuilder*')
mapfile -t official_matches < <(find "$OFFICIAL_DIR" -mindepth 1 -maxdepth 1 -type d -name '*imagebuilder*')
[[ "${#donor_matches[@]}" == 1 && "${#official_matches[@]}" == 1 ]] || exit 1
DONOR="${donor_matches[0]}"
OFFICIAL="${official_matches[0]}"
APK="$OFFICIAL/staging_dir/host/bin/apk"
[[ -x "$APK" && -s "$DONOR/packages/packages.adb" ]] || exit 1
# All six official indexes have been checked against frozen SHA256 and
# independently verified by native signature verification in core stage.
for feed in target base packages luci routing telephony; do
  [[ -s "$OUT/swap-indexes/$feed.adb" ]] || {
    echo "::error::Missing frozen official index $feed"; exit 1;
  }
done
BLOCKERS="$(jq -cr '.missing_stock_kernel_or_kmods' "$PLAN")"
echo "Stock modules with NO equivalent donor package: $BLOCKERS"
jq -e '.missing_stock_userland == [] and .world_roots_not_installed == []' "$PLAN" >/dev/null || {
  echo "::error::Official installed userspace world is incomplete"; exit 1;
}
# Strict enough to reveal new unexpected gaps, but the 2 known gaps are
# never claimed to be solved. The missing components need manual review.
jq -e '(.missing_stock_kernel_or_kmods - ["kmod-nf-log6","kmod-nft-fullcone"]) == []' \
  "$PLAN" >/dev/null || {
    echo "::error::Unexpected additional unavailable Julius kernel module"; exit 1;
}
ROOTFS="$WORK/full-stock-apk-sim"
mkdir -p "$ROOTFS/etc/apk/keys" "$ROOTFS/var/cache/apk" "$ROOTFS/lib/apk/db"
for owner in "$OFFICIAL" "$DONOR"; do
  label=immortalwrt
  [[ "$owner" == "$DONOR" ]] && label=julius
  for key in "$owner/keys/"*.pem; do
    [[ -f "$key" ]] || continue
    cp "$key" "$ROOTFS/etc/apk/keys/$label-$(basename "$key")"
  done
done
common=(--root "$ROOTFS" --arch aarch64_cortex-a53
  --keys-dir etc/apk/keys --cache-dir var/cache/apk
  --repositories-file /dev/null --timeout 75 --no-progress)
official_repos=()
for feed in target base packages luci routing telephony; do
  official_repos+=(-X "file://$OUT/swap-indexes/$feed.adb")
done
"$APK" "${common[@]}" add --initdb --usermode \
  > "$OUT/full-stock-apk-initdb.log" 2>&1 || {
    tail -n 50 "$OUT/full-stock-apk-initdb.log"; exit 1;
  }
# Must validate official signed repository indexes without allowing untrusted.
"$APK" "${common[@]}" "${official_repos[@]}" update \
  > "$OUT/full-stock-official-signed-update.log" 2>&1 || {
    tail -n 60 "$OUT/full-stock-official-signed-update.log"; exit 1;
  }
mixed_repos=(-X "file://$DONOR/packages/packages.adb" "${official_repos[@]}")
"$APK" "${common[@]}" --allow-untrusted "${mixed_repos[@]}" update \
  > "$OUT/full-stock-mixed-update.log" 2>&1 || {
    tail -n 70 "$OUT/full-stock-mixed-update.log"; exit 1;
  }
mapfile -t pins < "$OUT/full-installed-world-swap-pins.txt"
[[ "${#pins[@]}" -gt 140 ]] || {
  echo "::error::Unexpectedly small full-world package root set"; exit 1;
}
echo "Native APK solving ${#pins[@]} exactly pinned stock/donor packages"
SOLVED=false
if "$APK" "${common[@]}" --allow-untrusted "${mixed_repos[@]}" \
  add --simulate --usermode --no-scripts "${pins[@]}" \
  > "$OUT/full-stock-apk-native-simulate.log" 2>&1; then
  SOLVED=true
fi
tail -n 110 "$OUT/full-stock-apk-native-simulate.log" || true
jq -n --argjson simulated "$SOLVED" \
  --argjson dropped "$BLOCKERS" \
  --argjson requested "${#pins[@]}" \
  --argjson stock "$(jq -er .stock_installed_count "$PLAN")" \
  '{schema:1,status:"full-stock-world-partial-module-compatibility-test",
    pinned_roots_requested:$requested,
    original_official_installed_count:$stock,
    native_partial_world_solved:$simulated,
    donor_missing_original_kmods:$dropped,
    exact_world_preserved:($dropped|length == 0),
    no_untrusted_approval:true,
    complete_world_solver_passed:false,
    package_file_overlap_verified:false,
    kernel_runtime_abi_verified:false,
    f2fs_overlay_boot_verified:false,
    publishable:false}' \
  > "$OUT/full-stock-native-solver-result.json"
# Build failure is a compatibility result, not CI infrastructure failure.
echo "Partial full-world solve (still missing original modules): $SOLVED"
echo "This is a dry-run only. NO firmware built or approved."
