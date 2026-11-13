# RE-SS-01 Hybrid Builder：官方 Snapshot 复用路线图

> 目标：默认跟随 ImmortalWrt 官方 `qualcommax/ipq60xx` 最新 **已发布** Snapshot，复用它的交叉工具链、用户态 APK 和匹配的构建资料，仅自行编译 PPE/NSS 内核集成、必要的 kmod 与定制软件包，生成可离线重打包的独立 ImageBuilder + 配套 SDK。

## 基本原则

1. **默认 Hybrid，不再把“每周从 master 全量编译”当作日常路径。** 保留现有全源码 Builder 作为显式手动后备；引入新实现时先在独立分支验证，成功前不自动替换正式 Release。
2. **官方 Snapshot 是版本基准，而不是上游 master HEAD。** 以目标 `version.buildinfo` 的 commit 为目标内核源码基准；`feeds.buildinfo` 固定与目标同步的 feeds；用户态架构仓库还需独立锁定 `feeds.conf` 与其软件包索引。
3. **构建过程中不可追逐可变 URL。** 解析时冻结各文件的 SHA256、软件包归档 SHA256、源码提交；下载的文件逐一验证。构建前后核对官方目录关键元数据，发现切换则不发布，等待下次重新解析。
4. **永远不混用官方 kmod。** 自定义内核的 `kernel`、全部实际依赖的 `kmod-*` 由同一源码树构建；默认不打开 `CONFIG_ALL_KMODS`。要明确处理 `kernel` 版本与 ABI 依赖，不用忽略依赖的安装参数绕过。
5. **包源快照不是“同一天”就兼容。** target Snapshot 与通用 arch APK 可能是不同日期、不同 feed 提交。必须校验依赖闭包、`libc`/libgcc、SONAME/provides、包版本冲突；不兼容时选择性补编或失败，不发布混合镜像。
6. **离线可复现。** Release 包含构建锁文件、APK 镜像索引、归档校验和与来源清单；ImageBuilder 不依赖未来仍然可变的线上 Snapshot。
7. **保持现有 OTA 与 Firmware 工作流。** 只有通过 Builder/SDK 同 ABI 校验、ImageBuilder 重打包烟测、产物 manifest 审核及真实设备测试后才把 Hybrid Builder 切为默认发布路径。

## 分阶段实施（逐项验收）

### P0. 冻结接口与迁移范围（已开始）

- [x] 建独立开发分支，保留旧 `builder-immortalwrt.yml`、`build-immortalwrt.sh` 作为可随时使用的全源码后备。
- [x] 记录官方 Snapshot 的真实格式：目标 `version.buildinfo` 只有 `rNNNN-短 SHA`；目标 `feeds.buildinfo` 给 feed 全 SHA；架构 `feeds.conf` 可能与目标 feed SHA 不同。
- [ ] 冻结发布兼容接口：`builder-metadata.json`、`sdk-metadata.json`、`sdk-feeds.lock.json`、`imagebuilder-packages.txt`，为 Hybrid 元数据单独增加来源字段和 schema 版本，不冒充旧版本。

**验收**：兼容边界形成文档；现有稳定 Builder/固件流水线不变。

### P1. Snapshot Resolver + 可重复锁文件（第一阶段实现）

- [x] `scripts/resolve-immortalwrt-snapshot.py` 读取并锁定 target + arch 两套 `sha256sums`、各自的 feeds、完整源码提交及二进制 `packages.adb` 索引。
- [x] 验证 target/arch 索引 SHA256，锁定 ImageBuilder、SDK、Toolchain 资产哈希，识别官方 kmod ABI；6.18 系列内核才允许进入现有 PPE/NSS 移植。
- [x] 输出 schema 2 `snapshot-lock.json`，根据目标内核/工具链与 arch `sha256sums` 内容区分 `unchanged` / `packages-only` / `kernel-or-target`。
- [x] 离线测试覆盖更换 APK 内容但 feed 不变、坏索引、目录穿越、短 SHA 解析、内核不匹配、读取期间 Snapshot 切换。
- [x] 每日只读 CI 上传版本锁文件；已使用真实官方 Snapshot 验证，Github 提交解析使用 Actions Token 避免匿名 API 限额。

**验收进展**：2026-11-13 真实 Snapshot `r42542-e695009c15`、内核 ABI `6.18.55`，SHA256 索引校验通过。**仍需完成**官方可信 usign 签名验证与 APK 依赖闭包；当前索引锁绝不等同于可直接发布混合 Builder。

### P2. 定制内核与必要 kmod 的增量编译

