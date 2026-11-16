# WMA301 · Aurora v1.4.0 标准 APK 安装

## 构建路线

WMA301 继续复用 ImmortalWrt master / Linux 6.18 的**官方 mediatek/filogic ImageBuilder**。Aurora 不属于官方 LuCI 软件源，因此先从上游 [eamonxg/luci-theme-aurora](https://github.com/eamonxg/luci-theme-aurora) 拉取 `v1.4.0`，并验证固定提交 `84c27b66952e6fc4be60128067a6b88bfd34afb5`。

`scripts/aurora.py` 会校验主题文件、替换 LuCI 模板版本变量，然后使用**官方 ImageBuilder 自带的主机端 `apk mkpkg`** 生成原生 `noarch` 软件包：

```
luci-theme-aurora-1.4.0-r1.apk
```

主题文件放在 APK 的 `/www/luci-static/`、`/usr/share/ucode/luci/` 和 `/usr/share/licenses/` 中，依赖 `luci-base`。随后将 APK 放入 ImageBuilder 的 `packages/`，由 ImageBuilder 自动生成本地仓库索引并通过 `PACKAGES=luci-theme-aurora` 安装。ImageBuilder 的实际 manifest 必须包含 `luci-theme-aurora - 1.4.0-r1`，否则整个 FIT 构建失败。

**不需要额外 SDK，不编译内核，也不混用其他 ABI 的 APK。** Aurora 是纯 CSS、JavaScript、Ucode 模板资源，故其标准包架构为 `noarch`。使用 ImageBuilder 自带的官方主机端 APK 工具，与目标固件的 APK 格式一致。

## 与旧 Overlay 的区别

| 项目 | 旧方式 | 当前标准安装 |
| --- | --- | --- |
| 主题文件 | 放入 `FILES=` 根文件系统覆盖层 | 由 `luci-theme-aurora.apk` 拥有 |
| `apk list --installed` | 查不到主题 | 显示 `luci-theme-aurora` |
| 单独卸载 / 安装 | 无法由 APK 管理 | 使用 APK 包操作 |
| 固件 manifest | 不包含主题包 | **必须包含** `luci-theme-aurora` |
| 构建依赖 | 官方 ImageBuilder | 官方 ImageBuilder（自带 `apk mkpkg`） |
| 内核 | 官方 Linux 6.18 | 完全不变 |

`files/etc/uci-defaults/95-luci-preferences` 保持独立，负责注册 Aurora 和首次启动时的默认主题偏好。上游 `30_luci-theme-aurora` 不随主题 APK 安装，以免覆盖用户已选的主题。Bootstrap 继续保留作为回退选项。

## 发布和校验

WMA301 Actions 在固件生成后检查：

1. Aurora v1.4.0 固定源码 SHA 与 APK 构建命令、软件包哈希。
2. 实际 ImageBuilder manifest 中 Aurora 的名称及版本，不接受仅有 Overlay 文件的伪装产物。
3. FIT 的 DTB、NAND/UBI 安全边界、源版本、OTA 元数据和禁止包清单。
4. 将原生 APK 连同固件 FIT、安装清单及各自 SHA256 一起放入测试 Artifact；今后发布 Release 也同时上传该 APK。

单独在路由器上从下载的文件安装时，先校验 Release 中的 SHA256，并使用 `apk add ./luci-theme-aurora-1.4.0-r1.apk`。如果手动安装一个未由签名仓库提供的包，设备可能要求 `--allow-untrusted`；应确认来自本仓库且文件哈希匹配后再使用。

仅当前升级所需的 FIT 才采用独立 OTA 通道。主题包不是固件镜像，不能代替 sysupgrade。

## 主题回退

保留 Bootstrap。若页面出现异常，可通过 SSH 切回：

```sh
uci -q set luci.main.mediaurlbase='/luci-static/bootstrap'
uci -q commit luci
/etc/init.d/uhttpd restart
```

相关实现：[`scripts/aurora.py`](../scripts/aurora.py)、[`scripts/official_builder.py`](../scripts/official_builder.py)、[`scripts/verify_official.py`](../scripts/verify_official.py)。上述为 CI 构建验收，LuCI 视觉兼容性仍需真机确认。
