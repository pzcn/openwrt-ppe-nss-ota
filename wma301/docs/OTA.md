# WMA301 v2.0 OTA：已并入主仓库

> 本文更新于 2026-11-16。原仓库独立的 `wma301-ota` 页面、`wma301-ota-r<RunID>` 标签及 schema 3 格式属于**旧实现**，代码保留供迁移核对，但**不再打包进新版固件**。

## 当前路线

统一 OTA 采用主仓库 [`scripts/immortalwrt_ota.py`](../../scripts/immortalwrt_ota.py) 和 [`files/usr/sbin/ppe-update`](../../files/usr/sbin/ppe-update)；更新页面与亚瑟 / MX4200 保持一致，入口位于 **系统 → 备份 / 升级 → 在线固件更新**。

- 唯一可安装的硬件：已迁移到指定 121 MiB 单 UBI 布局的 WMA301 **v2.0**。
- OTA 渠道：`wma301-immortal-filogic`，Release 前缀 `imm-wma301-SNAPSHOT-r...`。
- 元数据：主仓库 schema 1，包含 WMA301 的 `board`、`profile`、`target`、`layout`、镜像与安装包清单 SHA256。
- 镜像格式：`immortalwrt-mediatek-filogic-tplink_wma301-v2-squashfs-sysupgrade.itb`。不会对 NAND 裸分区进行直接写入。
- 真实 FIT 的设备树、校准区域保护、分区布局、内容校验及实际包 manifest 经过 CI 验证；真机启动和升级必须另行验收。

## 构建和发布

使用主仓库的 [WMA301 独立 Action](../../.github/workflows/wma301-firmware.yml)，每天检查官方 ImageBuilder 并按来源 SHA256 缓存；默认上传 Actions Artifact，OTA 正式发布受到人工确认门槛保护。

- 默认 `release_mode=none`：只生成下载测试 Artifact。
- `release_mode=prerelease`：发布测试 Release，OTA 列表默认忽略它。
- `release_mode=stable` 且 `confirm_hardware_tested=true`：人工确认验收后才发布稳定 OTA。
- 运行中的 WMA301 后端禁止自动安装。LuCI 页面不提供自动安装控件；即使 UCI 残留 `auto=1`，`cmd_auto` 仍然拒绝刷写。

## NAND / UBI 前置检查

构建时将 `files/usr/libexec/ppe-update-wma301-preflight` 安装到固件。手动更新之前，它要求 `/tmp/sysinfo/board_name=tplink,wma301-v2`，`mtd6` 为精确匹配的 121 MiB UBI 分区，存在 `fit`、`ubootenv`、`ubootenv2`、`rootfs_data` 四卷。

缺少任何一项，OTA 就拒绝调用 `sysupgrade`。不使用 `-F`、`ubiformat` 或未经检验的原厂 A/B 镜像。

具体构建、测试步骤与软件下载策略见 [WMA301 README](../README.md) 和 [主仓库 OTA 说明](../../docs/CUSTOM-OTA.md)。
