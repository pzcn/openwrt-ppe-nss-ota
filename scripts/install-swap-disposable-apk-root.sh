#!/usr/bin/env bash
# Install a restricted *mixed* package closure into a throwaway scratch root.
# No package scripts/hooks run; no firmware is built or uploaded. This tests
# APK payload extraction/file conflicts beyond a dependency-only simulation.
set -Eeuo pipefail
ROOT="${GITHUB_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
LOCK="$(realpath "${1:?Expected locked Snapshot JSON}")"
OUT="$(realpath "${2:?Expected swap output directory}")"
WORK="${RUNNER_TEMP:-/tmp}/immortal-julius-swap"
REPORT="$OUT/full-stock-native-solver-result.json"
PLAN="$OUT/full-installed-world-swap-plan.json"
[[ -s "$REPORT" && -s "$PLAN" ]] || exit 1
jq -e '.donor_restricted_repo_simulation_succeeded == true and
        .publishable == false' "$REPORT" >/dev/null || {
  echo "::error::Restricted-native package solver did not succeed"; exit 1;
}
mapfile -t donor_dirs < <(find "$WORK/donor-ib-extracted" -mindepth 1 -maxdepth 1 -type d -name '*imagebuilder*')
mapfile -t official_dirs < <(find "${RUNNER_TEMP:-/tmp}/hybrid-ib-inspect/extracted" \
  -mindepth 1 -maxdepth 1 -type d -name '*imagebuilder*')
[[ "${#donor_dirs[@]}" == 1 && "${#official_dirs[@]}" == 1 ]] || exit 1
DONOR="${donor_dirs[0]}"
OFFICIAL="${official_dirs[0]}"
APK="$OFFICIAL/staging_dir/host/bin/apk"
[[ -x "$APK" ]] || exit 1
test -s "$OUT/swap-indexes/donor-restricted.adb"
cp "$OUT/swap-indexes/donor-restricted.adb" "$DONOR/packages/research-restricted.adb"
SHA="$(sha256sum "$DONOR/packages/research-restricted.adb" | cut -d' ' -f1)"
SCRATCH="$WORK/disposable-apk-root"
mkdir -p "$SCRATCH/etc/apk/keys" "$SCRATCH/var/cache/apk" "$SCRATCH/lib/apk/db"
for key in "$DONOR/keys/"*.pem; do
  [[ -f "$key" ]] && cp "$key" "$SCRATCH/etc/apk/keys/julius-$(basename "$key")"
done
for key in "$OFFICIAL/keys/"*.pem; do
  [[ -f "$key" ]] && cp "$key" "$SCRATCH/etc/apk/keys/immortalwrt-$(basename "$key")"
done

T="$(jq -er .target_url "$LOCK")"
A="$(jq -er .architecture_url "$LOCK")"
[[ "$T" == https://downloads.immortalwrt.org/snapshots/targets/qualcommax/ipq60xx ]] || exit 1
[[ "$A" == https://downloads.immortalwrt.org/snapshots/packages/aarch64_cortex-a53 ]] || exit 1
# Freeze both repositories: abort rather than consume a moving Snapshot.
for record in "target:$T:$WORK/immortalwrt-sha256sums" \
              "arch:$A:$WORK/immortalwrt-arch-sha256sums"; do
  kind="${record%%:*}"
  if [[ "$kind" == target ]]; then
    base="$T"
    frozen="$WORK/immortalwrt-sha256sums"
    hash="$(jq -er .target_checksums_sha256 "$LOCK")"
  else
    base="$A"
    frozen="$WORK/immortalwrt-arch-sha256sums"
    hash="$(jq -er .arch_checksums_sha256 "$LOCK")"
  fi
  [[ -s "$frozen" ]] || exit 1
  printf '%s  %s\n' "$hash" "$frozen" | sha256sum -c --status
  curl -fsSL --connect-timeout 15 --max-time 90 --retry 2 \
    "$base/sha256sums" -o "$WORK/$kind-before-install-sha256sums"
  cmp -s "$frozen" "$WORK/$kind-before-install-sha256sums" || {
    echo "::error::$kind Snapshot rotated before installation"; exit 1;
  }
done

official_repos=(-X "$T/packages/packages.adb")
for feed in base packages luci routing telephony; do
  official_repos+=(-X "$A/$feed/packages.adb")
done
donor_repos=(-X "file://$DONOR/packages/research-restricted.adb" "${official_repos[@]}")
common=(--root "$SCRATCH" --arch aarch64_cortex-a53
  --keys-dir etc/apk/keys --cache-dir var/cache/apk
  --repositories-file /dev/null --timeout 90 --no-progress)
mapfile -t pins < "$OUT/full-installed-world-swap-pins.txt"
[[ "${#pins[@]}" -gt 140 ]] || exit 1
"$APK" "${common[@]}" add --initdb --usermode \
  > "$OUT/disposable-apk-initdb.log" 2>&1 || {
  tail -n 60 "$OUT/disposable-apk-initdb.log"; exit 1;
}
# Verify signatures first, with --allow-untrusted DISABLED.
"$APK" "${common[@]}" "${official_repos[@]}" update \
  > "$OUT/disposable-official-signed-update.log" 2>&1 || {
  tail -n 80 "$OUT/disposable-official-signed-update.log"; exit 1;
}
# Temporary donor index was built from the pinned IB and is UNSIGNED.
# --allow-untrusted is ONLY used on this ephemeral runner, and never
# approved for a distributable firmware.
INSTALL_OK=false
echo "Scratch-only unpack of ${#pins[@]} roots (scripts disabled)"
if "$APK" "${common[@]}" --allow-untrusted "${donor_repos[@]}" \
    add --usermode --no-scripts "${pins[@]}" \
    > "$OUT/disposable-apk-install.log" 2>&1; then
  INSTALL_OK=true
  echo "APK payload extraction completed without reported package file conflicts."
else
  echo "::notice::Disposable APK install failed; inspect exact file/dependency error."
  tail -n 140 "$OUT/disposable-apk-install.log"
fi
if [[ "$INSTALL_OK" == true ]]; then
  [[ -s "$SCRATCH/lib/apk/db/installed" ]] || {
    echo "::error::No scratch installed package DB"; INSTALL_OK=false;
  }
fi
if [[ "$INSTALL_OK" == true ]]; then
  # Fail if a single old 6.18.55 module sneaks into the scratch root.
  old_modules="$(find "$SCRATCH/lib/modules" -mindepth 1 -maxdepth 1 \
    -type d ! -name 6.18.60 -printf '%f\n' 2>/dev/null || true)"
  [[ -z "$old_modules" ]] || { echo "::error::Foreign kernel modules: $old_modules"; INSTALL_OK=false; }
fi
jq -n --argjson succeeded "$INSTALL_OK" --argjson requests "${#pins[@]}" \
  --arg donor_repo_sha "$SHA" \
  '{schema:1,status:"throwaway-root-payload-install-experiment",
    requested_exact_pins:$requests,
    donor_restricted_index_sha256:$donor_repo_sha,
    scratch_payload_install_succeeded:$succeeded,
    package_scripts_disabled:true,ephemeral_root_only:true,
    kernel_abi_runtime_tested:false,
    original_missing_kmods_restored:false,
    f2fs_early_boot_verified:false,
    mixed_package_cryptographic_provenance_verified:false,
    secure_sysupgrade_produced:false,publishable:false}' \
  > "$OUT/disposable-apk-payload-install-result.json"
echo "Scratch install result: $INSTALL_OK. NEVER upload the extracted rootfs."
