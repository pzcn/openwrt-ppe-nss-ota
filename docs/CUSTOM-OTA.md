# ImmortalWrt 在线固件更新

入口：**系统 → 备份 / 升级 → 在线固件更新**。

固件使用 `re-ss-01-immortal-ppe-nss` OTA 渠道，读取 GitHub Releases 中的 `imm-arthur-SNAPSHOT2611-YYYYMMDDHHMM` 固件和 `ota.json`。下载之前检查设备型号、SHA256 和 `sysupgrade -T`，升级时按用户选择保留配置。

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
