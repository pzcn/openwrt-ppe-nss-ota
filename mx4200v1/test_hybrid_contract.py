#!/usr/bin/env python3
"""Offline MX4200 v1 Hybrid guardrails; no network or hardware needed."""
from pathlib import Path
import importlib.util

root = Path(__file__).resolve().parents[1]
script = (root / "mx4200v1/build-hybrid.sh").read_text()
common = (root / "scripts/hybrid-common.sh").read_text()
toolchain = (root / "scripts/reuse-official-toolchain.sh").read_text()
workflow = (root / ".github/workflows/mx4200v1-hybrid.yml").read_text()
old = (root / ".github/workflows/mx4200v1.yml").read_text()

def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, root / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

snapshot = load("snapshot", "scripts/resolve-immortalwrt-snapshot.py")
assert snapshot.PROFILES["qualcommax/ipq807x"] == "linksys_mx4200v1"
assert snapshot.PROFILES["qualcommax/ipq60xx"] == "jdcloud_re-ss-01"
sha = "a" * 64
name = "immortalwrt-toolchain-qualcommax-ipq807x_gcc-14.4.0_musl.Linux-x86_64.tar.zst"
snapshot.TARGET = "qualcommax/ipq807x"
assert snapshot.choose_asset({name: sha}, "toolchain") == {"filename": name, "sha256": sha}
snapshot.TARGET = "qualcommax/ipq60xx"
try:
    snapshot.choose_asset({name: sha}, "toolchain")
except ValueError:
    pass
else:
    raise AssertionError("ipq60xx resolver accepted an ipq807x toolchain")

planner = load("hybrid_builder", "scripts/hybrid_builder.py")
assert "luci-app-sing-box" in planner.LOCAL_PACKAGES
assert "luci-app-sing-box" in planner.MX4200_LOCAL_PACKAGES
assert "luci-theme-aurora" in planner.MX4200_LOCAL_PACKAGES

for required in (
    'HYBRID_TARGET="qualcommax/ipq807x"',
    'HYBRID_IMAGE_PROFILE="linksys_mx4200v1"',
    'mx4200v1/source.config', 'mx4200v1/packages.txt',
    'mx4200v1/port-ppe-nss.sh', 'mx4200v1/remove.txt',
    '--device mx4200v1',
    'CONFIG_KERNEL_CC_STACKPROTECTOR_REGULAR=y',
    'CONFIG_TARGET_DEVICE_qualcommax_ipq807x_DEVICE_linksys_mx4200v1=y',
    'FIT="$KDIR/linksys_mx4200v1-uImage.itb"',
    'phase device-fit CONFIG_IB= -C target/linux/qualcommax/image',
    '6144 * 1024', 'linksys_mx4200v1',
    'scripts/fit_configs.py', 'scripts/test-sdk-smoke.sh',
    'hybrid_ib_manifest', 'sha256sum --check --status sha256sums',
    'scripts/prepare-sing-box-luci.sh',
    'mx4200v1/stage-overlay.sh',
    'autocore luci-app-sing-box sing-box',

    'phase fwtool-host package/system/fwtool/host/compile',
    'staging_dir/host/bin/fwtool',
    '"$IB_FWTOOL" -i "$SYSUPGRADE_META" "$SYSUPGRADE"',
    'index("linksys,mx4200v1")',
    'sysupgrade.bin lacks readable OpenWrt firmware metadata',
):
    assert required in script, f"Missing MX4200 v1 guardrail: {required}"
for bad in (
    "scripts/apply-immortalwrt-compat.sh", "scripts/repack-immortalwrt.sh",
    "config/immortalwrt-re-ss-01.config", "immortalwrt_ota.py",
    "jdcloud_re-ss-01", "gh release", "gh workflow run",
):
    assert bad not in script, f"Arthur-only or publishing behavior: {bad}"

assert 'CONFIG_TARGET_DEVICE_qualcommax_ipq807x_DEVICE_linksys_mx4200v2=y' in script
assert 'HYBRID_IMAGE_PROFILE' in common and 'HYBRID_REQUIRED_IMAGE_PKGS' in common
assert '--config "$TOOLCHAIN_TARGET"' in toolchain and 'qualcommax/ipq807x' in toolchain
assert '"feat/mx4200v1-hybrid-builder"' in workflow
assert "if: github.event_name != 'pull_request'" in workflow
assert "contents: write" in workflow
assert "workflow_dispatch:" in workflow
assert "actions/upload-artifact@v4" in workflow
assert "mx4200v1/publish-release.sh builder" in workflow
assert "if: success() && github.ref == 'refs/heads/main'" in workflow
assert "gh workflow run" not in workflow
assert "schedule:" not in workflow
# The fast image entry consumes durable Releases. Retired umbrella cannot
# accidentally run a full Builder on ordinary pushes.
simple = (root / ".github/workflows/firmware-simple.yml").read_text()
legacy = (root / ".github/workflows/dual-device-immortalwrt.yml").read_text()
resolver = (root / "mx4200v1/resolve-release.py").read_text()
assert "workflow_dispatch:" in simple and "push:" in simple
assert "uses: ./.github/workflows/builder-immortalwrt-hybrid.yml" not in simple
assert "uses: ./.github/workflows/mx4200v1-hybrid.yml" not in simple
assert "gh release download" in simple
assert "mx4200v1/resolve-release.py" in simple
assert "push:" not in legacy and "schedule:" not in legacy
assert "workflow_dispatch:" in legacy
assert "mx4200-builder-" in resolver
assert '"source_commit"' in resolver
assert "No automatic compile" in resolver

assert "workflow_dispatch:" in old
assert (root / "mx4200v1/remove.txt").read_text().lstrip().startswith("#")
assert 'stage-overlay.sh' in (root / "mx4200v1/build.sh").read_text()
assert 'prepare-sing-box-luci.sh' in (root / "mx4200v1/build.sh").read_text()
assert 'CONFIG_PACKAGE_autocore=y' in (root / "mx4200v1/source.config").read_text()
assert 'CONFIG_PACKAGE_luci-app-sing-box=y' in (root / "mx4200v1/source.config").read_text()
for p in ("jq", "curl", "uclient-fetch", "jsonfilter"):
    assert f"CONFIG_PACKAGE_{p}=y" in (root / "mx4200v1/source.config").read_text()
    assert p in (root / "mx4200v1/packages.txt").read_text().splitlines()
    assert p in script.split("HYBRID_REQUIRED_IMAGE_PKGS=")[1].splitlines()[0]
assert all(p in (root / "mx4200v1/packages.txt").read_text().splitlines() for p in ("autocore", "luci-app-sing-box", "sing-box", "kmod-inet-diag", "kmod-tun"))
print("MX4200 v1 Hybrid offline contracts: OK; compilation and real hardware unverified")
