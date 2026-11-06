# 辽宁大学 Dr.COM 校园网认证（LuCI 自定义插件）

这个插件集成在定制版 OpenWrt 的 **网络 → 校园网认证** 菜单中，以 `curl` 完成网页登录与注销。**所有请求固定通过 OpenWrt 逻辑 WAN 接口的实际 L3 设备，不使用 WireGuard，也不修改系统的默认路由。** 它不安装旧版 Dr.COM 客户端、不修改路由表、防火墙、PPE/NSS 内核或者原有 OTA 系统。

## 功能

- 账号、密码：通过 LuCI 页面提交，实际网络请求由**路由器自身**发起，而不是浏览器或手机
- 记住账号和密码：需要主动勾选。保存到 `/etc/config/drcom`，文件权限 `0600`（仅 root）
- 不记住：账号和密码只用于这次认证请求，不写入持久化配置；已保存的旧凭据会被清除
- 再次登录：如果已经记住密码，界面显示保存的账号，密码框留空即可重新登录；RPC 永远不会返回已保存的密码
- 注销：向**可编辑的完整注销 URL** 发起 GET 请求，默认是 `http://gate.lnu.edu.cn/F.htm`
- 检查状态：尝试从网关 HTML 中读取 Dr.COM 的 `Dr.COMWebLoginID_0.htm`、`_1.htm` 标记；如果没有标记则显示“状态待确认”
- 清除已保存的凭据：与注销是两个独立操作，不会悄悄中断网络
- 自定义地址：登录 URL 和注销 URL **分别独立填写并保存**，支持 HTTP/HTTPS、域名或 IP、端口、路径和查询参数（例如 `http://192.168.1.1/0.htm`）

**新增每日定时自动认证**：勾选“每天 00:00 自动认证一次”并保存，OpenWrt cron 将在路由器系统**本地时间**的每天 00:00 发起**一次**登录请求，不定时重试、不在开机时自动认证。默认关闭。启用前必须先勾选“记住账号与密码”并成功保存账号密码。取消记住或清除已保存凭据时，自动认证自动关闭。手动注销后不会立即重新登录，但若仍保留自动开关，次日 00:00 会再次认证。

## 网页认证协议

默认登录 URL（支持在高级选项中完整修改 URL，并点击“保存认证地址”）：
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

默认注销 URL 的 `/F.htm` 路径来自其他 Dr.COM Web Portal 的已知实现。**辽宁大学官方说明确认门户支持注销，但未公布该版本的具体 HTTP API**。如果实际注销失败，请在辽宁大学校园网浏览器中打开 `http://gate.lnu.edu.cn/`，执行注销操作并使用开发者工具查看准确请求；然后修改高级选项中的完整注销 URL，或进一步适配 POST/其他参数。

项目无法从当前环境访问辽宁大学校园网网关（可能仅允许校内访问），因此**没有进行真实校园网账号登录/注销验证**。

## 在线状态的限制

HTTP 200 只表明 HTTP 请求完成，不代表认证成功。插件只在返回可识别的 Dr.COM 页面标记（或明确的中文成功/失败文案）时判断认证结果，否则显示“状态待确认”。建议在 **实际连接的校园网** 中验证结果。

你的亚瑟对外认证始终绑定 WAN 的实际 L3 出口接口（例如 `wan`、`eth0.2` 或 `pppoe-wan`），如果校园网认证绑定单个客户端 IP，那么识别的将是**WAN 上联 IP**。请确保网线/AP 上联拓扑符合校园网规则；不保证学校支持把一个账户共享给多个设备。网关若会检测或限制路由器，插件不会绕过该限制。

## 安全

1. 该学校门户默认是 **HTTP（非 HTTPS）**；账号和密码在校园网链路上明文提交。**不要在非可信网络中使用**，如学校支持 HTTPS 可将高级设置改为 HTTPS 域名，但不要在证书不可信时禁用 TLS 校验。
2. 建议用 HTTPS 访问 LuCI 管理后台，设置强管理密码，并仅允许可信设备访问路由器。LuCI RPC 提交账号密码时使用当前管理连接的传输保护。
3. 勾选记住密码意味着明文凭据会存在 root-only 的 `/etc/config/drcom`，并可能包含在 OpenWrt 系统配置备份中。不要公开分享配置备份。
4. 密码不经过 shell 参数或环境变量。临时请求文件使用 `0600` 独占创建并在读取后立即删除；curl HTTP 响应只留在临时文件，且不会原样回传 HTML（防止暴露门户内的个人信息）。
5. `rpcd` ACL 仅允许本插件的 `get_config/get_status/login/logout/forget/save_urls/set_auto` 方法，不对 LuCI 暴露任意 shell 命令权限。
6. 不自动改变 `/etc/config/network`、WAN、防火墙或路由策略，也不修改 WireGuard 接口。定时任务仅在用户主动开启并保存凭据后执行，且不上传完整响应或记录密码。

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
| `files/usr/libexec/drcom-web` | curl 手动/定时登录、注销和状态采集 |
| `files/usr/libexec/drcom-schedule` | 幂等维护 root crontab 的每日 0 点任务 |
| `files/etc/init.d/drcom` | 每次启动时确保 cron 项存在，不启动驻留进程 |
| `files/etc/uci-defaults/97-drcom-credentials-permissions` | 首次启动设置凭据权限并启用定时任务初始化 |
| `files/etc/config/drcom` | 默认网关地址（不带账号、密码） |
| `scripts/tests/test-drcom.py` | 本地模拟 HTTP 网关端到端测试（含完整可编辑 URL、午夜 cron 幂等性及自动认证；不访问真实学校） |

