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

- [x] 新增 `scripts/resolve-immortalwrt-snapshot.py`：读取 target `version.buildinfo`、`feeds.buildinfo`、`config.buildinfo`、`sha256sums` 及 arch `feeds.conf`；target 元数据进行 SHA256 校验。arch 独立 APK 索引仍待后续阶段锁定。
- [x] 严格解析校验文件名、目标/架构、提交格式、target SHA256；锁定官方 ImageBuilder、SDK、Toolchain 的文件名与 SHA256，单独记录 arch feeds 指纹。
- [x] 输出确定性的 `snapshot-lock.json`，计算 `kernel_fingerprint` / `packages_fingerprint`，支持 `unchanged` / `packages-only` / `kernel-or-target`。注意 `packages_fingerprint` 目前仅代表 arch feeds，不涵盖 APK 索引。
- [x] 第一批离线测试：变化分类、坏 checksum、路径污染、稳定性；还需覆盖 snapshot 发布切换期间的索引重读、arch APK 索引差异。
- [x] 新增只读 CI（每日及手动）上传锁文件与摘要，不做大规模编译、不会发布固件；在开发分支运行验证。

**验收**：CI 可稳定取得最新版官方数据、解析出完整锁；不一致时明确失败或记录警告，**绝不自动发布**。

### P2. 定制内核与必要 kmod 的增量编译

- [ ] 以锁定的 target commit 检出源码，使用 target 的 `feeds.buildinfo`；`config.buildinfo` 作为官方目标配置基线，选择唯一设备 RE-SS-01。
- [ ] 叠加现有 `port-ppe-nss-to-immortalwrt.sh`，构建 NSS Wi-Fi、PPE、DTS、临时 F2FS/sysupgrade 补丁。
- [ ] 复用校验后的官方交叉工具链；仅编译所选目标和必要 kmod，记录非官方的 kernel ABI。
- [ ] 保留完整源码后备，不允许 P2 的产物被旧 Firmware 自动当成可发布的 Builder。

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
