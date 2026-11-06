# 定制 OTA：OpenWrt 原生“备份 / 升级”页面内的在线更新

这是 pzcn 的 RE-SS-01 PPE+NSS 定制固件的在线升级系统，**只从自己的 GitHub Releases 更新**，不安装未经定制的上游镜像。

## 入口与页面布局

LuCI **系统 → 备份 / 升级** 页面的“操作”区域现在有两个并列的刷机功能模块：

- **刷新固件镜像**（官方原生）：选择本地 `sysupgrade.bin`、验证并刷机，仍然可以备份、恢复配置及查看备份文件列表。
- **在线固件更新（pzcn OTA）**：显示当前/最新版本、更新时间、额外软件包提醒，支持“重新检查”和“下载并安装新版本”。

旧菜单重命名为 **系统 → OTA 自动更新设置**，仍可配置自动检查时间和发布后的等待天数。新版 OTA 区域也链接这个设置页面。

新界面完全沿用 LuCI `form.SectionValue` 和原生按钮样式，备份/上传的官方功能保持不变。为了将 OTA 区域**嵌入同一页**，仓库保留了来自 `openwrt/luci` 的 `luci-mod-system` 标准 `view/system/flash.js` 基础页面，只新增在线更新模块与异步检查，不引入自定义 CSS。上游 LuCI 的该文件如果发生较大变化，后续构建需要同步更新这里的副本。

## 为什么以前能检查到版本却不让更新？

以前的手动 OTA 在发现新固件后，还会执行：

1. 对比已安装软件包与最新镜像的 manifest。
2. 从新固件对应的 PPE+NSS 软件仓库下载 APK 索引。
3. `apk add --simulate` 推演额外软件包能否在新系统安装。
4. 只要模拟检查没有完成、缺失一个可选插件或仓库临时不可用，就**禁用整个升级按钮**。

这不等于镜像无法安装，而是**混淆了软件包迁移风险与固件本身的有效性**。某些用户 APK 软件源本就不可用，模拟更容易误拦截。

## 新的手动 OTA 策略

用户看到新版本时，即使没有执行额外软件包兼容性模拟，仍显示“下载并安装”按钮。

| 检查 | 手动 OTA |
| --- | --- |
| 本机为 RE-SS-01、ROM 使用本仓库的定制 OTA channel | 必须通过 |
| 最新 Release 的仓库、型号、group、构建号与 `ota.json` 一致 | 必须通过 |
| 目标构建号高于当前版本，Release 内含合法 manifest | 必须通过 |
| manifest SHA256 和下载镜像 SHA256 | 必须通过 |
| 标准 `sysupgrade -T` 兼容性检测 | 必须通过 |
| 下载空间不足以容纳镜像 | 必须通过（按实际空间检查，不再简单使用 3 倍内存门槛） |
| 当前额外 APK 包在新系统里能否重新安装 | **不再阻止手动更新** |

手动更新前弹出确认对话框，明确提醒：额外插件可能需要重新安装。更新会保留当前 `/etc/apk/world` 与 ROM 差异形成的迁移清单，通过原有 `/etc/ppe-update/packages` 和开机恢复服务尽可能重装；某些依赖新内核 ABI 的第三方插件仍可能无法恢复。**配置备份到电脑**仍推荐执行。

**无须使用 `sysupgrade -F`，也不允许绕过设备型号/SHA256/镜像完整性等真正安全边界。**

### 自动更新

无人值守自动更新继续执行严格的额外软件包检查；如果软件源不可用、模拟失败或缺包，自动更新会暂缓，避免凌晨无人值守时失去预期插件。这个限制不影响手动更新。

### 从旧版本升级的首次过渡

**已经运行的旧固件仍有它自己的硬性软件包限制**，GitHub 不能远程修改它。若旧固件的 OTA 界面仍然阻止按钮，请先在电脑上下载本仓库最新 Release 的 `sysupgrade.bin`，使用原生“系统 → 备份 / 升级 → 刷写新的固件镜像”上传刷入一次。之后新版本就可在同页使用更宽松的在线 OTA。

不要为绕过旧版界面而执行 `sysupgrade -F`。正常刷机前备份 `/etc/config` 与重要用户文件。

## 固件校验与下载流程

1. 从 ROM 的 `/etc/pzcn-ota-release` 获取当前定制版构建号（保持上游 `/etc/ppe-release` 用于 NSS 匹配软件源）。
2. 查询 `https://api.github.com/repos/pzcn/openwrt-ppe-nss-ota/releases/latest` 和该 Release 的 `ota.json`。
3. 校验完整 channel、board、group、tag、发布编号和 manifest SHA256。
4. 更新镜像从固定仓库下载到 `/tmp/ppe-update`，比较 SHA256，并运行 `sysupgrade -T`。通过后调用标准 `sysupgrade`，**保留配置**。
5. 本地更新日志在 `/tmp/ppe-update.log`；网页会显示更新过程并等待路由器重启连回。

仓库发布的 `ota.json` 与 bin 并未使用独立固件签名，校验只能防止下载损坏或与指定 Release 不一致，不能抵御 GitHub 发布权限遭入侵的情况。

## 其他注意事项

- 互联网问题（GitHub Releases API 速率限制、网络封锁）可能影响检查和下载；仅软件包镜像源异常不会再阻止手动更新。
- 继续保持 PPE+NSS 适用的 kernel 模块源；手动升级并不能保证所有旧版 kmod 或第三方 APK 在新内核可用。
- OTA 不操作 GPT 分区表、不格式化 p27，不修改 U-Boot，但升级/恢复配置仍需要有可用的 overlay。
- 如果使用一段时间后升级失败，请保留错误日志而不是只复制顶部通用提示。

## 主要文件

| 文件 | 职责 |
| --- | --- |
| `files/www/luci-static/resources/view/system/flash.js` | LuCI 官方备份升级页基础上嵌入在线 OTA 兄弟模块 |
| `files/www/luci-static/resources/view/system/ppe-update.js` | 自动更新计划的配置页面 |
| `files/usr/share/luci/menu.d/luci-app-ppe-update.json` | 新“OTA 自动更新设置”菜单 |
| `files/usr/sbin/ppe-update` | GitHub Release 校验、手动/自动策略及刷机 |
| `files/usr/share/rpcd/acl.d/luci-app-ppe-update.json` | 限制 LuCI OTA status、start 和计划配置权限 |
| `scripts/write_ota_metadata.py` | 发布时生成带 SHA256 的 `ota.json` |
| `scripts/tests/test-custom-ota.sh` | 模拟手动/自动流程，保证不误绕过 SHA256 和 `sysupgrade -T` |
| `scripts/build.sh` | 集成上游 ImageBuilder、校验模板、发布固件 |

## SSH 诊断

```sh
ppe-update status
ppe-update check
cat /tmp/ppe-update.log
cat /etc/pzcn-ota-release
```

`ppe-update status` 即使没有运行 APK 依赖模拟，也能发现新固件。为了避免恢复失败，不应发布包含账号密码的日志或完整配置备份。
