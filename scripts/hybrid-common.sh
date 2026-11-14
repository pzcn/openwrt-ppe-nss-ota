# shellcheck shell=bash
# Shared steps of the hybrid Builder (full build and userland refresh).
# Source after `set -Eeuo pipefail`; requires ROOT to be set.

HB=(python3 "$ROOT/scripts/hybrid_builder.py")
HYBRID_SNAPSHOT_HOST="https://downloads.immortalwrt.org/snapshots"

# `! cmd` never trips `set -e`; fail explicitly when a forbidden match exists.
refuse() {
  local why="$1"; shift
  if "$@"; then echo "::error::$why" >&2; exit 1; fi
}

fetch_verified() {  # url dest sha256
  curl -fsSL --retry 3 --connect-timeout 20 --max-time 300 "$1" -o "$2"
  printf '%s  %s\n' "$3" "$2" | sha256sum -c --status || {
    echo "::error::SHA256 mismatch for $1 (snapshot rotated? retry later)" >&2; exit 1;
  }
}

hybrid_check_lock() {  # lock
  jq -e --arg host "$HYBRID_SNAPSHOT_HOST" '
    .schema == 2 and .target == "qualcommax/ipq60xx" and .architecture == "aarch64_cortex-a53"
    and .target_url == ($host + "/targets/qualcommax/ipq60xx")
    and .architecture_url == ($host + "/packages/aarch64_cortex-a53")' "$1" >/dev/null || {
    echo "::error::Not an ipq60xx official snapshot lock: $1" >&2; exit 1;
  }
}

# Official signing keys from a pinned immortalwrt/keyring commit.
hybrid_official_keys() {  # keyring_sha keys_dir work_dir
  local sha="$1" keys="$2" repo="$3/keyring"
  [[ "$sha" =~ ^[0-9a-f]{40}$ ]] || { echo "::error::Bad keyring commit: $sha" >&2; exit 1; }
  rm -rf "$repo"
  git init -q "$repo"
  git -C "$repo" remote add origin https://github.com/immortalwrt/keyring.git
  git -C "$repo" fetch -q --depth 1 origin "$sha"
  git -C "$repo" -c advice.detachedHead=false checkout -q --detach FETCH_HEAD
  mkdir -p "$keys"
  cp "$repo/apk/"*.pem "$keys/"
  test -s "$keys/immortalwrt-snapshots.pem"
}

# Download, SHA256-check and signature-verify the six official indexes, dump
# them as JSON. Fills HYBRID_INDEX_ARGS for `hybrid_builder.py closure`.
hybrid_official_indexes() {  # lock apk keys_dir idx_dir
  local lock="$1" apk="$2" keys="$3" idx="$4" repo rel sha url
  local target_url arch_url
  target_url="$(jq -er '.target_url' "$lock")"
  arch_url="$(jq -er '.architecture_url' "$lock")"
  mkdir -p "$idx"
  fetch_verified "$target_url/sha256sums" "$idx/target.sha256sums" "$(jq -er '.target_checksums_sha256' "$lock")"
  fetch_verified "$arch_url/sha256sums" "$idx/arch.sha256sums" "$(jq -er '.arch_checksums_sha256' "$lock")"
  HYBRID_INDEX_ARGS=()
  for repo in target base packages luci routing telephony; do
    if [[ "$repo" == target ]]; then
      rel="$(jq -er '.package_indexes.target.filename' "$lock")"
      sha="$(jq -er '.package_indexes.target.sha256' "$lock")"
      url="$target_url/$rel"
    else
      rel="$(jq -er --arg r "$repo" '.package_indexes.architecture[$r].filename' "$lock")"
      sha="$(jq -er --arg r "$repo" '.package_indexes.architecture[$r].sha256' "$lock")"
      url="$arch_url/$rel"
    fi
    fetch_verified "$url" "$idx/$repo.adb" "$sha"
    "$apk" --keys-dir "$keys" verify "$idx/$repo.adb" || {
      echo "::error::Official $repo index is not signed by the ImmortalWrt keyring" >&2; exit 1;
    }
    "$apk" adbdump --format json "$idx/$repo.adb" > "$idx/$repo.json"
    HYBRID_INDEX_ARGS+=(--index "$repo=$idx/$repo.json")
  done
  HYBRID_INDEX_ARGS+=(--target-sums "$idx/target.sha256sums" --arch-sums "$idx/arch.sha256sums")
}

