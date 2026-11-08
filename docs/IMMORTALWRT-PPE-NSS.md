# ImmortalWrt + PPE/NSS + 自定义 RE-SS-01 固件

本项目采用**两阶段构建**：只有内核、PPE/NSS、依赖或构建配置变化时才完整编译 ImmortalWrt，并生成专用 standalone ImageBuilder；仅修改 LuCI、配置或固件文件时直接复用这个 Builder。内核模块绝不混装不同版本的官方 APK。

## 代码来源

- 操作系统：`immortalwrt/immortalwrt` 的 `master`（Linux 6.18）
- 有线 PPE 与无线 NSS：`JuliusBairaktaris/openwrt-ppe-nss` 的 `ppe-nss`
- NSS 固件：`JuliusBairaktaris/nss-packages` 的 `ppe-nss`
- PPE QoS LuCI：`JuliusBairaktaris/luci` 的 `luci-app-ppe-qos`
- 用户自定义：本仓库 `files/`、`config/add.txt` 和 `config/translations/`

目标设备为京东云亚瑟 `jdcloud_re-ss-01`，保持 `ipq60xx` 的 512M Wi-Fi/NSS 内存配置；这与实际扩容至 1 GiB RAM 不冲突。编译使用独立构建配置 `config/immortalwrt-re-ss-01.config`。

## 与现有构建的关系

| 项目 | 现有 OpenWrt | 新 ImmortalWrt |
| --- | --- | --- |
| 工作流 | `.github/workflows/build.yml` | `.github/workflows/immortalwrt-reusable.yml` |
| 构建方式 | 上游 ImageBuilder | 首次完整编译生成专用 ImageBuilder，随后快速重打包 |
| PPE/NSS | 上游已经集成 | 从相同 PPE/NSS 分支移植 |
| 自定义文件 | `files/` | 复用 `files/` |
| OTA 渠道 | `re-ss-01-custom` | `re-ss-01-immortal-ppe-nss` |
| Release 标记 | `ota-ppe-nss-...` | `imm-ppe-nss-...` |
| GitHub latest | 现有渠道 | 不修改 latest |

### 已复用的自定义

- 中文 LuCI、Aurora、PPE/NSS 监控和 PPE QoS
- Dr.COM 校园网登录/注销和每天 0 点自动认证
- 备份/升级页面中的 OTA（额外安装软件包的恢复尝试也保留）
- Tailscale、sing-box JSON 面板、WireGuard 和网络唤醒
- 文件管理、ttyd、nlbwmon、statistics、wifihistory、irqbalance、lldpd、PBR
- p18 F2FS `rootfs_data` 可写层；p27 保留原分区，不设置自定义挂载点，也不执行旧 extroot 迁移

所有 kernel 模块必须由这个 ImmortalWrt 源码构建，不使用另一个固件的预编译 `kmod-*.apk`。

## 构建与发布


### 第一轮编译加速（已接入 CI）

- `actions/cache@v4` 缓存源码下载目录（`dl/`），减少每次重新拉取源码压缩包的时间。
- `CONFIG_CCACHE=y` 与 Actions 持久化对象缓存（最大约 1.6GB），重用相同编译器、编译参数和源码的编译结果。
- 每次仍然**重新检出官方 ImmortalWrt 和 Julius PPE/NSS 源码**，不缓存整个内核编译树，避免过时的设备树、驱动对象和内核 ABI 混用。
- 构建脚本报告下载和编译秒数，以及 `ccache` 命中率，便于与此前约 136 分钟的全量构建比较。
- PR 上新的提交可取消同一 PR 中尚未完成的旧编译，减少重复消耗。

官方 ImmortalWrt 已提供预编译 SDK、工具链和普通 APK，但 SDK 不能直接当作完整固件 Buildroot。内核、NSS 与 DTB 必须精确匹配；本轮**暂不启用官方快照 APK 的二进制混装**。等拿到新的缓存构建计时，再实施可验证的软件包/工具链复用，不能把第一轮缓存优化描述为已经达到 20～35 分钟。

### 一、生成专用 NSS ImageBuilder

GitHub Actions 工作流：`.github/workflows/immortalwrt-reusable.yml`。

