# Hybrid Builder：官方用户态 + 自编 PPE/NSS 内核

只编译和硬件、内核 ABI 或本仓库补丁相关的部分，其余 APK 直接复用 ImmortalWrt 官方 snapshot 的编译结果，首次 full 输出兼容的 ImageBuilder + SDK Release；之后 refresh 仅发布官方 APK 薄层，不再重复上传整个 Builder 或 SDK。这是现在的**默认（定时）Builder**；全源码 Builder 与增量 Builder 保留为手动后备。

| 文件 | 作用 |
|---|---|
| [`builder-immortalwrt-hybrid.yml`](../.github/workflows/builder-immortalwrt-hybrid.yml) | 每天检查 + `add.txt` 等改动推送时触发；`feat/hybrid-**` 分支推送也会跑（只发 prerelease，不触发固件），提交信息带 `[full]` 强制完整构建 |
| [`hybrid_builder.py`](../scripts/hybrid_builder.py) | 本地/官方划分、官方依赖闭包、identity、skip/refresh/full 判定 |
| [`build-immortalwrt-hybrid.sh`](../scripts/build-immortalwrt-hybrid.sh) | full：编译内核侧 |
| [`refresh-hybrid-builder.sh`](../scripts/refresh-hybrid-builder.sh) | refresh：从不可变基础 Builder 生成签名校验后的 APK 更新层，不重新压缩 IB/SDK |
| [`hybrid-common.sh`](../scripts/hybrid-common.sh) | 两者共用：签名/SHA256 校验、镜像、IB manifest 检查 |
| [`publish-hybrid-builder.sh`](../scripts/publish-hybrid-builder.sh) | full 的不可变基础 Builder 发布 | 
| [`hybrid_layer.py`](../scripts/hybrid_layer.py) | 薄层与基础 Builder 的 SHA256 绑定、包校验及安全安装 |
| [`publish-hybrid-layer.sh`](../scripts/publish-hybrid-layer.sh) | refresh 的不可变 APK 薄层发布及固件派发 |

## 分工

| 部分 | 来源 | 原因 |
|---|---|---|
| 内核源码树 | ImmortalWrt **master** + PPE/NSS 移植 | 已验证可编译的组合。官方 snapshot 常落后 master 数周，把 PPE 移植到旧树上会持续出现源码不一致 |
| 内核、全部被选中的 kmod | 本地编译 | vermagic 必须一致；kmod 列表由 Kconfig 依据完整软件包选择自动得出（含 Fullcone NAT） |
| base-files、libc/libgcc | 本地编译 | board 配置跟随本内核树；libc 用官方同一 toolchain |
| qca-ppe-qos、ppe-help、sqm-scripts(hw_ppe)、PPE QoS/Aurora/sing-box LuCI、NSS 固件 | 本地编译（`NO_DEPS`，只编 host 构建依赖） | 本仓库补丁或官方没有 |
| 其余所有用户态 | 官方 snapshot APK | 不再编译 Go/C 大包 |
| feeds | 官方 arch 仓库 `feeds.conf` 的提交 | 本地 feed 包与官方用户态同源 |
| 交叉工具链 | 官方 snapshot toolchain | libc/libgcc 与官方 APK 一致 |

## 三种模式（resolve 任务几十秒内决定）

| 模式 | 条件 | 做什么 | 预计耗时 |
|---|---|---|---|
| skip | identity 与最新基础 Builder/兼容薄层相同，且内核未过期 | 什么都不做 | 秒级 |
| refresh | 官方 snapshot 用户态或 `add.txt/remove.txt` 变了，内核侧未变且未过期 | 下载基础 IB（不下载 SDK），重算官方闭包，仅打包新的官方 APK 薄层；应用于基础 IB 出真实镜像冒烟测试。**不编译，也不重新压缩 IB/SDK** | 取决于 APK 数量和下载速度 |
| full | 内核侧变了（见下），或内核已超过 14 天 | 编译内核侧，镜像官方 APK，打包 IB+SDK | 首次约 1 小时，之后 host tools 走缓存 |

