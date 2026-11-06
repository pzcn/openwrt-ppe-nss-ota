# RE-SS-01 PPE+NSS 固件

面向京东云 RE-SS-01（亚瑟）的 OpenWrt PPE+NSS 定制固件。构建基于 [Qualcommax NSS Builder](https://github.com/JuliusBairaktaris/Qualcommax_NSS_Builder) 发布的 ImageBuilder，集成常用 LuCI 应用、中文语言包和设备管理功能。

当前设备配置：**1 GiB RAM、64 GB eMMC**。ImageBuilder 继续使用上游提供的 `jdcloud_re-ss-01` 设备配置（`ipq60xx-512m` 构建组）。

## 固件功能

- **网络加速**：PPE 有线硬件卸载、NSS Wi-Fi 数据路径
- **管理界面**：Aurora 主题、简体中文及 PPE QoS 汉化
- **常用应用**：文件管理、Web 终端、流量统计、无线历史记录、IRQ Balance、LLDP、PBR、WireGuard
- **存储**：F2FS `rootfs_data` 可写层，p27 ext4 挂载到 `/mnt/storage`
- **诊断工具**：`tcpdump`、`conntrack`、`ip-full` 等

### 内置 LuCI 页面

| 位置 | 功能 |
| --- | --- |
| **状态 → PPE / NSS 硬件加速** | 硬件卸载连接、NSS 状态、内核诊断、最近 24 次采样 |
| **网络 → 校园网认证** | Dr.COM 登录与注销、自定义认证地址、记住密码、每天 00:00 自动认证 |
| **系统 → 备份 / 升级** | 固件备份、上传刷机、在线检查与安装更新 |
| **系统 → 自动更新设置** | 自动更新计划与检查时间 |

所有新增页面使用 LuCI 原生控件，跟随系统主题。

## 校园网认证

1. 进入「网络 → 校园网认证」，填写完整的**登录 URL**和**注销 URL**，保存地址。
2. 输入账号密码，按需勾选「记住账号密码」，点击「连接校园网」。
3. 如需每日认证，在保存账号密码后启用「每天 00:00 自动认证」。

认证请求从 WAN 接口发起。对于需要本地 DNS 解析的校园网，直接使用认证网关 IPv4 地址通常更方便。

**密码提醒：** HTTP 门户使用明文传输；记住密码后，凭据会存入路由器的配置文件并可能进入配置备份。

详细说明：[校园网认证](docs/DRCOM-CAMPUS.md)。

## 固件更新

在「系统 → 备份 / 升级」中使用「在线固件更新」，检查并安装 GitHub Releases 中适配该设备的固件。

手动更新验证设备型号、镜像 SHA256 和 `sysupgrade -T`。升级后尝试恢复额外安装的软件包；自动更新还会在刷机前检查软件包兼容性。

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
- [LuCI 简体中文](docs/CHINESE-LOCALIZATION.md)
- `config/add.txt` / `config/remove.txt`：软件包增删
- `files/`：固件文件覆盖层
- `scripts/build.sh`：镜像构建与 Release 发布
- `scripts/tests/`：离线测试

固件升级前建议在电脑上留存配置备份。
