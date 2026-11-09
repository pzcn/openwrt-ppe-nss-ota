# 临时 eMMC 修复

脚本：`scripts/apply-immortalwrt-compat.sh`。当前适用于 ImmortalWrt 源码编译，修复分为两项。

## F2FS：重启后失去可写层

- OpenWrt 上游 [PR #26577](https://github.com/openwrt/openwrt/pull/26577)。
- 对 JDCloud RE-CS-02、RE-CS-07、RE-SS-01 的设备配置增加缺少的 `kmod-fs-f2fs`、`f2fs-tools`。
- 已存在的软件包和原始排除项保留，避免重复追加。
- RE-SS-01 曾在定制 ImmortalWrt 镜像上测试重启持久化；另外两台设备暂未真机测试。

## sysupgrade：勾选保留配置却未还原

- OpenWrt 上游 [PR #26576](https://github.com/openwrt/openwrt/pull/26576)。
- 当当前 ImmortalWrt `platform.sh` 缺少 `platform_copy_config` 时，为 JDCloud 三台 eMMC 设备及 Link NN6000 v1/v2 增加 `emmc_copy_config` 调用。
- 源码编译通过 `FILES` 包含修复后的 `platform.sh`；Builder 发布的 `base-overlay.tar.gz` 同样包含该文件，因此后续打包保持一致。
- 已有上游钩子时保留原始实现，并检查 Arthur 设备匹配。
- RE-SS-01 使用自定义 ImmortalWrt 构建进行了升级保留配置验证，不代表官方 OpenWrt 镜像测试结果。

## 移除原则

仅当 **ImmortalWrt 上游**真正包含对应修复，且实机完成重启/升级验证后，才能分别移除。OpenWrt PR 合并本身并不代表 ImmortalWrt 已同步。每项补丁单独处理，另一项仍然保留，避免影响其他设备修复。

操作固件升级前先备份配置，保留可用的串口或 U-Boot 恢复手段。
