#!/usr/bin/env bash
# Preseed the host LZO source archive from OpenWrt's source mirrors.
# The upstream host (oberhumer.com) has been stalling tools/install, and
# download.pl's curl has no overall timeout. Name, version and SHA256 are
# read from the checked-out tools/liblzo/Makefile, so a version bump upstream
# is followed automatically. Compilation and stamps are left to buildroot.
set -Eeuo pipefail

IMM="${1:?Usage: hybrid-prefetch-host-sources.sh <immortalwrt-tree> <dl-directory>}"
CACHE_DL="${2:?Usage: hybrid-prefetch-host-sources.sh <immortalwrt-tree> <dl-directory>}"
MK="$IMM/tools/liblzo/Makefile"
var() { sed -n "s/^$1[[:space:]]*:=[[:space:]]*//p" "$MK" | head -n1; }
NAME="$(var PKG_NAME)"; VERSION="$(var PKG_VERSION)"; EXPECTED="$(var PKG_HASH)"
SOURCE="$(var PKG_SOURCE)"
SOURCE="${SOURCE//\$(PKG_NAME)/$NAME}"; SOURCE="${SOURCE//\$(PKG_VERSION)/$VERSION}"
if [[ ! "$SOURCE" =~ ^[A-Za-z0-9._+-]+$ || ! "$EXPECTED" =~ ^[0-9a-f]{64}$ ]]; then
  echo "::error::Cannot parse liblzo source/hash from $MK" >&2
  exit 1
fi

mkdir -p "$CACHE_DL"
DEST="$CACHE_DL/$SOURCE"
check() { printf '%s  %s\n' "$EXPECTED" "$1" | sha256sum -c --status; }
if [[ -s "$DEST" ]] && check "$DEST"; then
  echo "Using SHA256-verified cached host source: $SOURCE"
  exit 0
fi

rm -f "$DEST"
tmp="$DEST.download"
for url in \
  "https://sources.cdn.openwrt.org/$SOURCE" \
  "https://downloads.openwrt.org/sources/$SOURCE"; do
  rm -f "$tmp"
  echo "Prefetching $SOURCE from $url"
  if curl -fsSL --connect-timeout 10 --max-time 100 --retry 2 --retry-delay 2 \
      "$url" -o "$tmp" && check "$tmp"; then
    mv -f "$tmp" "$DEST"
    echo "SHA256-verified $SOURCE ready; continuing regular tools/install."
    exit 0
  fi
done
rm -f "$tmp"
echo "::error::Could not obtain SHA256-matching $SOURCE from OpenWrt mirrors." >&2
echo "::error::Stopping before the upstream source downloader stalls for many minutes." >&2
exit 1
