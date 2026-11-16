# WMA301 v2.0 专属 OTA：单一固件源（当前默认屏蔽）

> **当前状态（2026-11-13）：** 仓库保留全部 OTA 实现、LuCI 页面、Shell 后端、测试和单通道发布逻辑；默认固件**不安装 OTA 相关文件**、不注入构建身份、不生成 OTA Release。两条工作流顶层均为 `WMA301_ENABLE_OTA: 'false'`。将它们一起改为 `'true'` 并重新构建，才会恢复下述流程。下面介绍的是重新启用后的行为。

此 OTA 独立于亚瑟 PPE/NSS OTA，**不覆盖原生 LuCI「备份/升级」页**，只适用于已迁移到本项目单 UBI 四卷布局的 WMA301 v2.0。

## 唯一 OTA 固件源

- 无 testing/stable 频道，也不需要人工运行提升发布工作流。官方 ImageBuilder 快速构建成功，经过 FIT、来源身份及元数据校验、Artifact 上传后，自动发布本次固件。
- 每次发布的独立 GitHub Release 标签：`wma301-ota-r<GitHubRunID>`。GitHub Releases 只是唯一 OTA 固件源的文件托管，**不需要手动管理不同频道**。
- 设备读取完整公开的发布，按 **Run ID 数值最大** 选择最新固件，旧的 testing/stable 和完整源码后备发布不会混入。
- 附件：`ota.json`、`immortalwrt-mediatek-filogic-tplink_wma301-v2-squashfs-sysupgrade.itb`、`SHA256SUMS` 和 `manifest.json`。远端发布元数据 schema=3，不再含 channel；固件内身份 schema=2 保持不变。
- 发布失败不影响既有公开版本；发布前先创建草稿并上传完整附件，最后公开。旧正式附件不能覆盖。
- **发布固件是自动的，但路由器不会自动下载、安装或定时更新**。实机未验收前默认禁止手动刷写。

## 快速构建与发布

`.github/workflows/official-builder.yml` 每日检查上游，也支持相关代码修改和手工触发。

1. 读取官方 Builder SHA256、复用精确哈希缓存、注入 WMA301 DTS 和软件包。
2. 在根文件系统嵌入 `/etc/wma301-ota-release`（构建编号、仓库 commit、官方 Builder SHA256、板型与分区布局）。
3. `scripts/verify_official.py` 验证 FIT 哈希、镜像内容、NAND/UBI 设备树与构建身份；`scripts/wma301_ota.py metadata` 对照 manifest 与实际 FIT SHA256。
4. 上传 14 天 Actions Artifact `WMA301_VERIFIED_FIT`，随后自动发布不可变版本 `wma301-ota-r<RunID>`。验证失败时不发布。
5. 设备端检查和下载时再次核验来源、板型、大小、SHA256；手动刷写前还要通过 `sysupgrade -T` 与四个 UBI 卷检查。

旧离线验收基线：[Actions #43392160741](https://github.com/pzcn/wma301-immortalwrt/actions/runs/43392160741)（原 testing/stable 代码）。单通道自动发布需要由新工作流确认。

## 设备使用

升级到包含单通道逻辑的固件后，LuCI 打开 **系统 → WMA301 在线更新**，可按需检查、下载、验证。

```sh
wma301-ota status
wma301-ota check
wma301-ota download
```

旧的 `wma301-ota.main.channel` 选项不再读取；可清理：

```sh
uci -q delete wma301-ota.main.channel
uci commit wma301-ota
```

没有可供检查的新 Release 时，表示尚无新版本成功公开，不代表快速构建一定失败。原有双通道的旧固件不会自动支持新的单通道格式，需要先受控手动迁移一次。

## 确认实机安全后启用手动升级

必须先在真实 WMA301 上核实 `/proc/mtd` 的 121 MiB `ubi`，以及 `fit`、`ubootenv`、`ubootenv2`、`rootfs_data` 四卷；还需确认启动、保留配置和恢复方式。

```sh
uci set wma301-ota.main.enable_flash='1'
uci commit wma301-ota
```

随后在 LuCI 手动安装，或运行 `wma301-ota start`。升级前会再次比较版本、验证大小、SHA256、`sysupgrade -T` 和四个 UBI 卷。仅调用原生 `sysupgrade`（默认保留配置），绝不修改 BL2/FIP、不调用 `ubiformat` 或 `sysupgrade -F`。升级日志：`/tmp/wma301-ota/update.log`。

```sh
uci set wma301-ota.main.enable_flash='0'
uci commit wma301-ota
```

上面两行关闭手动刷写权限。**不存在自动刷机定时任务。**

## 仍需验收

- [x] 独立 WMA301 身份及 FIT/UBI 检查、下载哈希、人工升级开关
- [ ] 单通道自动发布 Actions 实测，下载附件并复核匹配性
- [ ] WMA301 实机检查、下载及 sysupgrade -T
- [ ] 多轮 sysupgrade、保留配置、环境卷与恢复验证
- [ ] 按需增加额外 APK 恢复；不加入 sing-box

HTTPS + SHA256 检查元数据与下载内容的一致性，但不是独立固件签名。
