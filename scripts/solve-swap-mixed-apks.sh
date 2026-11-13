#!/usr/bin/env bash
# Read-only native APK3 mixed repository experiment:
# Julius prebuilt kernel/kmods + pinned ImmortalWrt userspace.
# All indexes/packages are SHA256-pinned before the test; no install or image.
set -Eeuo pipefail
ROOT="${GITHUB_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
LOCK="$(realpath "${1:?Expected official Snapshot lock}")"
OUT="$(realpath "${2:?Expected swap output dir}")"
WORK="${RUNNER_TEMP:-/tmp}/immortal-julius-swap"
DONOR_DIR="$WORK/donor-ib-extracted"
OFFICIAL_DIR="${RUNNER_TEMP:-/tmp}/hybrid-ib-inspect/extracted"
[[ -s "$OUT/swap-compatibility-report.json" ]] || exit 1
mapfile -t donor_matches < <(find "$DONOR_DIR" -mindepth 1 -maxdepth 1 -type d -name '*imagebuilder*')
mapfile -t official_matches < <(find "$OFFICIAL_DIR" -mindepth 1 -maxdepth 1 -type d -name '*imagebuilder*')
[[ "${#donor_matches[@]}" == 1 && "${#official_matches[@]}" == 1 ]] || {
  echo "::error::Both SHA256-verified ImageBuilders must be extracted"; exit 1;
}
DONOR="${donor_matches[0]}"
OFFICIAL="${official_matches[0]}"
APK="$OFFICIAL/staging_dir/host/bin/apk"
[[ -x "$APK" && -d "$DONOR/packages" ]] || exit 1
mkdir -p "$OUT/swap-indexes" "$WORK/mixed-apk-root/etc/apk/keys"
APKR="$WORK/mixed-apk-root"

