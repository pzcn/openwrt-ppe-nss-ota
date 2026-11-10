# sing-box 配置管理

固件预装 sing-box 内核与 [luci-app-sing-box v0.4.7](https://github.com/lauyv/luci-app-sing-box/tree/v0.4.7) 中文 JSON 管理界面，不再使用 HomeProxy。

- **LuCI 入口**：服务 → sing-box。
- **源码版本**：v0.4.7，固定提交 `fde997eb88c5d8d9b6dbc138b36e8a298402b03c`。
- **配置文件**：`/etc/sing-box/config.json`。
- **运行目录**：`/usr/share/sing-box`。
- **功能**：上传、编辑和校验 JSON、启停服务、查看日志。
- **默认状态**：sing-box 服务保持关闭，用户自行添加 JSON。

校验配置：

```sh
sing-box check -c /etc/sing-box/config.json -D /usr/share/sing-box
```

首次启动脚本 `95-sing-box-tun-user` 仅在服务关闭且默认用户为 sing-box 时，将其运行用户改为 root，以支持 TUN；不会覆盖自定义用户。

## 构建与升级

完整源码构建和匹配 SDK 补编都使用上述固定源码，并在编译前生成校验过 SHA256 的 Zashboard 资源。若现有 Builder 没有 `luci-app-sing-box` APK，固件工作流使用同版本 SDK 补编；没有对应 SDK 时，需要先完整编译 Builder。

HomeProxy 使用自己的 UCI 配置，不能自动迁回 sing-box JSON；升级前单独备份 `/etc/config/homeproxy`、`/etc/homeproxy/` 或之前的 `/etc/sing-box/config.json`。

## 与 Tailscale 共存

Tailscale 负责远程访问和 WOL，sing-box 负责代理。使用 TUN `auto_route` 时应排除 Tailscale 及代理节点的自身流量，避免路由回环。个人 JSON、节点凭据和 VPN 私钥不写入公开仓库。
