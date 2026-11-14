# RE-SS-01：ImmortalWrt 官方用户态 + Julius 预编译内核实验

> **仅供验证；不是可刷机固件。** [实验 PR #17](https://github.com/pzcn/openwrt-ppe-nss-ota/pull/17)，与原有 [Hybrid Builder PR #16](https://github.com/pzcn/openwrt-ppe-nss-ota/pull/16) 分离，正式 Builder/OTA 不变。

## 实验输入

- ImmortalWrt 官方 `qualcommax/ipq60xx` Snapshot：`r42542-e695009c15`，官方亚瑟固件和目标 SHA256 清单均锁定，已验证内核版本 **6.18.55**。
- JuliusBairaktaris [2026-11-07 PPE/NSS Release](https://github.com/JuliusBairaktaris/Qualcommax_NSS_Builder/releases/tag/ppe-nss-20261107T141109Z-42380319235)：该 RE-SS-01 固件实际归属 **ipq60xx-512m** 发布变体，内核 **6.18.60**。硬件即便扩容到 1 GiB，也不能因此假定上游发布了对应的 RE-SS-01 1g 内核。
- 双方都是 `sysupgrade-tar | append-metadata`，`kernel` 是 FIT (`config@cp03-c2`)，`root` 是 SquashFS。不是原始裸 FIT 文件，不应靠 `dd` 覆盖固件开头。
- 设备镜像配方的内核大小限制 **6 MiB** (6,291,456 字节)。

## 已验证（GitHub Actions）

| 检查 | ImmortalWrt | Julius |
|---|---:|---:|
| FIT 内容长度 | 6,044,640 B | 6,230,440 B |
| SquashFS 有效内容长度 | 9,685,552 B | 15,019,432 B |
| 解包后的内核模块目录 | `6.18.55` | `6.18.60` |
| 默认固件所含 `.ko` 文件数 | 91 | 113 |
| Julius RE-SS-01 发布变体 | — | 512m |

- [#43463537078](https://github.com/pzcn/openwrt-ppe-nss-ota/actions/runs/43463537078)：两套官方发布固件解析、FIT 设备树、大小限制、模块版本检查通过。
- [#43464139909](https://github.com/pzcn/openwrt-ppe-nss-ota/actions/runs/43464139909)：Julius 同批次 `imagebuilder-ipq60xx-512m.tar.zst` 与 `config-ipq60xx-512m.buildinfo` 通过 GitHub 发布资产 SHA256 验证；ImageBuilder **已包含**同 ABI 的 `kmod-fs-f2fs-6.18.60-r1.apk`、`kmod-wireguard-6.18.60-r1.apk`、`kmod-nss-wifi-drv-6.18.60-r1.apk`。默认 donor rootfs 未安装 F2FS 不等于无需/无法添加该模块。
- [#43464552257](https://github.com/pzcn/openwrt-ppe-nss-ota/actions/runs/43464552257)：在 CI 临时目录中生成了一份**研究用 TAR**，将 donor 的 `kernel` 替代官方的 `kernel`，并逐字节检查 `root` 和 `CONTROL` 保持原样。该 TAR 不附加 sysupgrade 元数据，不上传，执行后删除。

## 为什么还不是可刷机固件

**直接替换 FIT 内核并保留原始 SquashFS 不能正常视为完成。**

1. 原 ImmortalWrt rootfs 中的 91 个 `6.18.55` 内核模块及其 APK 依赖不能继续配合 Julius `6.18.60` 内核；即使模块的 `uname -r` 接近，也不能跳过 vermagic/ABI 检查。
2. 必须使用同一 Julius ImageBuilder 提供的**完整**内核、kmod、F2FS、NSS Wi-Fi 固件/启动服务，以及匹配的模块包索引。不能混用官方 ImmortalWrt 的 `kmod-*`。
3. 保留 ImmortalWrt 用户态意味着 `base-files`、`libc`、`apk-tools`、`procd`、`netifd` 等 APK 的选择与依赖约束必须重新求解，正确更新已安装包数据库，而不是仅复制 `.ko` 文件。
4. 本机的 F2FS `/overlay` 在启动早期必须可挂载；存在可下载的 `kmod-fs-f2fs` **不等于**已经证实可以在启动时装载。
5. 版本/签名/设备检查及 `sysupgrade -T` 烟测、真实设备 NSS/F2FS/保留配置测试仍未完成；无需冒险产出 OTA Release。

## 后续的实验验收关口

- [x] 验证 RE-SS-01 FIT 与 sysupgrade TAR 结构一致、内核尺寸满足分区限制。
- [x] 找到并校验 Julius 同 ABI 的 F2FS、NSS Wi-Fi、WireGuard 预编译 APK。
- [x] **机械性换核证明**：完整保留原始 ImmortalWrt 根文件系统。
- [x] 比较 ImmortalWrt 官方与 Julius Builder 的 21 类核心用户态 APK **文件版本**：[#43465055284](https://github.com/pzcn/openwrt-ppe-nss-ota/actions/runs/43465055284) 成功，**4 类版本一致、10 类不同、7 类在其中一套索引中未发现**；如 `base-files`、`busybox`、`procd`、`netifd`、`ubus`、`firewall4`、`dnsmasq`、`rpcd`、`uhttpd` 均有版本差异。这是版本清单审查，不是实际 APK 依赖求解或 ABI 通过。
- [ ] 让包管理器以 Julius kernel + 所需 kmod 为本地源，ImmortalWrt 用户态为用户态源，实际完成一致性求解；现已有 10 类核心 APK 版本漂移，必须真实检查 provides、soname、版本依赖与文件覆盖；出现冲突应报错而非强制忽略。
- [ ] 用 ImageBuilder 组装匹配的完整测试固件，检查模块 ABI、`Module.symvers`（如果可获得）、F2FS、NSS 与 `sysupgrade -T`。
- [ ] 经过亚瑟实机验证，才评估是否采用本路线作为默认。

**当前结论：内核可以在 sysupgrade TAR 的结构上替换，且同一 Julius Builder 已提供 F2FS/NSS/WireGuard 模块而无需重编译；但 Kernel ABI 从 6.18.55 变为 6.18.60、10 类核心用户态包版本漂移，仍需完成 APK 求解和系统/OTA 测试。现阶段不是可刷机固件。**

## 2026-11-14：全量原版 world + Julius 模块严格求解

- [x] [#43468735204](https://github.com/pzcn/openwrt-ppe-nss-ota/actions/runs/43468735204) 已解出真实官方固件的 `/etc/apk/world`（168 条）及 `/lib/apk/db/installed`（168 包）。其中 **94 个用户态包**全部能在被锁定的官方 Snapshot 软件仓库中按**原始名称和精确版本**找到，0 个用户态包需因仓库缺失而升级或降级。
- [x] [#43469237468](https://github.com/pzcn/openwrt-ppe-nss-ota/actions/runs/43469237468) 用真实原版已安装的 74 个 kernel/kmod 包逐个比对 Julius 6.18.60，明确缺 **`kmod-nf-log6`** 和 **`kmod-nft-fullcone`**；另加入 Julius NSS Wi-Fi、F2FS、WireGuard 的 3 个包后，能锁定 **93 个官方原版用户态 + 1 个 Julius firewall4 + 75 个 Julius kernel/kmod**，即 169 个精确版本要求。缺失的两个原版模块不计入此可求解计划，也不能据此宣称原版功能全部保留。
- [x] [#43469812454](https://github.com/pzcn/openwrt-ppe-nss-ota/actions/runs/43469812454)：原生 APK3 对这 **169 个精确版本**组成的方案完成 `--simulate` 求解成功。
- [x] [#43470065489](https://github.com/pzcn/openwrt-ppe-nss-ota/actions/runs/43470065489)：把 Julius 1,463 包仓库限制成 1,254 个 **kernel/kmod/NSS 固件/firewall4 候选**，其它 Julius `procd`、`netifd`、`ubus`、`libubox` 等用户态全部禁止参与。该更严格来源约束下 **169 个包仍能原生求解成功**，解决此前“73 包虽然通过却偷偷混入大量 Julius 用户态”的问题。
- [ ] **两种 kmod 缺口性质不同**：参考固定上游源码，ImmortalWrt `kmod-nf-log6` 在 6.18 所依赖的 `CONFIG_NF_LOG_IPV6` 只适用于 Linux 5.13 之前，Julius 把 Netfilter 日志归到 `kmod-nf-log`，需进一步核对实际模块、服务引用；`kmod-nft-fullcone` 属于 ImmortalWrt 额外 NAT 功能，Julius 无同名驱动，选择其 firewall4 可以通过求解**但可能丢失 Fullcone NAT 功能**。不得假装两个模块功能完全等价。
- [ ] [实际负载解包测试](https://github.com/pzcn/openwrt-ppe-nss-ota/actions/workflows/experiment-julius-kernel-swap.yml) 正在以一次性临时根目录、不执行软件包脚本的方式安装 169 个版本锁定包，验证文件覆盖/拆包而不是仅求解依赖；**不输出刷机镜像**。

**仍未完成**：整套 APK 二进制散列与签名根信任证据、运行时 SONAME/ABI 和文件冲突校验、全部功能（尤其 Fullcone NAT）的保留、F2FS 启动早期加载、NSS Wi-Fi、系统升级及配置保留、实机启动与回滚。发布/OTA 永久留在现有生产路径，除非以上全部通过。

## 2026-11-14：受限来源的 169 包实际解包测试

- [x] [#43470065489](https://github.com/pzcn/openwrt-ppe-nss-ota/actions/runs/43470065489) 再次验证 169 精确版本要求在**仅开放 Julius 的 kernel/kmods/NSS 固件/firewall4**的受限仓库下能够由 APK3 原生求解，不再允许 Jules 的随机基础用户态库进入。这是让 ImmortalWrt 保持官方用户态的关键证据。
- [x] [#43471131738](https://github.com/pzcn/openwrt-ppe-nss-ota/actions/runs/43471131738) 在 GitHub Actions 临时目录中真实执行 `apk add --usermode --no-scripts`，完整解出依赖集合，安装脚本没有执行。实际包集约 **180 包**，操作返回成功，APK 没有报告包间文件覆盖冲突；只存在本机临时根目录，产物未上传。此步骤不等于在亚瑟上实际启动。
- [x] APK scratch-root 初始化还需与官方 `base-files` 目录结构相符：原版 `/var -> tmp` 是相对软链接，不能由测试工具提前创建 `/var` 目录，否则 `base-files` 无法提交 `var`，属于测试环境搭建问题而不是两个发行版的文件冲突。已读取实际官方 SquashFS 的 `var` 软链接并预建到测试根目录后验证解包成功。
- [ ] 将真实安装后的 `lib/apk/db/installed` 与 169 个精确版本要求重新比较，确认所有最终文件都来自 6.18.60 模块树，检查 F2FS 模块及 `/etc/modules-boot.d` 的早期启动加载记录；见 [实验工作流](https://github.com/pzcn/openwrt-ppe-nss-ota/actions/workflows/experiment-julius-kernel-swap.yml)。

**不作为正式固件的原因不变**：Fullcone NAT 仍缺独立驱动；必须进一步完成 F2FS 持久化启动、NSS Wi-Fi、真实内核模块 ABI、sysupgrade 保留配置和实机验证。目前既没有发布签名的 ImageBuilder，也没有更新正式 OTA。

## 2026-11-14：完整 180 包落盘与模块启动配置验证

- [x] [#43471656302](https://github.com/pzcn/openwrt-ppe-nss-ota/actions/runs/43471656302)：按 169 个精确版本要求、通过受限 Julius 内核/模块软件源及官方 ImmortalWrt 用户态仓库，真正安装约 **180 个 APK** 到一次性根文件系统（禁止运行安装脚本）。APK 完整解包无包间文件覆盖冲突；重新读取实际 `lib/apk/db/installed` 发现全部 169 个要求**精确版本匹配**。
- [x] 临时根文件系统中的 `/lib/modules` 只有 **6.18.60**，无旧版 6.18.55 模块目录；已找到 `lib/modules/6.18.60/f2fs.ko`、`nss-wifi-drv.ko`、`wireguard.ko`。
- [x] `etc/modules-boot.d/30-fs-f2fs` 已存在。这表明作为根系统必需品的 F2FS 有**早期模块加载配置**，不仅仅是存在一个压缩包。但尚未在硬件上验证其启动时刻/overlay 挂载。
- [ ] 进一步要验证的不是基本 APK 依赖，而是完整固件生成、`sysupgrade -T`、新内核的内置驱动/模块 ABI、原版 `procd`/网络/无线运行、F2FS 持久化 overlay、升级配置保留，以及缺失的 Fullcone NAT 功能如何处理。

**以上只证明 Linux 6.18.60 预编译内核及模块配合官方 ImmortalWrt 用户态的文件级兼容性，没有发布刷机固件；正式 Builder/OTA 不变。**

## 2026-11-14：混合根文件系统压缩往返实验（新测试，待 CI 验证）

- 新增 `scripts/pack-swap-research-rootfs.py`：从上一步的临时 APK-installed root 生成 **临时** SquashFS，使用 `unsquashfs` 重新展开，验证 169 个精确版本、APK installed DB 哈希、`/var -> tmp` 软链接、6.18.60 的全部模块文件及文件权限、F2FS early autoload 配置是否一致。
- 临时用 Julius 的原版 FIT + 新压缩 rootfs 组成只用于 **TAR 成员与字节哈希检查** 的研究容器；其 `CONTROL` 被故意设置为 `BOARD=research-invalid-not-a-real-device`，不附加 fwtool metadata，所有容器和 SquashFS 临时文件在脚本退出时销毁，仅保留 JSON 报告。
- 新增测试 `scripts/tests/test-swap-rootfs-packaging.py` 并接入实验 Action，失败会阻断测试工作流。
- **提交不等于通过**：只有当实验 Actions 最新运行中的 `Repack disposable APK root...` 步骤成功且报告中的 `disposable_rootfs_file_roundtrip_passed=true`，才能称为压缩往返验证通过。
- 该测试 **不运行 APK 安装脚本，不进行 `sysupgrade -T`，不证明正常启动或 Linux 内核 ABI 兼容，不保存可刷固件**。下一阶段仍需严格的 package post-install/overlay 检查、真正的目标设备配置校验和实机验证。

## 2026-11-14：打包成功后的启动文件和模块版本审计

- [#43475440594](https://github.com/pzcn/openwrt-ppe-nss-ota/actions/runs/43475440594) 实际通过了新增的 `Repack disposable APK root into SquashFS, reextract and check research-only TAR` 步骤；`mksquashfs -> unsquashfs` 后 APK installed DB、模块文件、F2FS 早期加载配置和 /var 链接检查通过。临时研究 TAR 删除，**并未产生可刷固件**。
- 添加 `scripts/audit-swap-runtime-readiness.py`：比较 **官方原版 SquashFS** 与 APK-only 混合目录的 boot/board/init/upgrade 核心文件，给出缺失和哈希差异清单，不自动修复或照搬可能不兼容的内核关联配置。
- 扫描每个 `.ko` 内的 `vermagic` 版本串是否为 Julius 6.18.60，记录缺失、错误或无法解析的模块，并检查 modules.dep、modules.alias、F2FS、NSS Wi-Fi 和 WireGuard；版本串相同仍 **不等于**完成实际符号 ABI 或硬件验证。
- 新增独立测试和 CI 报告 `boot-runtime-static-audit.json`。审计结果尚需下一轮 CI 验证，不会自动放行镜像发布；`main`/正式 Builder/OTA 保持不变。

## 2026-11-14：真实 CI 报告与 ImageBuilder finalization 排查

- [#43476553612](https://github.com/pzcn/openwrt-ppe-nss-ota/actions/runs/43476553612) **成功**：原版 133 个启动相关路径与混合 rootfs 逐个对比，缺失 **0**，相同 **131**，不同 **2**（`etc/config/firewall`、`etc/config/openssl`）；混合 rootfs 新增 `etc/config/nss-wifi`、`etc/init.d/nss-wifi`、`etc/uci-defaults/90-nss-wifi-flowtable`。
- 全部 **103** 个实际扫描到的 `.ko` 含有与 Julius **6.18.60** 一致的 `vermagic` release 字符串，无缺失/不匹配；这是**字符串级**静态检查而非内核符号/真机运行证明。
- scratch root 未发现 `modules.dep` 与 `modules.alias`。不能自动认为这是损坏，因为上游 OpenWrt ImageBuilder 的 `package_install` 也使用 `apk add --no-scripts`，后续 `prepare_rootfs` 负责运行提取的 `*.post-install` 脚本并创建服务启用链接。不能把当前临时 APK-only 根文件系统直接当作最终设备 rootfs。
- 新增 `scripts/audit-swap-boot-finalization.py` 与对应单测：只读对比原版/Julius/混合系统的 `/etc/rc.d` 服务软链接、`lib/modules/<release>/modules.{dep,alias,builtin,order}`、`lib/apk/db/scripts.tar.gz` 安装后脚本数量。绝不执行 APK post-install、也不替代完整 ImageBuilder finalization。
- 该轮新 CI 尚待验证。后续若需要执行真正后处理，应在独立隔离的 ImageBuilder 流程中，并明确处理模块索引、服务启用状态及升级钩子，不能跳过到真实可刷包。
