# JDCloud RE-SS-01 PPE+NSS OTA ImageBuilder

A lightweight firmware packager for **JDCloud RE-SS-01 / AX1800 Pro**. The device originally has 512 MiB RAM and 64 GB eMMC; this installation has been upgraded to **1 GiB RAM** (storage size unchanged).

This repository **does not compile Linux, PPE, NSS or Wi-Fi drivers**. It downloads the latest full-build ImageBuilder and overlay from [JuliusBairaktaris/Qualcommax_NSS_Builder](https://github.com/JuliusBairaktaris/Qualcommax_NSS_Builder), adds the prebuilt Aurora theme APK, and generates a customized sysupgrade image from the same upstream hardware stack.

## Included

- Modern Linux 6.18 PPE wired offload and NSS Wi-Fi offload: **unchanged upstream**
- Aurora LuCI theme (prebuilt APK from [eamonxg/luci-theme-aurora/releases](https://github.com/eamonxg/luci-theme-aurora/releases))
- Simplified Chinese LuCI language packs, including SQM and BCP38; native Chinese LMO catalogs for upstream PPE Hardware QoS and the firmware update menu
- File manager, web terminal, per-client bandwidth, statistics, Wi-Fi station history, irqbalance UI, LLDP, PBR
- WireGuard UI/tools and diagnosis: tcpdump, ip-full, conntrack, conntrack netlink
- **PPE / NSS monitor (native LuCI):** standard status tables, last-24-sample trend, driver status and read-only debug counters; no custom dark styling.
- **Online OTA alongside Backup / Flash Firmware:** native LuCI sister section in **System → Backup / Flash Firmware**; manual OTA only requires matching custom device, checksums and `sysupgrade -T`, with extra-package migration as a warning rather than a blocker. Auto OTA remains stricter.
- **Dr.COM campus authentication (WAN-only):** editable login/logout URLs, optional saved credentials, daily 00:00 cron login; every HTTP request binds to the actual WAN L3 device and domain lookups use validated WAN DNS, never a WireGuard fallback.
- **Standard OpenWrt rootfs_data persistence:** include matching `kmod-fs-f2fs`, `f2fs-tools` and `mkf2fs`; p18 SquashFS tail is the normal writable overlay
- **Separate data partition:** p27 keeps its existing ext4 filesystem and mounts at `/mnt/storage` instead of `/overlay`
- Keeps Bootstrap as fallback
- Removes ip-tiny, libopenssl-oqsprovider and liboqs when dependency resolution permits

Officially translated LuCI apps use the Chinese language packs from OpenWrt's LuCI feed. **PPE Hardware QoS and the OTA menu have custom local LMO translations because the upstream UI lacks a matching official zh-cn language package.** Only Aurora requires a third-party APK. This intentionally reuses Aurora's released APK, not the newer unreleased GitHub source commit.

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

## LNU Dr.COM campus login

Go to **Network → 校园网认证** in LuCI. Enter your account and password, optionally tick **记住账号与密码**, then click **连接校园网**. Both the **full login URL** and **full logout URL** can be edited and saved independently (including IP/domain, port, path, query parameters). **No domain or gateway URL is prefilled in a new installation.** Fill in the two complete URLs, click **保存认证地址**, and only trust the success message when both values have been committed and read back from UCI.

To enable **每天 00:00 自动认证一次**, first save a remembered account and password, then enable the checkbox and click **保存自动认证设置**. Cron performs one POST at **00:00 router-local time** every day; verify that the router timezone is Asia/Shanghai for Beijing midnight. Auto-auth remains off by default. No periodic retries or boot-time login are included. Clearing remembered credentials disables auto-auth. **All login/logout/status/cron requests are pinned to WAN** using curl's `if!` interface binding and never fall back to WireGuard. For hostnames, DNS must also have a verified WAN route; if WAN-only DNS is unavailable, use a numeric IPv4 gateway URL.

**Important:** HTTP sends the account and password without transport encryption; only use on the trusted campus network and preferably manage LuCI over HTTPS. Remembered credentials are stored only in root-readable OpenWrt configuration and may be included in sysupgrade configuration backups. Logout endpoint and login-result markers must still be verified on the campus network. The app does not auto-reconnect, modify network routes or circumvent school gateway policy.

## Build and download

1. Go to [Actions → Build RE-SS-01 firmware](../../actions/workflows/build.yml).
2. Click **Run workflow** (leave upstream tag blank to use upstream's newest published release).
3. Download the **sysupgrade.bin** and **sha256sums** from [Releases](../../releases).

New upstream releases are also checked daily. The scheduled workflow skips builds already published for the same upstream, Aurora and storage-fix revision combination.

The build uses GitHub-hosted runners and needs no local OpenWrt toolchain.

### Upgrade

This outputs **sysupgrade only**. Use it from an existing compatible OpenWrt/PPE+NSS installation; it is not a U-Boot/factory image. Confirm the partition layout and back up the current settings **off the router**, as well as any important p27 data, before upgrading. Do not flash with `sysupgrade -F`.

### Device updates

The custom `ppe-update` tracks **only this repository's GitHub Releases**, rather than fetching an uncustomized upstream image. It verifies `ota.json`, the board and custom release channel, hashes the firmware and package manifest, and runs `sysupgrade -T` before installing. **Manual updates are not blocked by inability to simulate reinstalling optional APK packages**; users see a warning and these packages are restored on a best-effort basis after reboot. Unattended updates still require preflight of optional packages and are OFF until enabled explicitly.

Go to **System → Backup / Flash Firmware（系统 → 备份/升级）** for **online OTA**, directly below the standard local firmware flash module; these features now share the same native LuCI page. The old separate page is called **OTA 自动更新设置** and controls the optional unattended schedule. Existing firmware using the previous strict OTA may need **one manual upload of the latest sysupgrade.bin** to obtain the relaxed upgrade behavior. See [Custom OTA design and troubleshooting](docs/CUSTOM-OTA.md).

**Warning:** No firmware upgrade is guaranteed to preserve all configuration or user-installed software. Export a configuration backup to your PC first. Never use `sysupgrade -F`.

### Wi-Fi credentials

No Wi-Fi password is embedded in this **public** firmware or workflow. Configure WPA2/WPA3 and the 5 GHz network locally in LuCI after flashing. Do not put credentials into a public workflow, Release or firmware binary.

## Files

- `docs/PPE-NSS-MONITOR.md` — monitor page data sources, limitations and troubleshooting
- `docs/CUSTOM-OTA.md` — OTA data flow, safety checks and testing
- `docs/CHINESE-LOCALIZATION.md` — localization coverage, how to edit the Chinese strings
- `docs/DRCOM-CAMPUS.md` — Dr.COM campus portal login/logout details, privacy, limitations and testing
- `files/usr/share/rpcd/ucode/luci.drcom` — minimal RPC credential handling with read-only status
- `files/usr/libexec/drcom-web` — curl transport for manual/scheduled form login, with no password in process arguments
- `files/usr/libexec/drcom-schedule` — idempotent midnight cron setup
- `files/etc/init.d/drcom` — refreshes the cron schedule on boot
- `config/translations/` — source Chinese dictionaries for PPE QoS and OTA
- `scripts/build_luci_i18n.py` — compiles native LuCI LMO catalogs
- `files/usr/sbin/ppe-update` — customized OTA with manual vs unattended package policy
- `files/www/luci-static/resources/view/system/flash.js` — native Backup / Flash view with embedded online OTA sibling section
- `files/www/luci-static/resources/view/system/ppe-update.js` — advanced automatic OTA schedule settings
- `scripts/write_ota_metadata.py` — creates per-release `ota.json`
- `scripts/tests/test-custom-ota.sh` — offline CLI and metadata tests
- `.github/workflows/build.yml` — scheduled/manual GitHub Actions and Releases
- `scripts/build.sh` — obtain and assemble upstream ImageBuilder + Aurora APK
- `scripts/resolve_packages.py` — reconstruct upstream package manifest and custom additions/removals
- `config/add.txt` — software packages to install
- `config/remove.txt` — default packages to leave out
- `files/www/luci-static/resources/view/status/ppe-nss-monitor-native.js` — native LuCI PPE/NSS monitor
- `files/www/luci-static/resources/view/network/drcom-native.js` — native LuCI Dr.COM form and saved URL verification
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
