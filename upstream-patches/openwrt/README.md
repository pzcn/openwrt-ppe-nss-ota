# Upstream submission preparation: JDCloud RE-SS-01

These files are an isolated proposed change for **openwrt/openwrt**. They are kept on a separate staging branch of this repository, which is **not an OpenWrt fork**. No upstream PR has been opened by this branch.

## 1. F2FS dependencies

Proposed PR title:

`qualcommax: ipq60xx: add F2FS support for JDCloud RE-SS-01`

Patch: `0001-qualcommax-ipq60xx-add-f2fs-for-jdcloud-re-ss-01.patch`

Suggested PR description:

> JDCloud RE-SS-01 uses an eMMC-backed squashfs root filesystem with writable `rootfs_data` on a loop device. When creating this overlay, fstools chooses F2FS on this large block-backed area. The device image currently includes neither the F2FS kernel module nor the filesystem formatting tools.
>
> On a tested RE-SS-01 (modified to 1 GiB RAM / 64 GB eMMC), the F2FS-less image booted with `/rom` mounted as squashfs, but `mount_root` logged `overlay filesystem in /dev/loop0 has not been formatted yet` followed by `no usable overlay filesystem found, using tmpfs overlay`. As a result, configuration changes were lost on an ordinary reboot.
>
> After adding `kmod-fs-f2fs` and `f2fs-tools` to the firmware, the operator confirmed that the overlay was persistent and settings survived reboots.
>
> Add these two dependencies to the RE-SS-01 device package list. Link NN6000 devices in the same target already list the same packages.
>
> Testing was on a custom ImmortalWrt-based build, not an official OpenWrt image. Only the RE-SS-01 package list is changed; eMMC partitions and the ext4 data partition are unaffected.

After creating a genuine fork of `openwrt/openwrt` under `pzcn`, apply this patch on an up-to-date branch and use a Git commit with a DCO sign-off (`git commit -s`).

## 2. Sysupgrade configuration preservation

An upstream PR **already exists**, so please do not submit a duplicate:

- https://github.com/openwrt/openwrt/pull/26576

It covers `jdcloud,re-ss-01` plus four other eMMC devices. Proposed additional hardware test comment (not submitted because the linked GitHub integration returned HTTP 403 for upstream comments):

> Confirmed on JDCloud RE-SS-01 (ipq6000, eMMC) using a custom ImmortalWrt build based on the same upstream ipq60xx upgrade code. With F2FS support in both variants, sysupgrade's Keep settings option did not preserve configuration without a platform_copy_config hook; adding the hook to call emmc_copy_config fixed the upgrade-time config loss. Hardware tested was modified to 1 GiB RAM and 64 GB eMMC; this is not a test of official OpenWrt firmware.

