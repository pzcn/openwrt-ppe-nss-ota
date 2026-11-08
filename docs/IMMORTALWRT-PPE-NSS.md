# ImmortalWrt + PPE/NSS + 自定义 RE-SS-01 固件

这个构建**从源码编译**，不是把 ImmortalWrt 的 APK 混装到现有 OpenWrt ImageBuilder。

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
| 工作流 | `.github/workflows/build.yml` | `.github/workflows/build-immortalwrt.yml` |
| 构建方式 | 上游 ImageBuilder | 完整源码编译 |
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
- p18 F2FS 可写层及 p27 的 ext4 数据挂载，含旧 extroot 配置迁移脚本

所有 kernel 模块必须由这个 ImmortalWrt 源码构建，不使用另一个固件的预编译 `kmod-*.apk`。

## 构建与发布

在当前草稿 PR 中，通过 `pull_request` 自动触发实验构建并上传 Artifacts。**新工作流在合并到默认分支前通常不会出现在手动 Run workflow 的列表中**；待 CI 验证、合并后，可使用 **Actions → Build RE-SS-01 ImmortalWrt PPE+NSS → Run workflow** 手动构建。

默认 `publish_release=false`：只上传 14 天保留的固件 Artifacts，适合第一轮验证。确认可启动且加速有效后，再使用 `publish_release=true` 发布至独立的 ImmortalWrt Release，且 `--latest=false`，避免覆盖现有 OpenWrt 的 latest。

构建由 `scripts/build-immortalwrt.sh` 驱动，核心顺序：

1. 克隆两套源码和上游 Builder，记录各自精确提交 SHA；
2. 移植 `nss-wifi-drv`、ath11k 补丁、EDMA/PPE 对接及设备树；
3. 安装 ImmortalWrt 软件源、NSS 固件源和 PPE QoS，编译 LuCI 插件源代码；
4. 合并上游 PPE/NSS 覆盖层和本项目 `files/`；
5. 用当前用户软件包清单生成 `.config` 并运行 `make defconfig`，验证软件包未被丢弃；
6. 完整编译，验证固件、manifest 和 OTA SHA256，生成可选 Release。

本项目不包含原厂首次刷机镜像；输出为 `sysupgrade.bin`。

## 初次测试建议

先备份原固件设置以及 p27 数据，再用已有可恢复的 U-Boot/TTL 方案试刷。验证后再启用自动 OTA。

```sh
ubus call system board
df -h /overlay /mnt/storage
lsmod | grep -E 'nss|ath11k'
cat /sys/module/ath11k/parameters/nss_offload 2>/dev/null || true
ubus call luci.ppe-nss-monitor get_status
uci show firewall | grep flow_offloading
ppe-update status
```

特别检查 Wi-Fi NSS、PPE flowtable、WAN/LAN、F2FS 持久化、WireGuard、Tailscale 和 sing-box。仅编译成功**不能证明**这些运行时功能已通过真机验证。

## 注意

这是实验性移植。ImmortalWrt 与 Julius 的内核、mac80211 源码必须保持兼容；如果上游更新导致补丁无法应用，工作流应停止而不是发布缺少 NSS 的镜像。首次移植需要以真实 Actions 日志和真机测试作为验收结果。