- [x] 用锁定的 target commit 检出官方源码；从 target `feeds.buildinfo` 固定官方 feeds，以独立的 `config/hybrid-kernel-re-ss-01.config` 只选 RE-SS-01 + NSS/kmod（不套用官方 `ALL_KMODS` 构建机器人配置）。
- [x] 实际运行 `port-ppe-nss-to-immortalwrt.sh` 进行源码移植预检，并通过 `make defconfig` 确认保留 NSS、F2FS 等核心选项；F2FS/sysupgrade 补丁的最终固件集成仍待 P3 验证。
- [ ] 新增测试专用的 `compile-hybrid-kernel.sh`，使用 snapshot 锁定的官方 toolchain SHA256，按阶段编译 host tools、Kernel、mac80211、NSS Wi-Fi、PPE 模块；**编译验证进行中，尚未有已通过的内核产物**。
- [x] 旧 Builder 完整源码构建及 OTA 保持原样，Hybrid P2 只上传实验日志与产物清单，不发布 Builder/固件。

**验收**：生成定制内核/DTB/kmods，所有 kmod 的 `kernel=` 依赖与新内核严格一致。

### P3. APK 复用、离线仓库与 Builder/SDK 打包

- [ ] 对官方 target packages 和 arch `base/packages/luci/routing/telephony` 建立**本次锁定**的包索引与 SHA256 映射。
- [ ] 用户态包优先引用官方 APK，只下载最终依赖闭包；定制同名包优先本地版本并排除官方同名包。
- [ ] 对 `libc`、libgcc、libubox/ustream、openssl、apk 的提供项、架构和版本依赖做判定；有冲突才补编必要用户态库，无法解决就失败。
- [ ] 由**本地匹配内核**的构建树生成自洽 ImageBuilder 与 SDK；不从官方 IB 里手工覆盖内核文件。
- [ ] 镜像官方包仓库到 Release 并锁定散列；校验 SDK 的 `Module.symvers`、交叉编译和缺包补编功能。
- [ ] 验证 `make image`、manifest、PPE/NSS、F2FS、OTA；比较生成文件的哈希、体积和耗时。

**验收**：完整离线重打包成功；manifest 不混入官方 kmod；SDK 可编定制插件；产物可供测试设备刷入。

### P4. 默认切换与无变更跳过

- [ ] 新 Builder workflow 的默认模式设为 `hybrid`；`full-source` 只允许显式手动或指定后备运行。
- [ ] 每日解析 Snapshot、PPE/NSS 与定制输入的指纹；无变化跳过，只有 arch 用户态软件包变化则更新离线仓库，不触发 kernel 编译。
- [ ] 切换现有 Firmware/OTA 流水线使用经过验证的最新 Hybrid Release。
- [ ] 首次实机验证启动、NSS Wi-Fi、PPE、F2FS 持久层、`sysupgrade -T` 与保留配置；未验证前禁止自动升级推送。

**验收**：两次连续成功 Hybrid 构建 + 至少一次实机验证后启用正式发布；错误时保留旧 Release，不自动降级 ABI。

### P5. 性能回归与维护

- [ ] CI Summary 分别报告解析、下载复用 APK、源码准备、内核/kmod、Builder、SDK、打包和上传时长。
- [ ] 对比历史全量 Builder（2026-11-09 约 142 分钟）；设定可量化收益，若不能显著缩短则查明是否仍在编译大批 Go 包/host tools。
- [ ] 官方 Snapshot 不可用时保留上一版已验证 Builder；手动 `full-source` 后备，不进行无提示自动切换。
- [ ] 每个新 Builder 都保留 snapshot lock 和物料来源，方便复现及错误回滚。

## 当前需特别留意

截至 2026-11-13，官方 `snapshots/targets/qualcommax/ipq60xx` 目录所示目标构建时间是 10 月 21 日，`snapshots/packages/aarch64_cortex-a53` 是 10 月 26 日；二者不是同一轮 feed。**不能直接下载所有“最新” APK 拼接就宣称兼容。** 先有可靠的 Resolver 与依赖校验，再进入发布路径。

## 2026-11-13 已跑通的预检

- Snapshot 元数据与二进制 APK 索引：Actions #43428658957 通过，内核 6.18.55，版本 r42542-e695009c15。
- 官方源码提交 + PPE/NSS 移植：Actions #43429037968 通过，官方 commit e695009c15c623f4f6a83376b505faaf7a4ae5b5。
- 锁定 feeds + 最小内核配置的 Kconfig：Actions #43429262777 通过，NSS feed SHA 1f60d7e9409930bbd298eae1831c5b76d21eb1d2。
- 编译实验：新增 `.github/workflows/hybrid-kernel-build.yml`，**不发布任何可刷机产物**；完成实际构建和 ABI 审核之前不能认为 P2 已通过。

