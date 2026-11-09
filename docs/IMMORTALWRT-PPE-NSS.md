# ImmortalWrt PPE/NSS：源码构建与 ImageBuilder

## 系统来源

- 操作系统：`immortalwrt/immortalwrt` 的 `master`，目标 `qualcommax/ipq60xx`。
- 有线 PPE 与无线 NSS：`JuliusBairaktaris/openwrt-ppe-nss` 的 `ppe-nss` 分支。
- NSS firmware/feed：`JuliusBairaktaris/nss-packages` 的 `ppe-nss` 分支。
- PPE QoS LuCI：Julius LuCI `luci-app-ppe-qos` 分支。
- 设备：`jdcloud_re-ss-01`；实际 1 GiB 内存，使用兼容的 512M NSS 内存配置。

内核、DTB、无线驱动、NSS 固件和其他 kmod 都从同一源码组合编译。

## 构建入口

唯一正式 GitHub Actions 工作流：`.github/workflows/immortalwrt-reusable.yml`。

| 模式 | 步骤 |
| --- | --- |
| 完整源码构建 | `scripts/build-immortalwrt.sh` 移植 PPE/NSS、应用补丁、编译固件和专用 standalone ImageBuilder |
| 已有 Builder | 从 GitHub Releases 读取 `imm-builder-...`，由 `scripts/repack-immortalwrt.sh` 快速打包固件 |
| 无变化 | 定时检查无更新时跳过固件构建 |
| 代码 PR | 先运行离线测试，完整固件发布由正式工作流处理 |

Builder Release 包含 ImageBuilder 压缩包、`builder-metadata.json`、`base-overlay.tar.gz` 和 `imagebuilder-packages.txt`。校验源码 SHA、核心配置指纹与文件 SHA256 后才重打包。固件 Release 使用 `imm-ppe-nss-...` 标签。

## 两个兼容补丁

`scripts/apply-immortalwrt-compat.sh` 在本轮 ImmortalWrt 源码树补齐 F2FS 设备软件包，并基于**当前源码的** `platform.sh` 注入 sysupgrade 配置复制接口。首次完整固件和专用 Builder 的基础文件覆盖层都采用相同平台脚本。重新打包时会校验该脚本存在。

源码升级后检测到已有官方配置复制接口时，保留官方实现。分别在 ImmortalWrt 上游合并、真机验证后移除临时修复。详见 [临时补丁](TEMPORARY-PATCHES.md)。

## 软件包与 LuCI

原定制全部保留：Aurora、PPE QoS、Dr.COM、OTA、Tailscale、sing-box、WireGuard、WOL、文件管理、ttyd、nlbwmon、statistics、wifihistory、irqbalance、lldpd、PBR、tcpdump、conntrack、F2FS 工具、简体中文包。

添加/排除包见 `config/add.txt`、`config/remove.txt`；设备及内核配置见 `config/immortalwrt-re-ss-01.config`。源码构建检查 Kconfig 必选项；ImageBuilder 使用匹配的完整 APK 包仓库。

## 缓存现状

`dl/`、ccache 和官方 GCC/musl 工具链复用已接入。2026-11-09 的一次完整编译日志显示下载缓存命中、ccache 命中率 25.45%、官方工具链通过验证，但完整编译仍约 97 分钟。这些机制不能代替已有 Builder 的分支判定；下一轮单独研究加速方案。

ImageBuilder 已作为 Release 资产发布，没有第二套 Builder 缓存。

## 设备验证

建议在正式使用前核对：PPE flowtable、ath11k NSS、F2FS 重启持久化、sysupgrade 保留配置、p27 数据、WireGuard、Tailscale、sing-box、WOL 和 OTA。编译完成属于构建验证；设备运行效果以真机测试为准。
