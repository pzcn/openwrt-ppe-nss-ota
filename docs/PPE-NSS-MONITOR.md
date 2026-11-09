# PPE / NSS 硬件加速：真实驱动统计

入口：**状态 → PPE / NSS 硬件加速**。每 **8 秒** 刷新一次，只读取驱动已有的 debugfs 和内核接口，不写入设置、不清空计数器。

## 实际数据来源

| 指标 | 驱动数据来源 | 含义 |
| --- | --- | --- |
| PPE 活跃硬件流表项 | `*.ppe/offload` 的 `live_entries` | 当前安装到 PPE 的硬件流表项 |
| PPE 历史成功安装规则 | 同一接口的 `offloaded` | 自驱动初始化以来的累计安装次数，不是活跃连接数 |
| PPE 端口出口速率 | `*.ppe/egress` 的端口 TX 字节计数 | 交换机各硬件端口输出速率，**包括普通流量，不能当作纯硬件卸载速率** |
| NSS 已安装流表规则 | `*.nss/flows` 中 `installed 1` 的记录数 | NSS 固件当前仍安装的转发规则 |
| NSS 已安装桥接规则 | 上述记录中含 `bridged` 的规则数 | 观察无线与有线之间的 NSS 桥接加速 |
| NSS 历史下发固件规则 | `*.nss/flows` 的 `pushed` | 规则下发次数，不是实时流量 |
| NSS Wi-Fi 接收速率 | `*.nss/wifili_rx` 的 `vdev rx ... bytes` | Wi-Fi 数据通路接收入队的字节变化率，**不是 Wi-Fi 双向吞吐量** |
| NSS Wi-Fi 收包、待发包 | `wifili_rx` 的 `rx enqueue`、`tx rcvd` | 固件实际处理的数据通路计数 |
| Conntrack 卸载标记 | `/proc/net/nf_conntrack` | 仅作为辅助；桥接与 NSS 规则不一定对应 Conntrack 标记 |

原有防火墙 `flow_offloading_hw` 仍显示，但明确标注为**配置**，不能凭此断言有硬件流量。

## 采样约束

- 前端对两次**连续递增**的字节计数取差，再根据实际间隔换算 Mb/s；首次采样显示“采样中”。
- 驱动重置、计数器回绕或中断时不显示虚假的负速率。
- IPQ60xx 的 PPE 可能通过 **switchdev 直接加速桥接**，而无需产生 routed flowtable 规则，因此 `live_entries=0` 不是加速故障的证据。
- 因为 `*.ppe/flows` 会扫描硬件流表，常驻页面避免每 8 秒全表读取；需要核对某一条流的硬件包数时再通过 SSH 手动检查。
- 一部分路径在不同内核/驱动版本中可能不存在；缺失时显示“—”而非“0”。
- 只向 LuCI RPC 返回汇总计数；仅返回汇总计数，不含连接的 IP 地址、端口或流内容。

## 路由器 SSH 诊断

```sh
mount | grep debugfs
cat /sys/kernel/debug/*.ppe/offload
cat /sys/kernel/debug/*.ppe/egress
cat /sys/kernel/debug/*.nss/flows | head -n 12
cat /sys/kernel/debug/*.nss/wifili_rx | head -n 30
/usr/libexec/ppe-nss-telemetry
ubus call luci.ppe-nss-monitor get_status
```

*注意：* `cat .../*.nss/flows` 可能包含连接地址，诊断输出不要直接公开分享；LuCI 返回的仅是聚合计数。

## 关键源码

- [Julius PPE 流表](https://github.com/JuliusBairaktaris/openwrt-ppe-nss/blob/ppe-nss/target/linux/qualcommax/files/drivers/net/ethernet/qualcomm/qca_ppe_flow.c)：`live_entries`、`offloaded` 等。
- [Julius NSS 转发](https://github.com/JuliusBairaktaris/openwrt-ppe-nss/blob/ppe-nss/package/kernel/nss-wifi-drv/src/nss_flow.c)：`installed`、`pushed`、桥接规则。
- [Julius Wi-Fi 驱动](https://github.com/JuliusBairaktaris/openwrt-ppe-nss/blob/ppe-nss/package/kernel/nss-wifi-drv/src/nss_wifili.c)：每个 vdev 的 RX/TX 硬件统计。

## 固件组件

- `files/usr/libexec/ppe-nss-telemetry`：只读 debugfs 解析，输出脱敏 JSON。
- `files/usr/share/rpcd/ucode/luci.ppe-nss-monitor`：RPC 接口。
- `files/www/luci-static/resources/view/status/ppe-nss-monitor-native.js`：LuCI 前端。
- `scripts/tests/test-ppe-nss-telemetry.py`：模拟驱动格式的回归测试。
- `scripts/tests/test-ppe-nss-monitor.js`：页面采样与无效数据处理测试。