- **identity**（是否需要新 Builder）= 官方 snapshot + PPE/NSS/QoS LuCI/Julius builder 提交 + hybrid 配方 + 软件包列表。ImmortalWrt master 自身变动不在其中。
- **内核侧 identity**（能否 refresh）= PPE/NSS/QoS LuCI/Julius builder 提交 + 内核配方文件 + 官方 toolchain 的 GCC 版本 + libc 版本。官方每次 snapshot 换的 toolchain 包只要 GCC/musl 不变就不会触发重编。
- 内核最多复用 14 天（手动运行可调），之后用当时的 master 重编，以跟进内核修复。
- refresh 失败（例如新插件需要还没编的 kmod、或官方缺包）会自动转为 full。

## 流程细节

1. **resolve**：`resolve-immortalwrt-snapshot.py` 锁定最新已发布 snapshot（版本、feeds、toolchain、libc 版本、6 个 APK 索引的 SHA256），找到最新基础 Builder 及与之绑定的最新薄层；检查内核年龄、ABI 与内容 identity，判定模式。
2. **官方闭包（full 在编内核之前就算，失败得快）**：固定提交的 `immortalwrt/keyring` 公钥 `apk verify` 索引签名 + SHA256；本地同名包优先，官方 kernel/kmod 永不进入；官方包依赖未编的 kmod 或找不到依赖即报错；官方未发布但被选择的包自动改为本地编译（full）。
3. **编译（full）**：host tools → 内核 → 含 kmod 的源（正常依赖）→ 本地用户态（`NO_DEPS`）。
4. **镜像**：官方 APK 逐个核对 `sha256sums` 并 `apk verify` 单包签名（官方开启 SIGN_EACH_PACKAGE），放入 IB 离线仓库；`official-apks.json` 的 `mirrored` 记录实际来自官方的文件，refresh 只替换这些。
5. **检查**：IB `make manifest` 得到 `imagebuilder-packages.txt`，必须包含 PPE/NSS/F2FS 等关键包、不得含已排除的应用、镜像里每个 kmod 都必须是本地编译的；发布的 IB 不得含私钥（manifest 在临时副本上运行）；SDK 交叉编译冒烟（full）；用 `repack-immortalwrt.sh` 实际出一次 sysupgrade 镜像。
6. **发布**：full 仍用 `imm-builder-…-s<snapshot>` 输出完整 IB+SDK；refresh 则发 `imm-layer-<24位摘要>`，只含官方 APK、包清单、官方锁和绑定元数据。重打包固件时验证基础 Builder 的完整性和薄层文件哈希，删除基础 Builder 的旧官方 APK 后覆盖新官方 APK，内核 kmod 不变。

## 智能构建影响范围（亚瑟 / MX4200 隔离）

- 亚瑟 Hybrid Builder 对共享规划器 `hybrid_builder.py` 采用 AST 指纹，仅忽略确定无副作用的 `MX4200_LOCAL_PACKAGES` 包选择声明及格式/注释改动。亚瑟包选择、共享函数、内核/ABI 配方变更仍会正常改变指纹。
- `mx4200v1/**` 不在亚瑟的 Builder/固件构建输入中。MX4200 局部修改无需重编亚瑟 Builder，亦无需重新生成亚瑟固件。
- 亚瑟固件的 push 触发器只匹配实际打包、OTA、补编 SDK、插件选择及叠加文件；每日检查和手动运行时，进一步比较上一版 OTA `source_commit` 与当前提交之间的真正固件输入差异。Builder tag 未改变且差异为空时直接跳过。
- 若此前提交不可读取或文件差异检查失败，则保守地重打包；如果 Builder tag 改变则不跳过。
- 首次部署此改动时，Builder 指纹格式由源文件字节改为 AST，可能发生一次 `refresh`；此后 MX4200 包选择变化不应再引起无关刷新。

## 薄层发布与回退

- 基础完整 Builder 的 `imm-builder-*` Release 格式保持不变，SDK 继续与基础 Builder 的编译 ABI 绑定；refresh 不生成新的伪 Builder/SDK 元数据，也不会复制两份大型压缩包。
- `imm-layer-*` 薄层仅包含 `hybrid-userland-packages.tar.zst`（新的官方 APK）、`layer-metadata.json`、新包清单以及官方 Snapshot 锁。元数据绑定基础 Builder 的 Tag 和 SHA256、Kernel identity、签名校验过的官方 APK 清单和全部资产 SHA256。
- 打包固件时只选择与基础 Builder 精确匹配的薄层；默认仅自动选择正式发布的层，手动可指定 prerelease。`hybrid_layer.py install` 在安装前校验压缩包内每个 APK 的 SHA256，并拒绝路径穿越、软链接以及覆盖本地编译包。SDK、内核 FIT、kmods 来自基础 IB。
- 基础 Builder+薄层任意一个不匹配都会失败而非跳过校验；手动运行固件时可传 `layer_tag=none` 无条件回到基础 IB。refresh 冒烟测试必须实际调用 `repack-immortalwrt.sh` 并生成 sysupgrade 镜像后才发布。
- 每日固件检查不仅比较基础 `builder_tag` 和源码输入，还比较 OTA 上次记录的 `layer_tag`；纯层更新不会被误判成无需打包。
## 缓存

