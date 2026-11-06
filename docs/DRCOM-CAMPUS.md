# Dr.COM 校园网认证（LuCI 原生界面）

固件内置菜单：**网络 → 校园网认证**。登录、注销和 00:00 自动认证继续通过路由器 WAN 进行，不改 WireGuard、PBR、默认路由、防火墙或 PPE/NSS 驱动。

## 本次原生 UI 和地址持久化改进

- 前端使用 LuCI 内置的 `cbi-map`、`cbi-section`、`cbi-value`、`table` 和 `cbi-button`，自动跟随当前系统主题，不加载任何自定义深色 CSS。
- **全新安装的登录 URL 和注销 URL 都为空**；需要用户主动输入完整的 `http://...` / `https://...` URL。没有内置辽宁大学域名、旧地址回退或猜测网关 IP。
- **保存确认机制：** `save_urls` 首先调用 `uci.set` + `uci.commit('drcom')`，然后新建第二个 UCI cursor 从配置中重新读取并逐项比对；只有真实保存成功才返回带实际持久化 URL 的 `ok:true`。
- 前端收到保存结果后还会独立调用 `get_config` 再对比一次。如果地址和输入不一致，显示错误并保留表单输入，不会把旧地址悄悄覆盖回去。
- 为防止 LuCI 的旧 JavaScript 文件继续从浏览器缓存加载，页面改为独立资源 `view/network/drcom-native.js`，菜单路径自动指向新页面。
- **保留已有配置**：正常 sysupgrade 保留用户主动保存的 URL、密码和自动认证设置。仅当旧配置的登录/注销 URL **恰好等于此前固件硬编码的两条辽宁大学地址**，且没有保存账号、密码并且未启用自动认证时，首次启动会清理这两个旧默认值。真实的自定义地址和已保存凭据不会被清除。旧配置仅包含 `server`/`logout_path` 时不会再自动回退到学校地址，需要在新页面明确保存一次完整 URL。

## 配置方法

在 LuCI 页面首先填写并保存两个地址：

| 字段 | 示例格式（不是实际网关） | 使用方式 |
| --- | --- | --- |
| 登录 URL | `http://192.168.1.1/0.htm` | POST `DDDDD=账号&upass=密码&0MKKey=`，其中账号和密码使用 URL 编码 |
| 注销 URL | `http://192.168.1.1/F.htm` | GET 指定注销接口 |

`/F.htm` 是常见 Dr.COM 实现，但学校实际网关可能使用不同的注销接口，须在校园网内确认。若仅填写其中一个 URL，系统会提示补齐再保存。

填写账号、密码，可以勾选 **记住账号密码**，然后点击 **连接校园网**。取消勾选则不会持久化凭据，同时禁用每日自动认证。可以单独点击 **清除已保存的账号密码**，不会自动注销。

## 每天 00:00 自动认证

只有在保存了账号和密码后才允许启用。开启后，由 OpenWrt 的 `cron` 在路由器**本地时间**每天 00:00 执行一次：

```cron
0 0 * * * /usr/libexec/drcom-web auto >/dev/null 2>&1 # drcom-campus-auto
```

自动认证默认关闭；取消记住密码或清除凭据时会自动关闭。停电错过零点不会补跑。需要北京时间执行时，请将路由器时区设置为 Asia/Shanghai。

## 固定走 WAN，禁止 WireGuard 回退

所有请求通过 `ubus call network.interface.wan status` 读取实际的 `l3_device`，并设置 curl `--interface "if!$WAN_DEVICE" --ipv4 --noproxy '*'`，WAN 不可用或实际上是隧道接口则拒绝请求。

curl 的 `--interface` 不约束 DNS，且本固件的 curl 不带 c-ares，所以对域名 URL 的 DNS 查询另行处理：只使用 WAN 通告的 IPv4 DNS，并检查路由走 WAN 后，将解析结果通过 `curl --resolve` 固定给认证请求。如有复杂 OUTPUT PBR 规则，无法仅凭 `ip route get` 保证 `nslookup` 不被重定向；要完全避免 DNS 穿过 WireGuard，**直接填写网关 IPv4 URL**。

## 安全

