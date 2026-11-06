# PPE + NSS 硬件加速监控

这个页面是针对 JuliusBairaktaris/openwrt-ppe-nss 的 **qca_ppe + nss-wifi-drv** 新架构设计的轻量级 LuCI 只读仪表盘。它不是旧版 ECM / qca-nss-drv 监控插件。

## 访问

刷入包含本页面的固件后，在 LuCI 中进入：

**状态 → PPE / NSS 硬件加速**

使用 **LuCI 原生的 cbi-map、cbi-section 和 table 布局**，跟随 OpenWrt 当前主题（包括 Aurora）的颜色与排版，不使用自定义深色 CSS。默认每 **8 秒** 更新一次，支持暂停和手动刷新。最近 24 个样本以简洁的字符趋势显示，只保留在当前浏览器页面，不写入 eMMC。

## 真实数据来源

| 指标 | 采集接口 | 注意事项 |
| --- | --- | --- |
| 当前硬件卸载连接数 | `/proc/net/nf_conntrack`，包含 `[HW_OFFLOAD]` 标记的行数 | 仅为当前存活连接数，不是带宽或卸载流量百分比 |
| 软件 Flowtable 连接数 | `/proc/net/nf_conntrack` 中仅包含 `[OFFLOAD]`、没有 `[HW_OFFLOAD]` 的行数 | 不是所有未卸载的连接 |
| Conntrack 总量 | `/proc/net/nf_conntrack` 记录行数 | 不是 PPE 硬件流表容量 |
| PPE 开关 | 防火墙默认配置中的 `flow_offloading_hw` | 配置开启不代表当前一定有硬件连接 |
| PPE 内核诊断 | `/sys/kernel/debug/*.ppe/offload` | 驱动未提供或 debugfs 未挂载时明确提示不可用 |
| NSS Wi-Fi 活动路径 | `/sys/module/ath11k/parameters/nss_offload` | 1 表示 ath11k 当前使用 NSS 路径，0 为主机路径 |
| NSS 核心运行 | `/sys/kernel/debug/*.nss/boot` | 只将可解析的 0/1 计入运行核心数量 |
| NSS 流表接口是否存在 | `/sys/kernel/debug/*.nss/flows` | **只检查存在性，不读取流表数据** |

页面不会公开 conntrack 原始记录、IP 地址、端口或 NSS 的 flows 表。读取不修改防火墙、网络设置或 NSS 驱动。

需要真实测试时，请在局域网客户端与互联网之间产生持续 TCP 流量，例如下载大文件，然后观察 HW_OFFLOAD 是否出现。通过路由器自身 SSH 发起的流量通常不能作为硬件转发验证。

## 实现文件

- `files/www/luci-static/resources/view/status/ppe-nss-monitor-native.js`：原生 LuCI 状态页面、实时采样和趋势显示（不加载自定义样式）
- `files/usr/share/rpcd/ucode/luci.ppe-nss-monitor`：只读 ubus 采集接口
- `files/usr/share/rpcd/acl.d/luci-app-ppe-nss-monitor.json`：**只有 get_status 读取权限**
- `files/usr/share/luci/menu.d/luci-app-ppe-nss-monitor.json`：菜单入口

这些文件被 ImageBuilder 的 `FILES=files` 覆盖层直接打入 SquashFS。**不需要额外的软件包源、不需要修改内核模块、不需要安装旧版 luci-app-nss**。

## 排查

如果网页显示“通信异常”或所有指标不可用，在 SSH 中先运行：

```sh
ubus list 'luci.ppe-nss-monitor'
ubus call luci.ppe-nss-monitor get_status
mount | grep debugfs
grep -c HW_OFFLOAD /proc/net/nf_conntrack
cat /sys/module/ath11k/parameters/nss_offload
```

已登录 LuCI 的页面还依赖正常工作的 `rpcd-mod-ucode`。如果直接替换这些文件而不是通过固件升级安装，需要重启 `rpcd` 并刷新 LuCI 页面。

## 局限

- 驱动统计文件路径来自上游 PPE+NSS 文档，新内核或上游版本改变时可能需要适配。
- **没有硬件总带宽、处理器利用率、硬件卸载命中率等数据时不会虚构相关数值。**
- 首次集成尚未在真实 RE-SS-01 上进行网页功能测试；ImageBuilder 编译成功也不等同于每种 debugfs 格式都能解析。
