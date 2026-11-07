# Tailscale 与网络唤醒

本固件包含 OpenWrt 官方 `tailscale`、`luci-app-tailscale-community`、`luci-i18n-tailscale-community-zh-cn`，以及网络唤醒所需的 `luci-app-wol`、`etherwake`、`luci-i18n-wol-zh-cn`。

## Tailscale

入口：**服务 → Tailscale**。管理页面使用 OpenWrt 原生 LuCI 风格，中文语言包随固件一起安装。

首次使用时，在 LuCI 的终端或 SSH 中执行：

```sh
/etc/init.d/tailscale enable
/etc/init.d/tailscale start
tailscale up
tailscale status
```

`tailscale up` 会输出登录链接，在浏览器中完成登录后即可加入 Tailnet。登录状态保存在 `/etc/tailscale/tailscaled.state`；升级时建议通过 OpenWrt 配置备份保留 `/etc/tailscale`。

Tailscale 的隧道接口为 `tailscale0`，所需的 `kmod-tun` 与当前 NSS 内核匹配。网络出口和远程管理可以通过 Tailnet 进行；如果希望其他 Tailnet 设备访问 LAN 中的电脑，可另行配置子网路由或通过路由器执行网络唤醒。

## 网络唤醒（Wake on LAN）

入口：**服务 → 网络唤醒**。先添加电脑有线网卡的 MAC 地址，再选择对应 LAN 设备（如 `br-lan`，以设备实际网络接口为准）发送魔法包。电脑的 BIOS/UEFI 和系统网卡驱动需要启用局域网唤醒。

结合 Tailscale 使用时，可先远程登录路由器 LuCI，再由路由器在电脑所在的二层网络中发送唤醒包；Tailscale 的三层隧道本身不负责跨网段转发以太网广播。

## 固件更替

本版本从镜像包列表移除了之前加入的 sing-box 内核及 LuCI 插件，也取消了专属 TUN 用户初始化脚本。原有网络唤醒功能保持不变。此变更不主动清理设备上用户自行保存的旧配置文件。
