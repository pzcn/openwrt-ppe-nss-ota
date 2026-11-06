# 定制 OTA：仅更新 pzcn 的 RE-SS-01 固件

此功能基于上游 [JuliusBairaktaris/Qualcommax_NSS_Builder](https://github.com/JuliusBairaktaris/Qualcommax_NSS_Builder) 的 `ppe-update` 重新实现 **更新源、版本对比和升级前校验**。LuCI 菜单和 CLI 入口仍保持 `系统 → 固件更新` 以及 `/usr/sbin/ppe-update`。

## 一次性切换

此前发布的固件仍指向上游的 `ppenss.github.io`，**不会通过旧 OTA 自动获得本次改造**。请先手动刷入含 `custom-ota1` 的本仓库定制版镜像，再通过新的 LuCI 页面更新。

自动更新始终初始关闭，用户需要在 LuCI 手动启用。启用后由上游的 `/etc/init.d/ppe-update` 每天检查一次，等待时长由原有 `/etc/config/ppe-update` 管理。

## 固件如何发现更新

1. 固件中的 `/etc/pzcn-ota-release` 是 **ROM 级**本地身份，包含当前定制版 release tag 和 GitHub Actions 构建号；上游的 `/etc/ppe-release` 仍保留，以便继续取得匹配的 NSS 内核 kmod 源。
2. `ppe-update` 只读取固定的 `https://api.github.com/repos/pzcn/openwrt-ppe-nss-ota/releases/latest`。
3. 只允许 tag 符合 `ota-ppe-nss-*` 的 Release，并从固定仓库的该 Release 下载 `ota.json`。
4. 核对 `channel`、`repository`、`tag`、`board=jdcloud,re-ss-01`、`profile=jdcloud_re-ss-01`、`group=ipq60xx-512m`、固件/manifest 固定文件名及 SHA256 格式。
5. **只有 Release 的 `build` 数字严格大于本机固件构建号才允许升级。** 不用字符串比较版本号，也不会把标记为 latest 的旧 Release 当成新版本。
6. 下载并校验新版本 manifest，然后以新版本对应的上游 PPE+NSS 内核 feed 模拟安装现有额外软件包。模拟失败、源不可用或缺包，都会禁用一键更新；不支持 `-f` 绕过。
7. 下载 sysupgrade 镜像并与 `ota.json` 的 SHA256 校验，运行 `sysupgrade -T` 后再执行普通的 `sysupgrade`。
8. 旧版 `ppe-update` 已有的 `/etc/ppe-update/packages` 迁移、首次开机重装额外包、日志和 cron 服务继续保留。

**不会直接使用未定制的上游固件 Release。** 本仓库 GitHub Actions 先从上游下载 ImageBuilder，构建并发布定制固件，路由器 OTA 才检测到该发布。

## 信任边界与限制

- 只有存储在本仓库 Release 中的 JSON、manifest 和固件可以作为 OTA 候选；GitHub HTTPS + SHA256 防止传输错误。这里没有独立的固件签名或离线信任根，GitHub 仓库或发布权限如果被攻破仍有风险。
- 目前只检测 GitHub **最新正式 Release**，不会遍历历史版本；如果最新 Release 缺失 `ota.json` 或文件不完整，则拒绝更新，不会退回上游或其他下载源。
- 公共 GitHub Releases API 有速率限制，国内网络也可能无法直接访问；无法访问时页面显示错误，不进行刷机。
- 固件的内核 kmod 必须匹配对应上游 PPE+NSS 发布版本，不能从普通 OpenWrt Snapshot 随意安装。
- 软件包模拟安装是保守检查，无法确保所有用户数据、第三方文件都保留。**请先把当前配置导出到电脑**。自动更新建议完成至少一次手动验证后再启用。
- 由于保留 p27 数据分区、p18 F2FS 配置层和 LuCI 自定义内容，不能用未定制的上游 OTA 替换本版本。
- OTA 不更改 p18/p27 分区表、不格式化 p27，不修改 U-Boot；固件自身在首次启动时仍遵循 OpenWrt `rootfs_data` 初始化逻辑。

## 文件结构

| 文件 | 用途 |
|---|---|
| `files/usr/sbin/ppe-update` | 替换上游 CLI，保留原有 `restore` 语义 |
| `files/www/luci-static/resources/view/system/ppe-update.js` | LuCI 定制更新页面，明确显示来源并禁止强制升级 |
| `files/usr/share/rpcd/acl.d/luci-app-ppe-update.json` | 限制网页仅可执行 `status` 和 `start` |
| `scripts/write_ota_metadata.py` | 生成 SHA256 校验的 `ota.json` |
| `scripts/tests/test-custom-ota.sh` | 不联网、不刷机的元数据校验与版本比较测试 |
| `scripts/build.sh` | 写入 ROM 身份、生成 metadata、发布带 `ota.json` 的 Release |

## 命令行

```sh
cat /etc/pzcn-ota-release
cat /etc/ppe-release
ppe-update status
ppe-update check
# 在单独备份、确认更新后，可手动执行：
# ppe-update update
```

不要执行 `ppe-update update -f`；定制版本明确禁止跳过缺包检查。查看后台更新日志：`cat /tmp/ppe-update.log`。

新固件的 `/etc/ppe-release` 仍保存**上游**的内核 feed 身份；`/etc/pzcn-ota-release` 才是判断本仓库定制 OTA 当前版本的依据。
