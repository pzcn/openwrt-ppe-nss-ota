# ImmortalWrt 软件包与构建配置

本项目只使用 **ImmortalWrt + Julius PPE/NSS** 进行固件构建。内核、DTB、NSS Wi-Fi 驱动和 kmod 来自对应版本的源码编译及专用 ImageBuilder，不混装其他快照的内核模块。

## 文件分工

- `immortalwrt-re-ss-01.config`：目标设备、NSS/PPE、ImageBuilder、F2FS 和内核相关选项。
- `add.txt`：LuCI 应用、中文翻译、网络工具、WireGuard、Tailscale、sing-box、WOL 等必需包。
- `remove.txt`：需要移除的基础软件包。
- `translations/`：PPE QoS 与固件更新页面的自定义翻译，构建时生成 `.lmo`。

Aurora 固定为 v1.4.0、sing-box LuCI 固定为 v0.4.7；均从固定源码标签编译。PPE QoS 来自 Julius 的 LuCI 分支，其余常用软件包使用 ImmortalWrt feeds。

## F2FS 与存储

`kmod-fs-f2fs`、`f2fs-tools` 同时声明在软件包清单与编译配置；构建期间按需要补齐京东云设备级 `DEVICE_PACKAGES`。p18 上使用 SquashFS + F2FS 可写层。p27 保留独立 ext4 分区，由 ImmortalWrt 上游挂载机制管理。

## 测试

`scripts/tests/test-extra-apps.py` 负责防止用户插件与中文包遗漏；`scripts/tests/test-immortalwrt-compat.py` 测试两个临时修复。LuCI、Dr.COM、OTA、Builder 元数据都有独立离线测试。缺少必需 Kconfig 选项或编译产物时直接报错。
