# Aurora 主题：WMA301 安装与回退

## 来源与版本

- 上游：[eamonxg/luci-theme-aurora](https://github.com/eamonxg/luci-theme-aurora)
- 与亚瑟一致的版本：**v1.4.0**
- 源码提交：`84c27b66952e6fc4be60128067a6b88bfd34afb5`
- 许可证：Apache-2.0，固件包含上游 LICENSE
- 与代理服务无关联：本固件**不包含 sing-box / HomeProxy**

官方 `openwrt-25.12` LuCI feed 没有 Aurora APK，因此不能把
`luci-theme-aurora` 放入 `configs/official-packages.txt` 后期待
官方 ImageBuilder 自动安装成功。

## 快速构建（默认）

1. 工作流拉取上游主题 `v1.4.0` tag，校验真实 Git HEAD 必须等于固定 commit。若 tag 被修改，构建直接失败，不静默升级。
2. `scripts/aurora.py` 只复制上游已编译的 `htdocs/` 和 `ucode/` 安装资源；Ucode 模板严格按 LuCI `SubstituteVersion` 的方式替换版本占位符，避免未经替换的 `{# PKG_VERSION #}`。
3. `htdocs/` 映射到固件 `/www/`；`ucode/` 映射到 `/usr/share/ucode/luci/`；同时保留 `/usr/share/licenses/luci-theme-aurora/LICENSE`。
4. 不复制主题原始 `root/etc/uci-defaults/30_luci-theme-aurora`；由本仓库的 `files/etc/uci-defaults/95-luci-preferences` 负责 LuCI 主题注册与首启默认值。
5. 在验证 FIT 之前检查主题的 CSS/JS、header/sysauth 等模板及版本戳，`manifest.json` 记录主题版本、源 SHA 和安装方式。

**快速路径直接内置主题文件，不是独立可由 apk 管理的主题包。** CSS、JS、Ucode 都不涉及内核 ABI，故无须调用匹配 SDK。保留官方 Bootstrap 做回退，但还需在 WMA301 实机上验证 LuCI 和浏览器兼容性。

## 完整源码构建后备

`.github/workflows/firmware.yml` 使用同一个 tag/SHA，把主题源码放入临时 ImmortalWrt buildroot 的 `package/luci-theme-aurora`，并交给 LuCI 构建系统生成常规 `luci-theme-aurora` 软件包。该路径仍需完整源码构建，仅为手动后备。

主题原来的 `30_luci-theme-aurora` 会被移除，统一使用本仓库的首次启动设置，避免覆盖已有的用户主题选择。

## 默认主题与回退

仅在首次引入 Aurora、且 LuCI 原先仍使用默认 Bootstrap 时，自动把 Aurora 设为默认。如果此前用户主动选择了其他主题，脚本只注册 Aurora，不强行切换。

如果 Aurora 网页出现问题，可通过 SSH 重新切回 Bootstrap：

```sh
uci -q set luci.main.mediaurlbase='/luci-static/bootstrap'
uci -q commit luci
/etc/init.d/uhttpd restart
```

随后清理浏览器缓存并重新打开 LuCI。主题本身不提供新的 U-Boot/网络恢复能力。

## 离线构建验收记录

- **2026-11-13：[GitHub Actions #43388089333](https://github.com/pzcn/wma301-immortalwrt/actions/runs/43388089333) 全部成功。**
- 官方 ImageBuilder 快速路径验证 Aurora v1.4.0 固定 SHA 后，成功注入 **30 个主题文件**，生成 WMA301 sysupgrade FIT；FIT/DTS/NAND 检验和 `manifest.json` 的 `bundled_theme` 元数据检查通过。
- 实验 Artifact ZIP 大小约 **30.8 MB**，只上传 Actions Artifact，不发布 Release、不自动刷机。
- 完整源码双 FIT 后备仍未因本次主题改动完成实测；Aurora 在 WMA301 实机 LuCI 中的浏览器兼容性尚待验证。

## 验收标准

- `python3 scripts/test_aurora.py` 校验文件映射、模板版本戳、文件冲突与符号链接。
- 官方 ImageBuilder FIT 通过校验，`manifest.json` 的 `bundled_theme` 显示正确的 commit/version。
- 首次启动后 LuCI 能显示 Aurora，网络、终端、文件管理器等页面可使用。
- 保留配置升级后，用户手工选择的 Bootstrap 或其他主题不被覆盖。
- WMA301 256 MiB RAM、冷启动和掉电重启行为正常。

**GitHub Actions 全绿只说明编译与离线静态检查通过，不是实机通过。**
