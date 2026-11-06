# 辽宁大学 Dr.COM 校园网认证（LuCI 自定义插件）

这个插件集成在定制版 OpenWrt 的 **网络 → 校园网认证** 菜单中，以 `curl` 完成网页登录与注销。它不安装旧版 Dr.COM 客户端、不修改路由表、防火墙、PPE/NSS 内核或者原有 OTA 系统。

## 功能

- 账号、密码：通过 LuCI 页面提交，实际网络请求由**路由器自身**发起，而不是浏览器或手机
- 记住账号和密码：需要主动勾选。保存到 `/etc/config/drcom`，文件权限 `0600`（仅 root）
- 不记住：账号和密码只用于这次认证请求，不写入持久化配置；已保存的旧凭据会被清除
- 再次登录：如果已经记住密码，界面显示保存的账号，密码框留空即可重新登录；RPC 永远不会返回已保存的密码
- 注销：默认使用 GET `http://gate.lnu.edu.cn/F.htm`
- 检查状态：尝试从网关 HTML 中读取 Dr.COM 的 `Dr.COMWebLoginID_0.htm`、`_1.htm` 标记；如果没有标记则显示“状态待确认”
- 清除已保存的凭据：与注销是两个独立操作，不会悄悄中断网络
- 高级选项：认证服务器可填 HTTP/HTTPS 域名或 IPv4 地址（如 DNS 在未认证前不可用），注销路径可调整

**不包含自动连接、自动重试、开机认证或定时保活**，因为本次只要求手动登录/记住密码/注销。如果日后需要可在明确网络行为后另加选项。

## 网页认证协议

默认登录 URL：
```
http://gate.lnu.edu.cn/0.htm
```

POST 表单包含：

```
DDDDD=<账号，URL 编码>
upass=<密码，URL 编码>
0MKKey=
```

等价于用户给出的 `curl --data-urlencode` 示例。实际运行时，密码通过仅 root 可读的临时请求文件，进入 curl 的标准输入配置（`curl -K -`），**不会出现在 curl 命令行参数、系统日志或 RPC 状态返回中**。

注销路径 `/F.htm` 来自其他 Dr.COM Web Portal 的已知实现。**辽宁大学官方说明确认门户支持注销，但未公布该版本的具体 HTTP API**。如果实际注销失败，请在辽宁大学校园网浏览器中打开 `http://gate.lnu.edu.cn/`，执行注销操作并使用开发者工具查看准确请求；然后改高级选项中的路径，或进一步适配 POST/其他参数。

项目无法从当前环境访问辽宁大学校园网网关（可能仅允许校内访问），因此**没有进行真实校园网账号登录/注销验证**。

## 在线状态的限制

HTTP 200 只表明 HTTP 请求完成，不代表认证成功。插件只在返回可识别的 Dr.COM 页面标记（或明确的中文成功/失败文案）时判断认证结果，否则显示“状态待确认”。建议在 **实际连接的校园网** 中验证结果。

你的亚瑟对外认证是通过它的默认路由和出口 IP 进行的，如果校园网认证绑定单个客户端 IP，那么识别的将是**路由器自身上联 IP**。请确保网线/AP 上联拓扑符合校园网规则；不保证学校支持把一个账户共享给多个设备。网关若会检测或限制路由器，插件不会绕过该限制。

## 安全

1. 该学校门户默认是 **HTTP（非 HTTPS）**；账号和密码在校园网链路上明文提交。**不要在非可信网络中使用**，如学校支持 HTTPS 可将高级设置改为 HTTPS 域名，但不要在证书不可信时禁用 TLS 校验。
2. 建议用 HTTPS 访问 LuCI 管理后台，设置强管理密码，并仅允许可信设备访问路由器。LuCI RPC 提交账号密码时使用当前管理连接的传输保护。
3. 勾选记住密码意味着明文凭据会存在 root-only 的 `/etc/config/drcom`，并可能包含在 OpenWrt 系统配置备份中。不要公开分享配置备份。
4. 密码不经过 shell 参数或环境变量。临时请求文件使用 `0600` 独占创建并在读取后立即删除；curl HTTP 响应只留在临时文件，且不会原样回传 HTML（防止暴露门户内的个人信息）。
5. `rpcd` ACL 仅允许本插件的 `get_config/get_status/login/logout/forget` 方法，不对 LuCI 暴露任意 shell 命令权限。
6. 不自动改变 `/etc/config/network`、WAN、防火墙或路由策略。

## 检查

```sh
ubus -v list luci.drcom
ubus call luci.drcom get_config
ubus call luci.drcom get_status
stat -c '%a' /etc/config/drcom
which curl jsonfilter
```

`ubus call luci.drcom get_config` 不会返回密码。**不要**在终端命令里直接写带密码的 `ubus call ... login '{...}'`，因为 shell 历史可能保留密码；使用 LuCI 页面即可。

## 实现文件

| 文件 | 功能 |
| --- | --- |
| `files/www/luci-static/resources/view/network/drcom.js` | LuCI 页面交互 |
| `files/www/luci-static/resources/drcom-campus.css` | 独立响应式深色视觉 |
| `files/usr/share/luci/menu.d/luci-app-drcom.json` | LuCI 菜单入口 |
| `files/usr/share/rpcd/acl.d/luci-app-drcom.json` | 最小 RPC 授权 |
| `files/usr/share/rpcd/ucode/luci.drcom` | 账号处理、root-only 配置与 RPC |
| `files/usr/libexec/drcom-web` | 最小 curl 登录、注销、状态采集 |
| `files/etc/config/drcom` | 默认网关地址（不带账号、密码） |
| `scripts/tests/test-drcom.py` | 本地模拟 HTTP 网关端到端测试（不访问真实学校） |

插件集成方式与 PPE/NSS 监控页面一样，是 ImageBuilder 的 `FILES=files` 文件覆盖层，因此不是 APK 商店里独立可更新的软件包。
