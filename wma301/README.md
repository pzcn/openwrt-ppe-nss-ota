# TP-Link WMA301 v2.0 / v2.1 · ImmortalWrt master / Linux 6.18

本目录从 [pzcn/wma301-immortalwrt](https://github.com/pzcn/wma301-immortalwrt) 迁入主仓库，保留**官方 ImageBuilder + 仅编译 DTS** 的快速构建架构。与亚瑟、MX4200 共用 OTA 后端、LuCI「系统 → 备份 / 升级」页面和主仓库 GitHub Releases，但**设备树、内核、FIT、UBI 安全检查完全独立**。

> 适用于已从 OEM A/B 迁移到**单 121 MiB UBI / 四卷**布局的 **WMA301 v2.0 / v2.1**。不是原厂升级包，也不是 NAND 全片镜像，不能直接刷入仍使用原厂 A/B 布局的设备。旧版本的真机验收状态不代表新版本已验收；定时自动升级功能默认关闭，可由管理员自行在 LuCI 中开启。

## v2.0 / v2.1 硬件区别

v2.1 直接复用 v2.0 公共 DTSI、SPI-NAND 分区、UBI 四卷、网络、无线 MAC、按键与固件软件包；只有板型标识和状态灯 GPIO 不同。

| 项目 | v2.0 | v2.1 |
| --- | --- | --- |
| 红灯 | GPIO14，高电平有效 | GPIO12，低电平有效 |
| 绿灯 | GPIO15，高电平有效 | GPIO11，低电平有效 |
| Reset | GPIO1，低电平有效 | 同左 |
| WPS | GPIO0，低电平有效 | 同左 |

现在只生成一份通用 FIT、DTB、SquashFS、OTA 和 Release。DTS 同时定义 v2.0 的 GPIO14/15（高电平有效）与 v2.1 的 GPIO12/11（低电平有效）；`files/etc/diag.sh` 使用 OpenWrt 原生 LED 状态控制函数同时驱动两组状态灯。`compatible` 和 `SUPPORTED_DEVICES` 均包含 v2.0、v2.1，兼容既有板型的 sysupgrade；U-Boot、按键、网口和 NAND/UBI 结构不变。

## 构建和下载

**唯一自动构建入口**：[WMA301 · Official ImageBuilder + unified OTA](../.github/workflows/wma301-firmware.yml)。

- **每天检查** `snapshots/targets/mediatek/filogic` 的官方 ImageBuilder 版本及 SHA256；输入未变化且同周已有成功记录就跳过，避免重复下载/构建。
- 使用准确匹配官方 Snapshot 的 ImmortalWrt 源码、Linux 6.18 内核设备树头文件，只编译 WMA301 DTS；内核 Image、kmod 与 APK 都来自同一官方版本。
- 复用已校验的 ImageBuilder / Linux 头文件缓存，验证 Aurora v1.4.0 固定源码并通过 ImageBuilder 主机端 `apk mkpkg` 生成 **noarch 原生 APK**；验证 sysupgrade FIT 的 DTB、哈希、分区和板型。
- 验证 ImageBuilder **实际安装包 manifest**，强制拒绝 sing-box、Tailscale、DDNS-Go、Qualcomm PPE/NSS 专属包；将合法产物整理成统一 OTA 附件。
- 默认上传 `WMA301_VERIFIED_UNIFIED_OTA`（14 天 Actions Artifact），不会因 push/schedule 自动发布正式 OTA，更不会升级实体路由器。

原独立仓库的全源码 `master` 完整构建脚本、恢复 FIT 逻辑保留为人工后备参考，但本仓库没有为它新增第二条自动 Action。

## 首页 WAN 网口选择与盲插

入口不是独立菜单：**状态 → 概览 → 端口状态**。保留 ImmortalWrt 原生 `29_ports.js` 的四个端口状态卡片（连接、协商速率、收发流量），只在卡片上方新增「WAN 网口选择」。默认「自动识别」，也可以固定网口 1 / 2 / 3 / 4。卡片标注当前系统实际选中的 WAN/LAN 角色。

WMA301 v2.0 与 v2.1 使用相同 MT7531 DSA 端口集合：`lan1`、`lan2`、`lan3`、`wan`。目前 UI 中的逻辑编号 1–4 分别对应以上设备名；**尚未在四个实体插孔上实测标号与 Linux 接口名的对应关系**。

- 自动：逐个隔离已经插线的候选端口，以 DHCP 获取地址和默认网关作为判断；第一个成功者绑定为 WAN，另外三个归 LAN。WAN 物理链路存续期间锁定，不因互联网 Ping/租约问题抢占。断线再重新识别。
- 手动：选择具体网口作为 WAN，其余三个全部作为 LAN；只改端口角色，不更改 `network.wan.proto`（因此 PPPoE/静态 IP 可以手动指定 WAN）。
- 状态/设置由 `/usr/sbin/wma301-ports` 与 `/etc/init.d/wma301-ports` 实现，首次启动通过 UCI defaults 启用；主仓库 `wma301/scripts/stage_files.py` 会将所有服务文件和原生 UI 覆盖注入实际 ImageBuilder 镜像。

**注意：修改 GitHub 源码并不会改变已经运行的路由器。** 主仓库默认构建成功后只上传 `WMA301_VERIFIED_UNIFIED_OTA` Artifact；新功能必须安装包含此改动的新版固件才会显示，且升级后建议强制刷新 LuCI 页面（Ctrl/Command + Shift + R）。不应将未经真实硬件测试的 WAN/LAN 角色切换脚本视为已经验收。

**实机测试必须覆盖**：四口插线物理编号、DHCP 上联、仅接 LAN 的无上联情况、WAN 断线重插、远程管理口切换、WAN6 跟随与重启持久化。对于仍使用 OEM A/B 分区的设备不得直接刷写单 UBI FIT。

## 主仓库统一 OTA

**设备通道**：两版统一为 `wma301-immortal-filogic`。旧版 v2.1 已刷入设备初次迁移时可手动上传新的通用 FIT；迁移完成后两个版本共用 OTA。

**Release 标签**：`imm-wma301-SNAPSHOT-r<revision>-YYYYMMDDHHMM`，两种硬件共用同一个正式 Release。版本来自官方 Filogic Snapshot。

一个 Release 包含以下唯一一组附件。镜像沿用 `wma301-v2` 文件名以兼容旧升级客户端，实际同时支持 v2.1：

- `immortalwrt-mediatek-filogic-tplink_wma301-v2-squashfs-sysupgrade.itb`（仅 sysupgrade FIT）
- `immortalwrt-mediatek-filogic-tplink_wma301-v2.manifest`（实际安装的 APK 清单，必须包含 `luci-theme-aurora`）
- `luci-theme-aurora-1.4.0-r1.apk`（主题独立安装文件，可由 apk 管理）
- `ota.json`（与主仓库相同的 schema=1 + WMA301 独有 `layout` 标识）
- `sha256sums`、`manifest.json`（FIT / DTS 离线验证报告）、`official-provenance.json`（官方 ImageBuilder 来源锁）

OTA 入口仍是 LuCI **系统 → 备份 / 升级 → 在线固件更新**；继承 GitHub 代理选项、下载 SHA256、`sysupgrade -T` 和软件包恢复流程。旧仓库的独立 `wma301-ota` 页面与 Run ID 发布标签**不会打包**；旧 Release 不会被自动认作新通道版本。

### 发布安全门槛

- `main` push / schedule：只发布测试 Artifact，**不向 OTA 暴露**。
- 手动运行此 Action、`release_mode=prerelease`：发布仅供检查的 Release，设备上的 OTA 不会将 prerelease 识别为正式更新。
- 手动 `release_mode=stable` 且 `confirm_hardware_tested=true`：核验通过后才发布到设备可见的主仓库 OTA 通道。**不能把单纯 CI 成功当作真机验证。**
- WMA301 的手动更新及可选的定时自动升级与亚瑟、MX4200 共用同一套前后端。管理员可在 LuCI 设置更新时刻与延迟天数；默认关闭自动更新。每次刷写前仍执行独立的 NAND/UBI preflight。

## NAND / UBI 安全约束

| 区域 | 偏移 / 大小 | 用途 |
| --- | --- | --- |
| bl2 | 0–0x020000 | OEM BL2，禁止覆盖 |
| fip | 0x020000–0x3c0000 | OEM BL31 + 自定义 BL33，禁止覆盖 |
| reserved | 0x3c0000–0x400000 | 保留 |
| factory_info / art | 0x400000–0x500000 | 校准、MAC，禁止覆盖 |
| config | 0x500000–0x700000 | 原厂配置 |
| ubi | 0x700000–0x8000000 | 单 121 MiB UBI 分区 |

必须存在 `fit`、`ubootenv`、`ubootenv2`、`rootfs_data` 四卷。统一 OTA 在调用 `sysupgrade -T` / `sysupgrade` 前执行 `/usr/libexec/ppe-update-wma301-preflight`，核对板型、`mtd6` 的大小和擦除块信息、四卷名称，缺少任何一项就拒绝执行。**不执行 `ubiformat`、原始 mtd 写入、`sysupgrade -F`，不覆盖 BL2/FIP**。

这套检查只作用于在线更新入口；通过 LuCI 原生固件上传或 SSH 手动刷机仍须自行确认设备和恢复方法。

## 软件包策略

沿用原来的精简 [`configs/official-packages.txt`](configs/official-packages.txt)：中文 LuCI / Aurora、`autocore`（为 LuCI 提供 `/sbin/tempinfo` 温度读取）、WireGuard、WOL、PBR、SQM、filemanager、ttyd、nlbwmon、wifihistory、irqbalance、lldpd 等。**不预装** sing-box、HomeProxy、Tailscale、DDNS-Go、Qualcomm NSS / PPE QoS / 监控、F2FS/eMMC 专属包。与亚瑟 / MX4200 的同名可移植功能保持一致，但不强求 MT7981 固件体积或内存配置和 Qualcomm 路由器相同。

## 文件位置

- `device/`：通用 v2.x DTS / 分区布局；`files/etc/diag.sh` 为两版同步状态灯
- `scripts/official_builder.py`、`scripts/prepare.py`：适配官方 Filogic ImageBuilder
- `scripts/aurora.py`：将固定 SHA 的 Aurora 生成原生 `noarch` APK，取代旧 Overlay 安装
- `scripts/verify_official.py`：真实 FIT 哈希、DTS 和布局检查
- `scripts/stage_unified_ota.py`、`scripts/pack_unified_ota.py`：统一 OTA 及发布附件
- `files/usr/libexec/ppe-update-wma301-preflight`：本机 NAND/UBI 安全守卫
- `scripts/test_unified_ota.py`：本地不接触硬件的集成回归测试
- `docs/`：迁移背景、Aurora、官方 ImageBuilder 和历史 OTA 说明

参见 [主仓库 README](../README.md)、[统一 OTA 说明](../docs/CUSTOM-OTA.md)。
