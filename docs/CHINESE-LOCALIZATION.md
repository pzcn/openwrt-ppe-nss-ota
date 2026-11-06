# LuCI 简体中文本地化

本仓库不仅设置了 LuCI 的 `zh_cn` 语言偏好，还确保已经预装的应用有可用的翻译文件。**软件包清单、依赖及系统服务的英语名称不会被强行改名**，以免影响 `apk` 和自动更新。

## 覆盖范围

| 页面 / 软件包 | 来源 | 简体中文实现 |
|---|---|---|
| LuCI 基础菜单、系统和网络配置 | OpenWrt 官方 | `luci-i18n-base-zh-cn` |
| 防火墙 | OpenWrt 官方 | `luci-i18n-firewall-zh-cn` |
| APK 软件包管理 | OpenWrt 官方 | `luci-i18n-package-manager-zh-cn` |
| SQM 智能队列 | OpenWrt 官方 + PPE 构建 | **新增** `luci-i18n-sqm-zh-cn` |
| BCP38 出口过滤 | OpenWrt 官方 + PPE 构建 | **新增** `luci-i18n-bcp38-zh-cn` |
| 文件管理器、终端、流量分析、统计、Wi-Fi 历史、IRQ Balance、LLDP、PBR | OpenWrt 官方 | 已有对应 `luci-i18n-*-zh-cn` |
| PPE 硬件 QoS | JuliusBairaktaris 的 LuCI 分支 | **新增** `qca-ppe-qos.zh-cn.lmo`（61 项含菜单） |
| ppe-update 固件更新 | PPE+NSS 自定义组件 | **新增** `ppe-update.zh-cn.lmo`，已有更新页面正文为中文 |
| PPE / NSS 硬件加速监控 | 本仓库自研 | 原本就使用中文文字 |

WireGuard 协议界面的大部分通用文本属于 LuCI base 目录；当前官方 `luci-proto-wireguard` 没有独立的 `po/zh_Hans` 翻译目录，因此没有加入不存在的 `luci-i18n-proto-wireguard-zh-cn` 包。

## 技术实现

上游 PPE Hardware QoS 使用 `applications/luci-app-qca-ppe-qos/htdocs/luci-static/resources/view/network/qca-ppe-qos.js`，原本不存在简体中文 PO/LMO。这里按照该分支现有的 **60 条 gettext 文案** 写入对应中文字典，并补充菜单标题 `PPE QoS`。

构建时运行：

```sh
python3 scripts/tests/test-luci-i18n.py
python3 scripts/build_luci_i18n.py \
  --input config/translations/qca-ppe-qos.zh-cn.json \
  --output /tmp/qca-ppe-qos.zh-cn.lmo \
  --min-entries 61
```

构建器将生成的 `qca-ppe-qos.zh-cn.lmo` 和 `ppe-update.zh-cn.lmo` 一起放入固件中的：

```
/usr/lib/lua/luci/i18n/
```

这是 LuCI 官方的标准 LMO 翻译路径，切换为英文时不加载这些中文目录。相关的 QoS JS 和 QoS 驱动、NSS/PPE 模块均保持上游原样。翻译源存储为 UTF-8 JSON，编译成的 LMO 格式沿用 LuCI 官方 `po2lmo` 的 SuperFastHash、4 字节对齐与排序索引格式。

## 修改翻译

修改 `config/translations/qca-ppe-qos.zh-cn.json` 中的中文值（请不要修改英文 key）。如果上游 PPE QoS 新增英文文本，需要同时补全字典；没有对应词条时 LuCI 将自然回退显示英文。构建会检查本次已知词条数量以及 `%s`、`%d` 占位符一致性。

更新后如果仍显示英文，先检查 LuCI 语言是否为简体中文、清除浏览器缓存并重新登录；可以通过 SSH 验证：

```sh
ls -lh /usr/lib/lua/luci/i18n/qca-ppe-qos.zh-cn.lmo
ls -lh /usr/lib/lua/luci/i18n/ppe-update.zh-cn.lmo
apk info | grep -E 'luci-i18n-(sqm|bcp38)-zh-cn'
uci -q get luci.main.lang
```

注意：没有修改软件包的可执行程序文字或其他第三方应用的 WebUI，只处理 **已验证存在的 LuCI 汉化缺口**。
