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
