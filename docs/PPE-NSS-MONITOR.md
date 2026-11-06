# PPE / NSS 硬件加速监控

入口：**状态 → PPE / NSS 硬件加速**

使用 OpenWrt LuCI 原生样式展示 PPE 硬件卸载连接、NSS Wi-Fi 数据路径和内核统计。页面每 **8 秒** 更新一次，支持手动刷新和暂停；最近 24 次采样仅保存在浏览器当前页面。

## 监控指标

| 指标 | 数据来源 |
| --- | --- |
| 硬件卸载连接 | `/proc/net/nf_conntrack` 中的 `[HW_OFFLOAD]` |
| 软件 Flowtable 连接 | conntrack 中的 `[OFFLOAD]` |
| 连接跟踪总数 | `/proc/net/nf_conntrack` |
| PPE 硬件卸载开关 | 防火墙 `flow_offloading_hw` |
| PPE 内核统计 | `/sys/kernel/debug/*.ppe/offload` |
| NSS Wi-Fi 路径 | `/sys/module/ath11k/parameters/nss_offload` |
| NSS 核心状态 | `/sys/kernel/debug/*.nss/boot` |
| NSS flows 接口 | `/sys/kernel/debug/*.nss/flows` |

这些指标反映当前连接与驱动状态。测试硬件卸载时，可从局域网客户端发起持续下载，观察 `HW_OFFLOAD` 连接数。

## 诊断

```sh
ubus call luci.ppe-nss-monitor get_status
mount | grep debugfs
grep -c HW_OFFLOAD /proc/net/nf_conntrack
cat /sys/module/ath11k/parameters/nss_offload
```

如果页面提示通信异常，先确认 `rpcd` 服务与对应 ubus 对象正常。驱动版本变化时，部分 debugfs 统计路径可能需要调整。

## 组件

- `files/www/luci-static/resources/view/status/ppe-nss-monitor-native.js`：LuCI 监控页面
- `files/usr/share/rpcd/ucode/luci.ppe-nss-monitor`：监控数据接口
- `files/usr/share/rpcd/acl.d/luci-app-ppe-nss-monitor.json`：读取权限
- `files/usr/share/luci/menu.d/luci-app-ppe-nss-monitor.json`：菜单
