#!/usr/bin/env python3
"""Fast MX4200 v1 repack must never compile a new kernel or publish OTA."""
from pathlib import Path
root = Path(__file__).resolve().parents[1]
script = (root / "mx4200v1/repack-hybrid.sh").read_text()
workflow = (root / ".github/workflows/mx4200v1-fast-repack.yml").read_text()
must = (
    "BASE_SOURCE_SHA", "mx4200v1/source.config", "mx4200v1/port-ppe-nss.sh",
    "mx4200v1/packages.txt mx4200v1/remove.txt",
    "mx4200v1-hybrid-metadata.json", "check_parent_sum",
    "linux-qualcommax_ipq807x/linksys_mx4200v1-uImage.itb",
    "python3 \"$ROOT/scripts/fit_configs.py\"",
    "mx4200v1/stage-overlay.sh", "hybrid_image_request",
    "image PROFILE=linksys_mx4200v1", "PACKAGES=\"$REQUEST\"",
    "make -s -C \"$IB\" manifest", '\"$FWTOOL\" -i \"$FW_META\"',
    'index("linksys,mx4200v1")', "local-apks.txt", "sha256sum -c sha256sums",
    'publishable:false', 'hardware_tested:false',
    "unsquashfs -cat", "pzcn-integrated-ota",
    "OTA_CHANNEL=mx4200v1-immortal-ppe-nss",
)
for value in must:
    assert value in script, f"Missing immutable MX contract: {value}"
for forbidden in ("sysupgrade -F", "gh release create", "gh workflow run",
                  "CONFIG_TARGET_DEVICE_qualcommax_ipq807x_DEVICE_linksys_mx4200v2=y",
                  "make -C \"$IB\" target/compile", "make -C \"$IB\" toolchain/install",
                  "config/immortalwrt-re-ss-01.config", "scripts/repack-immortalwrt.sh"):
    assert forbidden not in script, f"Unsafe MX repack behavior: {forbidden}"
for needed in ("actions/download-artifact@v4", "required: true",
               "mx4200v1-hybrid-builder-sdk-test", "mx4200v1-hybrid-firmware-test",
               "mx4200v1-hybrid-diagnostics", "actions/upload-artifact@v4",
               "contents: read", "actions: read", "compression-level: 0"):
    assert needed in workflow, f"Missing CI contract: {needed}"
assert "43602206711" not in workflow and "5afd6581438af59b3392c35e82322ab41b09acb2" not in workflow
assert "gh release" not in workflow and "schedule:" not in workflow
# Durable Release provenance must be recorded as a tag, not fake run ID 0.
simple = (root / ".github/workflows/firmware-simple.yml").read_text()
assert "BASE_BUILDER_TAG:" in simple
assert 'BASE_RUN_ID: "0"' not in simple
assert "parent_builder_tag:" in script
print("MX4200 v1 fast-repack offline contracts: PASS")