# The Julius ImageBuilder contains 1463 prebuilt APKs but no repository
# index. Generate a temporary unsigned index ONLY from those verified bytes.
# It is not an approved distributed/signed repository.
echo "::group::Generate temporary donor APK v3 index"
(
  cd "$DONOR/packages"
  "$APK" --root "$DONOR" --keys-dir "$DONOR/keys" \
    mkndx --allow-untrusted --output packages.adb ./*.apk
) > "$OUT/donor-mkndx.log" 2>&1 || {
  tail -n 90 "$OUT/donor-mkndx.log" >&2
  echo "::error::Donor APK index generation failed"; exit 1;
}
test -s "$DONOR/packages/packages.adb"
"$APK" adbdump "$DONOR/packages/packages.adb" > "$OUT/swap-indexes/donor.txt"
echo "Donor index: $(grep -c '^  - name: ' "$OUT/swap-indexes/donor.txt") entries"
echo "::endgroup::"

# Copy public verification keys from both independently SHA-pinned builders.
# Distinct prefixed basenames preserve both signing roots if names collide.
for source in "$DONOR" "$OFFICIAL"; do
  prefix="julius"
  [[ "$source" == "$OFFICIAL" ]] && prefix="immortalwrt"
  for key in "$source/keys/"*.pem; do
    [[ -f "$key" ]] || continue
    cp "$key" "$APKR/etc/apk/keys/$prefix-$(basename "$key")"
  done
done
[[ -n "$(find "$APKR/etc/apk/keys" -name '*.pem' -print -quit)" ]] || exit 1

target_base="$(jq -er '.target_url' "$LOCK")"
arch_base="$(jq -er '.architecture_url' "$LOCK")"
repos=()
official_repos=()
for feed in target base packages luci routing telephony; do
  if [[ "$feed" == target ]]; then
    rel="$(jq -er '.package_indexes.target.filename' "$LOCK")"
    sha="$(jq -er '.package_indexes.target.sha256' "$LOCK")"
    base="$target_base"
  else
    rel="$(jq -er --arg feed "$feed" '.package_indexes.architecture[$feed].filename' "$LOCK")"
    sha="$(jq -er --arg feed "$feed" '.package_indexes.architecture[$feed].sha256' "$LOCK")"
    base="$arch_base"
  fi
  [[ "$rel" == packages/packages.adb || "$rel" == "$feed/packages.adb" ]] || {
    echo "::error::Unexpected official index path"; exit 1;
  }
  [[ "$sha" =~ ^[a-f0-9]{64}$ ]] || exit 1
  target="$OUT/swap-indexes/$feed.adb"
  curl -fsSL --connect-timeout 20 --max-time 90 --retry 2 \
    "$base/$rel" -o "$target"
  printf '%s  %s\n' "$sha" "$target" | sha256sum -c --status || exit 1
  "$APK" adbdump "$target" > "$OUT/swap-indexes/$feed.txt"
  official_repos+=("-X" "file://$target")
done
repos=("-X" "file://$DONOR/packages/packages.adb" "${official_repos[@]}")

python3 "$ROOT/scripts/plan-swap-mixed-apk-roots.py" \
  --donor-index "$OUT/swap-indexes/donor.txt" \
  --official-index-dir "$OUT/swap-indexes" \
  --output "$OUT/mixed-apk-roots.json" \
  --pins "$OUT/mixed-apk-roots.txt"

# First validate ALL six original official signed indexes with signature
# verification enabled. No --allow-untrusted here.
common=(--root "$APKR" --arch aarch64_cortex-a53
  --keys-dir etc/apk/keys --cache-dir var/cache/apk
  --repositories-file /dev/null --timeout 75 --no-progress)
"$APK" "${common[@]}" add --initdb --usermode > "$OUT/apk-initdb.log" 2>&1 || {
  tail -n 100 "$OUT/apk-initdb.log" >&2; exit 1;
}
echo "::group::Native verification of official signed repositories"
if "$APK" "${common[@]}" "${official_repos[@]}" update \
  > "$OUT/apk-official-signed-update.log" 2>&1; then
  SIGNATURES_VERIFIED=true
  echo "Official APK index signatures accepted without --allow-untrusted."
else
  SIGNATURES_VERIFIED=false
  tail -n 130 "$OUT/apk-official-signed-update.log" >&2
  echo "::warning::Official repositories rejected by native signature verification"
fi
echo "::endgroup::"

# Only a SCRATCH-ROOT simulation may allow the temporary donor index,
# because that index was generated from SHA256-verified archives but is not
# signed by a release key. This MUST NOT be used for shipping firmware.
echo "::group::Mixed pinned repositories: native APK solver"
if [[ "$SIGNATURES_VERIFIED" == true ]] &&
   "$APK" "${common[@]}" --allow-untrusted "${repos[@]}" update \
      > "$OUT/apk-mixed-update.log" 2>&1; then
  UPDATE_OK=true
else
  UPDATE_OK=false
  echo "::warning::Mixed repository update was not successful"
fi
echo "::endgroup::"

mapfile -t PINS < "$OUT/mixed-apk-roots.txt"
if [[ "$UPDATE_OK" == true ]] &&
   [[ "$(jq -r '.blockers|length' "$OUT/mixed-apk-roots.json")" == 0 ]]; then
  # --simulate is read-only; never execute package maintainer scripts.
  if "$APK" "${common[@]}" --allow-untrusted "${repos[@]}" \
    add --simulate --usermode --no-scripts "${PINS[@]}" \
    > "$OUT/apk-mixed-simulate.log" 2>&1; then
    SIMULATED=true
  else
    SIMULATED=false
    echo "::notice::Native APK solver rejects this mixture; no firmware produced."
  fi
else
  SIMULATED=false
  echo "Native solve blocked by missing roots/index verification." \
    > "$OUT/apk-mixed-simulate.log"
fi
tail -n 120 "$OUT/apk-mixed-simulate.log" || true
[[ "$UPDATE_OK" == true ]] || tail -n 100 "$OUT/apk-mixed-update.log" 2>/dev/null || true

# A successful small core sample is NOT enough to mark a full image viable.
# The real image would also need every selected userland dependency, donor
# kernel modules, signed local indexes, file overlap + boot tests.
jq -n --argjson signed "$SIGNATURES_VERIFIED" \
  --argjson update "$UPDATE_OK" \
  --argjson simulated "$SIMULATED" \
  --argjson pins "$(jq '.version_pins' "$OUT/mixed-apk-roots.json")" \
  --argjson blockers "$(jq '.blockers' "$OUT/mixed-apk-roots.json")" \
  --arg donor_index_sha "$(sha256sum "$DONOR/packages/packages.adb" | cut -d' ' -f1)" \
  '{schema:1,status:"mixed-apk-native-core-solver-test-only",
    official_indexes_signature_verified:$signed,
    donor_unsigned_test_index_sha256:$donor_index_sha,
    donor_index_origin:"content-pinned-julius-imagebuilder",
    mixed_indexes_updated:$update,
    pinned_core_simulation_succeeded:$simulated,
    requested_pins:$pins,root_blockers:$blockers,
    complete_world_solved:false,
    all_kernel_modules_abi_checked:false,
    official_userland_file_overlaps_checked:false,
    imagebuilder_assembled:false,
    boot_tested:false,publishable:false}' \
  > "$OUT/mixed-apk-native-solver-report.json"
jq '{official_indexes_signature_verified,mixed_indexes_updated,
     pinned_core_simulation_succeeded,requested_pins,root_blockers,publishable}' \
  "$OUT/mixed-apk-native-solver-report.json"
echo "No package installation, no flashable firmware, no OTA publication."
