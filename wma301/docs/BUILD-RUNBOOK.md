# WMA301 固件构建：长期计划与操作流程

> **master/6.18 迁移说明（2026-11-16）：** 下文 2026-11-13 成功的 CI 运行属于此前的 25.12 路线，不代表 6.18 已构建或实机验证。新快构建以官方 `snapshots/targets/mediatek/filogic` 的 SHA256、版本信息和 6.18 内核为准；完整构建跟踪 `master` HEAD。详见 [迁移检查单](MASTER-MIGRATION.md)。

> 策略：**官方 ImmortalWrt ImageBuilder 优先；只增量编译 WMA301 设备树；完整源码编译作为人工后备。** 不 Fork 上游；快速构建校验通过后上传验证 Artifact；OTA 功能及其自动发布目前默认屏蔽，代码保留。

## 一、已验证的基线

2026-11-13，[官方 Builder 快速构建 #43383051969](https://github.com/pzcn/wma301-immortalwrt/actions/runs/43383051969) 已通过全套 CI：预编译官方 Linux Image、WMA301 DTB 单独编译、SquashFS FIT 打包、FIT 哈希和 NAND/UBI 分区布局离线校验、Artifact 上传。

**缓存回归（2026-11-13）**：首次新流程 [#43384547653](https://github.com/pzcn/wma301-immortalwrt/actions/runs/43384547653) 用时约 2 分 33 秒，成功写入缓存；随后 [#43384953584](https://github.com/pzcn/wma301-immortalwrt/actions/runs/43384953584) 用时约 1 分 32 秒，完整 CI 通过。第二次日志确认 **1023 MB 官方 ImageBuilder** 和 **142 MB 匹配 Linux 源码**均为 Cache hit，且成功记录了构建指纹。该对比仅反映本次两轮 Actions，不是固定速度保证。定时跳过策略尚需下一次实际 `schedule` 触发后确认。

这只代表**代码和产物的离线验证**，不代表设备已通过启动、sysupgrade、SPI-NAND 长期写入或掉电持久化测试。

## 二、默认自动构建（本轮实施）

1. `.github/workflows/official-builder.yml` 每天读取官方 master SNAPSHOT 的 `mediatek/filogic/version.buildinfo` 和 `sha256sums`，解析 ImageBuilder 的真实 SHA256。
2. 计算指纹：**官方 Builder SHA256 + 本仓库与固件有关文件的内容哈希 + ISO 周次**。定时检查发现本周相同指纹已经**成功**，跳过重打包；官方固件、设备树、脚本或包清单变化立即触发；手工触发始终重新执行。每周至少生成一次新 Artifact，以免 14 天有效期内缺少可下载测试产物。
3. 需要构建时，从 GitHub Actions Cache 精确恢复对应 SHA256 的官方 ImageBuilder 归档；未命中再下载，命中后也**必须再次做 SHA256 检查**。不以 `latest` 或未校验的分支名缓存内核。
4. 重新读取官方索引，如与第一阶段的 Builder SHA256 不一致则终止，避免上游发布过程中的快照竞争。
5. 根据官方 `version.buildinfo` 对应 commit 获取同版本 ImmortalWrt 源码作为设备适配输入。Linux 原始源码归档按上游公布的 SHA256 做缓存；只抽取匹配内核的设备树头文件（包括 input-event-codes.h 的软链接目标）。
6. 使用 `scripts/official_builder.py` 注入设备 profile、WMA301 DTS、LAN/WAN、MAC、fw_env 和 FIT 升级逻辑，并从**固定 SHA 的 Aurora v1.4.0** 源码复制预编译的 LuCI 主题资源、注册默认主题。**不重新编译 Linux 内核、kmod、工具链，也不为了 Aurora 调用 SDK**。
7. 从 `configs/official-packages.txt` 读取预装包（允许负号排除包）。只接受规范包名，避免拼接任意 shell 语句。ImageBuilder 从官方配套 APK 仓库安装；缺失包则失败，不混用 SDK 或 ABI。
8. 生成 `squashfs-sysupgrade.itb`，再运行 `scripts/verify_official.py`，检查 FIT、SquashFS、WMA301 分区范围和只读标志、UBI 根卷，并记录官方版本、本仓库 SHA、所选包及输出 SHA256。
9. **全部通过且 Artifact 上传成功**之后，写入一条本周成功指纹缓存。失败不标记成功，以便下次自动重试。快速流程保留 14 天验证 Artifact，**默认不发布 OTA 固件源**，也不执行 sysupgrade、不写闪存。

```text
官方索引日检 / 设备代码变动 / 手工运行
             |
  Builder SHA256 + 本地代码哈希 + ISO 周
             |
  已有本周成功构建？ -- 是且仅为定时触发 --> 跳过
             |
             否
             v
   SHA256 键控缓存 / 下载 + 验证
             |
       匹配上游源码与 Linux 头文件
             |
    WMA301 DTB + Profile + 板级文件
             |
       ImageBuilder 重新打包 FIT
             |
       FIT / DTS / NAND 离线校验
             |
       验证 Artifact (14 天)
             |
       OTA 发布跳过（默认关闭）
             |
       成功指纹写入（仅全部成功）
```

## 三、完整源码后备

`.github/workflows/firmware.yml` 保留原有最新版 `master` HEAD 源码编译、双 FIT、离线验证和 pre-release 发布机制，但**取消原来的每日及 push 自动全量构建**，改为 Actions 页面手工触发。

| 流程 | 触发 | 内核来源 | 输出 | 发布 |
| --- | --- | --- | --- | --- |
| `official-builder.yml`（默认） | 每日检查 / push / 手动 | 官方 Builder 预编译内核 | sysupgrade FIT | Artifact；OTA Release 默认关闭 |
| `firmware.yml`（后备） | 手动 `workflow_dispatch` | 最新上游源码完整编译 | recovery + sysupgrade FIT | 原有 pre-release 规则 |

当需要还未进入官方 Builder 的上游修复、需要独立 initramfs-recovery，或者官方 Builder 不含必要驱动时，才使用完整源码后备。官方 Builder 可能比 upstream HEAD 旧，这是主动选择的版本一致性取舍。

## 四、日常操作 SOP

- **查看每天的检查：** 进入 Actions → “WMA301 | Official ImageBuilder fast-path”。metadata/job 显示是否跳过；有构建时从对应 run 下载 `WMA301_VERIFIED_FIT`，；默认不创建 OTA Release。
- **手动重跑快速构建：** Actions → 选择上述 workflow → Run workflow。手工运行不会因成功指纹而跳过。
- **修改包列表：** 编辑 `configs/official-packages.txt`，每行一个包（目前只有 `luci`），用 `-packagename` 排除默认包。能否安装要以同版本官方源为准。
- **执行完整构建：** Actions → “WMA301 | Follow ImmortalWrt, build and release” → Run workflow。需要强制重新生成相同源码版本时选择 `force=true`。原工作流可能发布预发布双 FIT，操作前先确认来源及用途。
- **缓存相关报错：** 不跳过 SHA256。如果缓存文件损坏，从仓库 Actions Cache 删除对应 SHA 键后重跑；如果是上游正在更新导致索引变化，稍后重新触发即可。
- **ABI/APK 缺失：** 禁止跨 kernel/vermagic、libc 或 target 混包；后续按 P2 引入同版本 SDK 补编，不要将编译失败伪装成成功。
- **设备树/升级脚本不兼容：** 保留失败状态；对照上游源修适配，或手动执行完整源码构建，绝不略过 `verify_official.py`。
- **部署前检查：** 只适用于已迁移为当前单 UBI 四卷布局的 WMA301 v2.0；绝不能将该 FIT 当原厂 A/B 全片镜像或 ubiformat 输入。

## 亚瑟软件同步（WMA301 独立适配）

通用插件与中文包已整理到 `configs/official-packages.txt`；Aurora v1.4.0 额外使用 [AURORA.md](AURORA.md) 所述固定源码与双路径安装；默认快速路径与完整源码路径应使用同一清单。WMA301 版本明确**不含 sing-box**，也不移植 Qualcomm NSS/PPE 和 eMMC/F2FS 代码。各项取舍参阅 [ARTHUR-SOFTWARE.md](ARTHUR-SOFTWARE.md)。

## WMA301 独立 OTA

已加入 [OTA.md](OTA.md) 所述的 WMA301 专属更新后端、LuCI 页面及唯一 OTA 固件源代码，但**默认屏蔽**：两条工作流中的 `WMA301_ENABLE_OTA: 'false'` 使 OTA 文件不进入固件，并跳过身份嵌入、元数据生成与自动发布。将两个工作流开关都改为 `'true'` 才能恢复；独立离线测试仍执行。首次升级、配置持久化及环境卷仍需实机验收。

## 五、后续研发任务与验收标准

| 优先级 | 状态 | 任务 | 验收 |
| --- | --- | --- | --- |
| P0 | ✅ 已验证 | 复用官方 Builder、独立 DTS、生成 FIT、离线验证 | 见 #43383051969 |
| P1 | 🟡 缓存命中与双轮 CI 已验证；定时去重待实测 | Builder/kernel SHA256 缓存；每日检查；同周成功去重；包列表与 manifest | #43384547653 与 #43384953584 全绿、缓存命中；仍需验证下一次 schedule 跳过逻辑 |
| P2 | ⬜ 待实施 | 用**匹配官方 Builder 的 SDK**只补编官方没有的第三方 APK | 不修改内核 ABI，不跨源安装；无缺包不下载 SDK |
| P3 | ⬜ 待研究 | 减少 recovery 的完整源码构建需求 | 如果不能安全复用 initramfs 生成，继续保留完整后备 |
| P4 | ⬜ 待实机验收 | 启动、LAN/WAN、Wi-Fi 校准、MAC、四 UBI 卷、升级保留配置、SPI-NAND ECC、冷启动及恢复 | 多轮实机升级/断电、存储和环境卷保持一致 |
| P5 | ⏸ 单通道 OTA 代码已实现但默认屏蔽 | 后续按需恢复自动发布、设备升级前检查及人工授权 | 开启后重新进行 CI 和 P4 实机验收；绝不自动刷写 |

## 六、维护原则

- **不 Fork** 官方 ImmortalWrt，不把设备私有分区数据写入源代码；保留精简适配层。
- 构建产物全部记录官方 Builder SHA256、上游 commit、设备仓库 commit、包清单、FIT SHA256。
- 两条工作流不能互相覆盖产物；快速路径只自动上传验证 Artifact；OTA Release 发布须显式开启，且绝不自动部署到路由器。
- 优化速度必须以哈希验证、来源一致、UBI 环境卷保护和实机安全为边界，失败优先保留上一成功固件。

更多细节：[OFFICIAL-IMAGEBUILDER.md](OFFICIAL-IMAGEBUILDER.md)。
