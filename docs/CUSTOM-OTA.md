# ImmortalWrt 在线固件更新

入口：**系统 → 备份 / 升级 → 在线固件更新**。

固件使用 `re-ss-01-immortal-ppe-nss` OTA 渠道，读取 GitHub Releases 中的 `imm-ppe-nss-...` 固件和 `ota.json`。下载之前检查设备型号、SHA256 和 `sysupgrade -T`，升级时按用户选择保留配置。

## 功能

- 在线检查、手动升级、更新记录。
- 每日按设定时间自动检查；发布后等待指定天数再安装。自动更新默认关闭。
- 升级后尝试恢复额外安装的软件包。
- 错误记录在 `/tmp/ppe-update.log`。

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