- `dl` 源码包、`ccache`：失败也会保存。
- host tools（`staging_dir/host`、`build_dir/host`）：按 `include/` 与 `tools/` 树缓存。OpenWrt 的 host 构建戳记包含文件 mtime，新克隆会让缓存全部失效，所以构建前把 `tools/` 的 mtime 设为由文件内容决定的固定值，并删除顶层 tools 戳记，让 make 逐个核对：内容没变的工具直接复用，变了的才重编。
- refresh 模式直接引用不可变基础 IB/SDK（当前基础包约 106/58 MB）；层发布不会重新打包这 164 MB，而是仅上传变更后的官方 APK 集合。

## 发布与上线

- full（新内核）默认 **prerelease**；固件工作流只用非 prerelease 的 Builder，所以新内核在实机验证前不会进入 OTA。
- refresh 薄层继承相容的上一版本状态：上一版已转正，则新的用户态更新可自动转正并触发固件打包；否则仍为 prerelease。薄层与对应基础 Builder 必须同时满足稳定版要求。
- 手动运行可用 `channel=release/prerelease` 覆盖，`build_mode=full` 强制重编；固件手动运行可指定 `builder_tag`、`layer_tag`，或者 `layer_tag=none` 只使用基础 Builder。

首次上线：

1. 手动运行 Hybrid Builder（第一次必为 full），看 Step Summary 的阶段耗时与包数量。
2. 固件工作流手动指定 `builder_tag=imm-builder-…`、`publish_release=false`，在亚瑟上测试 PPE、NSS Wi-Fi、F2FS overlay、`sysupgrade -T` 与保留配置。
3. 通过后在 Releases 页取消该 Builder 的 pre-release。此后官方用户态更新仅生成兼容的薄层并重新组装固件；只有 PPE/内核侧变化才重新发布完整 Builder prerelease。

## 已知限制

- `sha256sums.sig`（usign）未验证；信任根是固定提交 keyring 中的官方公钥（索引签名 + 每个 APK 签名）。
- refresh 期间 base-files 与 libc 来自上一次内核构建；官方 GCC/musl 版本变化会强制 full。
- 开发沙箱无法完整运行 OpenWrt 构建；规划与闭包逻辑已在真实 master + 官方 feeds 元数据上验证（111 个本地包，其中 97 个 kmod；183 个官方包，无缺失），完整流程以首次 Actions 运行为准。

## PR #16 SSH 调试（按需开启）

仅在 `feat/hybrid-official-snapshot` 分支的提交信息包含 `[ssh]` 时，强制 full 构建并启用临时 Tailscale SSH；失败后最多保留 45 分钟。正常构建、主分支、PR 检查和定时任务不受影响，SSH 调试运行禁止发布。

详细配置、Tailnet ACL、触发与结束命令：见 [Hybrid SSH 调试操作说明](HYBRID-SSH-DEBUG.md)。

## RE-SS-01 FIT 与 ImageBuilder 同步

`target/compile` 只确保内核编译；上游 `target/imagebuilder/Makefile` 仅复制当时 `KERNEL_BUILD_DIR` 已存在的文件。full 模式在打包 ImageBuilder 前对选中的 RE-SS-01 执行 `target/linux/qualcommax/image` 的专属 FIT 目标，生成 `jdcloud_re-ss-01-uImage.itb`；检查 FIT 大小不超过 6144 KiB、包含 `config@cp03-c2`，并在打包后验证该文件进入 ImageBuilder 且字节一致。Repack 阶段同样提前检查 FIT，绝不借用不同内核 ABI 的官方 FIT。

SSH 调试只有提交标题以 `[ssh] ` 开头才启用，避免普通修复提交的正文引用该字符串时触发并因未配置 OAuth 密钥而失败。
