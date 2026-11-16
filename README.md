# ImmortalWrt 多设备固件 · 亚瑟 / MX4200 v1 / WMA301 v2.0

基于 [ImmortalWrt](https://github.com/immortalwrt/immortalwrt) 的三设备固件管理仓库。京东云亚瑟（`qualcommax/ipq60xx`）与 Linksys MX4200 v1（`qualcommax/ipq807x`）使用 [Julius PPE/NSS](https://github.com/JuliusBairaktaris/openwrt-ppe-nss)；**TP-Link WMA301 v2.0**（`mediatek/filogic`）复用 ImmortalWrt 官方 Linux 6.18、MT7981 驱动及设备专用 DTS。三台设备共用 OTA 界面与 Release 规范，但**内核、固件镜像和升级脚本不能交叉使用**。

> 亚瑟和 MX4200 已有正式 OTA。**WMA301 6.18 目前只生成 CI 验证 Artifact，尚未开放稳定 OTA**；须先完成启动、NAND/UBI、配置保留和恢复的真机验收，再手动批准正式发布。WMA301 的 OTA **强制仅人工安装、永不自动刷写**。

## 正式 OTA 与 WMA301 测试构建（2026-11-16）

| 设备 | 固件版本 | 镜像下载 |
| --- | --- | --- |
| 京东云亚瑟 RE-SS-01 · IPQ60xx | [`imm-arthur-SNAPSHOT-r42542-202611161651`](https://github.com/pzcn/openwrt-ppe-nss-ota/releases/tag/imm-arthur-SNAPSHOT-r42542-202611161651) | [sysupgrade.bin](https://github.com/pzcn/openwrt-ppe-nss-ota/releases/download/imm-arthur-SNAPSHOT-r42542-202611161651/immortalwrt-qualcommax-ipq60xx-jdcloud_re-ss-01-squashfs-sysupgrade.bin) |
| Linksys MX4200 **v1** · IPQ807x | [`imm-mx4200v1-SNAPSHOT-r42541-202611161651`](https://github.com/pzcn/openwrt-ppe-nss-ota/releases/tag/imm-mx4200v1-SNAPSHOT-r42541-202611161651) | [sysupgrade.bin](https://github.com/pzcn/openwrt-ppe-nss-ota/releases/download/imm-mx4200v1-SNAPSHOT-r42541-202611161651/immortalwrt-qualcommax-ipq807x-linksys_mx4200v1-squashfs-sysupgrade.bin) · [factory.bin](https://github.com/pzcn/openwrt-ppe-nss-ota/releases/download/imm-mx4200v1-SNAPSHOT-r42541-202611161651/immortalwrt-qualcommax-ipq807x-linksys_mx4200v1-squashfs-factory.bin) |
| TP-Link **WMA301 v2.0** · MT7981 | `imm-wma301-SNAPSHOT-r<revision>-YYYYMMDDHHMM` | [WMA301 独立 Actions](.github/workflows/wma301-firmware.yml)（先发布验证 Artifact，OTA 正式发布待实机验收） |

- 亚瑟和 MX4200 的两个 Release 都是 **正式版**（非 prerelease），分别包含 `ota.json`、软件包清单及 SHA256 校验文件，MX4200 额外包含 sysupgrade 设备元数据。
- 两套固件共用一次打包任务的构建时间戳，但 **r42542 / r42541 是各自 Builder 锁定的 ImmortalWrt 修订号**，不代表可使用同一个内核或软件包。
- 本轮固件将 NSS 日志 shadow hrtimer 的默认轮询周期设为 **100 ms**（`log_poll_us=100000`）；该参数控制日志轮询，不是 PPE/NSS 数据面转发频率。
- 历史版本及匹配的 Builder/SDK 见 [GitHub Releases](https://github.com/pzcn/openwrt-ppe-nss-ota/releases)。完整打包记录：[Actions #43834663103](https://github.com/pzcn/openwrt-ppe-nss-ota/actions/runs/43834663103)。

## 设备差异

| 项目 | 亚瑟 RE-SS-01 | MX4200 v1 | WMA301 v2.0 |
| --- | --- | --- | --- |
| Target | `qualcommax/ipq60xx` | `qualcommax/ipq807x` | `mediatek/filogic` |
| 内核 / 加速 | 本地 Hybrid PPE/NSS | 本地 Hybrid PPE/NSS | 官方 Linux 6.18 / MediaTek PPE、WED |
| 存储 | eMMC / F2FS + 独立 ext4 | Linksys NAND / 双镜像 UBI | OEM BL2/BL31 + 自定义 BL33 / 单 121 MiB UBI |
| Builder | 本地 Hybrid、匹配 SDK | 本地 Hybrid、匹配 SDK | **直接复用官方 ImageBuilder，编译本机 DTS** |
| 升级 | eMMC 配置保留补丁 | 原生双镜像 | FIT / `ubootenv` 等 UBI 卷保护，手动 OTA |

详见 [MX4200 README](mx4200v1/README.md)、[WMA301 README](wma301/README.md)。

## 主要功能

三台设备共享可移植的基础 LuCI 和网络工具；WMA301 **不预装 sing-box、Tailscale、DDNS-Go，也不移植 Qualcomm PPE/NSS 插件、驱动或遥测页面**。以下功能表中的代理与 Qualcomm 专属项仅适用于亚瑟 / MX4200。

| 类型 | 功能 |
| --- | --- |
| 加速与无线 | PPE 有线硬件卸载、NSS Wi-Fi、PPE QoS、SQM，PPE/NSS 运行状态 |
| 网络与远程管理 | WireGuard、Tailscale、PBR、LLDP、IRQ Balance、WOL / Etherwake |
| 代理 | `sing-box` + `luci-app-sing-box` v0.4.7 中文 JSON 管理界面，默认不启用代理 |
| 系统与诊断 | LuCI 中文 / Aurora、文件管理、ttyd、nlbwmon、wifihistory、DDNS-Go、autoreboot、cpufreq、autocore、tcpdump |
| OTA | 原生“系统 → 备份 / 升级”中的在线检查、手动更新、版本校验、GitHub 代理选择、可选自动检查/安装 |

**不预装**：HomeProxy、DiskMan、Statistics 及对应语言包。Dr.COM 校园网登录源码保留在仓库，但不会打包进当前固件。软件包清单分别位于 [`config/add.txt`](config/add.txt) / [`config/remove.txt`](config/remove.txt) 和 [`mx4200v1/packages.txt`](mx4200v1/packages.txt) / [`mx4200v1/remove.txt`](mx4200v1/remove.txt)。

## OTA 使用与安全

入口：**LuCI → 系统 → 备份 / 升级 → 在线固件更新**。三台设备共用 LuCI 与 OTA 后端，按板型严格隔离发布渠道：

- 亚瑟：`imm-arthur-...` / `re-ss-01-immortal-ppe-nss`
- MX4200 v1：`imm-mx4200v1-...` / `mx4200v1-immortal-ppe-nss`
- WMA301 v2.0：`imm-wma301-...` / `wma301-immortal-filogic`（仅已迁移单 UBI 的 v2.0；正式 Release 需人工确认）

OTA 使用版本与设备标识校验、SHA256、`sysupgrade -T` 等检查；GitHub Release 下载优先使用 `curl`，失败时可回退 `uclient-fetch`。可选直连或 HTTPS GitHub 代理，但公共代理并不能提供独立的端到端真实性保证。

已运行兼容 OpenWrt/ImmortalWrt 的设备应使用对应 **sysupgrade** 文件；MX4200 的 **factory** 镜像只用于支持该格式的原厂安装路径。**禁止在 MX4200 v2 上刷 v1 镜像，也不要通过 `sysupgrade -F` 绕过检查。**

升级前先备份配置和重要数据，尤其要验证亚瑟 F2FS 可写层、MX4200 双镜像及配置保留。MX4200 默认关闭无人值守升级；**WMA301 即使恢复了旧 UCI 的 auto=1，也会在 OTA 后端拒绝自动刷写**。WMA301 必须通过 NAND 几何、四 UBI 卷和 sysupgrade 校验。

路由器上可检查：

```sh
ppe-update status
ppe-update check
cat /tmp/ppe-update.log
```

详见 [在线更新说明](docs/CUSTOM-OTA.md) 和 [临时兼容补丁](docs/TEMPORARY-PATCHES.md)。

## 构建与发布

**固件打包与 Builder 分离**：日常改动 LuCI、插件清单、翻译或 OTA 覆盖层时，优先复用各设备已发布、ABI 匹配的 ImageBuilder；不因为这些改动重新编译内核。

| 工作流 | 职责 |
| --- | --- |
| [Firmware · Arthur & MX4200](.github/workflows/firmware-simple.yml) | **当前双设备固件入口**。独立解析两套已发布 Builder，打包并做回归校验；两设备共享时间戳，一台失败不触发另一台的内核重编 |
| [Arthur Hybrid Builder](.github/workflows/builder-immortalwrt-hybrid.yml) | 按来源和指纹决定跳过、刷新官方 Snapshot 用户态 APK 或编译新内核 / PPE/NSS / 配套 ImageBuilder + SDK |
| [MX4200 Hybrid Builder](.github/workflows/mx4200v1-hybrid.yml) | 独立编译 ipq807x PPE/NSS、6 MiB FIT、factory/sysupgrade；发布可复用的 MX4200 Builder 预发布版 |
| [WMA301 Official Builder + OTA](.github/workflows/wma301-firmware.yml) | **独立 Action**。按 SHA256 复用官方 Filogic 6.18 ImageBuilder 和缓存，仅编译设备树、打包 FIT；统一 OTA 元数据 / LuCI；默认只上传 Artifact，人工批准后可发布预览/正式 OTA |
| [Arthur 独立重打包](.github/workflows/firmware-immortalwrt.yml) | 高级/单设备手动操作及双设备工作流内部调用 |
| [旧版 Full Source Builder](.github/workflows/builder-immortalwrt.yml) | 手动后备构建，不是日常固件打包入口 |

最新 Builder：[`imm-builder-2fe3065a-ec9306fa-5796d271-...`（亚瑟）](https://github.com/pzcn/openwrt-ppe-nss-ota/releases/tag/imm-builder-2fe3065a-ec9306fa-5796d271-g827215b29490-pcae13671-f3a7075a6-sd21482dd) 和 [`mx4200-builder-f1b46e2caf726290c0c42ca7`（MX4200）](https://github.com/pzcn/openwrt-ppe-nss-ota/releases/tag/mx4200-builder-f1b46e2caf726290c0c42ca7)。**Builder 的 prerelease 状态与固件的 stable 状态是两回事**：新内核先以 Builder 预发布产物保存；经显式发布请求及 CI 校验后，才生成设备可发现的正式 OTA 固件。

- `main` 的固件输入改动会触发双设备打包，但**普通推送不会自动把新内核发布到正式 OTA**。
- 手动运行双设备固件工作流可选择设备和 `publish`；手动发布时 MX4200 使用预发布固件模式。**两台同时正式发布**使用受控的主分支显式发布标记 `[release-ota-stable]`，并经过各自校验。
- 固件打包不重新编译内核；亚瑟若缺少特定插件 APK，可使用同一 Builder 配套 SDK 补编，失败时拒绝发布；MX4200 缺少兼容 APK 则拒绝打包，不从其他 ABI 拼包。

详细架构和兼容性说明：[Hybrid Builder](docs/HYBRID-BUILDER.md) · [ImmortalWrt / PPE/NSS 构建](docs/IMMORTALWRT-PPE-NSS.md)。

## 存储与兼容补丁（亚瑟专用）

- p18：SquashFS / F2FS `rootfs_data`，用于配置持久化。
- p27：单独的 ext4 数据分区；不会因固件构建而自动格式化，也不作为旧式 extroot 强行挂载。
- 暂保留 **F2FS** 与 **sysupgrade 保留配置** 两项补丁，待上游修复并实机确认后移除。参考 [F2FS PR #26577](https://github.com/openwrt/openwrt/pull/26577) 和 [sysupgrade PR #26576](https://github.com/openwrt/openwrt/pull/26576)。

排查：

```sh
df -h /overlay
block info | grep mmcblk0p27
logread | grep -Ei 'f2fs|overlay|mount_root'
```

## 文档与目录

- [MX4200 v1 专项说明](mx4200v1/README.md)
- [WMA301 v2.0 专项说明](wma301/README.md)
- [OTA 更新说明](docs/CUSTOM-OTA.md)
- [Hybrid Builder](docs/HYBRID-BUILDER.md)
- [构建与版本判定](docs/IMMORTALWRT-PPE-NSS.md)
- [临时补丁](docs/TEMPORARY-PATCHES.md)
- [PPE/NSS 监控](docs/PPE-NSS-MONITOR.md)
- [Tailscale 与 WOL](docs/TAILSCALE-WOL.md)
- [sing-box](docs/SINGBOX.md)
- [Dr.COM 源码（不打包）](docs/DRCOM-CAMPUS.md)
- [中文本地化](docs/CHINESE-LOCALIZATION.md)

目录：`config/` 为亚瑟软件包清单，`files/` 为共用 LuCI/OTA 模板，`mx4200v1/` 为 ipq807x 专项，`wma301/` 为 MT7981 官方 Builder、设备树、FIT 校验及单 UBI 防护，`scripts/` 为共享元数据、构建与测试。
