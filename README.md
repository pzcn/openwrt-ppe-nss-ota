# 京东云亚瑟 RE-SS-01 ImmortalWrt PPE/NSS 固件

本仓库统一构建 **ImmortalWrt + Julius PPE/NSS** 定制固件，目标设备为京东云 RE-SS-01（亚瑟）。当前实机扩容到 **1 GiB RAM、64 GB eMMC**，编译继续采用兼容的 ipq60xx 512M NSS 内存配置。

## 已集成的功能

| 类型 | 组件 |
| --- | --- |
| 网络加速 | PPE 有线硬件卸载、NSS Wi-Fi、PPE QoS、SQM |
| LuCI 与中文 | Aurora 主题、原生管理页、简体中文语言包 |
| 网络工具 | WireGuard、PBR、LLDP、IRQ Balance、tcpdump、conntrack |
| 管理插件 | filemanager、ttyd、nlbwmon、wifihistory、autoreboot、cpufreq、ddns-go、autocore |
| 远程访问 | Tailscale、中文 LuCI 管理页面 |
| 代理 | sing-box 内核、v0.4.7 中文 LuCI JSON 管理界面，默认关闭 |
| 网络唤醒 | luci-app-wol、Etherwake、简体中文 |
| 更新 | 在线检查、SHA256 与 `sysupgrade -T` 验证、自动更新与软件包恢复 |

### 内置页面

- **状态 → PPE / NSS 硬件加速**：硬件加速状态、连接统计、折叠诊断。
- **系统 → 备份 / 升级**：手动升级、在线检查、自动更新设置。
- **VPN → Tailscale**：远程组网和服务管理。
- **服务 → sing-box**：JSON 配置、校验及服务控制。
- **服务 → 网络唤醒**：通过 LAN 接口向指定 MAC 发送唤醒包。

**校园网登录（Dr.COM）已从固件构建中排除。** LuCI 页面、RPC、认证脚本和自动登录的源码仍保存在仓库。参见 [Dr.COM 源码说明](docs/DRCOM-CAMPUS.md)。

完整插件清单在 [config/add.txt](config/add.txt)，核心构建选项在 [config/immortalwrt-re-ss-01.config](config/immortalwrt-re-ss-01.config)，自动测试会检查必需插件是否齐全。

## Actions

| 工作流 | 自动触发 | 产物 |
| --- | --- | --- |
| [固件打包 Firmware](../../actions/workflows/firmware-immortalwrt.yml) | `main` 的代码、LuCI、OTA、插件配置变化；每天检查一次 | 从已发布 Builder 重打包 `imm-ppe-nss-...` 固件 |
| [源码 Builder + SDK](../../actions/workflows/builder-immortalwrt.yml)（后备） | 仅手动触发 | 同一轮源码编译发布 `imm-builder-...` ImageBuilder、匹配 SDK 和 feed 锁定文件 |
| [Hybrid Builder](../../actions/workflows/builder-immortalwrt-hybrid.yml)（默认） | 每天检查；`add.txt` 等改动推送时 | 内核侧不变时只替换官方 APK（不编译，约 10 分钟）；PPE/内核侧变化时只编内核、kmod 和定制包。新内核以 prerelease 发布，见 [docs/HYBRID-BUILDER.md](docs/HYBRID-BUILDER.md) |

Hybrid Builder 每天先用几十秒判断：无变化跳过；只有官方用户态或插件列表变化时复用上一版内核、ImageBuilder 和 SDK，仅替换官方 APK；PPE/NSS 或内核配方变化时才编译内核侧。非 prerelease 的 Builder 发布后自动触发固件工作流。固件工作流始终默认选用最新发布的 Builder（可手动指定），仅校验其设备型号、发行元数据与资产 SHA256，不比较当前代码的 Builder 核心指纹。固件工作流仍会在源码和 Builder 均未变化时跳过打包，且**只进行固件打包，不涉及内核编译**。

- 修改 `files/`、LuCI、OTA、翻译或 `config/add.txt`：使用最新发布的 Builder 打包。
- 添加已编译的插件 APK：直接重打包。若 Builder 缺少 APK，固件工作流自动使用同一 Release 配套 SDK 补编并加入离线仓库，无需重新编译内核；没有 SDK 的旧 Builder 缺包时需先手动完整编译一次。
- 修改编译配置、内核或 PPE/NSS 代码：Hybrid Builder 编译新的内核侧，以 prerelease 发布，实机验证后在 Releases 页转正即生效。
- [Releases](../../releases) 保存 Builder（包含配套 OpenWrt SDK）和固件，附 SHA256 与版本锁定信息；未来可用 SDK 补编与当前 Builder ABI 匹配的插件 APK。

详细说明：[构建与版本判定](docs/IMMORTALWRT-PPE-NSS.md)。

## 两个临时兼容补丁

构建时暂时保留：

1. **F2FS 可写层**：为京东云 eMMC 设备补齐 `kmod-fs-f2fs` 和 `f2fs-tools`，保证 p18 的 rootfs_data 可持久写入。
2. **sysupgrade 保留配置**：补齐 ipq60xx eMMC `platform_copy_config` 与 `emmc_copy_config` 的调用关系。

上游对应 [F2FS PR #26577](https://github.com/openwrt/openwrt/pull/26577)、[sysupgrade PR #26576](https://github.com/openwrt/openwrt/pull/26576)。等 ImmortalWrt 上游合并修复并经设备验证后，分别移除本地兼容补丁。详见 [临时补丁管理](docs/TEMPORARY-PATCHES.md)。

## 存储与升级

- **p18 / rootfs**：SquashFS + F2FS `rootfs_data`。
- **p27**：已有 ext4 数据分区。固件使用 ImmortalWrt 自身挂载逻辑，无专用 extroot 或自动格式化配置。

升级之前请导出配置并备份重要数据。首次从旧固件升级，建议手动选择正确的 `imm-ppe-nss-...` 镜像并确认分区状态。

```sh
df -h /overlay
block info | grep mmcblk0p27
logread | grep -Ei 'f2fs|overlay|mount_root'
ubus call luci.ppe-nss-monitor get_status
```

## 文档

- [ImmortalWrt 构建](docs/IMMORTALWRT-PPE-NSS.md)
- [临时补丁](docs/TEMPORARY-PATCHES.md)
- [Dr.COM 校园网](docs/DRCOM-CAMPUS.md)
- [在线更新](docs/CUSTOM-OTA.md)
- [PPE / NSS 监控](docs/PPE-NSS-MONITOR.md)
- [Tailscale 与 WOL](docs/TAILSCALE-WOL.md)
- [sing-box 配置管理](docs/SINGBOX.md)
- [中文本地化](docs/CHINESE-LOCALIZATION.md)

源码布局：`config/` 保存设备、插件与翻译配置；`files/` 为固件覆盖层；`scripts/` 保存源码构建、固件打包、补丁与测试代码。

## Linksys MX4200 v1 (separate test target)

The isolated `qualcommax/ipq807x` **MX4200 v1** PPE/NSS test build is under [`mx4200v1/`](mx4200v1/README.md). It has its own [GitHub Actions workflow](.github/workflows/mx4200v1.yml), source config, package list and build artifacts. This does not reuse Arthur's `ipq60xx` ImageBuilder or enable MX4200 OTA before hardware testing.
