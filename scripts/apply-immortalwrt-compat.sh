#!/usr/bin/env bash
# Temporary F2FS + sysupgrade fixes until included and verified in ImmortalWrt.
set -Eeuo pipefail
IMM="$1"
OVERLAY="$2"
test -n "$IMM" && test -n "$OVERLAY" || { echo "Usage: $0 IMM_SOURCE FILES_OVERLAY" >&2; exit 2; }
DEVICE="$IMM/target/linux/qualcommax/image/ipq60xx.mk"
PLATFORM="$IMM/target/linux/qualcommax/ipq60xx/base-files/lib/upgrade/platform.sh"
test -s "$DEVICE" && test -s "$PLATFORM"

python3 - "$DEVICE" <<'PY'
from pathlib import Path
import re
import sys

target = Path(sys.argv[1])
content = target.read_text(encoding="utf-8")
changed = []
for device in ("jdcloud_re-cs-02", "jdcloud_re-cs-07", "jdcloud_re-ss-01"):
    pattern = re.compile(r"^define Device/" + re.escape(device) + r"\n(.*?)^endef", re.M | re.S)
    match = pattern.search(content)
    if match is None:
        raise SystemExit(f"Missing device: {device}")
    body = match.group(1)
    packages = re.findall(r"^\tDEVICE_PACKAGES :=[^\n]*$", body, re.M)
    if len(packages) != 1:
        raise SystemExit(f"Unexpected packages line: {device}")
    line = packages[0]
    present = line.split(":=", 1)[1].strip().split()
    missing = [p for p in ("kmod-fs-f2fs", "f2fs-tools") if p not in present]
    if missing:
        body = body.replace(line, line + " " + " ".join(missing), 1)
        content = content[:match.start(1)] + body + content[match.end(1):]
        changed.append(device)
target.write_text(content, encoding="utf-8")
print("F2FS packages: " + (", ".join(changed) if changed else "already upstream"))
PY

# Use the matching ImmortalWrt platform.sh rather than a historical SHA.
OUTPUT="$OVERLAY/lib/upgrade/platform.sh"
install -D -m 0644 "$PLATFORM" "$OUTPUT"
if grep -Eq '^[[:space:]]*platform_copy_config[[:space:]]*\(' "$PLATFORM"; then
    grep -Fq 'jdcloud,re-ss-01' "$PLATFORM" || {
        echo "::error::Upstream config-copy hook has unclear RE-SS-01 support" >&2
        exit 1
    }
    echo "sysupgrade: upstream hook present, local hook skipped."
else
    grep -Fq 'emmc_do_upgrade "$1"' "$PLATFORM" || {
        echo "::error::Expected eMMC upgrade code missing" >&2
        exit 1
    }
    cat >> "$OUTPUT" <<'PATCH'

# Temporary configuration backup for ipq60xx eMMC sysupgrade.
platform_copy_config() {
    case "$(board_name)" in
    jdcloud,re-cs-02|\
    jdcloud,re-cs-07|\
    jdcloud,re-ss-01|\
    link,nn6000-v1|\
    link,nn6000-v2)
        emmc_copy_config
        ;;
    esac
}
PATCH
    echo "sysupgrade: temporary emmc_copy_config hook applied."
fi
sh -n "$OUTPUT"
grep -Fq 'emmc_copy_config' "$OUTPUT"
