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

## Hybrid Builder (experimental)

The new [MX4200 v1 Hybrid test workflow](../.github/workflows/mx4200v1-hybrid.yml)
uses official ImmortalWrt `qualcommax/ipq807x` Snapshot APKs and its own
SHA256-pinned toolchain while compiling PPE/NSS kernel, kmods and custom
packages locally. The target profile is `linksys_mx4200v1` only; it never
mixes with Arthur's `qualcommax/ipq60xx` kernel or ImageBuilder.

Push to `feat/mx4200v1-hybrid-builder` for a test run. On success the workflow
uploads factory/sysupgrade binaries and the matching standalone ImageBuilder/
SDK as separate testing artifacts. It **does not publish a Release, generate
OTA metadata, or flash the router**. The original
[full-source workflow](../.github/workflows/mx4200v1.yml) stays as fallback.

Gates: 6 MiB FIT limit, FIT boot configuration, exact v1 package manifest,
both factory and sysupgrade images, and SDK compile smoke. Successful CI is
**not** proof that the router can boot or safely sysupgrade.

### Required sysupgrade metadata

The MX4200 v1 firmware built before the host-`fwtool` fix (Actions
#43592253791) is **not safe to sysupgrade**: its ImageBuilder log includes
`fwtool: command not found`, so the generated sysupgrade binary lacks
the required OpenWrt metadata trailer. Do not bypass this with `sysupgrade -F`.

The Hybrid workflow now builds `package/system/fwtool/host/compile` before
ImageBuilder packaging, checks that the ImageBuilder archive contains the
host binary, and **requires `fwtool -i` to read the produced sysupgrade file**.
CI also checks the metadata for the `linksys,mx4200v1` supported-device
identifier. Any missing or invalid metadata fails the workflow before
firmware artifacts are uploaded. Use `*-squashfs-sysupgrade.bin` from a
successful **new** run for OpenWrt-to-OpenWrt upgrades; the
`*-squashfs-factory.bin` has a different purpose.

## MX4200 v1: LuCI temperature, PPE update removal, sing-box

- **Temperature:** install ImmortalWrt `autocore` to provide
  `/sbin/tempinfo`. LuCI Status > Overview uses `luci.getTempInfo`.
  The stock qualcommax kernel already has `CONFIG_QCOM_TSENS=y`.
  After flashing, inspect `/sbin/tempinfo` and
  `/sys/class/thermal/thermal_zone*/{type,temp}` if no valid reading.
- **Remove Julius system updater:** strip the `ppe-update` service, config,
  uci-default, keep.d, command, LuCI menu, ACL and view from the PPE base
  overlay. A one-time UCI-default cleans any settings carried over by
  sysupgrade. Standard System > Backup / Flash Firmware remains.
- **sing-box:** use the same pinned `lauyv/luci-app-sing-box` v0.4.7 build
  as Arthur, with official `sing-box`, `flock`, `kmod-inet-diag` and
  `kmod-tun`, no HomeProxy.

Both the MX4200 Hybrid build and the full-source fallback use the shared
`mx4200v1/stage-overlay.sh` cleanup. Boot confirmation alone does not
verify temperature readings, sing-box routing or upgrade behavior.

## Fast firmware repack from a verified MX4200 Hybrid ImageBuilder

The independent [fast-repack workflow](../.github/workflows/mx4200v1-fast-repack.yml)
uses the immutable ImageBuilder from successful [Hybrid run #43602206711](https://github.com/pzcn/openwrt-ppe-nss-ota/actions/runs/43602206711).
It downloads that run's ImageBuilder, original SHA256 manifest, base overlay
and local kmod provenance, then produces MX4200 v1 factory/sysupgrade files
**without recompiling kernel, PPE/NSS, SDK, or the toolchain**.

- Successful reference repack: [Actions #43609137873](https://github.com/pzcn/openwrt-ppe-nss-ota/actions/runs/43609137873),
  artifact `mx4200v1-fast-repacked-firmware-test`. The actual sysupgrade
  metadata was parsed using the ImageBuilder's `fwtool` and contains
  `supported_devices: ["linksys,mx4200v1"]`.
- `mx4200v1/repack-hybrid.sh` verifies SHA256 for the parent ImageBuilder,
  overlay and official snapshot lock, checks the bundled 6 MiB FIT, keeps
  Linksys upstream NAND/UBI upgrade files intact, rejects non-parent kmods,
  and validates factory/sysupgrade outputs with a new SHA256 manifest.
- Any changes to `source.config` or `port-ppe-nss.sh` require rebuilding the
  MX4200 Builder. For userspace package additions, the requested APK must
  already exist in the pinned offline ImageBuilder; missing packages cannot
  silently fall back to another target or kernel ABI.
- Run on `feat/mx4200v1-fast-repack` pushes. The workflow also accepts
  `source_run_id` and `source_commit` inputs when manually dispatched after
  the workflow has been made available on the default branch. Source
  artifacts currently retain for 14 days, so a durable long-term cache or
  independently retained immutable base Builder is still needed.
- This workflow is a **zero-delta reuse of the already pinned official APK
  set**, not yet a new MX4200 official-APK delta layer. It does not publish
  Release/OTA or flash any router. The prior full-source and full Hybrid
  workflows remain available for new kernel/ABI builds.
