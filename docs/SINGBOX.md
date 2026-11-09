# HomeProxy（sing-box 内核）

固件预装 [ImmortalWrt HomeProxy](https://github.com/immortalwrt/luci/tree/master/applications/luci-app-homeproxy) 管理界面及 `sing-box` 内核，替代原来的第三方 `luci-app-sing-box` 页面。

## 管理与配置

- **LuCI 入口**：服务 → HomeProxy。
- **配置路径**：`/etc/config/homeproxy`；HomeProxy 规则、证书和资源位于 `/etc/homeproxy/`。
- **代理内核**：`sing-box`（来自匹配的 ImmortalWrt packages）。
- **运行行为**：首次启动按 HomeProxy 上游默认配置运行；是否启用由用户在 HomeProxy 中控制。

HomeProxy 使用自己的 UCI 配置体系，**不直接兼容**先前 `luci-app-sing-box` 的 JSON 管理页面配置，也不会自动导入原来的 `/etc/sing-box/config.json`。升级前请单独备份已有配置，需要时按 HomeProxy 的规则和节点格式手动迁移。

原固件的 `95-sing-box-tun-user` 首次启动脚本已移除；该脚本只适用于旧版 LuCI 应用，不能用于 HomeProxy。固件仍保留 TUN 所需的内核模块及 HomeProxy 的 nftables TPROXY 依赖。

## 与 Tailscale 共存

HomeProxy/sing-box 和 Tailscale 可以在同一台路由器上使用，但启用 TUN、透明代理或更改默认路由时，需要排除 Tailscale 控制和远程管理流量，以及代理节点自身的连接，以免路由循环或管理断线。

节点凭据、个人规则、VPN 私钥均不写入公开仓库。路由器上保存的 HomeProxy 配置需要独立备份。
