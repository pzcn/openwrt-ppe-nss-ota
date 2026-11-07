# sing-box 配置管理

固件集成了 sing-box 完整内核和 [luci-app-sing-box](https://github.com/lauyv/luci-app-sing-box) 中文 LuCI 管理界面，与 Tailscale、网络唤醒同时保留。

## 管理与配置

- **LuCI 入口**：服务 → sing-box
- **面板版本**：`v0.4.7`，APK 在构建中按固定 SHA-256 校验
- **内核来源**：匹配的 OpenWrt 软件源
- **配置文件**：`/etc/sing-box/config.json`
- **运行目录**：`/usr/share/sing-box`
- **支持功能**：JSON 上传、编辑、校验、保存、启停及查看日志

固件默认保持 sing-box 停用，用户可自行上传 JSON 后验证：

```sh
sing-box check -c /etc/sing-box/config.json -D /usr/share/sing-box
```

为了在 OpenWrt 上使用 TUN，首次启动配置脚本仅在 sing-box 服务仍关闭、运行用户仍为默认 `sing-box` 时，把运行用户设为 `root`。保留用户自行修改的账号设置。

## 与 Tailscale 共存

路由器同时内置 Tailscale 与 sing-box：Tailscale 可用于远程管理与网络唤醒，sing-box 处理独立的代理连接。若启用 sing-box TUN 的 `auto_route`，需要针对实际 WAN/WWAN 设计路由，明确排除 Tailscale 流量及代理节点的自身连接，避免远程管理断线或流量循环。

从 Windows JSON 迁移时，`route.default_interface` 的 `WLAN`、Windows 进程规则和 WindowsApps 路径需要更换为 Linux/OpenWrt 对应设置。

个人 JSON、节点密码与 WireGuard 私钥不写入公开固件仓库。保存在路由器上的配置应单独备份。
