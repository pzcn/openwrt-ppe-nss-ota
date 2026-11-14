# PR #16：Hybrid Builder 临时 SSH 调试

## 适用范围与边界

此功能仅在仓库 `pzcn/openwrt-ppe-nss-ota` 的 `feat/hybrid-official-snapshot` 分支上，通过带有 `[ssh]` 的 **push 提交信息** 显式触发。触发后始终选择 full 构建；一旦构建脚本失败，Runner 在同一个临时环境里保留最多 45 分钟。构建正常时不会等待。此调试模式一律禁止自动发布，即使构建成功。

旧的已结束 Actions 不能 SSH 重连；必须使用新一轮启用此模式的构建。实验分支上的 workflow_dispatch 按钮可能不可用，因为 GitHub 要求 workflow 在默认分支存在；因此本分支提供专用触发文件。

## 一次性 Tailnet 设置

1. 在 Tailscale 管理台创建一个仅供 CI 调试使用的标签：`tag:gh-hybrid-debug`。
2. 创建具有 `auth_keys` 写入权限、仅允许该标签的 **OAuth client**。官方 `tailscale/github-action@v4` 会使用它为每次运行注册临时节点，并在 job 完成后退出。
3. 在 GitHub 仓库 **Settings → Secrets and variables → Actions** 新增两个 Repository secrets：
   - `TS_DEBUG_OAUTH_CLIENT_ID`（OAuth client ID）
   - `TS_DEBUG_OAUTH_SECRET`（OAuth client secret）
4. 在 Tailnet 的 Access controls 中对 **自己实际登录的 Tailscale 身份** 开放到此标签的 TCP 22 和 SSH `runner` 用户。以下为需要合并进现有策略的示例片段，替换邮箱；不要直接覆盖现有全部策略：

```json
{
  "tagOwners": {
    "tag:gh-hybrid-debug": ["autogroup:admin"]
  },
  "grants": [
    {
      "src": ["your-login@example.com"],
      "dst": ["tag:gh-hybrid-debug"],
      "ip": ["tcp:22"]
    }
  ],
  "ssh": [
    {
      "action": "accept",
      "src": ["your-login@example.com"],
      "dst": ["tag:gh-hybrid-debug"],
      "users": ["runner"]
    }
  ]
}
```

`tagOwners`、`grants`、`ssh` 应与现有 Tailnet 策略合并，不要用这个片段直接替换完整策略。不要对 `autogroup:member` 广泛开放此标签，更不要给所有人 `root` 登录。

## 启动一次可 SSH 的测试

在本地克隆的 PR #16 分支运行：

```bash
git switch feat/hybrid-official-snapshot
date -u +%FT%TZ > config/hybrid-ssh-debug.trigger
git add config/hybrid-ssh-debug.trigger
git commit -m "debug: investigate Hybrid Builder [ssh]"
git push origin feat/hybrid-official-snapshot
```

**为什么需要修改触发文件？** 此 workflow 设置了 push paths 过滤，单独创建空提交不一定能启动构建。`[ssh]` 仅触发调试，触发文件本身不含密钥、不修改固件内容。

打开 GitHub Actions 的 Hybrid Builder 运行页面。在步骤 `Enable Tailscale SSH on temporary runner` 中记录 Tailscale 私有 IP。构建失败后，步骤 `Hold failed hybrid runner for SSH` 会显示登录指令，也会写入 Actions Summary。

在自己已登录同一 Tailnet 的电脑上：

```bash
tailscale ssh runner@100.x.y.z
cd /home/runner/work/_temp/immortal-hybrid/immortalwrt
# 检查编译日志，重新运行失败的 make 或 ImageBuilder 命令
```

上面的 IP 仅为占位符，必须以当次 Actions 日志中的 IP 为准。如果是 Windows，确保已安装 Tailscale，并从支持 Tailscale SSH 的终端连接。

完成调试后，在 Runner 内执行（实际路径以 Actions 日志为准）：

```bash
touch /home/runner/work/_temp/hybrid-ssh-debug-done
```

不主动结束，约 43 分钟后等待循环退出，以确保留出缓存上传的时间；整个保持步骤最长 45 分钟。

## 注意事项

- **Runner 内修改不会自动同步到 GitHub 仓库。** 验证修复后，将对应补丁应用到 PR #16 并提交。原构建步骤失败后，Actions 结果仍为失败，不会因 SSH 调试或触发结束文件变成成功；需要新 CI 复验。
- 工作流仍保存失败构建的源码下载缓存和 ccache，方便下一次运行。Runner 自身是一次性的，关闭后工作目录会删除。
- SSH 用户为 GitHub Ubuntu Runner 自带的 `runner`；该环境可能含有构建用凭据、GitHub Token 或 Tailscale 状态，必须严格限制 Tailnet ACL 和具备仓库写权限的人员。不要将 OAuth secret、私钥或 Runner 用户凭据打印到 Actions 日志、上传到 Artifacts 或提交到代码库。
- 若没有配置两个 OAuth secrets，带 `[ssh]` 的运行会在构建开始前直接提示缺失配置，不会无意义地跑完内核构建。
- 本阶段只保留失败现场，不自动恢复编译阶段。断点续构将在后续独立实施。

参考：[Tailscale GitHub Action](https://tailscale.com/docs/integrations/github/github-action)、[Tailscale SSH](https://tailscale.com/docs/features/tailscale-ssh)。
