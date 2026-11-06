# PPE / NSS 硬件加速

入口：**状态 → PPE / NSS 硬件加速**

页面沿用 OpenWrt LuCI 原生布局，每 **8 秒** 自动刷新一次。

## 页面内容

- **加速引擎**：PPE 硬件流量卸载、NSS Wi-Fi 加速、NSS 运行核心数。
- **连接统计**：硬件卸载连接、软件卸载连接、Conntrack 总连接数。
- **内核诊断**：默认折叠，展开后查看 PPE offload 统计和 NSS 驱动信息。

连接统计来自 `/proc/net/nf_conntrack` 中的 `[HW_OFFLOAD]` 与 `[OFFLOAD]` 标记；硬件卸载开关来自防火墙 UCI，NSS 状态来自驱动和 debugfs。

## 诊断命令

```sh
ubus call luci.ppe-nss-monitor get_status
grep -c HW_OFFLOAD /proc/net/nf_conntrack
cat /sys/module/ath11k/parameters/nss_offload
```

## 组件

- `files/www/luci-static/resources/view/status/ppe-nss-monitor-native.js`：LuCI 页面
- `files/usr/share/rpcd/ucode/luci.ppe-nss-monitor`：数据接口
- `files/usr/share/rpcd/acl.d/luci-app-ppe-nss-monitor.json`：读取权限
- `files/usr/share/luci/menu.d/luci-app-ppe-nss-monitor.json`：菜单
