# JDCloud RE-SS-01 PPE+NSS OTA ImageBuilder

A lightweight firmware packager for **JDCloud RE-SS-01 / AX1800 Pro (IPQ60xx; expanded hardware variant: 1 GiB RAM, 64 GB eMMC)**.

This repository **does not compile Linux, PPE, NSS or Wi-Fi drivers**. It downloads the latest full-build ImageBuilder and overlay from [JuliusBairaktaris/Qualcommax_NSS_Builder](https://github.com/JuliusBairaktaris/Qualcommax_NSS_Builder), adds the prebuilt Aurora theme APK, and generates a customized sysupgrade image from the same upstream hardware stack.

## Included

- Modern Linux 6.18 PPE wired offload and NSS Wi-Fi offload: **unchanged upstream**
- Aurora LuCI theme (prebuilt APK from [eamonxg/luci-theme-aurora/releases](https://github.com/eamonxg/luci-theme-aurora/releases))
- Simplified Chinese LuCI language packs, including the selected apps
- File manager, web terminal, per-client bandwidth, statistics, Wi-Fi station history, irqbalance UI, LLDP, PBR
- WireGuard UI/tools and diagnosis: tcpdump, ip-full, conntrack, conntrack netlink
- **Persistent ext4 overlay on the expanded eMMC:** existing `/dev/mmcblk0p27` mounted as `/overlay` during PREINIT
- ext4 maintenance utilities (`e2fsprogs`); no F2FS driver or `mkfs.f2fs` is required for the configured overlay
- Keeps Bootstrap as fallback
- Removes ip-tiny, libopenssl-oqsprovider and liboqs when dependency resolution permits

All selected LuCI apps and their translations are from OpenWrt's official LuCI feed. **Only Aurora requires a third-party APK.** This intentionally reuses Aurora's released APK, not the newer unreleased GitHub source commit.

## Persistent storage on the expanded eMMC

The expanded device's reported layout is:

- **p18:** 2 GiB rootfs partition. Its SquashFS firmware remains unchanged.
- **p27:** approximately 54.13 GiB, already formatted as ext4.

The firmware embeds `/etc/config/fstab` in the read-only image and configures `/dev/mmcblk0p27` as extroot at `/overlay`. OpenWrt's early `mount_root` path can read this ROM-side configuration and mount p27 before trying to initialize the unused tail of p18. This avoids the failed F2FS initialization path that previously left the device using `/tmp/root` (tmpfs).

**The firmware does not format p27, run mkfs, wipe the partition, change the GPT, or modify U-Boot.** On a successful first extroot boot, OpenWrt creates `/overlay/upper` and `/overlay/work` on the existing ext4 filesystem. Back up p27 before flashing anyway: if those directories already exist, they will be used by the overlay. Keep personal files in a separate directory such as `/overlay/data`, not inside `upper` or `work`.

This configuration uses the whole p27 filesystem as the writable system overlay; it is **not** mounted as a separate `/mnt/storage` volume. The p18 SquashFS partition is left intact, and its unused tail is not reformatted by this extroot configuration.

The fstab entry assumes the expanded device exposes the partition as `/dev/mmcblk0p27`. If the device node is different or p27 cannot be mounted, extroot will not activate and the system may fall back to its internal rootfs_data path (which may still be volatile on a device without F2FS support). Verify the mount after flashing:

```sh
grep -E ' /overlay |overlayfs:' /proc/mounts
df -h /overlay /
block info | grep mmcblk0p27
logread | grep -i extroot
```

A successful boot should show `/dev/mmcblk0p27` mounted on `/overlay`, with `overlayfs:/overlay` backing `/`.

## Build and download

1. Go to [Actions → Build RE-SS-01 firmware](../../actions/workflows/build.yml).
2. Click **Run workflow** (leave upstream tag blank to use upstream's newest published release).
3. Download the **sysupgrade.bin** and **sha256sums** from [Releases](../../releases).

New upstream releases are also checked daily. The scheduled workflow skips builds already published for the same upstream, Aurora and storage-fix revision combination.

The build uses GitHub-hosted runners and needs no local OpenWrt toolchain.

### Upgrade

This outputs **sysupgrade only**. Use it from an existing compatible OpenWrt/PPE+NSS installation; it is not a U-Boot/factory image. Confirm the expanded partition layout and back up p27 before upgrading. Do not flash with `sysupgrade -F`.

### Device updates

This repository automates generating releases, **not on-device OTA**. The upstream `ppe-update` mechanism still points to upstream builds; automatic upstream replacement is disabled by our first-boot overlay to avoid silently replacing your custom image. Upgrade manually from this repository's Releases.

### Wi-Fi credentials

No Wi-Fi password is embedded in this **public** firmware or workflow. Configure WPA2/WPA3 and the 5 GHz network locally in LuCI after flashing. Do not put credentials into a public workflow, Release or firmware binary.

## Files

- `.github/workflows/build.yml` — scheduled/manual GitHub Actions and Releases
- `scripts/build.sh` — obtain and assemble upstream ImageBuilder + Aurora APK
- `scripts/resolve_packages.py` — reconstruct upstream package manifest and custom additions/removals
- `config/add.txt` — software packages to install
- `config/remove.txt` — default packages to leave out
- `files/etc/config/fstab` — PREINIT extroot configuration for p27
- `files/etc/uci-defaults/95-luci-preferences` — Chinese + Aurora defaults

## Compatibility and limitations

- This persistence configuration is specifically for the described **expanded 64 GB eMMC layout** with p27 at `/dev/mmcblk0p27`. Do not assume it applies to a stock or differently partitioned RE-SS-01.
- The upstream builder currently includes `jdcloud_re-ss-01` only in its `ipq60xx-512m` group; its `ipq60xx-1g` group does not include this device profile. The workflow therefore retains the only published RE-SS-01 profile instead of selecting an ImageBuilder that cannot build this device. A physical RAM upgrade does not by itself provide an upstream 1 GiB NSS/ath11k build profile.
- Requires upstream ImageBuilder, upstream OpenWrt snapshot package feeds and public GitHub releases to remain accessible from GitHub Actions.
- **APK ABI/version compatibility is not guaranteed** for latest OpenWrt snapshot feeds or the Aurora prebuilt package; the job fails if dependencies cannot be resolved, rather than publishing a partial image.
- Official OpenWrt packages are fetched only for non-kernel user-space additions. Kernel modules are taken from the upstream **matching IPQ60xx ImageBuilder**, never from the generic OpenWrt snapshot feed.
- The upstream author does not claim RE-SS-01 hardware has undergone full validation. Always retain a recovery path and test wireless NSS.
