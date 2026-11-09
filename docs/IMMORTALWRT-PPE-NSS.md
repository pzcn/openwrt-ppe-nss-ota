# ImmortalWrt PPE/NSS：源码构建与 ImageBuilder

## 系统来源

- 操作系统：`immortalwrt/immortalwrt` 的 `master`，目标 `qualcommax/ipq60xx`。
- 有线 PPE 与无线 NSS：`JuliusBairaktaris/openwrt-ppe-nss` 的 `ppe-nss` 分支。
- NSS firmware/feed：`JuliusBairaktaris/nss-packages` 的 `ppe-nss` 分支。
- PPE QoS LuCI：Julius LuCI `luci-app-ppe-qos` 分支。
- 设备：`jdcloud_re-ss-01`；实际 1 GiB 内存，使用兼容的 512M NSS 内存配置。

内核、DTB、无线驱动、NSS 固件和其他 kmod 都从同一源码组合编译。

## 两条工作流及触发条件

**固件工作流：** `.github/workflows/firmware-immortalwrt.yml`

- `main` 分支的 `scripts/`、`files/`、`config/` 和固件工作流变动时执行。
- 每天 04:19 UTC 检查最新 Builder 与当前源码；如果最新版固件已经包含同一 Builder 和同一源码提交，则跳过。
- 支持手动选择 `builder_tag`、强制重新打包及是否发布 Release。
- `pull_request` 只执行离线验证，不编译固件。
- 只执行 `scripts/repack-immortalwrt.sh`，默认选择最新发布的 Builder，手动指定标签时使用指定版本。当前仓库的 Builder 编译指纹与既有 Release 不同时，仍然可以重打包；不会调用完整内核编译。

**Builder 工作流：** `.github/workflows/builder-immortalwrt.yml`

- **每周日 05:43 UTC（北京时间 13:43）自动完整编译一次**，也可以随时点击 `Run workflow` 手动触发完整编译。
- 两种触发方式完全一致，均直接调用 `scripts/build-immortalwrt.sh`；**不预先检查上游是否更新，不比较旧版 Builder 来跳过编译**。
- 编译包含 ImmortalWrt、PPE/NSS、feeds、内核、所有 APK 和独立 ImageBuilder，并运行重打包烟雾测试。
- 编译成功后上传 ImageBuilder 到 Releases，随后使用 `workflow_dispatch` 自动触发固件工作流。
- 保留必要的文件校验与 Release 标签冲突保护：如果编译结果的标签已经存在，不覆盖旧 Release，但仍完成本次编译和触发固件工作流。

**两条流水线之间的契约：**

- Builder Release：`imm-builder-...`，包含 ImageBuilder 压缩包、`builder-metadata.json`、`base-overlay.tar.gz`、`imagebuilder-packages.txt`。
- 固件 Release：`imm-ppe-nss-...`，包含 sysupgrade、manifest、`ota.json` 和 Builder 元数据。
- `builder-metadata.json` 中的指纹用于记录该 Builder 的编译来源，而不是要求它与当前 Git 代码一致。固件侧校验 Builder 自身的 Release 标签、设备型号、渠道，以及压缩包、覆盖层和软件包列表的 SHA256；软件包只能来自该 Builder 的仓库。
- `ota.json` 记录 `builder_tag` 和 `source_commit`，用于每天的无变动跳过判断。

## Builder 与固件的职责边界

Dr.COM 等自定义 LuCI 页面、认证脚本和启停逻辑属于**固件覆盖层**，不属于 Builder 的内核、NSS 或 APK 编译依赖。完整源码构建中仅在生成测试固件时调用通用的 `scripts/stage-firmware-overlay.sh`；正式的 ImageBuilder 重打包也调用此脚本。Dr.COM 源码完整保留，但不会打包到新固件。

Builder 的 `scripts/build-immortalwrt.sh` 指纹会忽略明确标记的 **firmware-only overlay** 区块，核心源码构建命令仍参与指纹。以后改动 App 开关、LuCI 页面或者认证脚本，**不需要因此重新编译 Builder**。Builder 流水线也不再执行 Dr.COM 专项测试；其测试保留在固件流水线。

注意：源码指纹变化不会使已编译 Builder 失效。新固件使用 Builder 编译时对应的内核与软件包仓库；新添加的插件若缺少匹配 APK，打包会报错，需等待下次 Builder 源码编译。

## 插件更新范围

`config/add.txt`、`config/remove.txt` 不再使已有 Builder 的**核心兼容性**失效。打包会按最新插件清单尝试选用匹配 Builder 内的软件包：APK 已存在可直接重打包；不存在则明确失败，不能强行混用普通 Snapshot kmod。两个清单变化也会产生新的 Builder 发行版指纹，使下一次每周或手动完整构建能够补编缺少的软件包。

官方 packages、LuCI、routing、telephony 与 NSS/QoS feed 使用单独的源码提交指纹，能识别主系统 SHA 未变化时的上游插件版本更新。只有 Builder 重新编译后，新 APK 才能用于后续固件打包。

## 两个兼容补丁

`scripts/apply-immortalwrt-compat.sh` 在本轮 ImmortalWrt 源码树补齐 F2FS 设备软件包，并基于**当前源码的** `platform.sh` 注入 sysupgrade 配置复制接口。首次完整固件和专用 Builder 的基础文件覆盖层都采用相同平台脚本。重新打包时会校验该脚本存在。

源码升级后检测到已有官方配置复制接口时，保留官方实现。分别在 ImmortalWrt 上游合并、真机验证后移除临时修复。详见 [临时补丁](TEMPORARY-PATCHES.md)。

## 软件包与 LuCI

当前固件保留：Aurora、PPE QoS、OTA、Tailscale、sing-box、WireGuard、WOL、文件管理、ttyd、nlbwmon、statistics、wifihistory、irqbalance、lldpd、PBR、tcpdump、conntrack、F2FS 工具、简体中文包。

Dr.COM 校园网认证 App 的菜单、后端、启动脚本和定时认证任务在两条固件构建路径中排除，源码和离线测试保留在仓库。

添加/排除包见 `config/add.txt`、`config/remove.txt`；设备及内核配置见 `config/immortalwrt-re-ss-01.config`。源码构建检查 Kconfig 必选项；ImageBuilder 使用匹配的完整 APK 包仓库。

## 缓存现状

`dl/`、ccache 和官方 GCC/musl 工具链复用已接入。2026-11-09 的一次完整编译日志显示下载缓存命中、ccache 命中率 25.45%、官方工具链通过验证，但完整编译仍约 97 分钟。这些机制不影响固件工作流复用最新已发布 Builder；下一轮单独研究加速方案。

ImageBuilder 已作为 Release 资产发布，没有第二套 Builder 缓存。

## 设备验证

建议在正式使用前核对：PPE flowtable、ath11k NSS、F2FS 重启持久化、sysupgrade 保留配置、p27 数据、WireGuard、Tailscale、sing-box、WOL 和 OTA。编译完成属于构建验证；设备运行效果以真机测试为准。
