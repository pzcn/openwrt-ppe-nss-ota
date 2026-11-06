# Dr.COM 校园网认证

入口：**网络 → 校园网认证**

支持自定义认证服务器、账号密码持久保存、登录、注销以及每天零点自动认证。界面使用 LuCI 原生组件。

## 使用

1. 在同一张卡片中填写**认证地址**（例如 `http://192.168.1.1`）、**用户名**和**密码**，点击「保存认证信息」。无需先登录。
2. 点击「连接校园网」即可使用保存的凭据认证。刷新后用户名会保留，密码框显示已保存的掩码；RPC 仅返回密码已保存标记，浏览器不读取实际密码。
3. 如需定时登录，勾选「每天零点认证」，点击「保存自动认证设置」。
4. 使用「注销认证」退出当前认证，使用「清除已保存的账号密码」管理凭据。

新安装的认证地址输入框为空，由用户自行配置。支持域名、IPv4、端口及目录。系统自动使用 `/0.htm` 登录、`/F.htm` 注销。

**地址格式示例：**

| 项目 | 示例 |
| --- | --- |
| 认证地址 | `http://192.168.1.1` |
| 自动生成的登录 URL | `http://192.168.1.1/0.htm` |
| 自动生成的注销 URL | `http://192.168.1.1/F.htm` |

示例地址需替换为校园网实际网关地址。

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

北京时间请设置时区为 `Asia/Shanghai`。清除已保存凭据时，自动认证开关同步关闭。

## 配置与排查

```sh
uci -q get drcom.main.login_url
uci -q get drcom.main.logout_url
ubus call luci.drcom get_config
ubus call luci.drcom get_status
logread -e rpcd | tail -n 30
```

认证地址与用户名、密码使用一次 UCI 提交并重新读取校验。地址保存和账号认证都可以独立操作。更改网关地址或其他设置而不改变用户名时，密码框留空即保留原密码；修改用户名时需要输入密码。

**凭据说明：** HTTP 认证会明文传输密码；保存后密码保存在权限为 `0600` 的 `/etc/config/drcom` 中，配置备份也可能包含密码。密码框中的圆点仅是已保存状态的提示，并非浏览器读回的密码。建议使用 HTTPS LuCI 管理页面。

## 组件

- `files/www/luci-static/resources/view/network/drcom-native.js`：LuCI 页面
- `files/usr/share/rpcd/ucode/luci.drcom`：UCI 与认证 RPC
- `files/usr/libexec/drcom-web`：curl 请求
- `files/usr/libexec/drcom-schedule`：每日定时任务
- `files/etc/config/drcom`：认证设置
- `scripts/tests/test-drcom.py`：模拟认证测试
- `scripts/tests/test-drcom-rpc.js`：地址保存测试
