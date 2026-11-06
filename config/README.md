# Software sources and dependencies

**Standard official OpenWrt LuCI feed**: filemanager, ttyd, nlbwmon, statistics, wifihistory, irqbalance, lldpd, pbr, and their zh-cn translations. They do **not** require a third-party feed.

**Official OpenWrt userspace feeds**: wireguard-tools, tcpdump, ip-full, conntrack, application daemons such as ttyd, collectd, nlbwmon, irqbalance, lldpd and pbr. Their dependencies must resolve from the pinned image's own local packages, or the snapshot feeds.

**Upstream matching kernel feed only**: kmod-nf-conntrack-netlink, matched to this exact PPE+NSS kernel release.

**External third-party APK**: Aurora, pinned to a release from eamonxg/luci-theme-aurora. Requires APK, not IPK; included in the ImageBuilder local package repository. Its source commit may be newer than the latest published release.

**Removal candidates**: ip-tiny, libopenssl-oqsprovider, liboqs. If a dependency requires them, image assembly fails, requiring an explicit decision, rather than silently overriding removals.

Theme changes do not modify NSS/PPE acceleration. The workflow intentionally keeps Bootstrap.
