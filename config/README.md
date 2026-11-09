# ImmortalWrt 软件包与构建配置

本项目只使用 **ImmortalWrt + Julius PPE/NSS** 进行固件构建。内核、DTB、NSS Wi-Fi 驱动和 kmod 来自对应版本的源码编译及专用 ImageBuilder，不混装其他快照的内核模块。

## 文件分工

- `immortalwrt-re-ss-01.config`：目标设备、NSS/PPE、ImageBuilder、F2FS 和内核相关选项。
- `add.txt`：LuCI 应用、中文翻译、网络工具、WireGuard、Tailscale、sing-box、WOL 等必需包。
- `remove.txt`：需要移除的基础软件包。
- `translations/`：PPE QoS 与固件更新页面的自定义翻译，构建时生成 `.lmo`。

Aurora 固定为 v1.4.0，从固定源码标签编译。HomeProxy、定时重启、CPU 调频、磁盘管理、DDNS-Go、autocore、default-settings-chn 和中文翻译均来自 ImmortalWrt 官方 feeds。PPE QoS 来自 Julius 的 LuCI 分支。

## 中国区默认设置与 APK 软件源

`default-settings-chn` 首次启动会配置中文环境、上海时区和 NTP，并可能切换 APK 镜像。此固件使用自编译 NSS 内核，`files/etc/uci-defaults/98-keep-immortalwrt-apk-feed` 在它之前设置官方 ImmortalWrt 源，避免被改到第三方普通软件源；已有自定义镜像设置不覆盖。

## F2FS 与存储

`kmod-fs-f2fs`、`f2fs-tools` 同时声明在软件包清单与编译配置；构建期间按需要补齐京东云设备级 `DEVICE_PACKAGES`。p18 上使用 SquashFS + F2FS 可写层。p27 保留独立 ext4 分区，由 ImmortalWrt 上游挂载机制管理。

## 插件选择和 Builder 复用

调整 `add.txt`、`remove.txt` 会立即触发固件工作流，优先复用现成 Builder 的 ABI 兼容 APK。若新增插件还未编译，固件打包会失败并明确提示，Builder 将在下一次每周自动构建或手动执行时编译新版本。核心内核配置变化只能通过新的 Builder 生效。

## 测试

`scripts/tests/test-extra-apps.py` 负责防止用户插件与中文包遗漏；`scripts/tests/test-immortalwrt-compat.py` 测试两个临时修复。LuCI、Dr.COM、OTA、Builder 元数据都有独立离线测试。缺少必需 Kconfig 选项或编译产物时直接报错。
