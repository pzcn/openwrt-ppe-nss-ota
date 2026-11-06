# Software sources and dependencies

**Standard official OpenWrt LuCI feed**: filemanager, ttyd, nlbwmon, statistics, wifihistory, irqbalance, lldpd, pbr, and their zh-cn translations. They do **not** require a third-party feed.

**Official OpenWrt userspace feeds**: wireguard-tools, tcpdump, ip-full, conntrack, application daemons such as ttyd, collectd, nlbwmon, irqbalance, lldpd and pbr. Their dependencies must resolve from the pinned image's own local packages, or the snapshot feeds.

**Upstream matching kernel feed only**: kmod-nf-conntrack-netlink and kmod-fs-ext4, matched to this exact PPE+NSS kernel release. The ext4 driver is also selected by the upstream target defaults; it is listed explicitly so the persistence requirement is visible in this repository.

**Persistent storage for the expanded eMMC variant**:
- `block-mount` provides the early extroot `block` helper. It is already selected in the upstream common build config and is also listed as an explicit package requirement here.
- `kmod-fs-ext4` provides the matching kernel filesystem driver.
- `e2fsprogs` provides ext4 maintenance utilities.
- `files/etc/config/fstab` is embedded in the read-only image and mounts the existing `/dev/mmcblk0p27` ext4 partition as `/overlay` during PREINIT.
- p27 is **not formatted**. No F2FS driver or `mkfs.f2fs` is needed for this overlay path.

This storage configuration is specific to the expanded 64 GB eMMC partition layout. It does not repartition the device or alter U-Boot.

**External third-party APK**: Aurora, pinned to a release from eamonxg/luci-theme-aurora. Requires APK, not IPK; included in the ImageBuilder local package repository. Its source commit may be newer than the latest published release.

**Removal candidates**: ip-tiny, libopenssl-oqsprovider, liboqs. If a dependency requires them, image assembly fails, requiring an explicit decision, rather than silently overriding removals.

Theme changes do not modify NSS/PPE acceleration. The workflow intentionally keeps Bootstrap.
