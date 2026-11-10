# ImmortalWrt 软件包与构建配置

本项目只使用 **ImmortalWrt + Julius PPE/NSS** 进行固件构建。内核、DTB、NSS Wi-Fi 驱动和 kmod 来自对应版本的源码编译及专用 ImageBuilder，不混装其他快照的内核模块。

## 文件分工

- `immortalwrt-re-ss-01.config`：目标设备、NSS/PPE、ImageBuilder、F2FS 和内核相关选项。
- `add.txt`：LuCI 应用、中文翻译、网络工具、WireGuard、Tailscale、sing-box、WOL 等必需包。
- `remove.txt`：需要移除的基础软件包，以及旧 Builder 中不再需要的 LuCI 应用。
- `translations/`：PPE QoS 与固件更新页面的自定义翻译，构建时生成 `.lmo`。

Aurora 固定为 v1.4.0、sing-box LuCI 固定为 v0.4.7，均从固定源码标签编译。定时重启、CPU 调频、DDNS-Go、autocore、default-settings-chn 和中文翻译均来自 ImmortalWrt 官方 feeds。PPE QoS 来自 Julius 的 LuCI 分支。

**HomeProxy 不仅从固件清单排除，也从新版 Builder 的 LuCI feed 源码目录、软件包索引和配套 SDK 导出中移除。** 旧 Builder 的固件重打包仍保留 `remove.txt` 里的排除规则。SDK 按锁定 feeds SHA 补编新包时，也会在生成索引前排除 HomeProxy；不会修改上游 Git 提交和 ABI 锁。

## 中国区默认设置与 APK 软件源

`default-settings-chn` 首次启动会配置中文环境、上海时区和 NTP，并可能切换 APK 镜像。此固件使用自编译 NSS 内核，`files/etc/uci-defaults/98-keep-immortalwrt-apk-feed` 在它之前设置官方 ImmortalWrt 源，避免被改到第三方普通软件源；已有自定义镜像设置不覆盖。

## F2FS 与存储

`kmod-fs-f2fs`、`f2fs-tools` 同时声明在软件包清单与编译配置；构建期间按需要补齐京东云设备级 `DEVICE_PACKAGES`。p18 上使用 SquashFS + F2FS 可写层。p27 保留独立 ext4 分区，由 ImmortalWrt 上游挂载机制管理。

## 三阶段构建与复用

1. **完整 Builder（`builder-immortalwrt.yml`）**：每周一次或手动触发。编译内核、NSS、内核模块、软件包、ImageBuilder 和同 ABI 的 SDK；沿用下载缓存、ccache 和 Go 构建缓存。仅适用于内核/NSS/工具链或底层补丁更新。
2. **增量 Builder（`builder-incremental.yml`）**：软件包清单变化时自动触发，也可手动指定现有 Builder 标签。下载同一 Release 内完整验证过的 ImageBuilder/SDK，使用已有 SDK APK 缓存按需补包，移除 HomeProxy 源码和 APK，重新封装两份归档并签发独立版本、SHA256 和来源信息。**不重新编译内核或 NSS**。
3. **固件（`firmware-immortalwrt.yml`）**：代码修改后复用现有 Builder；在增量 Builder 发布后会指定新 Builder 再生成固件。ImageBuilder 负责完整固件组装和最终 manifest 校验。

增量 Builder 是 *基于旧 ABI 的新发布包*，不是新的内核构建。当目标内核、NSS、编译工具链等真正发生变化时，仍需选择完整 Builder。旧版 SDK 的运行时 ABI 和 immutable feeds SHA 不会被增量 Builder 擅自改写；新版 Builder/SDK 通过 `derived_from_builder` 可回溯来源。

HomeProxy 从新版 SDK 实际源码入口、软件包 APK、生成索引和默认勾选中排除；`luci-app-sing-box` 则继续保留。

## 测试

`scripts/tests/test-extra-apps.py` 负责防止用户插件与中文包遗漏；`scripts/tests/test-immortalwrt-compat.py` 测试两个临时修复。LuCI、Dr.COM、OTA、Builder 元数据都有独立离线测试。缺少必需 Kconfig 选项或编译产物时直接报错。
