# WMA301 与亚瑟固件的软件功能同步

同步来源：[pzcn/openwrt-ppe-nss-ota](https://github.com/pzcn/openwrt-ppe-nss-ota) 的 `config/add.txt`、`config/remove.txt` 及 LuCI 首次启动配置。

**此次明确不安装 sing-box**（既不安装内核，也不移植 sing-box JSON LuCI、开机配置或相关依赖）。HomeProxy 同样不随固件预装。两个路由器硬件和用途不同，不能简单照搬整个文件树。

## GitHub Actions 实测

- **[快速构建 #43386109613](https://github.com/pzcn/wma301-immortalwrt/actions/runs/43386109613)：成功。** 使用官方 ImageBuilder 将当前 42 项预选软件包（另有 7 项排除规则）打包进 WMA301 sysupgrade FIT，通过 FIT/DTS/NAND 校验并上传实验 Artifact。
- GitHub Actions Artifact ZIP 约 30.6 MB；这是下载包的大小，不等同于闪存写入占用，也不证明设备在 256 MiB RAM 上同时运行所有服务稳定。
- 已检查仓库文件树和预装包列表，没有 sing-box 源码、Lua/LuCI 管理界面或正向选择的 sing-box 包。
- **完整源码双 FIT 后备尚未重新完整编译实测**；其软件包同步和工作流 YAML 修复保留为后备。

## 已移植的官方软件包

- LuCI + 简体中文、文件管理、ttyd 终端、nlbwmon、Wi-Fi 历史、IRQBalance、LLDP、PBR、定时重启。
- WireGuard、tcpdump、ip-full、conntrack、curl/jsonfilter 等网络维护工具。
- SQM + BCP38 及其中文包；这里是 MT7981 原生软件队列，不包含亚瑟 Qualcomm PPE/NSS QoS。
- WOL/Etherwake 默认安装；Tailscale 原生 LuCI 及中文包、DDNS-Go 及中文界面**仍在软件清单里，但默认以负号排除**。
- 移除可能重复或不适合此设计的 HomeProxy、Diskman、Statistics 和 ip-tiny。

统一软件清单：`configs/official-packages.txt`。恢复可选软件时，将对应负号条目改为正向条目；恢复 OTA 另需修改工作流开关。默认快速构建使用配套官方 ImageBuilder APK；原完整源码构建后备也会引用同一清单。更改清单将触发重新打包。

## 已移植的通用配置

- `files/etc/uci-defaults/95-luci-preferences`：简体中文 + **仅在首次引入 Aurora 且当前为默认 Bootstrap 时**切换 Aurora。保留已选择的其他主题，Bootstrap 仍可回退。不改 Wi-Fi、密码或 OTA。
- `Aurora v1.4.0`：从与亚瑟一致的上游源码、固定 SHA `84c27b66952e6fc4be60128067a6b88bfd34afb5` 获取。快速 ImageBuilder 使用带版本戳的预编译主题资源，不额外下载 SDK；完整源码后备安装标准 LuCI 主题包。见 [AURORA.md](AURORA.md)。

## Aurora 主题同步

- 主题源码：`eamonxg/luci-theme-aurora`，版本 `v1.4.0`，与亚瑟同源，CI 校验提交 SHA。
- 快速构建：向固件 overlay 添加原项目编译好的 `/www/luci-static/aurora`、LuCI JavaScript 与 Ucode 模板，带 Apache-2.0 LICENSE。**不是独立 APK，无法通过 `apk info luci-theme-aurora` 查看包安装状态。**
- 完整源码后备：从相同源码编译 `luci-theme-aurora` 标准包。
- 保留 `luci-theme-bootstrap`；故障时可 SSH 恢复，详见 [AURORA.md](AURORA.md)。

## 此次不移植

| 项目 | 原因 |
| --- | --- |
| sing-box 服务和 JSON LuCI | 用户明确不要；完全不打包 |
| HomeProxy | 无代理组件需求 |
| QCA NSS / PPE 驱动、QoS、遥测页面 | Qualcomm IPQ60xx 特有；WMA301 是 MediaTek MT7981 |
| eMMC / F2FS / extroot 补丁 | WMA301 为单 UBI + UBIFS overlay，不需要亚瑟 eMMC 修复 |
| Dr.COM 校园网认证 | 亚瑟当前也没有默认装进固件，WMA301 不移植 |
| 亚瑟的 eMMC OTA 和 flash.js 覆盖代码 | 不直接复制；已单独实现 [WMA301 OTA](OTA.md)，使用专属 FIT/UBI 校验和独立发布渠道 |
| CPU 频率调节、autocore/default-settings-chn | 与 SoC、设备预置项关联；先不在 WMA301 强行启用 |

## 后续计划

1. CI 对完整包清单打包，定位不存在的 APK、依赖冲突与 FIT 体积。
2. 为无匹配官方二进制的**确实必要**软件包补充同 ABI 官方 SDK 构建；没有缺包不下载 SDK。
3. 实机验证 LuCI、WOL、Wi-Fi MAC、WireGuard、SQM、rootfs_data 和配置保留；Tailscale/DDNS-Go 暂不打包。
4. WMA301 专属 OTA 的后端、LuCI 和单通道发布代码仍保留，当前默认不注入固件、不自动发布；后续需要时再启用并实机验收。不能用亚瑟的升级脚本直接写 WMA301 NAND。

已验证的构建流程和失败回退详见 [BUILD-RUNBOOK.md](BUILD-RUNBOOK.md)。
