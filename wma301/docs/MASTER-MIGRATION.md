# WMA301 v2.0 migration to ImmortalWrt master / Linux 6.18

## Purpose and status

- Use official `immortalwrt/immortalwrt` `master`, retaining the open-source `mt76/mt7915e` + PPE/WED driver architecture.
- The daily quick path uses `https://downloads.immortalwrt.org/snapshots/targets/mediatek/filogic/`; snapshot ImageBuilder filename is `immortalwrt-imagebuilder-mediatek-filogic.Linux-x86_64.tar.zst`.
- The manual full-source path uses the newest `master` HEAD to build recovery and sysupgrade FITs.
- On 2026-11-16, the published Filogic snapshot is `r42542-e695009c15` and uses 6.18.55; the current `master` source is already 6.18.60. Never mix kernels or APK/kmod feeds from different revisions.
- This migration is **experimental and hardware-untested**. The stable 25.12 project `main` branch is not changed by this review branch.

## Safety contracts

- TP-Link WMA301 **v2.0 only**, already migrated to a single 121 MiB UBI partition.
- Preserve original BL2/BL31 and current custom BL33. Do not overwrite protected FIP, factory_info, art or config partitions.
- Preserve `fit`, `ubootenv`, `ubootenv2` and `rootfs_data`. A sysupgrade FIT is **not** a raw NAND image.
- Retain `kmod-mt7915e`, MT7981 firmware and WO firmware; this is **not** chasey-dev's `mt_wifi/HNAT/WARP` driver set.
- OTA remains off by default. PR builds never publish OTA releases.

## CI acceptance criteria

1. Run all offline tests and validate firmware package names/geometry.
2. Resolve `version.buildinfo` and the exact ImageBuilder + SDK hashes from the same official snapshot.
3. Fetch the commit corresponding to that snapshot revision; check `KERNEL_PATCHVER=6.18` and the kernel tarball SHA256.
4. Compile only WMA301 DTB against the snapshot's matching Linux source, reuse official Image and packages; fail on mismatched ABI or missing structure.
5. Verify FIT payloads, SquashFS, hashes, NAND partition protections, `rootdisk` and packaged images. Upload 14-day Artifact; no automatic flashing.
6. Independently run the manually dispatched `master` full build and verify **both** FITs.

## Hardware tests before merging to production

- Boot both rescue and sysupgrade FIT on migrated WMA301 v2.0.
- Verify wired DSA switch (LAN1-3/WAN), wireless EEPROM/MAC addresses and radio operation.
- Verify PPE/WED behavior, reboot persistence of UBI `rootfs_data`, and recovery if sysupgrade fails.
- Keep the 25.12 production version available for rollback and do not enable OTA without physical validation.
