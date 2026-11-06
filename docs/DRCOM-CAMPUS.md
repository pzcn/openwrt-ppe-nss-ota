# Dr.COM 校园网认证

入口：**网络 → 校园网认证**

支持自定义认证服务器、账号密码登录、注销、记住凭据以及每天零点自动认证。界面使用 LuCI 原生组件。

## 使用

1. 填写完整的**登录 URL**和**注销 URL**，点击「保存认证地址」。
2. 输入账号密码，点击「连接校园网」。按需勾选「记住账号密码」。
3. 如需定时登录，勾选「每天 00:00 自动认证一次」，点击保存。
4. 使用「注销认证」退出当前认证，使用「清除已保存的账号密码」管理凭据。

新安装的 URL 输入框为空，由用户自行配置。登录与注销地址可以使用域名或 IPv4、端口、路径与查询参数。

**地址格式示例：**

| 项目 | 示例 |
| --- | --- |
| 登录 URL | `http://192.168.1.1/0.htm` |
| 注销 URL | `http://192.168.1.1/F.htm` |

示例地址需替换为校园网实际接口；Dr.COM 门户的注销路径可能因部署而异。

## 认证方式

登录由路由器发起，向填写的 URL 提交以下表单：

```text
DDDDD=<账号>
upass=<密码>
0MKKey=
```

账号密码由 `curl --data-urlencode` 进行 URL 编码。状态检查、登录、注销及定时认证统一使用 WAN 出口设备。域名会优先使用 WAN DNS，并通过 `curl --resolve` 固定解析结果。

## 自动认证

使用 OpenWrt cron，每天路由器本地时间 **00:00** 执行一次，开启前需保存账号密码：

```cron
0 0 * * * /usr/libexec/drcom-web auto >/dev/null 2>&1 # drcom-campus-auto
```

北京时间请设置时区为 `Asia/Shanghai`。关闭记住密码或清除凭据时，自动认证开关同步关闭。

## 配置与排查

```sh
uci -q get drcom.main.login_url
uci -q get drcom.main.logout_url
ubus call luci.drcom get_config
ubus call luci.drcom get_status
logread -e rpcd | tail -n 30
```

地址保存使用 UCI 提交及两次读取校验。遇到保存错误，可根据界面显示的错误码检查配置与 `rpcd`。

**凭据说明：** HTTP 认证会明文传输密码；记住密码后，配置文件 `/etc/config/drcom` 权限为 `0600`，配置备份也可能包含密码。使用时建议从 HTTPS LuCI 管理页面访问。

## 组件

- `files/www/luci-static/resources/view/network/drcom-native.js`：LuCI 页面
- `files/usr/share/rpcd/ucode/luci.drcom`：UCI 与认证 RPC
- `files/usr/libexec/drcom-web`：curl 请求
- `files/usr/libexec/drcom-schedule`：每日定时任务
- `files/etc/config/drcom`：认证设置
- `scripts/tests/test-drcom.py`：模拟认证测试
- `scripts/tests/test-drcom-rpc.js`：地址保存测试