- 若学校只提供 HTTP，校园网链路上的账号和密码仍以明文传输。管理路由器时建议使用 LuCI HTTPS。
- 记住密码会以 `0600` 权限保存至 `/etc/config/drcom`，并可能进入正常的 sysupgrade 配置备份。不要公开分享备份。
- RPC 的 `get_config` 仅回传用户名和有无保存密码，不返回实际密码。curl 从私有临时文件的标准输入获得一次性账号密码，不放在进程命令行或日志。
- 状态识别采用门户返回值。HTTP 200 不等于认证成功；未识别的响应显示未确认。
- 尚未使用辽宁大学真实账号在校园网内验证该门户的成功标记及注销接口。

## 2026-11-06：修复“保存结果与填写的地址不一致”

之前的 LuCI RPC 调用没有开启 `reject:true`，若 ubus 返回权限错误、方法不存在或 ucode 后端异常，浏览器可能收到非对象结果（例如数字状态码），却将其误报为“保存结果与填写的地址不一致”。这条提示本身不能证明 UCI 地址不一致。

现在：

- 在 LuCI RPC 中明确启用 `reject:true`，真实 ubus 错误不再变成一个无意义的地址不匹配提示。
- 后端 `save_urls` 直接依次执行 `uci.load`、`uci.set`、`uci.commit` 和新游标读回验证；异常和错误按阶段返回 `uci_load`、`uci_set`、`uci_commit`、`chmod`、`uci_reload`、`uci_mismatch`、`backend_exception`，而不是只返回布尔值。
- 后端 `get_config` 与 `save_urls` 返回 `backend_revision=drcom-rpc9`，前端检测到旧版本时会提示重启 rpcd，而不是判断地址不一致。
- 为避免不同版本的 ucode 对双变量 `for-in` 遍历产生歧义，通用 UCI 保存方法改为遍历 `keys(changes)`；URL 保存方法则使用独立的显式 `uci.set`。
- GitHub Actions 增加 mock UCI 的 RPC 保存逻辑测试，覆盖保存成功、地址更换、无效地址、UCI 加载/设置/提交失败和权限失败。

修复后如果依然提示失败，建议**保留新提示中的错误码**，然后检查：

```sh
ubus -v list luci.drcom
ubus call luci.drcom get_config
logread -e rpcd | tail -n 30
uci -q get drcom.main.login_url
uci -q get drcom.main.logout_url
```

这里不会输出已保存的密码（不要运行 `uci show drcom` 或公开备份），可以用来区分 RPC 未注册、配置文件写入错误与覆盖层持久化异常。

## 排查“保存后刷新又变成旧地址”

先在网页点击 **保存认证地址**，确认出现“已保存并验证”后刷新。若提示失败，先看是否使用新的 `drcom-native.js` 页面并尝试浏览器强制刷新。再在 SSH 中查看：

```sh
uci -q get drcom.main.login_url
uci -q get drcom.main.logout_url
ubus call luci.drcom get_config
stat -c '%a %n' /etc/config/drcom
mount | grep ' on /overlay '
```

正常情况下这两条 UCI 地址与 `get_config` 返回一致。如果保存后路由器重启才丢配置，还需检查 `/overlay` 是否持久化（与之前的 F2FS 配置分区问题有关），不能单靠前端解决。

## 主要文件

- `files/www/luci-static/resources/view/network/drcom-native.js`：LuCI 原生表单与保存后两次读回确认
- `files/usr/share/rpcd/ucode/luci.drcom`：UCI 持久化、只读配置返回、手动/自动认证 RPC
- `files/usr/libexec/drcom-web`：通过 WAN 的 curl 请求；没有任何硬编码校园网域名
- `files/etc/config/drcom`：空的登录/注销 URL 及关闭的自动认证开关
- `files/etc/uci-defaults/98-drcom-clear-unused-legacy-url`：仅在没有用户凭据时清理旧固件预置的辽宁大学地址
- `files/usr/libexec/drcom-schedule`：每天零点 cron 管理
- `scripts/tests/test-drcom.py`：不联网的本地模拟网关测试
- `scripts/tests/test-luci-native.py`：原生页面和地址持久化检查