### 安全说明

目前解析器只验证官方传输文件与其同源 `sha256sums` 的 SHA256，**还未使用预先可信的 ImmortalWrt usign 公钥验证 `sha256sums.sig`**；`checksum_signature_verified=false`。这不影响只读实验，但在默认构建发布前必须补足可信来源认证、arch/target 版本依赖校验，并确保正式固件中无来自官方的 kernel/kmod。

## 2026-11-13 P3 APK 复用进展

- [x] `hybrid-official-apk-plan.py` 基于官方 target/arch 双份 sha256sums 建立候选清单。实际测试：**46 个官方用户态候选包、5 个明确的本地内核包、1 个定制包，无直接缺包或包名歧义**；`etherwake` 已验证可依照固定哈希下载。
- [x] `hybrid-dependency-audit.py` 使用官方 ImageBuilder 自带的 **apk-tools 3.0.5** 对 6 个经过 SHA256 校验的 `packages.adb` 解码，追踪用户态包的静态传递依赖。测试 [Actions #43433599484](https://github.com/pzcn/openwrt-ppe-nss-ota/actions/runs/43433599484) 成功：46 个根包对应 **139 个候选传递包**、0 个缺失、4 个需要 APK 求解器处理的歧义、10 个本地内核/基础 ABI 依赖。
- [x] 内核精简配置已补充由上述审计发现的 7 个模块：`kmod-ifb`、`kmod-inet-diag`、`kmod-netlink-diag`、`kmod-nf-conntrack-netlink`、`kmod-nft-core`、`kmod-nft-nat`、`kmod-sched-cake`。保留 `ALL_KMODS=n`，并增加 Kconfig 强校验。**新增模块的 Kconfig 和实际编译仍须以 Actions 通过结果为准。**
- [x] 实测原生 APK 3 求解器的 `update` + `fetch --recursive`：Actions [#43434153668](https://github.com/pzcn/openwrt-ppe-nss-ota/actions/runs/43434153668) 使用官方 ImageBuilder 的签名密钥与六套索引，成功取得 `etherwake` 的 **3 个递归依赖 APK**，逐包与锁定 `sha256sums` 对照一致，拒绝官方 kmod/本地定制包。此为单包闭包验证，不代表全部插件 ABI 已通过。
- [ ] 当前静态审计只记录 `provides`、`depends`、潜在缺失项；**不等同于**满足版本约束、SONAME、签名信任或可刷入内核的完整离线库。最终镜像必须由官方 apk-tools 求解，并只允许本地编译的 kernel/kmod 和匹配 ABI 基础包。

**待解决歧义**：`ip`、`nftables`、`tc`、`uci-firewall`。它们是候选提供者冲突，不能通过简单选第一个包解决。实际依赖的本地模块还包括 `kmod-tun`、`kmod-wireguard`、`kmod-nf-conntrack-netlink` 等，共计 9 项内核模块；另需验证 `libc` 的来源和 ABI。

## 2026-11-13 P2/P3 进一步实测

- **P3 原生依赖解析已通过单包案例**：[#43434153668](https://github.com/pzcn/openwrt-ppe-nss-ota/actions/runs/43434153668)，`apk-tools 3.0.5` 完成索引刷新、包递归下载及 SHA256 校验。要扩展到完整清单，必须把本地 kernel/kmods 与定制包作为求解源，不应混入官方内核模块。
- **P2 首轮完整定向编译失败**：[#43429939501](https://github.com/pzcn/openwrt-ppe-nss-ota/actions/runs/43429939501)，官方工具链复用成功，`make download` 510 秒，但 `tools/install` 在 `tools/liblzo` 失败，尚未进入 kernel/kmod 生成。错误输出不够详细；已增设 `hybrid-host-liblzo-diagnostic.yml` 单项冗长日志重现。
- **官方 ImageBuilder host tool 现状**：[#43434739222](https://github.com/pzcn/openwrt-ppe-nss-ota/actions/runs/43434739222)，其中 472 个 host/bin 可执行文件，但无 `staging_dir/host` stamp，也无 `build_dir/host` 工作树。不能仅复制 host 二进制就伪造 OpenWrt 构建状态；需验证完整 staging 依赖或优先完成单项失败修复。
- **发布约束保持不变**：上述结果只允许继续试验；无完整独立 Hybrid Builder+SDK，无本地 kernel ABI 以及全部包源依赖校验之前，不切换生产默认、不发布 OTA。
