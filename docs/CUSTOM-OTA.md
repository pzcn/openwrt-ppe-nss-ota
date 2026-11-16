# ImmortalWrt 在线固件更新

入口：**系统 → 备份 / 升级 → 在线固件更新**。

主仓库按设备隔离三个 OTA 渠道，通过同一 LuCI 和 `ppe-update` 后端检查 GitHub Releases 中的固件和 `ota.json`：

- 亚瑟：`re-ss-01-immortal-ppe-nss` → `imm-arthur-SNAPSHOT-r<revision>-YYYYMMDDHHMM`；
- MX4200 v1：`mx4200v1-immortal-ppe-nss` → `imm-mx4200v1-SNAPSHOT-r<revision>-YYYYMMDDHHMM`；
- WMA301 v2.0：`wma301-immortal-filogic` → `imm-wma301-SNAPSHOT-r<revision>-YYYYMMDDHHMM`，镜像格式为 `sysupgrade.itb`。

三台设备使用独立 profile、board、group、manifest 和版本序列，下载前校验固件元数据、SHA256 和 `sysupgrade -T`。

## 功能

- 在线检查、手动升级、更新记录。
- 每日按设定时间自动检查；发布后等待指定天数再安装。自动更新默认关闭。
- 升级后尝试恢复额外安装的软件包。
- 错误记录在 `/tmp/ppe-update.log`。

## GitHub 代理

在“系统 → 备份与升级 → 在线固件更新”的设置里选择：

- **直连 GitHub**（默认）
- **GHFast**：`https://ghfast.top`
- **GHProxy**：`https://ghproxy.net`
- **GH-Proxy**：`https://gh-proxy.com`
- **自定义**：填写只含 HTTPS 域名和可选路径的代理前缀，例如 `https://proxy.example.com`。不要填写完整的 GitHub 下载链接。

使用公共代理时，Release 附件优先通过代理下载，失败自动尝试直连；版本列表优先访问官方 GitHub API，直连失败才尝试当前选择的代理（部分代理不支持 GitHub API）。 HTTP 下载优先使用 `curl`（避免部分 GitHub Release 302 响应的超长 CSP 头导致 `uclient-fetch` 卡住），仅当 `curl` 不可用或下载失败时才尝试 `uclient-fetch`。代理可用性因网络而异，并非永久保证。第三方代理可以看到公开请求；请选择可信提供商。OTA 仍检查设备型号、校验和与 `sysupgrade -T`，但第三方代理同时篡改元数据和下载内容的风险不能仅靠 SHA256 消除。

这项设置写入 `/etc/config/ppe-update`，亚瑟和 MX4200 使用相同的后端；`auto=0` 默认不变。

## 使用建议

先导出路由器配置并备份重要文件。早期 OpenWrt OTA 镜像采用另一发布格式；切换到 ImmortalWrt 时可在 [Releases](../../releases) 下载对应 sysupgrade 文件，通过 LuCI 原生上传功能安装。

启用无人值守升级前，建议完成 F2FS 持久化及 sysupgrade 配置保存的实机测试。

## 排查

```sh
ppe-update status
ppe-update check
cat /tmp/ppe-update.log
```

OTA 后端模板位于 `files/usr/sbin/ppe-update`，由 `scripts/immortalwrt_ota.py` 在构建时适配 ImmortalWrt 渠道；LuCI 页面位于 `files/www/luci-static/resources/view/system/flash.js`。


## WMA301 的特殊保护

WMA301 的官方 Linux 6.18 / Filogic ImageBuilder 固件在独立的 [WMA301 Action](../.github/workflows/wma301-firmware.yml) 中构建，**默认只上传验证 Artifact**。主仓库正式 OTA Release 只能在手动选择 `release_mode=stable` 且确认完成真机验收后发布；`prerelease` 不进入设备的 OTA 更新列表。

WMA301 OTA 适用范围严格限定为**已完成单 UBI 分区迁移的 WMA301 v2.0**。它在调用 `sysupgrade` 前还检查 `mtd6` 与 `fit`、`ubootenv`、`ubootenv2`、`rootfs_data` 卷，并要求远端 `layout` 标识一致。发现原厂 A/B 布局、缺卷或错误板型时拒绝在线刷写。不执行 `ubiformat`、裸 NAND 写入或 `sysupgrade -F`。

**WMA301 永不自动安装 OTA**：运行时 `cmd_auto` 被硬性关闭，LuCI 不显示自动升级设置；仍保留手动检查、GitHub 代理和人工下载/安装按钮。恢复旧 UCI 配置依然禁止自动刷写。WMA301 不安装 sing-box、Tailscale、DDNS-Go 或 Qualcomm 专属插件。详见 [WMA301 说明](../wma301/README.md)。
