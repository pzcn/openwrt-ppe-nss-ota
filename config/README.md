# Software sources and dependencies

**Standard official OpenWrt LuCI feed**: filemanager, ttyd, nlbwmon, statistics, wifihistory, irqbalance, lldpd, pbr, and their zh-cn translations. They do **not** require a third-party feed.

**Official OpenWrt userspace feeds**: wireguard-tools, tcpdump, ip-full, conntrack, application daemons such as ttyd, collectd, nlbwmon, irqbalance, lldpd and pbr. Their dependencies must resolve from the pinned image's own local packages, or the snapshot feeds.

**Matching upstream kernel feed only**: `kmod-nf-conntrack-netlink` and `kmod-fs-f2fs` must come from the exact PPE+NSS ImageBuilder. Kernel modules from generic OpenWrt snapshots will not load into the upstream NSS kernel.

**Standard OpenWrt rootfs_data, with F2FS enabled for the large p18 tail**:
- Upstream's common config already selects `block-mount`; the qualcommax target already has `kmod-fs-ext4` and `e2fsprogs`. They remain explicit requirements in `config/add.txt`.
- `kmod-fs-f2fs` supplies an early autoloadable matching F2FS filesystem module.
- `f2fs-tools` includes `mkf2fs` (installs `/usr/sbin/mkfs.f2fs`) and `f2fsck`; user-space tools come from the official OpenWrt feed.
- Upstream `fstools` chooses F2FS for the unformatted rootdisk space after SquashFS when this space exceeds 100 MiB (unless overridden by a kernel command-line filesystem option). On the reported p18 2 GiB rootfs, the unformatted tail was roughly 1.99 GiB.
- `files/etc/config/fstab` no longer configures extroot. It mounts the existing p27 ext4 storage at `/mnt/storage`; it never formats or repartitions p27.
- `files/etc/uci-defaults/96-migrate-legacy-extroot` changes *only* the known previous `fstab.expanded_emmc_extroot` entry to `/mnt/storage` when retained configuration overrides the ROM fstab.

The official RE-SS-01 device definition does not explicitly select F2FS packages, even though other official devices (for example Link NN6000) do. This repository is adding the packages to address the confirmed missing driver/tool problem; we are not changing upstream `fstools`, kernel images, GPT, U-Boot or NSS.


**LuCI 简体中文本地化**:
- 官方已经提供的翻译包直接从官方 LuCI APK 源安装（包括本次补充的 `luci-i18n-sqm-zh-cn` 和 `luci-i18n-bcp38-zh-cn`）。
- `luci-app-qca-ppe-qos` 来自上游独立 LuCI 分支，当前没有 `po/zh_Hans` 翻译目录。通过本仓库 `config/translations/qca-ppe-qos.zh-cn.json` 编译标准 `qca-ppe-qos.zh-cn.lmo`，由 ImageBuilder 文件覆盖层安装，不替换 PPE QoS 的 JavaScript。
- OTA 原有菜单 `Firmware update` 用 `ppe-update.zh-cn.lmo` 翻译，现有中文 OTA 页面保持不变。
- 构建时运行 `scripts/build_luci_i18n.py` 和离线测试；显示英文的官方组件优先补官方 `luci-i18n-*-zh-cn`，不要随意覆盖同名官方翻译目录。
- 用户仍可以在 LuCI 中切换英文；本仓库本地翻译只有 zh-cn 目录生效。

**External third-party APK**: Aurora, pinned to a release from eamonxg/luci-theme-aurora. Requires APK, not IPK; included in the ImageBuilder local package repository. Its source commit may be newer than the latest published release.

**Removal candidates**: ip-tiny, libopenssl-oqsprovider, liboqs. If a dependency requires them, image assembly fails, requiring an explicit decision, rather than silently overriding removals.

Theme changes do not modify NSS/PPE acceleration. The workflow intentionally keeps Bootstrap.
