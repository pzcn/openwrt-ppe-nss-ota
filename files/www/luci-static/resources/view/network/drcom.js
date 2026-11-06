'use strict';
'require view';
'require rpc';
'require ui';

const getConfig = rpc.declare({ object: 'luci.drcom', method: 'get_config', expect: {} });
const getStatus = rpc.declare({ object: 'luci.drcom', method: 'get_status', expect: {} });
const login = rpc.declare({
	object: 'luci.drcom', method: 'login',
	params: [ 'username', 'password', 'remember', 'login_url', 'logout_url' ],
	expect: {}
});
const logout = rpc.declare({ object: 'luci.drcom', method: 'logout', expect: {} });
const forget = rpc.declare({ object: 'luci.drcom', method: 'forget', expect: {} });
const saveUrls = rpc.declare({
	object: 'luci.drcom', method: 'save_urls',
	params: [ 'login_url', 'logout_url' ], expect: {}
});
const setAuto = rpc.declare({
	object: 'luci.drcom', method: 'set_auto',
	params: [ 'enabled' ], expect: {}
});

return view.extend({
	handleSave: null,
	handleSaveApply: null,
	handleReset: null,
	_busy: false,
	_nodes: null,

	load: function() {
		return Promise.all([
			L.resolveDefault(getConfig(), {}),
			L.resolveDefault(getStatus(), { ok: false, state: 'unreachable', message: '无法获取网关状态' })
		]);
	},

	n: function(name) {
		return this._nodes && this._nodes[name];
	},

	put: function(name, text) {
		var node = this.n(name);
		if (node)
			node.textContent = text;
	},

	busy: function(flag) {
		this._busy = flag;
		[ 'loginBtn', 'logoutBtn', 'refreshBtn', 'forgetBtn', 'autoBtn', 'urlsBtn' ].forEach(L.bind(function(name) {
			var node = this.n(name);
			if (node)
				node.disabled = flag;
		}, this));
	},

	show: function(result, context) {
		var state = result && result.state || 'unknown';
		var valid = !!(result && result.ok);
		var indicator = this.n('indicator');
		var legend = this.n('legend');
		var caption = this.n('response');
		var map = {
			online: ['已认证', 'online'],
			offline: ['未认证', 'offline'],
			unreachable: ['无法连接', 'error'],
			unknown: ['状态待确认', 'unknown']
		};
		var item = map[state] || map.unknown;
		if (!valid && state !== 'offline')
			item = ['请求失败', 'error'];
		if (indicator)
			indicator.className = 'dr-status-dot dr-status-' + item[1];
		if (legend)
			legend.textContent = item[0];
		if (caption)
			caption.textContent = (context ? context + ' · ' : '') +
				(result && result.message || '尚未获得认证服务器的有效响应');
	},

	syncConfig: function() {
		return getConfig().then(L.bind(function(c) {
			if (!this._nodes)
				return;
			this._nodes.account.value = c.username || '';
			this._nodes.remember.checked = !!c.remember;
			this._nodes.loginUrl.value = c.login_url || 'http://gate.lnu.edu.cn/0.htm';
			this._nodes.logoutUrl.value = c.logout_url || 'http://gate.lnu.edu.cn/F.htm';
			this._nodes.auto.checked = !!c.auto;
			this._nodes.hasSaved = !!c.has_password;
			this.put('autoState', c.auto ? '已开启 · 每天 00:00' : '未开启 · 手动认证');
			this.put('saved', c.has_password
				? '密码已保存在路由器内（此处不会回显）；留空可使用已保存密码'
				: '尚未保存密码；勾选“记住账号密码”并登录后才会保存');
		}, this));
	},

	refresh: function() {
		if (this._busy)
			return Promise.resolve();
		this.busy(true);
		this.put('activity', '正在联系校园网门户…');
		return getStatus().then(L.bind(function(data) {
			this.show(data, '状态检查');
		}, this)).catch(L.bind(function() {
			this.show({ ok: false, state: 'unreachable', message: '状态检查失败' });
		}, this)).finally(L.bind(function() {
			this.busy(false);
			this.put('activity', '仅使用 WAN 出口访问认证服务器；不经 WireGuard。域名解析也需通过 WAN DNS 校验。');
		}, this));
	},

	doLogin: function() {
		if (this._busy)
			return Promise.resolve();
		var u = this.n('account').value.trim();
		var p = this.n('password').value;
		var r = this.n('remember').checked;
		var loginUrl = this.n('loginUrl').value.trim();
		var logoutUrl = this.n('logoutUrl').value.trim();
		if (!u || (!p && !this._nodes.hasSaved)) {
			ui.addNotification(null, E('p', '请填写账号和密码。'), 'warning');
			return Promise.resolve();
		}
		this.busy(true);
		this.put('activity', '正在发送 Dr.COM 认证请求…');
		return login(u, p, r, loginUrl, logoutUrl).then(L.bind(function(data) {
			this.show(data, '登录请求');
			this.n('password').value = '';
			return this.syncConfig();
		}, this)).catch(L.bind(function() {
			this.show({ ok: false, state: 'unknown', message: '认证服务暂时不可用' }, '登录');
		}, this)).finally(L.bind(function() {
			this.busy(false);
			this.put('activity', '请求强制走 WAN，不走 WireGuard；如果 WAN DNS 不可用，请使用校园网网关 IP。');
		}, this));
	},

	doLogout: function() {
		if (this._busy)
			return Promise.resolve();
		this.busy(true);
		this.put('activity', '正在向门户发送注销请求…');
		return logout().then(L.bind(function(data) {
			this.show(data, '注销请求');
		}, this)).catch(L.bind(function() {
			this.show({ ok: false, state: 'unknown', message: '无法连接注销接口' });
		}, this)).finally(L.bind(function() {
			this.busy(false);
			this.put('activity', '已向设置的注销地址发送请求；本日不会立即自动重连，下次计划执行是 00:00');
		}, this));
	},

	doSaveUrls: function() {
		if (this._busy)
			return Promise.resolve();
		var loginUrl = this.n('loginUrl').value.trim();
		var logoutUrl = this.n('logoutUrl').value.trim();
		if (!loginUrl || !logoutUrl) {
			ui.addNotification(null, E('p', '请填写完整的登录和注销 URL。'), 'warning');
			return Promise.resolve();
		}
		this.busy(true);
		return saveUrls(loginUrl, logoutUrl).then(L.bind(function(result) {
			ui.addNotification(null, E('p', result.message || '操作完成'), result.ok ? 'info' : 'error');
			if (result.ok)
				return this.syncConfig();
		}, this)).catch(function() {
			ui.addNotification(null, E('p', '无法保存认证地址'), 'error');
		}).finally(L.bind(function() {
			this.busy(false);
		}, this));
	},

	doSaveAuto: function() {
		if (this._busy)
			return Promise.resolve();
		var wanted = this.n('auto').checked;
		this.busy(true);
		return setAuto(wanted).then(L.bind(function(result) {
			ui.addNotification(null, E('p', result.message || '保存结果未知'), result.ok ? 'info' : 'error');
			return this.syncConfig();
		}, this)).catch(L.bind(function() {
			ui.addNotification(null, E('p', '保存每日自动认证设置失败'), 'error');
			return this.syncConfig();
		}, this)).finally(L.bind(function() {
			this.busy(false);
		}, this));
	},

	doForget: function() {
		if (this._busy)
			return Promise.resolve();
		if (!window.confirm('确定清除路由器保存的校园网账号和密码？这不会注销当前连接。'))
			return Promise.resolve();
		this.busy(true);
		return forget().then(L.bind(function(result) {
			if (result.ok) {
				this._nodes.hasSaved = false;
				this.n('password').value = '';
				this.n('account').value = '';
				this.n('remember').checked = false;
				this.n('auto').checked = false;
				this.put('autoState', '未开启 · 手动认证');
				this.put('saved', '已清除保存在路由器上的账号密码');
			}
			ui.addNotification(null, E('p', result.message || '操作完成'), result.ok ? 'info' : 'error');
		}, this)).catch(function() {
			ui.addNotification(null, E('p', '清除凭据失败'), 'error');
		}).finally(L.bind(function() { this.busy(false); }, this));
	},

	render: function(data) {
		var config = data[0] || {};
		var status = data[1] || {};
		this._nodes = { hasSaved: !!config.has_password };

		var account = E('input', {
			'class': 'dr-input',
			'type': 'text',
			'autocomplete': 'username',
			'placeholder': '请输入学号或校园网账号',
			'value': config.username || '',
			'maxlength': '128'
		});
		var password = E('input', {
			'class': 'dr-input',
			'type': 'password',
			'autocomplete': 'off',
			'placeholder': config.has_password ? '已保存密码，留空直接使用' : '请输入校园网密码',
			'maxlength': '256'
		});
		var remember = E('input', { 'type': 'checkbox', 'checked': !!config.remember });
		var loginUrl = E('input', {
			'class': 'dr-input',
			'type': 'url',
			'value': config.login_url || 'http://gate.lnu.edu.cn/0.htm',
			'placeholder': 'http://认证服务器IP/0.htm',
			'maxlength': '512'
		});
		var logoutUrl = E('input', {
			'class': 'dr-input',
			'type': 'url',
			'value': config.logout_url || 'http://gate.lnu.edu.cn/F.htm',
			'placeholder': 'http://认证服务器IP/F.htm',
			'maxlength': '512'
		});
		var auto = E('input', { 'type': 'checkbox', 'checked': !!config.auto });

		var loginBtn = E('button', {
			'class': 'dr-button dr-button-primary',
			'type': 'button',
			'click': L.bind(this.doLogin, this)
		}, [E('span', { 'class': 'dr-btn-icon' }, '↗'), '连接校园网']);
		var logoutBtn = E('button', {
			'class': 'dr-button dr-button-muted',
			'type': 'button',
			'click': L.bind(this.doLogout, this)
		}, '注销认证');
		var refreshBtn = E('button', {
			'class': 'dr-button dr-button-text',
			'type': 'button',
			'click': L.bind(this.refresh, this)
		}, '↻  检查状态');
		var urlsBtn = E('button', {
			'class': 'dr-button dr-button-muted dr-urls-save',
			'type': 'button',
			'click': L.bind(this.doSaveUrls, this)
		}, '保存认证地址');
		var autoBtn = E('button', {
			'class': 'dr-button dr-button-primary dr-auto-save',
			'type': 'button',
			'click': L.bind(this.doSaveAuto, this)
		}, '保存自动认证设置');
		var forgetBtn = E('button', {
			'class': 'dr-forget',
			'type': 'button',
			'click': L.bind(this.doForget, this)
		}, '清除已保存的账号密码');

		var indicator = E('span', { 'class': 'dr-status-dot dr-status-unknown' });
		var legend = E('strong', { 'class': 'dr-status-value' }, '检测中');
		var response = E('span', { 'class': 'dr-status-message' }, '正在读取门户状态');

		this._nodes.account = account;
		this._nodes.password = password;
		this._nodes.remember = remember;
		this._nodes.loginUrl = loginUrl;
		this._nodes.logoutUrl = logoutUrl;
		this._nodes.auto = auto;
		this._nodes.autoBtn = autoBtn;
		this._nodes.urlsBtn = urlsBtn;
		this._nodes.loginBtn = loginBtn;
		this._nodes.logoutBtn = logoutBtn;
		this._nodes.refreshBtn = refreshBtn;
		this._nodes.forgetBtn = forgetBtn;
		this._nodes.indicator = indicator;
		this._nodes.legend = legend;
		this._nodes.response = response;

		var saved = E('p', { 'class': 'dr-saved' },
			config.has_password ? '已记住密码；留空可直接使用' : '尚未保存密码');
		this._nodes.saved = saved;
		var autoState = E('span', { 'class': 'dr-auto-state-label' },
			config.auto ? '已开启 · 每天 00:00' : '未开启 · 手动认证');
		this._nodes.autoState = autoState;

		var activity = E('div', { 'class': 'dr-activity' },
			'请求由路由器执行；校园网将识别路由器出口 IP');
		this._nodes.activity = activity;

		var root = E('div', { 'class': 'dr-campus-root' }, [
			E('link', { 'rel': 'stylesheet', 'href': L.resource('drcom-campus.css') }),
			E('section', { 'class': 'dr-header' }, [
				E('div', { 'class': 'dr-topline' }, [
					E('span', { 'class': 'dr-sign' }, '◈'),
					E('span', { 'class': 'dr-wordmark' }, 'DR.COM'),
					E('span', { 'class': 'dr-top-sep' }),
					E('span', { 'class': 'dr-campus-tag' }, 'WAN-ONLY · DR.COM WEB PORTAL')
				]),
				E('div', { 'class': 'dr-header-body' }, [
					E('div', {}, [
						E('div', { 'class': 'dr-kicker' }, 'CAMPUS NETWORK ACCESS'),
						E('h2', { 'class': 'dr-title' }, [
							'校园网络', E('span', '认证中心')
						]),
						E('p', { 'class': 'dr-intro' }, '为京东云亚瑟设计的 Dr.COM 认证工具。自定义服务器地址，所有请求只走 WAN、不走 WireGuard；支持每天 00:00 自动认证。')
					]),
					E('div', { 'class': 'dr-orbit', 'aria-hidden': 'true' }, [
						E('span', { 'class': 'dr-orbit-inner' }, 'LNU'),
						E('span', { 'class': 'dr-orbit-node' })
					])
				])
			]),
			E('div', { 'class': 'dr-content' }, [
				E('div', { 'class': 'dr-layout' }, [
					E('section', { 'class': 'dr-panel dr-form' }, [
						E('div', { 'class': 'dr-section-eyebrow' }, 'ACCOUNT · 账号信息'),
						E('h3', { 'class': 'dr-panel-title' }, '登录校园网'),
						E('p', { 'class': 'dr-panel-subtitle' }, '使用学校分配的校园网账号进行认证。'),
						E('label', { 'class': 'dr-field' }, [
							E('span', '校园网账号'), account
						]),
						E('label', { 'class': 'dr-field' }, [
							E('span', '登录密码'), password
						]),
						E('label', { 'class': 'dr-remember' }, [
							remember,
							E('span', {}, [
								E('strong', '记住账号与密码'),
								E('small', '仅在勾选时保存到路由器，使用 root 权限保护')
							])
						]),
						saved,
						E('div', { 'class': 'dr-actions' }, [loginBtn, logoutBtn]),
						E('div', { 'class': 'dr-divider' }),
						E('details', { 'class': 'dr-advanced' }, [
							E('summary', '高级选项 · 自定义完整认证地址'),
							E('label', { 'class': 'dr-field' }, [
								E('span', '登录 URL（POST 到此地址）'), loginUrl
							]),
							E('label', { 'class': 'dr-field' }, [
								E('span', '注销 URL（GET 到此地址）'), logoutUrl
							]),
							E('p', '支持完整 HTTP/HTTPS 地址。所有请求固定 WAN；域名通过 WAN DNS 解析，如果无法确定 DNS 也走 WAN，请直接填写网关 IP。'),
							E('div', { 'class': 'dr-urls-actions' }, urlsBtn)
						]),
						E('div', { 'class': 'dr-auto-section' }, [
							E('div', { 'class': 'dr-section-eyebrow' }, 'AUTOMATION · 每日自动认证'),
							E('label', { 'class': 'dr-remember dr-auto-switch' }, [
								auto,
								E('span', {}, [
									E('strong', '每天 00:00 自动认证一次'),
									E('small', '按路由器系统本地时间执行；开启前必须记住账号与密码')
								])
							]),
							E('div', { 'class': 'dr-auto-state' }, autoState),
							autoBtn
						]),
						E('div', { 'class': 'dr-forget-wrap' }, forgetBtn)
					]),
					E('aside', { 'class': 'dr-side' }, [
						E('section', { 'class': 'dr-panel dr-status-panel' }, [
							E('div', { 'class': 'dr-section-eyebrow' }, 'NETWORK STATUS · 连接状态'),
							E('div', { 'class': 'dr-status-line' }, [indicator, legend]),
							response,
							E('div', { 'class': 'dr-status-rule' }),
							refreshBtn,
							activity
						]),
						E('section', { 'class': 'dr-panel dr-guide' }, [
							E('div', { 'class': 'dr-section-eyebrow' }, 'CONNECTION DETAILS'),
							E('h3', '认证流程'),
							E('div', { 'class': 'dr-step' }, [
								E('span', '01'), E('div', {}, [
									E('b', '发送认证请求'), E('p', '向你设置的完整登录 URL 提交 DDDDD、upass 和 0MKKey 参数。')
								])
							]),
							E('div', { 'class': 'dr-step' }, [
								E('span', '02'), E('div', {}, [
									E('b', '确认认证状态'), E('p', '分析门户响应。不能仅以 HTTP 200 判断登录成功。')
								])
							]),
							E('div', { 'class': 'dr-step' }, [
								E('span', '03'), E('div', {}, [
									E('b', '按需安全注销'), E('p', '通过注销接口断开认证，已保存的凭据不会随之清除。')
								])
							])
						]),
						E('div', { 'class': 'dr-security' }, [
							E('span', 'i'),
							E('span', '学校门户使用 HTTP 时，账号密码在校园链路上明文传输。请勿在不可信网络使用；建议为路由器管理页面启用 HTTPS。')
						])
					])
				])
			]),
			E('div', { 'class': 'dr-footer' }, [
				E('span', 'DR.COM  ·  CAMPUS AUTHENTICATION'),
				E('span', '00:00 SCHEDULE · OPENWRT · PZCN CUSTOM')
			])
		]);
		this.show(status, '当前网关');
		return root;
	}
});
