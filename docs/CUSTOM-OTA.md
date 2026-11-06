# 在线固件更新

入口：**系统 → 备份 / 升级 → 在线固件更新**

与 OpenWrt 原生固件上传功能位于同一页面。提供版本检查、手动安装和更新日志。自动升级计划也在本页面配置，直接位于在线固件更新区域内。

## 升级方式

| 功能 | 流程 |
| --- | --- |
| 在线检查 | 从当前项目的 GitHub Releases 读取最新发布及 `ota.json` |
| 手动升级 | 下载固件、校验镜像、执行 `sysupgrade -T` 后安装 |
| 软件包恢复 | 记录额外安装的软件包，升级后尝试重新安装 |
| 自动升级 | 开启无人值守更新后，每天按设定时间检查，达到发布后等待天数即自动下载安装 |

手动安装以设备型号和镜像校验为准。部分额外插件可能需要在升级后手动恢复。

## 更新过程

1. 检查 RE-SS-01 设备型号、发布渠道和版本。
2. 验证 `ota.json`、软件包清单与镜像 SHA256。
3. 下载固件并运行 `sysupgrade -T`。
4. 执行 `sysupgrade`，保留配置并重启设备。
5. 首次启动后尝试恢复额外软件包。

升级前建议从「备份 / 升级」页面将配置备份到电脑。

## 自动更新

自动更新默认关闭，默认每天 04:00 所在小时检查，发布满 1 天后安装。开启后，由系统 cron 按路由器本地时间执行；在该小时内随机选择分钟。自动和手动使用相同的固件 SHA256、设备型号及 `sysupgrade -T` 检查，额外软件包在升级后尝试恢复。更改设置后会更新运行计划。

## 从旧版过渡

如果当前版本的在线更新按钮仍受旧版软件包检查限制，可从 [Releases](../../releases) 下载新版本 `sysupgrade.bin`，通过「备份 / 升级」中的本地上传功能升级一次。

## 排查

```sh
ppe-update status
ppe-update check
cat /tmp/ppe-update.log
```

版本检查依赖 GitHub Releases 网络连接。下载与升级错误会记录在 `/tmp/ppe-update.log`。

## 相关文件

- `files/www/luci-static/resources/view/system/flash.js`：在线更新界面
- `files/usr/sbin/ppe-update`：检查与升级命令
- `scripts/write_ota_metadata.py`：发布元数据
- `scripts/tests/test-custom-ota.sh`：升级流程测试
