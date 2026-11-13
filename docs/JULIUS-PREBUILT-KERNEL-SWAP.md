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
- [ ] 比较 ImmortalWrt 官方与 Julius Builder 的基础用户态 APK 版本及依赖约束。
- [ ] 让包管理器以 Julius kernel + 所需 kmod 为本地源，ImmortalWrt 用户态为用户态源，实际完成一致性求解；出现缺包/版本冲突应报错而非强制忽略。
- [ ] 用 ImageBuilder 组装匹配的完整测试固件，检查模块 ABI、`Module.symvers`（如果可获得）、F2FS、NSS 与 `sysupgrade -T`。
- [ ] 经过亚瑟实机验证，才评估是否采用本路线作为默认。

**当前结论：内核可以在 sysupgrade TAR 的结构上替换，而且无需重新编译 F2FS/NSS 模块；但不能声称保留官方 rootfs 后已经具备可刷机兼容性。**