插件集成方式与 PPE/NSS 监控页面一样，是 ImageBuilder 的 `FILES=files` 文件覆盖层，因此不是 APK 商店里独立可更新的软件包。

## 每天 00:00 自动认证的设置与验证

在 LuCI 的「网络 → 校园网认证」中先填写账号、密码，勾选 **记住账号与密码**，然后点击“连接校园网”。在页面下方勾选 **每天 00:00 自动认证一次**，点击“保存自动认证设置”。如果没有保存的密码，插件会明确拒绝开启，不会创建无效登录。

这条定时任务是：

```cron
0 0 * * * /usr/libexec/drcom-web auto >/dev/null 2>&1 # drcom-campus-auto
```

它在每次开机由 `/etc/init.d/drcom` 幂等维护，其他已有 cron 任务不会删除。即使开关关闭，任务仍可保留但自动登录程序直接退出，**不会向网关发送任何请求**。此行为避免多次启用后重复生成任务。路由器时区请设置为 **Asia/Shanghai（中国标准时间）**，否则会在实际系统本地时间 00:00 执行，而不是北京时间 00:00。若路由器在 00:00 断电，不会补跑漏掉的任务。

```sh
uci -q get drcom.main.auto
uci -q get drcom.main.remember
grep drcom-campus-auto /etc/crontabs/root
date '+%Y-%m-%d %H:%M:%S %Z'
```

**手动触发同样的认证用于排查：** 在确认凭据和链接无误后，可以执行 `/usr/libexec/drcom-web auto`，它会按已存设置登录；如果没有开启自动认证则不发送请求。不要在日志中记录账号密码。

**旧版迁移：** 如果先前版本保存的是 `drcom.main.server` 和 `drcom.main.logout_path`，新版本会从旧字段推导登录/注销 URL；首次在页面保存地址后采用新字段。不会清空保存的账号密码。

## 仅 WAN 出口：避开 WireGuard 与 PBR

本版本的手动登录、注销、状态检查和每日 00:00 自动登录都采用以下流程：

1. 使用 `ubus call network.interface.wan status` 检查 WAN 必须处于 `up: true` 状态，动态提取 `l3_device`，例如 `wan`、`eth0.2`、`pppoe-wan`。如果 WAN 不可用或实际出口是 WireGuard/tun/tailscale 等隧道设备，直接拒绝发送认证。不会回退系统默认路由。
2. 对实际 `curl` 请求强制加入 `--interface "if!$WAN_DEVICE"`、`--noproxy '*'`、`--ipv4`，不自动追踪跳转。这限制了 HTTP/HTTPS 数据连接的物理出口，即使你的 WireGuard/PBR 将普通默认路由改到隧道也不会让认证连接转向 WG。
3. **域名解析单独约束。** OpenWrt 官方 curl 使用 `--disable-ares`，`--interface` 不会约束 DNS。对于域名 URL，插件只使用 `network.interface.wan status` 中由 WAN 提供的 IPv4 DNS，并检查 `ip -4 route get <DNS>` 的出口必须是相同的 WAN L3 设备。通过该 DNS 的 `nslookup -type=A` 返回 IPv4 后，使用 curl `--resolve 域名:端口:IP`，阻止 curl 再通过系统 DNS 查询。
4. 如果无法确认 WAN DNS 能走 WAN、DNS 失败或者 WAN 已断开，**认证会失败并给出提示**，不会偷偷改用 WireGuard。对于学校认证网关，最稳定的方式是将完整登录/注销 URL 直接填写成 IPv4 地址，如 `http://192.168.1.1/0.htm` 和 `http://192.168.1.1/F.htm`（这里仅为地址格式示例，不是学校实际网关）。这样完全不需要域名解析。

**局限：** `ip route get` 检查的是内核普通路由。若用户另装非常规 `nftables`/PBR OUTPUT 强制标记规则，可能对独立执行的 `nslookup` DNS 查询重定向，单靠路由查询无法覆盖所有自定义策略。若必须在任意 PBR 规则下确保 DNS 绝对不经过 WG，**请使用认证服务器的 IPv4 地址，不要使用域名**；这种模式不会发起 DNS 请求。

可在 SSH 上检查：

```sh
ubus call network.interface.wan status
ip -4 route show
# 使用实际 WAN 设备名替换 WAN_L3：
curl -q -sS --noproxy '*' --interface 'if!WAN_L3' --ipv4 \
  --connect-timeout 4 --max-time 8 -I http://192.168.1.1/
```

上述 IP 仅用于展示用法，测试时请替换成你所在校园网的实际认证网关地址。真正的请求不应使用公共 IP 测试，因为可能对未授权网站发起多余请求。
