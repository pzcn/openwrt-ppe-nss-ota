#!/usr/bin/env bash
# Build the original pinned LuCI package for full source or matching SDK.
set -Eeuo pipefail
DEST="${1:?Expected package directory}"
[[ ! -e "$DEST" ]] || { echo "Already exists: $DEST" >&2; exit 1; }
VERSION=v0.4.7
SHA=fde997eb88c5d8d9b6dbc138b36e8a298402b03c
mkdir -p "$(dirname "$DEST")"
git clone --quiet --depth 1 --branch "$VERSION" \
  https://github.com/lauyv/luci-app-sing-box.git "$DEST"
actual="$(git -C "$DEST" rev-parse HEAD)"
[[ "$actual" == "$SHA" ]] || {
  echo "::error::sing-box LuCI tag changed: $actual != $SHA" >&2; exit 1;
}
if ! command -v pnpm >/dev/null 2>&1; then
  npm install -g pnpm@10
fi
bash "$DEST/dashboard/build.sh"
test -s "$DEST/htdocs/luci-static/sing-box/dashboard/index.html"