- 自动查询 ImmortalWrt `master`、Julius `ppe-nss` 和上游 Builder `main` 的完整 SHA。
- 使用这些 SHA 与核心配置文件指纹构成**确定性的 Builder Release 标签**：`imm-builder-...`。
- 如果该版本已存在，直接跳过完整内核编译。
- 如果不存在，使用 `scripts/build-immortalwrt.sh` 完整编译，产出固件和 `CONFIG_IB_STANDALONE=y` 的 ImageBuilder。
- Builder Release 同时保存 `builder-metadata.json`、`base-overlay.tar.gz`、`imagebuilder-packages.txt` 和自带 APK 的 ImageBuilder 压缩包。

**为什么必须自己生成 Builder：** 目前 NSS Wi-Fi 移植修改了内核、DTB 和 ath11k；官方预编译 kmod 无法保证与之 ABI 相容。其他 LuCI 和工具尽量保持 ImmortalWrt 官方源代码，编译后的 APK 一次性随 Builder 存档，后续无需重新编译。

### 二、从专用 Builder 快速生成固件

`scripts/repack-immortalwrt.sh` 会：

1. 下载 Builder Release 的四个必需文件并核对 SHA256、源码 SHA 和核心配置指纹；
2. 复用已有编译好的内核/设备树/驱动和全部匹配 APK；
3. 合并 PPE/NSS 基础文件和本仓库 `files/`，重新生成 LuCI 中文及 OTA 元数据；
4. 调用 `make image PROFILE=jdcloud_re-ss-01 PACKAGES=... FILES=...`；
5. 可选择发布新的 `imm-ppe-nss-...` 固件 Release。

所有 ImageBuilder 产物与 APK 均来自**同一次完整编译**。这一版没有直接引入官方快照二进制包，避免软件包及 kmod ABI 漂移；后续可按具体包和版本校验后逐步复用官方用户空间 APK。

### 三、自动检测与更新

该工作流每天 **03:41 UTC（北京时间 11:41）** 检查一次：

| 变更类型 | 执行操作 |
| --- | --- |
| ImmortalWrt 内核或 Julius PPE/NSS 上游 SHA 变化 | 完整编译、发布新 ImageBuilder 和固件 |
| Builder 构建配置或软件包列表变化 | 完整编译并发布新的 Builder |
| 仅 `files/`、LuCI、OTA、翻译等变化 | 使用现有 Builder 快速重打包固件 |
| 没有任何更新 | 跳过构建 |

推送到默认分支上的相关文件也会触发工作流；`workflow_dispatch` 支持手动强制重建 Builder 或仅产出 Actions Artifacts。

**自动发布的只是经过构建验证的固件文件。** 路由器仍通过独立 ImmortalWrt OTA 渠道检查/下载安装，是否无人值守安装由设备端“启用自动更新”配置决定。

OpenWrt 通道 `ota-ppe-nss-...`、GitHub Release `latest` 均不受影响。ImmortalWrt 的 Builder Release 与固件 Release 都带 `--latest=false`，不抢占原来的 latest。

注意：GitHub 的 `schedule` 只会在仓库**默认分支**执行。当前开发分支合并到 `main` 前，不会自行开始每日调度。

### 四、原有完整源码工作流

`.github/workflows/build-immortalwrt.yml` 仍然保留，用于手动实验编译和 PR 测试；新工作流负责按版本判断是否真的需要完整编译。Builder 通过 `scripts/immortalwrt_builder.py` 生成版本元数据和完整性校验。

## 初次测试建议

先备份原固件设置以及 p27 数据，再用已有可恢复的 U-Boot/TTL 方案试刷。验证后再启用自动 OTA。

```sh
ubus call system board
df -h /overlay
block info | grep mmcblk0p27
lsmod | grep -E 'nss|ath11k'
cat /sys/module/ath11k/parameters/nss_offload 2>/dev/null || true
ubus call luci.ppe-nss-monitor get_status
uci show firewall | grep flow_offloading
ppe-update status
```

特别检查 Wi-Fi NSS、PPE flowtable、WAN/LAN、F2FS 持久化、官方 p27 挂载行为、WireGuard、Tailscale 和 sing-box。仅编译成功**不能证明**这些运行时功能已通过真机验证。首次新 Builder 应先通过设备端 PPE/NSS、F2FS、网络与 sysupgrade 测试，再启用路由器无人值守安装。

## 注意

这是实验性移植。ImmortalWrt 与 Julius 的内核、mac80211 源码必须保持兼容；如果上游更新导致补丁无法应用，工作流应停止而不是发布缺少 NSS 的镜像。首次移植需要以真实 Actions 日志和真机测试作为验收结果。
