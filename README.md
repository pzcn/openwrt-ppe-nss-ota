# RE-SS-01 PPE+NSS 固件

面向京东云 RE-SS-01（亚瑟）的 OpenWrt PPE+NSS 定制固件。构建基于 [Qualcommax NSS Builder](https://github.com/JuliusBairaktaris/Qualcommax_NSS_Builder) 发布的 ImageBuilder，集成常用 LuCI 应用、中文语言包和设备管理功能。

当前设备配置：**1 GiB RAM、64 GB eMMC**。ImageBuilder 继续使用上游提供的 `jdcloud_re-ss-01` 设备配置（`ipq60xx-512m` 构建组）。

## 固件功能

- **网络加速**：PPE 有线硬件卸载、NSS Wi-Fi 数据路径
- **管理界面**：Aurora 主题、简体中文及 PPE QoS 汉化
- **常用应用**：文件管理、Web 终端、流量统计、无线历史记录、IRQ Balance、LLDP、PBR、WireGuard
- **代理与唤醒**：sing-box 核心、中文 LuCI 配置管理、网络唤醒（Etherwake，含简体中文翻译）
- **存储**：F2FS `rootfs_data` 可写层，p27 ext4 挂载到 `/mnt/storage`
- **诊断工具**：`tcpdump`、`conntrack`、`ip-full` 等

### 内置 LuCI 页面

| 位置 | 功能 |
| --- | --- |
| **状态 → PPE / NSS 硬件加速** | 加速引擎、连接统计、折叠内核诊断 |
| **网络 → 校园网认证** | Dr.COM 自定义地址、账号密码保存、登录注销和 0 点自动认证 |
| **系统 → 备份 / 升级** | 固件备份、上传刷机、在线检查、安装更新与自动更新设置 |
| **服务 → sing-box** | 上传、编辑、校验 JSON、控制服务及查看日志 |
| **服务 → 网络唤醒** | 选择电脑的 MAC 和 LAN 接口，发送唤醒包 |

所有新增页面使用 LuCI 原生控件，跟随系统主题。

## 校园网认证

1. 进入「网络 → 校园网认证」，填写**认证基础地址**、用户名和密码，点击「保存认证信息」。
2. 点击「连接校园网」，使用已保存的账号认证。
3. 如需每日认证，勾选「启用0点自动认证」并保存。

认证请求从 WAN 接口发起。对于需要本地 DNS 解析的校园网，直接使用认证网关 IPv4 地址通常更方便。

**密码提醒：** HTTP 门户使用明文传输；记住密码后，凭据会存入路由器的配置文件并可能进入配置备份。

详细说明：[校园网认证](docs/DRCOM-CAMPUS.md)。

## sing-box 与网络唤醒

sing-box 的 LuCI 应用提供中文 JSON 管理页面；首次安装后服务保持关闭状态。请在设备上导入已调整到 OpenWrt/Linux 的配置，再校验和启动。

网络唤醒使用官方 LuCI 插件和简体中文语言包，配合 `etherwake` 向 LAN 内的电脑发送魔法包。

详细说明：[sing-box 与网络唤醒](docs/SINGBOX-WOL.md)。

## 固件更新

在「系统 → 备份 / 升级」中使用「在线固件更新」，检查并安装 GitHub Releases 中适配该设备的固件。

手动和自动更新都会验证设备型号、镜像 SHA256 和 `sysupgrade -T`，升级后尝试恢复额外安装的软件包。自动更新设置在同一页面保存。

若设备上仍运行旧版 OTA，可先从 [Releases](../../releases) 下载新固件，通过原生固件上传功能升级一次。

详细说明：[在线更新](docs/CUSTOM-OTA.md)。

## 构建与下载

1. 打开 [Actions → Build RE-SS-01 firmware](../../actions/workflows/build.yml)。
2. 选择 **Run workflow**，可填写上游发行版 tag；留空则选择最新发布版本。
3. 从 [Releases](../../releases) 下载 `sysupgrade.bin` 和校验文件。

工作流也会定期检查上游构建并生成对应版本。

## 存储与升级

原始 64 GB eMMC 分区布局：

| 分区 | 用途 |
| --- | --- |
| p18（活动 rootfs） | SquashFS 固件和 F2FS `rootfs_data` 可写层 |
| p27 | ext4 数据存储，挂载到 `/mnt/storage` |

首次初始化可能格式化 p18 中尚未建立文件系统的可写空间。**升级前请备份路由器配置和重要数据，核对当前设备的分区布局。**

此前使用 p27 extroot 的安装，启动迁移脚本会将对应 fstab 挂载点调整为 `/mnt/storage`。

升级后可检查：

```sh
df -h /overlay /mnt/storage
block info | grep mmcblk0p27
logread | grep -Ei 'f2fs|rootfs_data|overlay'
```

固件镜像为 `sysupgrade` 格式，适用于已有兼容系统的设备。

## 代码与说明

- [PPE / NSS 硬件加速监控](docs/PPE-NSS-MONITOR.md)
- [Dr.COM 校园网认证](docs/DRCOM-CAMPUS.md)
- [在线更新](docs/CUSTOM-OTA.md)
- [sing-box 与网络唤醒](docs/SINGBOX-WOL.md)
- [LuCI 简体中文](docs/CHINESE-LOCALIZATION.md)
- `config/add.txt` / `config/remove.txt`：软件包增删
- `files/`：固件文件覆盖层
- `scripts/build.sh`：镜像构建与 Release 发布
- `scripts/tests/`：离线测试

固件升级前建议在电脑上留存配置备份。
