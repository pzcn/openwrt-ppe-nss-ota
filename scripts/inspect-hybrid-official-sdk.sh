#!/usr/bin/env bash
# Inspect the SHA256-locked official SDK without importing foreign kernel ABI.
set -Eeuo pipefail
ROOT="${GITHUB_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
LOCK="${1:?Pass snapshot-lock.json}"
LOCK="$(realpath "$LOCK")"
OUT="${2:-$ROOT/out-hybrid-sdk-inspect}"
WORK="${RUNNER_TEMP:-/tmp}/immortal-hybrid-sdk-inspect"
mkdir -p "$OUT" "$WORK/extracted"
jq -e '.schema == 2 and .target == "qualcommax/ipq60xx"' "$LOCK" >/dev/null
NAME="$(jq -er '.assets.sdk.filename' "$LOCK")"
SHA="$(jq -er '.assets.sdk.sha256' "$LOCK")"
URL="$(jq -er .target_url "$LOCK")/$NAME"
[[ "$NAME" =~ ^immortalwrt-sdk-qualcommax-ipq60xx[A-Za-z0-9._+~-]*[.]tar[.]zst$ ]] || exit 1
[[ "$SHA" =~ ^[a-f0-9]{64}$ ]] || exit 1
[[ "$URL" == https://downloads.immortalwrt.org/snapshots/targets/qualcommax/ipq60xx/* ]] || exit 1
curl -fsSL --connect-timeout 15 --max-time 300 --retry 2 "$URL" -o "$WORK/$NAME"
printf '%s  %s\n' "$SHA" "$WORK/$NAME" | sha256sum -c --status
tar -I zstd -xf "$WORK/$NAME" -C "$WORK/extracted"
mapfile -t sdks < <(find "$WORK/extracted" -mindepth 1 -maxdepth 1 -type d -name '*sdk*')
[[ "${#sdks[@]}" -eq 1 ]] || {
  echo "::error::Unexpected official SDK extraction layout"; exit 1;
}
SDK="${sdks[0]}"
test -s "$SDK/Makefile"
num() { find "$@" 2>/dev/null | wc -l; }
HOST_BIN="$(num "$SDK/staging_dir/host/bin" -maxdepth 1 -type f -executable)"
HOST_STAMPS="$(num "$SDK/staging_dir/host/stamp" -type f)"
HOSTPKG_STAMPS="$(num "$SDK/staging_dir/hostpkg/stamp" -type f)"
HOST_BUILD_DIRS="$(num "$SDK/build_dir/host" -mindepth 1 -maxdepth 1 -type d)"
SDK_MODULE_SYMVERS="$(find "$SDK/build_dir" -type f -name Module.symvers -print -quit)"
test -s "$SDK_MODULE_SYMVERS" || {
  echo "::error::Official SDK lacks a nonempty kernel Module.symvers"; exit 1;
}
num_modules="$(wc -l < "$SDK_MODULE_SYMVERS")"
{
  echo "Pinned SDK: $NAME"
  echo "Version: $(jq -er .snapshot_version "$LOCK")"
  echo "SHA256: $SHA"
  echo "SDK host/bin executable files: $HOST_BIN"
  echo "SDK host stamp files: $HOST_STAMPS"
  echo "SDK hostpkg stamp files: $HOSTPKG_STAMPS"
  echo "SDK build_dir/host directories: $HOST_BUILD_DIRS"
  echo "Official kernel Module.symvers: $(realpath --relative-to="$SDK" "$SDK_MODULE_SYMVERS")"
  echo "Official kernel exported symbols: $num_modules"
  echo "Cross-compilers:"
  find "$SDK/staging_dir" -type f -name '*-gcc' -perm /111 -printf '%P\n' | head -n 12
} > "$OUT/sdk-layout.txt"
cat "$OUT/sdk-layout.txt"
jq -n \
  --arg snapshot "$(jq -er .snapshot_version "$LOCK")" \
  --arg sha "$SHA" \
  --argjson host_tools "$HOST_BIN" \
  --argjson host_stamps "$HOST_STAMPS" \
  --argjson hostpkg_stamps "$HOSTPKG_STAMPS" \
  --argjson host_build_dirs "$HOST_BUILD_DIRS" \
  --argjson kernel_symbols "$num_modules" \
  '{schema:1,status:"test-only-sdk-feasibility",
    snapshot:$snapshot,archive_sha256:$sha,
    host_bin_executables:$host_tools,host_stamps:$host_stamps,
    hostpkg_stamps:$hostpkg_stamps,host_build_directories:$host_build_dirs,
    official_kernel_symbols:$kernel_symbols,
    custom_kernel_symvers_compatible:false,ready_for_hybrid_publishing:false}' \
  > "$OUT/sdk-inspection.json"
echo "Official SDK inspected; its Module.symvers is NOT approved for PPE/NSS."
