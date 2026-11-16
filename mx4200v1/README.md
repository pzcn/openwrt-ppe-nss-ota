# Linksys MX4200 v1 · ImmortalWrt PPE/NSS

**MX4200 v1 已有独立的正式 OTA 固件**，与京东云亚瑟共用 LuCI 在线更新界面和大部分软件包，但使用 **ipq807x 专用内核、ImageBuilder、SDK、OTA 渠道**。完整项目说明见 [仓库首页](../README.md)。

> **仅支持 MX4200 v1，不支持 v2。** 2026-11-16 版本通过 GitHub Actions 构建、元数据与 SHA256 校验；尚未因此证明真机启动、NAND 双镜像升级和恢复都安全。请保留可用的恢复手段，默认不要启用自动安装。

## 最新正式固件（2026-11-16）

- **Release**：[`imm-mx4200v1-SNAPSHOT-r42541-202611161651`](https://github.com/pzcn/openwrt-ppe-nss-ota/releases/tag/imm-mx4200v1-SNAPSHOT-r42541-202611161651)
- **OpenWrt / ImmortalWrt 升级**：[`immortalwrt-qualcommax-ipq807x-linksys_mx4200v1-squashfs-sysupgrade.bin`](https://github.com/pzcn/openwrt-ppe-nss-ota/releases/download/imm-mx4200v1-SNAPSHOT-r42541-202611161651/immortalwrt-qualcommax-ipq807x-linksys_mx4200v1-squashfs-sysupgrade.bin)
- **仅适用于受支持原厂安装流程**：[`immortalwrt-qualcommax-ipq807x-linksys_mx4200v1-squashfs-factory.bin`](https://github.com/pzcn/openwrt-ppe-nss-ota/releases/download/imm-mx4200v1-SNAPSHOT-r42541-202611161651/immortalwrt-qualcommax-ipq807x-linksys_mx4200v1-squashfs-factory.bin)
- **构建记录**：[双设备固件 Actions #43834663103](https://github.com/pzcn/openwrt-ppe-nss-ota/actions/runs/43834663103)
- **对应 Builder**：[`mx4200-builder-f1b46e2caf726290c0c42ca7`](https://github.com/pzcn/openwrt-ppe-nss-ota/releases/tag/mx4200-builder-f1b46e2caf726290c0c42ca7)，含可复用 ImageBuilder、匹配 SDK、Snapshot 锁定信息及校验文件（Builder 本身仍是 prerelease）。

正式 Release 包含 factory / sysupgrade、`ota.json`、`mx4200v1-ota-identity.json`、`snapshot-lock.json`、`sha256sums`、manifest 和 `sysupgrade.metadata.json`。安装前需确认设备确实是 v1，并使用正确镜像。

## 设备和升级边界

| 项目 | MX4200 v1 |
| --- | --- |
| SoC / RAM | Qualcomm IPQ8174 / 512 MiB |
| Target / profile | `qualcommax/ipq807x` / `linksys_mx4200v1` |
| 存储 / 升级 | 原生 NAND / UBI，沿用 ImmortalWrt / Linksys 双镜像逻辑 |
| 内核分区 | FIT 6 MiB 限制（6144 KiB），构建时校验镜像大小、FIT 配置 |
| OTA 渠道 | `mx4200v1-immortal-ppe-nss`；仅筛选 `imm-mx4200v1-...` 正式 Release |
| 平台脚本 | 不覆写 `/lib/upgrade/platform.sh`，不引入亚瑟的 eMMC、F2FS 或分区修复 |

**旧的某些测试镜像缺少 `fwtool` 附加的 sysupgrade 元数据，不能安全用于升级。** 当前构建会用 `fwtool -i` 检验元数据尾部，检查 `supported_devices` 包含 `linksys,mx4200v1`，校验 FIT 及 SHA256；失败不发布镜像。**不要用 `sysupgrade -F` 绕过设备或元数据校验**，不要将 v1 镜像用于 v2。

## LuCI、软件包与 OTA

与亚瑟保持一致的功能包括：PPE/NSS 加速及监控、PPE QoS / SQM、中文 LuCI / Aurora、Tailscale、WireGuard、WOL、PBR、DDNS-Go、sing-box + 中文 LuCI JSON 配置、filemanager、ttyd、nlbwmon、wifihistory、irqbalance、lldpd、autoreboot、cpufreq、autocore 和诊断工具。

- 同一套 LuCI “**系统 → 备份 / 升级 → 在线固件更新**”与 `ppe-update` 后端，支持手动检查、SHA256、`sysupgrade -T`、GitHub HTTPS 代理切换与错误日志。
- MX4200 在固件覆盖层中设置 `ppe-update.main.auto=0`；**默认禁止无人值守安装**。在配置保留、双镜像恢复和网络功能真机测试完成前，不建议开启。
- 不包含亚瑟 F2FS 专用依赖；不包含 HomeProxy、DiskMan、Statistics、Dr.COM 登录程序。详细差异见 [`packages.txt`](packages.txt)、[`remove.txt`](remove.txt) 和 [主仓库说明](../README.md)。
- LuCI 温度读取依赖 `autocore` 提供的 `/sbin/tempinfo`；若无温度，检查 `/sys/class/thermal/thermal_zone*/`。
- 本轮 NSS 日志 shadow hrtimer 默认调整为 **100 ms**（`log_poll_us=100000`），不是加速转发轮询周期。

## 当前构建流程

| 工作流 | 作用 |
| --- | --- |
| [双设备固件打包](../.github/workflows/firmware-simple.yml) | 日常固件入口；从最新兼容的 MX4200 **长期保存的 Builder Release** 取 ImageBuilder，快速重打包 factory / sysupgrade；不重新编译内核或 SDK |
| [MX4200 Hybrid Builder](../.github/workflows/mx4200v1-hybrid.yml) | 内核、PPE/NSS、SDK 等变化后全量编译；通过校验后发布独立的不可变 Builder **预发布版**，同时上传手动测试固件 |
| [MX4200 fast repack](../.github/workflows/mx4200v1-fast-repack.yml) | 专项测试/诊断，复用指定已有产物，不替代日常固件工作流 |
| [原始全源码构建](../.github/workflows/mx4200v1.yml) | 手动后备或调试 |
| [旧统一编排工作流](../.github/workflows/dual-device-immortalwrt.yml) | 保留手动诊断，不再作为日常自动编排入口 |

`resolve-release.py` 检查 Builder Release 的来源提交、目标 profile、所需附件及与当前 MX4200 内核配置/端口/软件包清单的兼容性。无法找到匹配的 Builder 时，**固件工作流不会自行触发全量编译**；自动推送任务跳过，手动重打包失败并提示先运行 Hybrid Builder。

`repack-hybrid.sh` 校验 ImageBuilder、基础覆盖层、Snapshot 锁、同一 ABI 的 kmod 及产出的固件。两台设备的软件包列表尽量同步，但 `qualcommax/ipq807x` **不能复用** 亚瑟的 `qualcommax/ipq60xx` ImageBuilder、SDK、kmod 或升级脚本。

固件普通 `main` 推送只打包并上传供检查的 Actions artifact；**正式 OTA 需要显式发布请求**。手动 `publish=true` 对 MX4200 生成固件 prerelease；经明确的受控主分支发布标记 `[release-ota-stable]` 和 CI 校验才发布稳定 OTA。不要把 Builder 预发布版当成可刷写固件。

核心配置与源码：[`source.config`](source.config)、[`port-ppe-nss.sh`](port-ppe-nss.sh)、[`build-hybrid.sh`](build-hybrid.sh)、[`stage-overlay.sh`](stage-overlay.sh)、[`ota-artifacts.sh`](ota-artifacts.sh)、[`publish-release.sh`](publish-release.sh)。

## 手动升级建议

先备份配置及重要数据，确认 MX4200 v1 型号、供电、网络和救援路径。从现有兼容 OpenWrt/ImmortalWrt 升级时选择官方 Release 的 **sysupgrade.bin**，保留配置与否按实际场景判断。升级后检查 LAN/WAN、所有无线、PPE/NSS、Tailscale、sing-box、配置持久化、双镜像切换与恢复；不要未经验证就无人值守升级。

排查 OTA：

```sh
ppe-update status
ppe-update check
cat /tmp/ppe-update.log
```

参考：[完整项目 README](../README.md) · [在线更新](../docs/CUSTOM-OTA.md) · [Actions 构建记录](https://github.com/pzcn/openwrt-ppe-nss-ota/actions/runs/43834663103)。
