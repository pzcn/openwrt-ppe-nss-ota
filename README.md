# JDCloud RE-SS-01 PPE+NSS OTA ImageBuilder

A lightweight firmware packager for **JDCloud RE-SS-01 / AX1800 Pro (IPQ60xx, 512 MiB)**.

This repository **does not compile Linux, PPE, NSS or Wi-Fi drivers**. It downloads the latest full-build ImageBuilder and overlay from [JuliusBairaktaris/Qualcommax_NSS_Builder](https://github.com/JuliusBairaktaris/Qualcommax_NSS_Builder), adds prebuilt Aurora theme APK, and generates a customized sysupgrade image from the same upstream hardware stack.

## Included

- Modern Linux 6.18 PPE wired offload and NSS Wi-Fi offload: **unchanged upstream**
- Aurora LuCI theme (prebuilt APK from [eamonxg/luci-theme-aurora](https://github.com/eamonxg/luci-theme-aurora/releases))
- Simplified Chinese LuCI language packs, including the selected apps
- File manager, web terminal, per-client bandwidth, statistics, Wi-Fi station history, irqbalance UI, LLDP, PBR
- WireGuard UI/tools and diagnosis: tcpdump, ip-full, conntrack, conntrack netlink
- Keeps Bootstrap as fallback
- Removes ip-tiny, libopenssl-oqsprovider and liboqs when dependency resolution permits

All selected LuCI apps and their translations are from OpenWrt's official LuCI feed. **Only Aurora requires a third-party APK.** This intentionally reuses Aurora's released APK, not the newer unreleased GitHub source commit.

## Build and download

1. Go to [Actions → Build RE-SS-01 firmware](../../actions/workflows/build.yml).
2. Click **Run workflow** (leave upstream tag blank to use upstream's newest published release).
3. Download the **sysupgrade.bin** and **sha256sums** from [Releases](../../releases).

New upstream releases are also checked daily. The scheduled workflow skips builds already published for the same upstream and Aurora release combination.

The build uses GitHub-hosted runners and needs no local OpenWrt toolchain.

### Upgrade

This outputs **sysupgrade only**. Use it from an existing compatible OpenWrt/PPE+NSS installation; it is not a U-Boot/factory image. Confirm partition layout and backup first. Do not flash with `sysupgrade -F`.

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
- `files/etc/uci-defaults/95-luci-preferences` — Chinese + Aurora defaults

## Compatibility and limitations

- Requires upstream ImageBuilder, upstream OpenWrt snapshot package feeds and public GitHub releases to remain accessible from GitHub Actions.
- **APK ABI/version compatibility is not guaranteed** for latest OpenWrt snapshot feeds or the Aurora prebuilt package; the job fails if dependencies cannot be resolved, rather than publishing a partial image.
- Official OpenWrt packages are fetched only for non-kernel user-space additions. The selected kernel module is taken from the upstream **matching IPQ60xx ImageBuilder**, never from the generic OpenWrt snapshot feed.
- The upstream author does not claim RE-SS-01 hardware has undergone full validation. Always retain a recovery path and test wireless NSS.
