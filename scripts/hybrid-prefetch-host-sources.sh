#!/usr/bin/env bash
# Preseed the exact host LZO source archive for the pinned ImmortalWrt
# Snapshot. The upstream primary download host has been stalling tools/install.
# This does NOT skip source compilation or fake OpenWrt host-tool stamps.
set -Eeuo pipefail

CACHE_DL="${1:?Usage: hybrid-prefetch-host-sources.sh <cached-dl-directory>}"
mkdir -p "$CACHE_DL"
DEST="$CACHE_DL/lzo-2.10.tar.gz"
EXPECTED="c0f892943208266f9b6543b3ae308fab6284c5c90e627931446fb49b4221a072"

verified() {
  [[ -s "$DEST" ]] && printf '%s  %s\n' "$EXPECTED" "$DEST" | sha256sum -c --status
}
if verified; then
  echo "Using SHA256-verified cached host source: lzo-2.10.tar.gz"
  exit 0
fi

rm -f "$DEST"
# OpenWrt's public source mirrors; never accept the archive unless its
# digest matches the pinned upstream tools/liblzo/Makefile package hash.
for url in \
  "https://sources.cdn.openwrt.org/lzo-2.10.tar.gz" \
  "https://downloads.openwrt.org/sources/lzo-2.10.tar.gz"; do
  tmp="$DEST.download"
  rm -f "$tmp"
  echo "Prefetching host liblzo from $url"
  if curl -fsSL --connect-timeout 10 --max-time 100 --retry 2 --retry-delay 2 \
      "$url" -o "$tmp" &&
      printf '%s  %s\n' "$EXPECTED" "$tmp" | sha256sum -c --status; then
    mv -f "$tmp" "$DEST"
    echo "SHA256-verified lzo host source ready; continuing regular tools/install."
    exit 0
  fi
  rm -f "$tmp"
done
echo "::error::Could not obtain SHA256-matching lzo-2.10.tar.gz from OpenWrt mirrors." >&2
echo "::error::Stopping before the upstream source downloader stalls for many minutes." >&2
exit 1
