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
- 编译包含 ImmortalWrt、PPE/NSS、feeds、内核、所有 APK、独立 ImageBuilder 和匹配的 **OpenWrt SDK**，并运行重打包烟雾测试。
- 编译成功后在 **同一个 `imm-builder-...` Release** 上传 ImageBuilder、SDK、SHA256 元数据与 feeds 锁定文件，然后使用 `workflow_dispatch` 触发固件工作流。
- 保留必要的文件校验与 Release 标签冲突保护：如果标签已经存在，不覆盖旧 Release；必须确认其 SDK 资产齐全才视为成功。SDK 归档也校验基本构建规则、工具链及内核 `Module.symvers`。

**两条流水线之间的契约：**

- Builder Release：`imm-builder-...`，包含 ImageBuilder 压缩包、`builder-metadata.json`、`base-overlay.tar.gz`、`imagebuilder-packages.txt`，以及 `immortalwrt-sdk-*.tar.zst`、`sdk-metadata.json`、`sdk-feeds.lock.json`。
- 固件 Release：`imm-ppe-nss-...`，包含 sysupgrade、manifest、`ota.json` 和 Builder 元数据。
- `builder-metadata.json` 中的指纹用于记录该 Builder 的编译来源，而不是要求它与当前 Git 代码一致。固件侧校验 Builder 自身的 Release 标签、设备型号、渠道，以及压缩包、覆盖层和软件包列表的 SHA256；软件包只能来自该 Builder 的仓库。
- `ota.json` 记录 `builder_tag` 和 `source_commit`，用于每天的无变动跳过判断。


## 匹配 OpenWrt SDK：为新增插件补编 APK

SDK **不是 ImageBuilder 的替代品**：ImageBuilder 将已有 APK 和覆盖层组装成固件；SDK 则包含与 Builder 同一次源码构建的目标头文件、库、交叉编译器以及内核符号表，可以补编用户态软件包及匹配当前内核的 kmod。

完整 Builder 编译增加 `CONFIG_SDK=y`，并且因为当前优先使用经过 SHA256 校验的 ImmortalWrt 官方外部交叉工具链，必须同时设置 `CONFIG_EXTERNAL_TOOLCHAIN_SDK=y`。源码的 `target/sdk/Config.in` 明确规定这一依赖。两者由同一次 `make` 构建；SDK 缺少交叉编译工具链、构建规则或 `Module.symvers` 时将拒绝发布。

打开 [Releases](../../releases) 中对应的 `imm-builder-...` 标签，一起下载：

- `immortalwrt-sdk-qualcommax-ipq60xx*.tar.zst`：目标 `qualcommax/ipq60xx` 的配套 SDK；
- `sdk-metadata.json`：SDK 归档 SHA256、对应 Builder 标签及 Builder 元数据 SHA256；
- `sdk-feeds.lock.json`：ImmortalWrt 与六个 feed（packages、luci、routing、telephony、nss、独立 PPE QoS LuCI）的源码提交；
- `builder-metadata.json`：与其配套的独立 ImageBuilder 来源信息。

在仓库根目录校验（替换为下载的实际文件名）：

```sh
python3 scripts/immortalwrt_sdk.py verify \
  --metadata sdk-metadata.json \
  --builder-metadata builder-metadata.json \
  --archive immortalwrt-sdk-qualcommax-ipq60xx_gcc-14.4.0_musl.Linux-x86_64.tar.zst \
  --feed-lock sdk-feeds.lock.json
```

解压 SDK 后可按上游惯例添加 feed 或本地 package、运行 `make defconfig`、再运行 `make package/<包路径>/compile V=s`。**必须将所需 feed 锁定为 `sdk-feeds.lock.json` 内对应的提交**，不能直接拿其当前 HEAD 的新软件包冒充同一 Builder 版本。补编结果需要加入 **对应 Builder** 的离线 APK 仓库，才能由 ImageBuilder 正确处理依赖；尤其不能从别的固件混用 kmod、libc、libgcc。

