# 京东云亚瑟 RE-SS-01 ImmortalWrt PPE/NSS 固件

本仓库统一构建 **ImmortalWrt + Julius PPE/NSS** 定制固件，目标设备为京东云 RE-SS-01（亚瑟）。当前实机扩容到 **1 GiB RAM、64 GB eMMC**，编译继续采用兼容的 ipq60xx 512M NSS 内存配置。

## 已集成的功能

| 类型 | 组件 |
| --- | --- |
| 网络加速 | PPE 有线硬件卸载、NSS Wi-Fi、PPE QoS、SQM |
| LuCI 与中文 | Aurora 主题、原生管理页、简体中文语言包 |
| 网络工具 | WireGuard、PBR、LLDP、IRQ Balance、tcpdump、conntrack |
| 管理插件 | filemanager、ttyd、nlbwmon、statistics、wifihistory |
| 远程访问 | Tailscale、中文 LuCI 管理页面 |
| 代理 | sing-box 内核、v0.4.7 LuCI JSON 管理页面，默认关闭 |
| 网络唤醒 | luci-app-wol、Etherwake、简体中文 |
| 更新 | 在线检查、SHA256 与 `sysupgrade -T` 验证、自动更新与软件包恢复 |

### 内置页面

- **状态 → PPE / NSS 硬件加速**：硬件加速状态、连接统计、折叠诊断。
- **系统 → 备份 / 升级**：手动升级、在线检查、自动更新设置。
- **VPN → Tailscale**：远程组网和服务管理。
- **服务 → sing-box**：JSON 配置、校验和服务控制。
- **服务 → 网络唤醒**：通过 LAN 接口向指定 MAC 发送唤醒包。

**校园网登录（Dr.COM）已从固件构建中排除。** LuCI 页面、RPC、认证脚本和自动登录的源码仍保存在仓库。参见 [Dr.COM 源码说明](docs/DRCOM-CAMPUS.md)。

完整插件清单在 [config/add.txt](config/add.txt)，核心构建选项在 [config/immortalwrt-re-ss-01.config](config/immortalwrt-re-ss-01.config)，自动测试会检查必需插件是否齐全。

## 两套独立 Actions

| 工作流 | 自动触发 | 产物 |
| --- | --- | --- |
| [固件打包 Firmware](../../actions/workflows/firmware-immortalwrt.yml) | `main` 的代码、LuCI、OTA、插件配置变化；每天检查一次 | 从已发布 Builder 重打包 `imm-ppe-nss-...` 固件 |
| [源码 Builder](../../actions/workflows/builder-immortalwrt.yml) | 每周日自动完整编译一次，或随时手动触发 | 完整编译并发布 `imm-builder-...` ImageBuilder |

Builder 无需预先检查上游是否更新：定时或手动触发后直接完整源码编译，成功发布后自动触发固件工作流。固件工作流始终默认选用最新发布的 Builder（可手动指定），仅校验其设备型号、发行元数据与资产 SHA256，不比较当前代码的 Builder 核心指纹。固件工作流仍会在源码和 Builder 均未变化时跳过打包，且**只进行固件打包，不涉及内核编译**。

- 修改 `files/`、LuCI、OTA、翻译或 `config/add.txt`：使用最新发布的 Builder 打包。
- 添加已编译的插件 APK：无需重新编译；若 Builder 不包含所需 APK，打包会明确报错，等待每周自动编译或手动触发 Builder。
- 修改编译配置、内核或 PPE/NSS 代码：由下一次每周/手动源码构建生成新 Builder。
- [Releases](../../releases) 分别保存 Builder 和固件，且带 SHA 与完整性校验。

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
- [sing-box](docs/SINGBOX.md)
- [中文本地化](docs/CHINESE-LOCALIZATION.md)

源码布局：`config/` 保存设备、插件与翻译配置；`files/` 为固件覆盖层；`scripts/` 保存源码构建、固件打包、补丁与测试代码。
