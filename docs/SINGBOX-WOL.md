# sing-box 与网络唤醒

本固件内置 [luci-app-sing-box](https://github.com/lauyv/luci-app-sing-box)、sing-box 核心，以及 OpenWrt 官方 `luci-app-wol`。两者使用 OpenWrt LuCI 原生页面。

## sing-box

入口：**服务 → sing-box**。页面提供 JSON 上传、编辑、格式化、校验、保存、服务状态和日志。此 LuCI 应用使用项目自身的简体中文界面。

- 固件打包的是作者发布的 `v0.4.7` APK，构建时使用固定 SHA-256 验证来源；内核从当前 OpenWrt 兼容软件源安装。
- 初次安装保留 sing-box 关闭状态。通过 LuCI 私下上传配置，校验后再保存、启动。
- 默认 JSON 路径：`/etc/sing-box/config.json`。运行目录：`/usr/share/sing-box`。
- TUN 模式需要 root 访问网络接口和路由。首次启动配置脚本会在服务关闭且仍使用原厂 `sing-box` 用户时，将运行用户调整为 root。
- LuCI 中的运行面板是 sing-box 的独立 API 客户端；浏览器要能访问 JSON 里配置的 API 监听地址。

### 从 Windows JSON 迁移

已有的 Windows 配置使用 TUN、Hysteria2、WireGuard endpoint、DNS 分流和原生 API。迁移到路由器时应重点检查：

1. `route.default_interface` 中的 `WLAN`：换成实际 WAN/WWAN 出口的接口名，或者采用适合路由器的接口自动检测。
2. `WindowsTerminal.exe`、`sing-box.exe`、`tailscaled.exe`、`easytier.exe`、WindowsApps 路径正则：改为 Linux 路由器能识别的规则。路由器透明转发的 LAN 客户端流量通常以域名、目标 IP、来源网段/设备分流更合适。
3. TUN 的 `auto_route`、DNS 劫持和防火墙规则：结合当前 LAN、WWAN 与 PPE/NSS 路由选择检查，避免路由递归。
4. WireGuard endpoint 的私有地址、路由规则、端口及绑定网卡：检查与 OpenWrt 已有 WireGuard 接口是否冲突。
5. 监听在 `127.0.0.1` 的 API 仅在路由器本机可访问；独立 Web 面板访问需要单独考虑安全的 API 接入方式。

**私有配置文件由用户在路由器上导入。** GitHub 固件仓库只包含管理程序和必要依赖。

配置文件可先通过 `sing-box check -c /etc/sing-box/config.json -D /usr/share/sing-box` 校验。应用自身对上传的 JSON 也提供校验按钮。

## 网络唤醒（Wake on LAN）

入口：**服务 → 网络唤醒**。安装 `luci-app-wol`、`etherwake`、`luci-i18n-wol-zh-cn`。

配置待唤醒电脑的网卡 MAC 地址，选择与电脑通过网线相连的局域网接口（通常为 `br-lan`，以设备实际接口为准），即可发送魔法包。电脑的 BIOS/UEFI 和网卡驱动需要开启相应的局域网唤醒支持。

本固件的 `luci-app-wol` 使用 OpenWrt 官方简体中文语言包，界面随 LuCI 的语言设置显示中文。
