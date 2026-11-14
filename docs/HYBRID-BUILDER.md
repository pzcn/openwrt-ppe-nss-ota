# Hybrid Builder：官方用户态 + 自编 PPE/NSS 内核

目标：不再每次从源码完整编译。只编译和硬件、内核 ABI 或本仓库补丁相关的部分，其余 APK 直接复用 ImmortalWrt 官方 snapshot 的编译结果，最后拼成同样格式的 ImageBuilder + SDK Release。

工作流：[`builder-immortalwrt-hybrid.yml`](../.github/workflows/builder-immortalwrt-hybrid.yml)；主脚本：[`build-immortalwrt-hybrid.sh`](../scripts/build-immortalwrt-hybrid.sh)；规划逻辑：[`hybrid_builder.py`](../scripts/hybrid_builder.py)。原全源码 Builder 保持不变，可随时手动使用。

## 分工

| 部分 | 来源 | 原因 |
|---|---|---|
| 内核源码树 | ImmortalWrt **master** + PPE/NSS 移植 | 与全源码 Builder 相同、已验证可编译的组合。官方 snapshot 常落后 master 数周（6.18.55 vs PPE 的 6.18.60，generic 补丁差 189 个文件），把 PPE 移植到旧 snapshot 树上会不断出现源码不一致 |
| 内核、全部被选中的 kmod | 本地编译 | vermagic 必须与本内核一致；kmod 列表由 Kconfig 根据完整软件包选择自动得出（含 ImmortalWrt 的 Fullcone NAT），不手工维护 |
| base-files、libc/libgcc | 本地编译 | 设备 board 配置跟随本内核树；libc 用官方同一 toolchain |
| qca-ppe-qos、ppe-help、sqm-scripts(hw_ppe)、PPE QoS/Aurora/sing-box LuCI、NSS 固件 | 本地编译（`NO_DEPS`，只编译 host 构建依赖） | 本仓库补丁或官方没有 |
| 其他所有用户态（sing-box、tailscale、LuCI、procd…） | 官方 snapshot APK | 不再编译 Go/C 大包 |
| feeds | 钉在官方 arch 仓库 `feeds.conf` 的提交 | 本地编译的 feed 包与官方用户态来自同一提交 |
| 交叉工具链 | 官方 snapshot toolchain（SHA256 由锁文件给出） | libc/libgcc 与官方 APK 一致 |

## 流程

1. **resolve**（每天，几十秒）：`resolve-immortalwrt-snapshot.py` 锁定最新**已发布**官方 snapshot（版本、feeds、toolchain、6 个 APK 索引的 SHA256），读取 PPE/NSS 上游分支头。计算 identity = snapshot + PPE/NSS/LuCI 提交 + 本仓库 hybrid 配方 + `add.txt/remove.txt`。已有同 identity 的 Release 就跳过（ImmortalWrt master 自身变动不触发重编）。
2. **配置**：设备配置 + `add.txt`/`remove.txt` 全量选择，`defconfig` 后 Kconfig 自动选出所需 kmod。
3. **官方闭包（编译内核之前完成，失败得快）**：
   - 从固定提交的 `immortalwrt/keyring` 取官方公钥，`apk verify` 校验 6 个 `packages.adb` 签名，并核对锁定的 SHA256；
   - `hybrid_builder.py plan` 区分本地/官方；`closure` 求出官方依赖闭包：本地同名包优先，官方 kernel/kmod 永不进入；官方包依赖我们没编的 kmod、或依赖找不到时直接报错；官方未发布但被选择的包自动改为本地编译。
4. **编译**：host tools → 内核 → 含 kmod 的源（正常依赖）→ 本地用户态（`NO_DEPS`）。
5. **镜像**：官方 APK 逐个核对 `sha256sums` 并 `apk verify`（官方 snapshot 开启了 SIGN_EACH_PACKAGE），放入离线仓库。ImageBuilder 不依赖会滚动的线上 snapshot。
6. **打包与冒烟**：生成 standalone ImageBuilder + SDK（含本内核 `Module.symvers`），用 IB `make manifest` 得到 `imagebuilder-packages.txt` 并检查镜像里的每个 kmod 都是本地编译的；SDK 交叉编译冒烟；用 `repack-immortalwrt.sh` 实际出一次 sysupgrade 镜像。
7. **发布**：默认 **prerelease**。固件工作流只选非 prerelease 的 Builder，所以在实机验证前不会进入 OTA。

## 上线步骤

1. 手动运行 Hybrid Builder 工作流，检查 Step Summary 的阶段耗时、本地包/官方包数量。
2. 用固件工作流手动指定该 Builder：`builder_tag=imm-builder-...`，`publish_release=false`，下载产物在亚瑟上测试 PPE、NSS Wi-Fi、F2FS overlay、`sysupgrade -T` 与保留配置。
3. 通过后在 Releases 页把该 Builder 的 prerelease 去掉（或以后手动运行时取消 `prerelease`），固件工作流随即默认使用它。
4. 稳定后再考虑停用全源码 Builder 的每周定时。

## 已知限制

- `sha256sums.sig` 尚未验证；信任根是固定提交 keyring 中的官方公钥（索引签名 + 每个 APK 签名）。
- 本仓库无法在开发沙箱完整运行 OpenWrt 构建；规划逻辑已在真实 master + 官方 feeds 元数据上验证（111 个本地包，其中 97 个 kmod；183 个官方包，无缺失），完整编译以首次 Actions 运行为准。
- `add.txt` 新增插件会改变 identity，触发一次新的 Hybrid Builder；临时也可由固件工作流用配套 SDK 补编。
