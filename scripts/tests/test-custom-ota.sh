#!/usr/bin/env bash
# Offline smoke tests for the customized OTA. No network and NEVER flashes.
set -euo pipefail
cd "$(dirname "$0")/../.."
HERE="$PWD"
OTA="$HERE/files/usr/sbin/ppe-update"
GENERATOR="$HERE/scripts/write_ota_metadata.py"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

sh -n "$OTA"
node --check "$HERE/files/www/luci-static/resources/view/system/ppe-update.js"
python3 -m json.tool "$HERE/files/usr/share/rpcd/acl.d/luci-app-ppe-update.json" >/dev/null
test "$(python3 - "$HERE/files/usr/share/rpcd/acl.d/luci-app-ppe-update.json" <<'PY'
import json,sys
a = json.load(open(sys.argv[1]))["luci-app-ppe-update"]
print(",".join(a["write"]["file"]))
PY
)" = "/usr/sbin/ppe-update start"

mkdir -p "$WORKDIR/fixture"
IMG="$WORKDIR/fixture/openwrt-pzcn-qualcommax-ipq60xx-jdcloud_re-ss-01-squashfs-sysupgrade.bin"
MANIFEST="$WORKDIR/fixture/openwrt-pzcn-qualcommax-ipq60xx-jdcloud_re-ss-01.manifest"
truncate -s 1300000 "$IMG"
printf '%s\n' 'base-files 1' 'firewall4 1' 'kmod-nss-wifi-drv 1' 'luci-base 1' 'luci-theme-aurora 1' >"$MANIFEST"
printf '%-110s\n' '# A test package list for the OTA manifest' >>"$MANIFEST"
TAG='ota-ppe-nss-20261106T000000Z-testing-custom-ota1'
python3 "$GENERATOR" --tag "$TAG" --build 200 \
  --upstream 'ppe-nss-20261031T192351Z-41234004220' \
  --group ipq60xx-512m --profile jdcloud_re-ss-01 \
  --image "$IMG" --manifest "$MANIFEST" --output "$WORKDIR/fixture/ota.json"

python3 - "$WORKDIR/fixture/ota.json" "$TAG" <<'PY'
import json,sys
m=json.load(open(sys.argv[1]))
assert m["tag"] == sys.argv[2]
assert m["schema"] == 1
assert m["image_sha256"] and len(m["image_sha256"]) == 64
assert m["manifest_sha256"] and len(m["manifest_sha256"]) == 64
assert m["build"] == 200
assert m["channel"] == "re-ss-01-custom"
PY

cat >"$WORKDIR/fixture/github.json" <<EOF
{"tag_name":"$TAG"}
EOF

cat >"$WORKDIR/upstream" <<EOF
TAG='ppe-nss-20261031T192351Z-41234004220'
GROUP='ipq60xx-512m'
SITE='https://ppenss.github.io'
REPO='JuliusBairaktaris/Qualcommax_NSS_Builder'
EOF
cat >"$WORKDIR/custom" <<EOF
OTA_TAG='ota-ppe-nss-20261031T192351Z-41234004220-old'
OTA_BUILD=101
OTA_CHANNEL='re-ss-01-custom'
EOF

# A jsonfilter-compatible stub for the subset of @.field selectors used by OTA.
# This shell function is only sourced by the test process.
cat >"$WORKDIR/mock.sh" <<'EOF'
jsonfilter() {
    local file='' expr=''
    while [ "$#" -gt 0 ]; do
        case "$1" in
            -i) file="$2"; shift 2 ;;
            -e) expr="$2"; shift 2 ;;
            *) return 2 ;;
        esac
    done
    python3 -c 'import json,sys; o=json.load(open(sys.argv[1])); print(o.get(sys.argv[2][2:],""))' "$file" "$expr"
}
fetch() {
    case "$1" in
        https://api.github.com/repos/pzcn/openwrt-ppe-nss-ota/releases/latest)
            cp "$FIXTURE/github.json" "$2" ;;
        */ota.json)
            cp "$FIXTURE/ota.json" "$2" ;;
        */openwrt-pzcn-qualcommax-ipq60xx-jdcloud_re-ss-01.manifest)
            cp "$FIXTURE/openwrt-pzcn-qualcommax-ipq60xx-jdcloud_re-ss-01.manifest" "$2" ;;
        *) echo "UNEXPECTED_NETWORK_URL: $1" >&2; return 1 ;;
    esac
}
EOF
export FIXTURE="$WORKDIR/fixture" PPE_RELEASE="$WORKDIR/upstream" \
       PZCN_RELEASE="$WORKDIR/custom" PPE_STATE="$WORKDIR/state" \
       PPE_WORK="$WORKDIR/work" PPE_UPDATE_LIB=1
mkdir -p "$WORKDIR/work" "$WORKDIR/state"
export OTA

test_case() {
    local label="$1" command="$2"
    if sh -c '. "$OTA"; . "$FIXTURE/../mock.sh"; BOARD="jdcloud,re-ss-01"; '"$command"; then
        printf 'PASS %s\n' "$label"
    else
        printf 'FAIL %s\n' "$label" >&2
        exit 1
    fi
}

test_case 'custom latest release validated and newer' \
    'lookup ""; [ "$LATEST_BUILD" -eq 200 ]; newer; grep -qx "kmod-nss-wifi-drv" "$WORK/manifest"'

test_case 'current build equal to latest means no upgrade' \
    'OTA_BUILD=200; OTA_TAG="ota-ppe-nss-20261106T000000Z-testing-custom-ota1"; index; ! newer'

test_case 'no downgrade when latest build number is older' \
    'OTA_BUILD=201; index; ! newer'

test_case 'reject mismatched hardware' \
    'BOARD="other,board"; ! ( index )'

test_case 'reject unsafe force-upgrade before flashing' \
    '! ( cmd_update "" "-f" )'

test_case 'manifest SHA256 mismatch blocks use' \
    'cp "$WORK/manifest.full" "$WORK/manifest.before" 2>/dev/null || :; printf "bad-package 1\n" >>"$FIXTURE/openwrt-pzcn-qualcommax-ipq60xx-jdcloud_re-ss-01.manifest"; ! ( lookup "" )'

# Reset manifest for subsequent tests.
head -n -1 "$MANIFEST" >"$WORKDIR/manifest.saved"
mv "$WORKDIR/manifest.saved" "$MANIFEST"

# Valid metadata is required; never allow a stray or old Release.
printf '%s\n' '{"tag_name":"unrelated/release"}' >"$WORKDIR/fixture/github.json"
test_case 'reject foreign GitHub release tags' \
    '! ( lookup "" )'

echo 'Custom OTA tests completed (offline; no firmware was flashed).'
