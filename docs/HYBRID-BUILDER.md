# Hybrid Builder：官方用户态 + 自编 PPE/NSS 内核

只编译和硬件、内核 ABI 或本仓库补丁相关的部分，其余 APK 直接复用 ImmortalWrt 官方 snapshot 的编译结果，拼成与原来格式相同的 ImageBuilder + SDK Release。这是现在的**默认（定时）Builder**；全源码 Builder 与增量 Builder 保留为手动后备。

| 文件 | 作用 |
|---|---|
| [`builder-immortalwrt-hybrid.yml`](../.github/workflows/builder-immortalwrt-hybrid.yml) | 每天检查 + `add.txt` 等改动推送时触发；`feat/hybrid-**` 分支推送也会跑（只发 prerelease，不触发固件），提交信息带 `[full]` 强制完整构建 |
| [`hybrid_builder.py`](../scripts/hybrid_builder.py) | 本地/官方划分、官方依赖闭包、identity、skip/refresh/full 判定 |
| [`build-immortalwrt-hybrid.sh`](../scripts/build-immortalwrt-hybrid.sh) | full：编译内核侧 |
| [`refresh-hybrid-builder.sh`](../scripts/refresh-hybrid-builder.sh) | refresh：复用上一版，只换官方 APK，不编译 |
| [`hybrid-common.sh`](../scripts/hybrid-common.sh) | 两者共用：签名/SHA256 校验、镜像、IB manifest 检查 |
| [`publish-hybrid-builder.sh`](../scripts/publish-hybrid-builder.sh) | 发布与 prerelease 策略 |

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
| skip | identity 与最新 hybrid Builder 相同 | 什么都不做 | 秒级 |
| refresh | 只有官方 snapshot 用户态或 `add.txt/remove.txt` 变了 | 下载上一版 IB+SDK，重算官方闭包，替换镜像的官方 APK，重签元数据，出一次镜像做冒烟测试。**不编译** | 10–15 分钟 |
| full | 内核侧变了（见下），或内核已超过 14 天 | 编译内核侧，镜像官方 APK，打包 IB+SDK | 首次约 1 小时，之后 host tools 走缓存 |

- **identity**（是否需要新 Builder）= 官方 snapshot + PPE/NSS/QoS LuCI/Julius builder 提交 + hybrid 配方 + 软件包列表。ImmortalWrt master 自身变动不在其中。
- **内核侧 identity**（能否 refresh）= PPE/NSS/QoS LuCI/Julius builder 提交 + 内核配方文件 + 官方 toolchain 的 GCC 版本 + libc 版本。官方每次 snapshot 换的 toolchain 包只要 GCC/musl 不变就不会触发重编。
- 内核最多复用 14 天（手动运行可调），之后用当时的 master 重编，以跟进内核修复。
- refresh 失败（例如新插件需要还没编的 kmod、或官方缺包）会自动转为 full。

## 流程细节

1. **resolve**：`resolve-immortalwrt-snapshot.py` 锁定最新已发布 snapshot（版本、feeds、toolchain、libc 版本、6 个 APK 索引的 SHA256），读取上游分支头，找到最新的 hybrid Builder，判定模式。
2. **官方闭包（full 在编内核之前就算，失败得快）**：固定提交的 `immortalwrt/keyring` 公钥 `apk verify` 索引签名 + SHA256；本地同名包优先，官方 kernel/kmod 永不进入；官方包依赖未编的 kmod 或找不到依赖即报错；官方未发布但被选择的包自动改为本地编译（full）。
3. **编译（full）**：host tools → 内核 → 含 kmod 的源（正常依赖）→ 本地用户态（`NO_DEPS`）。
4. **镜像**：官方 APK 逐个核对 `sha256sums` 并 `apk verify` 单包签名（官方开启 SIGN_EACH_PACKAGE），放入 IB 离线仓库；`official-apks.json` 的 `mirrored` 记录实际来自官方的文件，refresh 只替换这些。
5. **检查**：IB `make manifest` 得到 `imagebuilder-packages.txt`，必须包含 PPE/NSS/F2FS 等关键包、不得含已排除的应用、镜像里每个 kmod 都必须是本地编译的；发布的 IB 不得含私钥（manifest 在临时副本上运行）；SDK 交叉编译冒烟（full）；用 `repack-immortalwrt.sh` 实际出一次 sysupgrade 镜像。
6. **发布**：tag 为 `imm-builder-…-s<snapshot>`，标题带 identity。

## 缓存

- `dl` 源码包、`ccache`：失败也会保存。
- host tools（`staging_dir/host`、`build_dir/host`）：按 `include/` 与 `tools/` 树缓存。OpenWrt 的 host 构建戳记包含文件 mtime，新克隆会让缓存全部失效，所以构建前把 `tools/` 的 mtime 设为由文件内容决定的固定值，并删除顶层 tools 戳记，让 make 逐个核对：内容没变的工具直接复用，变了的才重编。
- refresh 模式本身就是对上一版内核侧产物的复用。

## 发布与上线

- full（新内核）默认 **prerelease**；固件工作流只用非 prerelease 的 Builder，所以新内核在实机验证前不会进入 OTA。
- refresh 继承上一版的状态：上一版已转正，则新的用户态更新自动转正并触发固件打包；否则仍为 prerelease。
- 手动运行可用 `channel=release/prerelease` 覆盖，`build_mode=full` 强制重编。

首次上线：

1. 手动运行 Hybrid Builder（第一次必为 full），看 Step Summary 的阶段耗时与包数量。
2. 固件工作流手动指定 `builder_tag=imm-builder-…`、`publish_release=false`，在亚瑟上测试 PPE、NSS Wi-Fi、F2FS overlay、`sysupgrade -T` 与保留配置。
3. 通过后在 Releases 页取消该 Builder 的 pre-release。此后官方用户态更新与插件改动都会自动生成新 Builder 并打包固件；只有 PPE/内核侧变化会产生新的 prerelease 等待实机验证。

## 已知限制

- `sha256sums.sig`（usign）未验证；信任根是固定提交 keyring 中的官方公钥（索引签名 + 每个 APK 签名）。
- refresh 期间 base-files 与 libc 来自上一次内核构建；官方 GCC/musl 版本变化会强制 full。
- 开发沙箱无法完整运行 OpenWrt 构建；规划与闭包逻辑已在真实 master + 官方 feeds 元数据上验证（111 个本地包，其中 97 个 kmod；183 个官方包，无缺失），完整流程以首次 Actions 运行为准。
