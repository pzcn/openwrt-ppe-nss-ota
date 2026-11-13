#!/usr/bin/env bash
# Inspect the *actual official firmware's* APK installed database and world.
# Version pinning 11 core roots is not sufficient to preserve ImmortalWrt:
# the 73-package dry-run imported 45 Julius-only package versions.
set -Eeuo pipefail
ROOT="${GITHUB_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
OUT="$(realpath "${1:?Expected swap output directory}")"
WORK="${RUNNER_TEMP:-/tmp}/immortal-julius-swap"
IMM_SQUASHFS="$WORK/extracted/immortalwrt.squashfs"
DEST="$WORK/official-immortalwrt-db"
[[ -s "$IMM_SQUASHFS" ]] || exit 1
mkdir -p "$DEST"

# The full stock rootfs includes device nodes; extract only APK metadata.
unsquashfs -ls "$IMM_SQUASHFS" \
  > "$OUT/official-rootfs-path-inventory.txt"
grep -E '/(etc/apk/world|lib/apk/db/installed)$' \
  "$OUT/official-rootfs-path-inventory.txt" || true
unsquashfs -no-progress -no-xattrs -d "$DEST" "$IMM_SQUASHFS" \
  etc/apk/world lib/apk/db/installed \
  > "$OUT/official-rootfs-apkdb-unpack.log"

WORLD="$DEST/etc/apk/world"
INSTALLED="$DEST/lib/apk/db/installed"
if [[ -s "$WORLD" ]]; then
  cp "$WORLD" "$OUT/official-rootfs-world.txt"
  echo "Official world requests: $(wc -l < "$WORLD")"
  sed -n '1,28p' "$WORLD"
else
  echo "::warning::Official rootfs has no /etc/apk/world"
fi
if [[ -s "$INSTALLED" ]]; then
  echo "Official installed DB: $(wc -c < "$INSTALLED") bytes"
  file "$INSTALLED" | tee "$OUT/official-installed-db-filetype.txt"
  find "${RUNNER_TEMP:-/tmp}/hybrid-ib-inspect/extracted" \
    -type f -path '*/staging_dir/host/bin/apk' -print -quit \
    > "$OUT/official-apk-executable-path.txt"
  APK="$(cat "$OUT/official-apk-executable-path.txt")"
  if [[ -x "$APK" ]] && "$APK" adbdump "$INSTALLED" \
    > "$OUT/official-rootfs-installed-adbdump.txt" \
    2> "$OUT/official-rootfs-installed-adbdump-error.txt"; then
    echo "Official installed DB decoded:"
    grep -c '^  - name: ' "$OUT/official-rootfs-installed-adbdump.txt" || true
  else
    echo "::warning::Native apk3 could not parse this installed DB as an ADB archive."
    head -c 64 "$INSTALLED" | od -An -tx1 \
      > "$OUT/official-installed-db-header.txt"
  fi
else
  echo "::warning::Official rootfs has no /lib/apk/db/installed"
fi

# Analyze the *entire* official rootfs installed userland against the
# precise target+arch package versions pinned in this experimental run.
# Old Snapshot target and arch feeds can be published at different times.
if [[ -s "$INSTALLED" && -s "$WORLD" ]] &&
   grep -q '^P:' "$INSTALLED" &&
   [[ -s "$OUT/swap-indexes/target.txt" ]]; then
  python3 "$ROOT/scripts/audit-swap-official-world.py" \
    --installed-db "$INSTALLED" --world "$WORLD" \
    --official-index-dir "$OUT/swap-indexes" \
    --output "$OUT/official-rootfs-world-availability.json"
else
  echo "::warning::Cannot audit full installed world; required APK metadata/index absent"
fi
jq -n \
  --argjson world_present "$([[ -s "$WORLD" ]] && echo true || echo false)" \
  --argjson installed_present "$([[ -s "$INSTALLED" ]] && echo true || echo false)" \
  --argjson adbdump_present "$([[ -s "$OUT/official-rootfs-installed-adbdump.txt" ]] && echo true || echo false)" \
  '{schema:1,status:"official-world-inspection-only",
    world_present:$world_present,installed_db_present:$installed_present,
    installed_adbdump_available:$adbdump_present,
    all_official_packages_pinned:false,complete_world_solved:false,
    publishable:false}' > "$OUT/official-world-inspection.json"
echo "Official rootfs APK database inspection complete; no firmware modified."
