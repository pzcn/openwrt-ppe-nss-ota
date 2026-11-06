# JDCloud RE-SS-01 PPE+NSS OTA ImageBuilder

A lightweight firmware packager for **JDCloud RE-SS-01 / AX1800 Pro**. The device originally has 512 MiB RAM and 64 GB eMMC; this installation has been upgraded to **1 GiB RAM** (storage size unchanged).

This repository **does not compile Linux, PPE, NSS or Wi-Fi drivers**. It downloads the latest full-build ImageBuilder and overlay from [JuliusBairaktaris/Qualcommax_NSS_Builder](https://github.com/JuliusBairaktaris/Qualcommax_NSS_Builder), adds the prebuilt Aurora theme APK, and generates a customized sysupgrade image from the same upstream hardware stack.

## Included

- Modern Linux 6.18 PPE wired offload and NSS Wi-Fi offload: **unchanged upstream**
- Aurora LuCI theme (prebuilt APK from [eamonxg/luci-theme-aurora/releases](https://github.com/eamonxg/luci-theme-aurora/releases))
- Simplified Chinese LuCI language packs, including the selected apps
- File manager, web terminal, per-client bandwidth, statistics, Wi-Fi station history, irqbalance UI, LLDP, PBR
- WireGuard UI/tools and diagnosis: tcpdump, ip-full, conntrack, conntrack netlink
- **Custom premium PPE / NSS monitor:** LuCI Status page with real hardware connection history, driver health and read-only debug counters
- **Customized OTA update:** only follows this repository's GitHub Releases, checks exact device and build metadata, validates SHA256, and uses the upstream package migration logic
- **Standard OpenWrt rootfs_data persistence:** include matching `kmod-fs-f2fs`, `f2fs-tools` and `mkf2fs`; p18 SquashFS tail is the normal writable overlay
- **Separate data partition:** p27 keeps its existing ext4 filesystem and mounts at `/mnt/storage` instead of `/overlay`
- Keeps Bootstrap as fallback
- Removes ip-tiny, libopenssl-oqsprovider and liboqs when dependency resolution permits

All selected LuCI apps and their translations are from OpenWrt's official LuCI feed. **Only Aurora requires a third-party APK.** This intentionally reuses Aurora's released APK, not the newer unreleased GitHub source commit.

## Standard OpenWrt rootfs_data storage

The factory 64 GB eMMC layout reported for this device has a 2 GiB rootfs partition (observed as p18) and an existing ~54.13 GiB ext4 storage partition (p27).

The firmware now follows the **stock fstools mechanism**, not extroot. On first boot, fstools detects the SquashFS image in the active rootfs partition and uses the writable space after the image (via a loop device) for `rootfs_data`. If unformatted and larger than 100 MiB, fstools normally chooses F2FS. This build adds the matching early-autoloadable `kmod-fs-f2fs` from the upstream ImageBuilder and the official `f2fs-tools` / `mkf2fs` / `f2fsck` user tools.

The **p27 ext4 partition remains separate**, at `/mnt/storage`. It is *not* formatted, wiped or repartitioned. First boot may format the **previously unformatted p18 rootfs tail** as F2FS; back up data and settings first. We do not alter U-Boot, GPT, Linux, PPE, NSS or Wi-Fi drivers.

The official RE-SS-01 device profile itself does **not** explicitly select F2FS packages, but some other official OpenWrt devices (e.g. Link NN6000) do. We add these missing packages while keeping the upstream kernel unchanged. This is an application of the official rootfs_data boot mechanism, not a claim that the official RE-SS-01 image already contains the same dependencies.

### Migrating from our previous p27 extroot firmware

Back up the router configuration **off the device** and any important files on p27 before flashing. A saved fstab from the old image points p27 to `/overlay`; a one-time UCI defaults script changes precisely that known entry to `/mnt/storage` if `sysupgrade` restores it. Other mount entries and p27 files are preserved. The old `upper` and `work` directories on p27 are intentionally not deleted. The previous firmware remains available in Releases for recovery.

After flashing and rebooting, verify:

```sh
cat /proc/mounts | grep -E ' /overlay | /mnt/storage |overlayfs:'
df -h /overlay /mnt/storage
block info | grep mmcblk0p27
logread | grep -Ei 'f2fs|rootfs_data|overlay|extroot'
```

Expected: `/overlay` is backed by a loop device with F2FS, and `/mnt/storage` is backed by p27 with ext4. `/overlay` must **not** be tmpfs or p27. On some systems the first boot includes restoring saved settings, so review the mount result again after another reboot.

## Build and download

1. Go to [Actions → Build RE-SS-01 firmware](../../actions/workflows/build.yml).
2. Click **Run workflow** (leave upstream tag blank to use upstream's newest published release).
3. Download the **sysupgrade.bin** and **sha256sums** from [Releases](../../releases).

New upstream releases are also checked daily. The scheduled workflow skips builds already published for the same upstream, Aurora and storage-fix revision combination.

The build uses GitHub-hosted runners and needs no local OpenWrt toolchain.

### Upgrade

This outputs **sysupgrade only**. Use it from an existing compatible OpenWrt/PPE+NSS installation; it is not a U-Boot/factory image. Confirm the partition layout and back up the current settings **off the router**, as well as any important p27 data, before upgrading. Do not flash with `sysupgrade -F`.

### Device updates

The custom `ppe-update` bundled in this image now tracks **only this repository's GitHub Releases**, rather than fetching an uncustomized upstream image. It checks a release's `ota.json` metadata (board, build number, source), hashes the firmware and package manifest, simulates reinstallation of extra packages and uses `sysupgrade` with settings preservation. If the package check fails, the one-click update is disabled. **Automatic updates remain OFF until enabled explicitly** in LuCI.

Starting with this OTA-enabled image, go to **System → Firmware update / 系统 → 固件更新** to check your customized release channel. The previous images lack this implementation and must be upgraded manually once. See [Custom OTA design and troubleshooting](docs/CUSTOM-OTA.md).

**Warning:** No firmware upgrade is guaranteed to preserve all configuration or user-installed software. Export a configuration backup to your PC first. Never use `sysupgrade -F`.

### Wi-Fi credentials

No Wi-Fi password is embedded in this **public** firmware or workflow. Configure WPA2/WPA3 and the 5 GHz network locally in LuCI after flashing. Do not put credentials into a public workflow, Release or firmware binary.

## Files

- `docs/PPE-NSS-MONITOR.md` — monitor page data sources, limitations and troubleshooting
- `docs/CUSTOM-OTA.md` — OTA data flow, safety checks and testing
- `files/usr/sbin/ppe-update` — customized OTA with an upstream-compatible CLI
- `scripts/write_ota_metadata.py` — creates per-release `ota.json`
- `scripts/tests/test-custom-ota.sh` — offline CLI and metadata tests
- `.github/workflows/build.yml` — scheduled/manual GitHub Actions and Releases
- `scripts/build.sh` — obtain and assemble upstream ImageBuilder + Aurora APK
- `scripts/resolve_packages.py` — reconstruct upstream package manifest and custom additions/removals
- `config/add.txt` — software packages to install
- `config/remove.txt` — default packages to leave out
- `files/www/luci-static/resources/view/status/ppe-nss-monitor.js` — PPE / NSS status dashboard
- `files/usr/share/rpcd/ucode/luci.ppe-nss-monitor` — read-only telemetry endpoint
- `files/etc/config/fstab` — separate ext4 storage mount at `/mnt/storage` (no extroot)
- `files/etc/uci-defaults/96-migrate-legacy-extroot` — converts the previous preserved p27 extroot configuration
- `files/etc/uci-defaults/95-luci-preferences` — Chinese + Aurora defaults

## Compatibility and limitations

- This persistence configuration uses the original **64 GB eMMC layout**, with p27 at `/dev/mmcblk0p27`. Verify actual device numbering before flashing; a different partition layout needs different storage mount settings.
- The rootfs_data initialization may format the **unformatted tail of the active rootfs partition**; do not store personal data there. It never runs mkfs on p27.
- The upstream builder currently includes `jdcloud_re-ss-01` only in its `ipq60xx-512m` group; its `ipq60xx-1g` group does not include this device profile. The workflow therefore retains the only published RE-SS-01 profile instead of selecting an ImageBuilder that cannot build this device. A physical RAM upgrade does not by itself provide an upstream 1 GiB NSS/ath11k build profile.
- Requires upstream ImageBuilder, upstream OpenWrt snapshot package feeds and public GitHub releases to remain accessible from GitHub Actions.
- **APK ABI/version compatibility is not guaranteed** for latest OpenWrt snapshot feeds or the Aurora prebuilt package; the job fails if dependencies cannot be resolved, rather than publishing a partial image.
- Official OpenWrt packages are fetched only for non-kernel user-space additions. Kernel modules are taken from the upstream **matching IPQ60xx ImageBuilder**, never from the generic OpenWrt snapshot feed.
- The upstream author does not claim RE-SS-01 hardware has undergone full validation. Always retain a recovery path and test wireless NSS.
