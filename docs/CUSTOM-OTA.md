# ImmortalWrt 在线固件更新

入口：**系统 → 备份 / 升级 → 在线固件更新**。

主仓库按设备隔离三个 OTA 渠道，通过同一 LuCI 和 `ppe-update` 后端检查 GitHub Releases 中的固件和 `ota.json`：

- 亚瑟：`re-ss-01-immortal-ppe-nss` → `imm-re-ss-01-SNAPSHOT-r<revision>-YYYYMMDDHHMM`；
- MX4200 v1：`mx4200v1-immortal-ppe-nss` → `imm-mx4200v1-SNAPSHOT-r<revision>-YYYYMMDDHHMM`；
- WMA301 v2.0：`wma301-immortal-filogic` → `imm-wma301-SNAPSHOT-r<revision>-YYYYMMDDHHMM`，镜像格式为 `sysupgrade.itb`。

三台设备使用独立 profile、board、group、manifest 和版本序列，下载前校验固件元数据、SHA256 和 `sysupgrade -T`。

**RE-SS-01 标签迁移：** 之前发布的 `imm-arthur-` 是历史 Release 名称，保留供查阅；新发布统一使用 `imm-re-ss-01-`。已刷旧版固件的 OTA 客户端仍按旧前缀筛选 Release，因此首次迁移须在 LuCI 原生固件上传入口手动安装一次新固件。迁移完成后，在线检查、定时升级都使用新前缀。固件文件名及设备板型标识保持原样。

## 功能

- 在线检查、手动升级、更新记录。
- 每日按设定时间自动检查；发布后等待指定天数再安装。自动更新默认关闭。
- 升级后仅尝试恢复相对当前 ROM 出厂软件清单额外安装、且新固件未内置的顶层软件包；旧版依赖和内核 ABI 包不自动恢复。
- 错误记录在 `/tmp/ppe-update.log`。

## 手动更新的交互流程

手动点击 **下载并安装新版本** 后会先展示目标版本和固件大小，并明确告知：**确认一次后自动连续执行下载 → SHA256 完整性校验 → `sysupgrade -T` 兼容性检查 → 保存额外软件包清单 → 刷写 → 自动重启**，中途没有第二次安装确认。手动确认与定时无人值守更新是两回事；三台设备都可以独立启用定时更新（默认关闭）。

- 下载：每 1.5 秒从 `ppe-update progress` 读取阶段、目标大小和临时镜像的真实文件大小，以最近 5 秒传输量计算近期速度和预计剩余时间。代理重试重新开始写入时，进度与测速窗口自动重置。
- 校验与刷写：切换到明确的状态文案，不把“100% 下载完成”误写成“升级成功”。刷写交给原生 `sysupgrade`，随后路由器自行重启；页面使用 LuCI 的重连等待逻辑。
- 错误：中断升级并保留弹窗，显示空间不足、下载失败、哈希不匹配、设备兼容性不符等建议；详细日志可展开查看。下载错误附带 curl 失败摘要，镜像兼容性失败附带 `sysupgrade -T` 的原始诊断。不使用 `sysupgrade -F`。
- 页面刷新：若手动升级仍在进行，可重新读取当前进度。临时状态保存在 `/tmp/ppe-update/progress.json`，重启后自动清除。RPC 的 `progress` 是只读查询，不修改闪存。
- 定时任务：仍按原有 `auto`、`hour`、`delay` 配置执行。此 UI 增强不改变自动升级策略、各设备的安全前置检查或固件发布渠道。

## 软件包恢复：避免旧固件依赖污染

新版 `ppe-update` 首先比较 `/etc/apk/world` 与 `/rom/etc/apk/world`，识别相对**当前 ROM 出厂系统**真正额外请求安装的顶层软件包。再与新固件 manifest 比较，仅保存新固件未内置的内容。旧固件自带的 Btrfs、collectd、Lua 兼容组件及其依赖只有经用户明确额外安装才被视为恢复对象。单凭“旧 ROM 有、当前 world 没有”无法判断用户是否要求卸载；只保留用户明确写入 world 的 `!软件包` 排除项。

`kmod-*` 和类似 `libubox20261103` 的 ABI 日期版本绑定库不跨固件自动补装；如果确实需要，应在新固件上安装与新内核和用户态 ABI 配套的新包。若当前 ROM world 缺失，将记录警告并跳过自动恢复，而不是自动补装旧固件全部软件包。

为了处理此前已产生的长队列，v2 恢复清单在 `/etc/ppe-update/packages` 首行带有格式标记。升级后发现没有标记的旧队列，会自动备份至 `/etc/ppe-update/packages.legacy`，停止重复调用 `apk add`；当前已安装软件保持原样，旧列表完整保留。管理员可按需检查：

```sh
cat /etc/ppe-update/packages.legacy
cat /etc/apk/world
cat /rom/etc/apk/world
```

LuCI 仅显示待恢复项数，点击后展开名称；旧版归档列表显示备份项数而非完整刷屏。已经由旧算法成功装入 world 的历史软件不能完全从来源上识别，需要自行检查决定是否保留。

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

**WMA301 支持按配置自动安装 OTA**：LuCI 与亚瑟、MX4200 显示相同的更新计划、检查时间、等待天数及代理设置。定时升级仍经过 WMA301 特有的分区布局检查以及原生 `sysupgrade -T`；默认关闭自动更新，管理员可手动启用。WMA301 不安装 sing-box、Tailscale、DDNS-Go 或 Qualcomm 专属插件。详见 [WMA301 说明](../wma301/README.md)。