# Mirror the closure into a package directory. Local builds of the same name
# always win. Each APK is checked against sha256sums and its own signature.
hybrid_mirror() {  # official_json pkg_dir apk keys_dir work_dir [local_search_dir]
  local plan="$1" dest="$2" apk="$3" keys="$4" work="$5" search="${6:-$2}" name file url sha
  local list="$work/mirror.tsv"
  mkdir -p "$dest"
  : > "$list"
  HYBRID_SKIPPED=0
  while IFS=$'\t' read -r name file url sha; do
    if [[ -n "$(find "$search" -type f -name "$name-[0-9]*.apk" -print -quit)" ]]; then
      HYBRID_SKIPPED=$((HYBRID_SKIPPED + 1))
      continue
    fi
    printf '%s\t%s\t%s\n' "$file" "$url" "$sha" >> "$list"
  done < <(jq -r '.mirror[] | [.name, .filename, .url, .sha256] | @tsv' "$plan")
  while IFS=$'\t' read -r file url sha; do
    printf '%s\0%s\0%s\0' "$file" "$url" "$sha"
  done < "$list" | DEST="$dest" xargs -0 -n3 -P8 sh -c '
    curl -fsSL --retry 3 --connect-timeout 20 --max-time 300 "$1" -o "$DEST/$0" &&
    printf "%s  %s\n" "$2" "$DEST/$0" | sha256sum -c --status ||
    { echo "::error::Official APK failed download/SHA256: $0" >&2; exit 255; }'
  HYBRID_MIRRORED="$(wc -l < "$list")"
  # Official snapshots set SIGN_EACH_PACKAGE.
  local files=()
  mapfile -t files < <(cut -f1 "$list" | sed "s|^|$dest/|")
  if (( ${#files[@]} )); then
    "$apk" --keys-dir "$keys" verify "${files[@]}" || {
      echo "::error::Mirrored official APKs failed signature verification" >&2; exit 1;
    }
  fi
  # Record exactly which files came from the official snapshot: a later
  # refresh removes these, and only these, from the ImageBuilder.
  jq --rawfile files <(cut -f1 "$list") \
    '.mirrored = ($files | split("\n") | map(select(length > 0)))' "$plan" > "$plan.tmp"
  mv "$plan.tmp" "$plan"
  echo "Mirrored $HYBRID_MIRRORED official APKs ($HYBRID_SKIPPED provided locally)."
}

# Resolve the firmware package set with the ImageBuilder itself and enforce
# the image contract: required packages present, excluded ones absent, and
# every kmod one we compiled for this kernel.
hybrid_ib_manifest() {  # ib_dir out_dir local_apks_file
  local ib="$1" out="$2" local_list="$3" request="" line p apk
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"; request+=" $line"
  done < "$ROOT/config/add.txt"
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"; for p in $line; do request+=" -$p"; done
  done < "$ROOT/config/remove.txt"
  # OpenWrt generates packages.adb from local + mirrored APKs; make sure
  # the index was actually created before asking APK to resolve the manifest.
  make -C "$ib" -s package_index
  [[ -s "$ib/packages/packages.adb" ]] || {
    echo "::error::ImageBuilder failed to generate packages/packages.adb" >&2
    exit 1
  }
  make -C "$ib" -s manifest PROFILE=jdcloud_re-ss-01 STRIP_ABI=1 PACKAGES="$request" \
    > "$out/imagebuilder.manifest"
  awk 'NF >= 3 && $2 == "-" && $1 ~ /^[a-z0-9][a-z0-9+._-]*$/ &&
       $1 != "kernel" && $1 != "libc" && $1 != "base-files" { print $1 }' \
    "$out/imagebuilder.manifest" | sort -u > "$out/imagebuilder-packages.txt"
  for p in kmod-nss-wifi-drv luci-app-sing-box sing-box luci-app-autoreboot \
    luci-app-cpufreq default-settings-chn autocore luci-app-ddns-go kmod-fs-f2fs \
    qca-ppe-qos luci-app-qca-ppe-qos luci-theme-aurora sqm-scripts; do
    grep -Fxq "$p" "$out/imagebuilder-packages.txt" || {
      echo "::error::ImageBuilder manifest missing $p" >&2; exit 1;
    }
  done
  for p in luci-app-homeproxy luci-i18n-homeproxy-zh-cn luci-app-diskman \
    luci-i18n-diskman-zh-cn luci-app-statistics luci-i18n-statistics-zh-cn; do
    refuse "Image still includes $p" grep -Fxq "$p" "$out/imagebuilder-packages.txt"
  done
  while read -r apk; do
    grep -Fxq "$apk" "$local_list" || { echo "::error::Foreign kmod in image: $apk" >&2; exit 1; }
  done < <(awk '$1 ~ /^kmod-/ { print $1 "-" $3 ".apk" }' "$out/imagebuilder.manifest")
}

# A published ImageBuilder may carry public keys only.
hybrid_check_archive_keys() {  # archive
  refuse "ImageBuilder archive contains a private signing key: $1" \
    sh -c 'tar -I zstd -tf "$1" | grep -Eq "(^|/)(local-)?private-key[.]pem$|/key-build$"' _ "$1"
}

hybrid_info() {  # output identity kernel_identity built_at kernel_parent keyring
  jq -n --arg identity "$2" --arg kernel "$3" --arg built "$4" --arg parent "$5" --arg keyring "$6" \
    '{identity: $identity, kernel_identity: $kernel, kernel_built_at: $built,
      kernel_parent: (if $parent == "" then null else $parent end), keyring_commit: $keyring}' > "$1"
}

hybrid_summary() {  # out_dir title
  [[ -n "${GITHUB_STEP_SUMMARY:-}" ]] || return 0
  {
    echo "## $2 $(jq -r .tag "$1/builder-metadata.json")"
    echo "- Official snapshot: \`$(jq -r .official_snapshot.snapshot_version "$1/builder-metadata.json")\`"
    echo "- Kernel built: $(jq -r .hybrid.kernel_built_at "$1/builder-metadata.json")"
    echo "- Local packages: $(jq '.local_packages | length' "$1/local-plan.json")"
    echo "- Official APKs mirrored: $(jq '.mirror | length' "$1/official-apks.json")"
    echo "- Image packages: $(wc -l < "$1/imagebuilder-packages.txt")"
    echo ""
    echo "| Phase | Seconds |"
    echo "|---|---:|"
    awk -F'\t' '{ printf "| %s | %s |\n", $1, $2 }' "$1/timings.tsv"
  } >> "$GITHUB_STEP_SUMMARY"
}
