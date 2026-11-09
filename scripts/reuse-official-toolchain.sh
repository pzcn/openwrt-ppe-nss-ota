#!/usr/bin/env bash
# Reuse the officially packaged ImmortalWrt ipq60xx cross toolchain where it
# matches our GCC/musl/arch requirements; keep kernel, DTB and NSS source-built.
set -Eeuo pipefail

IMM="${1:?ImmortalWrt source tree is required}"
CACHE_DL="${2:?Persistent download cache is required}"
STATUS_FILE="${3:?Output status path is required}"
MODE="${IMM_USE_OFFICIAL_TOOLCHAIN:-auto}"
case "$MODE" in
  auto|off|required) ;;
  *) echo "::error::Invalid IMM_USE_OFFICIAL_TOOLCHAIN: $MODE" >&2; exit 1 ;;
esac
mkdir -p "$CACHE_DL" "$(dirname "$STATUS_FILE")"
if [[ "$MODE" == off ]]; then
  printf 'toolchain=source\nreason=disabled\n' > "$STATUS_FILE"
  echo "Official toolchain disabled; compiling original ImmortalWrt toolchain."
  exit 0
fi

# Pin the official snapshot archive by checksum: a moving snapshot cannot
# silently substitute another compiler/libc under the same Builder tag.
ARCHIVE="immortalwrt-toolchain-qualcommax-ipq60xx_gcc-14.4.0_musl.Linux-x86_64.tar.zst"
SHA256="560d48f55910abbe3060d1c3a7140459eae010770745a498bb579ea05075238a"
URL="https://downloads.immortalwrt.org/snapshots/targets/qualcommax/ipq60xx/$ARCHIVE"
DEST="$CACHE_DL/$ARCHIVE"
WORK="${RUNNER_TEMP:-/tmp}/immortal-official-toolchain"
ORIGINAL_CONFIG="$WORK/config.backup"
mkdir -p "$WORK"

use_official() {
  # Refuse to mix distinct GCC/musl versions with this full-source tree.
  grep -Fq 'default "14.4.0"' "$IMM/toolchain/gcc/Config.version" || return 1
  grep -Eq '^PKG_VERSION:=1[.]2[.]6$' "$IMM/toolchain/musl/common.mk" || return 1
  if [[ ! -s "$DEST" ]] || ! echo "$SHA256  $DEST" | sha256sum -c --status; then
    rm -f "$DEST"
    curl -fL --retry 2 --connect-timeout 15 --max-time 180 \
      --output "$DEST.partial" "$URL" || return 1
    mv "$DEST.partial" "$DEST" || return 1
  fi
  echo "$SHA256  $DEST" | sha256sum -c --status || return 1
  mkdir -p "$WORK/extracted"
  tar -I zstd -xf "$DEST" -C "$WORK/extracted" || return 1
  local info toolchain target
  mapfile -t infos < <(find "$WORK/extracted" -mindepth 2 -maxdepth 4 \
    -type f -name info.mk)
  [[ "${#infos[@]}" -eq 1 ]] || return 1
  info="${infos[0]}"
  toolchain="${info%/info.mk}"
  grep -Fxq 'GCC_VERSION=14.4.0' "$info" || return 1
  grep -Fxq 'LIBC_TYPE=musl' "$info" || return 1
  grep -Fxq 'LIBC_VERSION=1.2.6' "$info" || return 1
  target="$(bash "$IMM/scripts/ext-toolchain.sh" \
    --toolchain "$toolchain" --print-target)" || return 1
  [[ "$target" == aarch64-*musl* ]] || return 1
  bash "$IMM/scripts/ext-toolchain.sh" --toolchain "$toolchain" --test c || return 1
  bash "$IMM/scripts/ext-toolchain.sh" --toolchain "$toolchain" --test c++ || return 1

  cp "$IMM/.config" "$ORIGINAL_CONFIG"
  # External toolchains require explicit permission to package ImageBuilder.
  # ext-toolchain.sh appends the exact compiler paths and libraries, then
  # invokes defconfig. Reassert the required IB flags before the final pass.
  printf 'CONFIG_DEVEL=y\nCONFIG_EXTERNAL_TOOLCHAIN_IB=y\n' >> "$IMM/.config"
  # The official script derives the buildroot from its argv[0], using
  # "${0%/scripts/*}". A relative "scripts/ext-toolchain.sh" invocation
  # silently writes to "scripts/ext-toolchain.sh/.config" instead of .config.
  # Always supply the absolute path, then prove it configured THIS buildroot.
  if ! (cd "$IMM" && bash "$IMM/scripts/ext-toolchain.sh" \
      --toolchain "$toolchain" --overwrite-config --config qualcommax/ipq60xx); then
    cp "$ORIGINAL_CONFIG" "$IMM/.config"
    return 1
  fi
  if ! grep -Fqx "CONFIG_TOOLCHAIN_ROOT=\"$toolchain\"" "$IMM/.config"; then
    echo "::warning::Official toolchain configuration did not set its absolute root; reverting to source toolchain." >&2
    cp "$ORIGINAL_CONFIG" "$IMM/.config"
    return 1
  fi
  cat >> "$IMM/.config" <<'CONFIG'
CONFIG_EXTERNAL_TOOLCHAIN=y
CONFIG_EXTERNAL_TOOLCHAIN_IB=y
CONFIG_IB=y
CONFIG_IB_STANDALONE=y
CONFIG_CCACHE=y
CONFIG
  for required in \
    'CONFIG_EXTERNAL_TOOLCHAIN=y' \
    'CONFIG_EXTERNAL_TOOLCHAIN_IB=y' \
    "CONFIG_TOOLCHAIN_ROOT=\"$toolchain\""; do
    if ! grep -Fqx "$required" "$IMM/.config"; then
      echo "::warning::Official toolchain setup missing $required; falling back to source compilation" >&2
      cp "$ORIGINAL_CONFIG" "$IMM/.config"
      return 1
    fi
  done
  printf 'toolchain=official-immortalwrt\narchive=%s\nsha256=%s\ncompiler=GCC 14.4.0\nlibc=musl 1.2.6\n' \
    "$ARCHIVE" "$SHA256" > "$STATUS_FILE"
  echo "Using verified official ImmortalWrt prebuilt toolchain: $ARCHIVE"
}
if ! use_official; then
  if [[ -f "$ORIGINAL_CONFIG" ]]; then
    cp "$ORIGINAL_CONFIG" "$IMM/.config"
  fi
  if [[ "$MODE" == required ]]; then
    echo "::error::Official cross toolchain unavailable/incompatible (required mode)" >&2
    exit 1
  fi
  printf 'toolchain=source\nreason=official-archive-unavailable-or-incompatible\n' > "$STATUS_FILE"
  echo "::warning::Official toolchain unavailable/incompatible; using fresh source-built toolchain."
fi