这次仅实现 **SDK 的构建、校验和发布**。尚未实现“通过 SDK 自动补编缺失包并上传到 Builder APK 仓库”，该功能需要单独的工作流及严格的版本匹配。发布 SDK 会增加一定磁盘、压缩和上传时间，但**不会重编第二套内核/NSS**。

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

当前固件保留：Aurora、PPE QoS、OTA、Tailscale、HomeProxy/sing-box、WireGuard、WOL、文件管理、ttyd、nlbwmon、statistics、wifihistory、irqbalance、lldpd、PBR、autoreboot、cpufreq、default-settings-chn、autocore、diskman、ddns-go、tcpdump、conntrack、F2FS 工具、简体中文包。

Dr.COM 校园网认证 App 的菜单、后端、启动脚本和定时认证任务在两条固件构建路径中排除，源码和离线测试保留在仓库。旧版 `luci-app-sing-box` 从预装列表删除，改用 ImmortalWrt 官方 `luci-app-homeproxy`；sing-box 内核保留。`default-settings-chn` 的镜像源切换由固件 UCI 默认脚本阻止，以保留匹配的 NSS 软件源。

添加/排除包见 `config/add.txt`、`config/remove.txt`；设备及内核配置见 `config/immortalwrt-re-ss-01.config`。源码构建检查 Kconfig 必选项；ImageBuilder 使用匹配的完整 APK 包仓库。

## Builder 编译耗时与加速

[2026-11-09 Builder Actions #42594186291](https://github.com/pzcn/openwrt-ppe-nss-ota/actions/runs/42594186291) 实际耗时约 **142 分钟**；构建脚本报告 `make download` **143 秒**，`make -j$(nproc)` **7884 秒**（131.4 分钟）。这是首次未命中历史下载缓存与 ccache 的冷启动，ccache 只有同一轮任务内部的 **3183/29977（10.62%）** 命中。官方 GCC 14.4.0/musl 1.2.6 交叉工具链已经被复用。

现在恢复三种独立缓存：

- `.build-cache/dl`：下载源码归档、Go modules；
- `.build-cache/ccache`：C/C++ 编译对象（1.6 GB 上限）；
- `.build-cache/go-build`：Go 的标准库和交叉编译结果，配置项 `CONFIG_GOLANG_BUILD_CACHE_DIR`，不再丢在每次构建都会清空的 `tmp/go-build`。

同时使用 GitHub `actions/setup-go@v6` 安装官方 Go 1.26 二进制，利用官方 packages feed 自带的 `GOLANG_EXTERNAL_BOOTSTRAP_ROOT` 与 `GOLANG_BUILD_BOOTSTRAP` 配置跳过多级旧 Go 自举。匹配的 Go 1.27 宿主编译器仍会构建。设置未生效时在主编译之前明确告警，并自动使用上游默认方式继续编译。新增分阶段计时，后续可以对比实际收益。

GitHub Actions 默认缓存 **7 天未访问可能清理**，仓库额度默认 **10 GB**；每周一次编译接近 7 天边界。若缓存经常失效，应将仓库 Actions 缓存保留期调整到至少 14 天（在 GitHub 设置中操作），或者改用有持久磁盘的自托管 Runner。任何缓存都不能跨编译组合强行复用不兼容的 NSS/kmod 内核对象。

本项目已经使用官方预编译交叉工具链；大幅缩短编译时间的下一步通常是更高核心数的 Runner 或受版本校验约束的持久化增量构建，而不是给 `make download` 增加线程。**本次改动尚未跑完整源码构建性能对照**，加速幅度需从下一次 Actions 日志测量。

## 设备验证

建议在正式使用前核对：PPE flowtable、ath11k NSS、F2FS 重启持久化、sysupgrade 保留配置、p27 数据、WireGuard、Tailscale、sing-box、WOL 和 OTA。编译完成属于构建验证；设备运行效果以真机测试为准。
