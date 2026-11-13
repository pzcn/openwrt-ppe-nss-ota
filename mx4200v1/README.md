# Linksys MX4200 v1 — ImmortalWrt PPE + NSS

This isolated target is a **test build**, not a published OTA channel.
It reuses ImmortalWrt master as the OS and JuliusBairaktaris/openwrt-ppe-nss
(ppe-nss branch) for modern wired PPE/EDMA and ath11k NSS Wi-Fi.

## Hardware and image contracts

- Device: Linksys MX4200 **v1 only** (IPQ8174, 512 MiB RAM, NAND/UBI).
- Target: `qualcommax/ipq807x`, device `linksys_mx4200v1`.
- Kernel FIT partition: **6144 KiB**; select REGULAR stack protection rather
  than STRONG, following Julius' `ipq807x-6m-kernel` build profile.
- Images: `squashfs-factory.bin` (for supported OEM install workflows) and
  `squashfs-sysupgrade.bin` (for compatible running OpenWrt/ImmortalWrt).
- v2 is intentionally excluded. Never install the v1 image on v2.
- The original Linksys NAND/UBI and dual-image upgrade logic are inherited
  from ImmortalWrt. No custom `platform.sh` is installed.

## Actions

Run [MX4200 v1 - ImmortalWrt PPE NSS test build](../.github/workflows/mx4200v1.yml)
via GitHub Actions > Run workflow. Changes inside `mx4200v1/` also trigger it.
The job produces two downloadable testing artifacts:

1. `mx4200v1-firmware-test`: factory/sysupgrade firmware, manifest, checksums,
   and the three upstream commit IDs.
2. `mx4200v1-builder-sdk-test`: standalone ImageBuilder and ABI-matched SDK
   compiled from **the same source checkout** for future incremental builds.

This workflow does not publish Releases, create OTA metadata, or flash routers.
The existing Arthur (`ipq60xx`) workflows and releases remain unchanged.

## Initial software selection

PPE wired hardware offload, NSS Wi-Fi, PPE QoS/SQM, Aurora, Simplified Chinese
LuCI, WireGuard, Tailscale, WOL, file manager, ttyd, nlbwmon, PBR, LLDP, and
diagnostic tools. The v1 has 512 MiB RAM, so zram-swap is included.
Sing-box and Arthur's eMMC/F2FS patches are **not** part of this first image.

Source packages and options live in `packages.txt` and `source.config`.
The port script is `port-ppe-nss.sh`; `build.sh` compiles everything.
The first run uses a locally compiled toolchain (the existing toolchain reuse
script is pinned specifically to `ipq60xx` and must not be used here).

## Validation stages

- [x] Isolated profile and upstream port sources defined
- [x] Offline contract checks in the workflow
- [ ] Full successful GitHub Actions compilation and image inspection
- [ ] Confirm the FIT kernel is within the 6 MiB flash partition
- [ ] On-device: boot, WAN/LAN, three radios, NSS Wi-Fi, PPE flows
- [ ] On-device: sysupgrade with config retention and dual-image recovery
- [ ] Publish independently versioned MX4200 v1 Builder/SDK and OTA after tests

**Do not use unattended upgrades or overwrite both stock boot slots during
early testing.** Keep a known-good recovery route and backup configuration
and flash calibration data before changing firmware.
