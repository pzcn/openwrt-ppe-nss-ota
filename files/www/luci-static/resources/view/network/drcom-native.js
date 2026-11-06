'use strict';
'require view';
'require rpc';
'require ui';

const getConfig = rpc.declare({ object: 'luci.drcom', method: 'get_config', expect: {}, reject: true });
const getStatus = rpc.declare({ object: 'luci.drcom', method: 'get_status', expect: {}, reject: true });
const login = rpc.declare({
	object: 'luci.drcom', method: 'login',
	params: [ 'username', 'password', 'remember', 'login_url', 'logout_url' ], expect: {}, reject: true
});
const logout = rpc.declare({ object: 'luci.drcom', method: 'logout', expect: {}, reject: true });
const forget = rpc.declare({ object: 'luci.drcom', method: 'forget', expect: {}, reject: true });
const saveUrls = rpc.declare({
	object: 'luci.drcom', method: 'save_urls',
	params: [ 'login_url', 'logout_url' ], expect: {}, reject: true
});
const setAuto = rpc.declare({
	object: 'luci.drcom', method: 'set_auto', params: [ 'enabled' ], expect: {}, reject: true
});

// The portal exposes /0.htm for login and /F.htm for logout.
// Keep the LuCI field on the base address; the existing RPC stores full URLs.
function normalizePortalAddress(url) {
	return (url || '').trim()
		.replace(/\/(?:0|F)\.htm(?:\?[^#]*)?$/i, '')
		.replace(/\/+$/, '');
}

function buildPortalUrls(address) {
	var base = normalizePortalAddress(address);
	return { base: base, login: base + '/0.htm', logout: base + '/F.htm' };
}

function field(label, input, help) {
	return E('div', { 'class': 'cbi-value' }, [
		E('label', { 'class': 'cbi-value-title', 'for': input.id }, label),
		E('div', { 'class': 'cbi-value-field' }, [
			input,
			help ? E('div', { 'class': 'cbi-value-description' }, help) : E([])
		])
	]);
}

function button(label, handler, cls) {
	return E('button', {
		'type': 'button', 'class': 'btn cbi-button ' + (cls || ''),
		'click': handler
	}, label);
}

return view.extend({
	handleSave: null,
	handleSaveApply: null,
	handleReset: null,
	_busy: false,
	_nodes: null,

	load: function() {
		return Promise.all([
			L.resolveDefault(getConfig(), {}),
			L.resolveDefault(getStatus(), {
				ok: false, state: 'unknown', message: '无法取得认证状态'
			})
		]);
	},

	n: function(key) {
		return this._nodes && this._nodes[key];
	},

	setText: function(key, value) {
		if (this.n(key))
			this.n(key).textContent = value;
	},

	setBusy: function(isBusy) {
		this._busy = isBusy;
		[ 'saveUrls', 'login', 'logout', 'refresh', 'forget', 'setAuto' ].forEach(L.bind(function(key) {
			if (this.n(key))
				this.n(key).disabled = isBusy;
		}, this));
	},

	notify: function(message, success) {
		ui.addNotification(null, E('p', message), success ? 'info' : 'error');
	},

	showStatus: function(result) {
		var state = result && result.state || 'unknown';
		var name = state === 'online' ? '已认证'
			: state === 'offline' ? '未认证'
			: state === 'unreachable' ? '无法连接'
			: '未确认';
		if (!result || result.ok !== true)
			name = '需要检查';
		this.setText('connection', name);
		this.setText('response', result && result.message || '尚无网关响应');
	},

	syncConfig: function() {
		return getConfig().then(L.bind(function(c) {
			if (!c || typeof c !== 'object' || c.error)
				throw new Error(c && c.error || '获取校园网配置失败');
			this.n('portalUrl').value = normalizePortalAddress(c.login_url);
			this.n('username').value = c.username || '';
			this.n('remember').checked = !!c.remember;
			this.n('auto').checked = !!c.auto;
			this._nodes.hasSaved = !!c.has_password;
			this.setText('saved', c.has_password
				? '路由器已保存此账号的密码；密码框留空可以重新认证。'
				: '没有保存密码，勾选“记住账号密码”后登录才会保存。');
			this.setText('autoStatus', c.auto ? '已启用，每天 00:00 执行' : '未启用');
			return c;
		}, this));
	},

	addresses: function() {
		return buildPortalUrls(this.n('portalUrl').value);
	},

	validateAddresses: function() {
		var urls = this.addresses();
		if (!/^https?:\/\/[A-Za-z0-9][A-Za-z0-9.-]*(?::[0-9]{1,5})?(?:\/[A-Za-z0-9._~%!$&()*+,;=:@/-]*)?$/.test(urls.base)) {
			this.notify('请填写认证地址，例如 http://192.168.1.1（可包含端口和目录）。', false);
			return null;
		}
		return urls;
	},

	doSaveUrls: function() {
		if (this._busy)
			return Promise.resolve();
		var target = this.validateAddresses();
		if (!target)
			return Promise.resolve();

		this.setBusy(true);
		return saveUrls(target.login, target.logout).then(L.bind(function(result) {
			// Distinguish RPC failures from a genuine UCI readback mismatch.
			// Older versions silently turned ubus errors into numeric replies.
			if (!result || typeof result !== 'object')
				throw new Error('RPC 未返回有效结果，请确认 luci.drcom 服务已注册并重新登录 LuCI');
			if (result.ok !== true)
				throw new Error((result.message || '后端拒绝保存') +
					(result.code ? '（' + result.code + '）' : ''));
			if (result.backend_revision !== 'drcom-rpc9')
				throw new Error('浏览器页面和 rpcd 后端版本不一致，请重启 rpcd 并刷新浏览器');
			if (result.login_url !== target.login || result.logout_url !== target.logout)
				throw new Error('后端返回的保存地址与输入不一致');
			return getConfig().then(L.bind(function(c) {
				if (!c || c.error)
					throw new Error(c && c.error || '无法读取已保存的配置');
				if (c.backend_revision !== 'drcom-rpc9')
					throw new Error('rpcd 后端版本不匹配，请重启 rpcd');
				if (c.login_url !== target.login || c.logout_url !== target.logout)
					throw new Error('UCI 再次读取的地址与输入不一致，请检查 /overlay 和 /etc/config/drcom');
						this.notify('认证地址已保存并核对成功', true);
			}, this));
		}, this)).catch(L.bind(function(e) {
				this.notify('认证地址保存失败：' + (e.message || e), false);
		}, this)).finally(L.bind(function() { this.setBusy(false); }, this));
	},

	doLogin: function() {
		if (this._busy)
			return Promise.resolve();
		var urls = this.validateAddresses();
		if (!urls)
			return Promise.resolve();
		var user = this.n('username').value.trim();
		var secret = this.n('password').value;
		var remember = this.n('remember').checked;
		if (!user || (!secret && !this._nodes.hasSaved)) {
			this.notify('请输入账号和密码。', false);
			return Promise.resolve();
		}

		this.setBusy(true);
		this.setText('response', '正在通过 WAN 发起认证…');
		return login(user, secret, remember, urls.login, urls.logout).then(L.bind(function(result) {
			this.showStatus(result);
			if (result && result.saved === true) {
				this.n('password').value = '';
				return this.syncConfig();
			}
			this.notify(result && result.message || '认证请求失败', false);
		}, this)).catch(L.bind(function(e) {
			this.notify('认证请求失败：' + (e.message || e), false);
		}, this)).finally(L.bind(function() { this.setBusy(false); }, this));
	},

	doLogout: function() {
		if (this._busy)
			return Promise.resolve();
		this.setBusy(true);
		return logout().then(L.bind(function(r) {
			this.showStatus(r);
			if (!r || r.ok !== true)
				this.notify(r && r.message || '注销请求失败', false);
		}, this)).catch(L.bind(function(e) {
			this.notify('注销失败：' + (e.message || e), false);
		}, this)).finally(L.bind(function() { this.setBusy(false); }, this));
	},

	doRefresh: function() {
		if (this._busy)
			return Promise.resolve();
		this.setBusy(true);
		return getStatus().then(L.bind(this.showStatus, this))
			.catch(L.bind(function() {
				this.showStatus({ ok: false, message: '无法读取 WAN 认证状态' });
			}, this))
			.finally(L.bind(function() { this.setBusy(false); }, this));
	},

	doAuto: function() {
		if (this._busy)
			return Promise.resolve();
		var enabled = !!this.n('auto').checked;
		this.setBusy(true);
		return setAuto(enabled).then(L.bind(function(r) {
			if (!r || r.ok !== true)
				this.notify(r && r.message || '保存自动认证设置失败', false);
			else
				this.notify(r.message || '自动认证设置已保存', true);
			return this.syncConfig();
		}, this)).catch(L.bind(function(e) {
			this.notify('自动认证设置失败：' + (e.message || e), false);
			return this.syncConfig();
		}, this)).finally(L.bind(function() { this.setBusy(false); }, this));
	},

	doForget: function() {
		if (this._busy)
			return Promise.resolve();
		if (!window.confirm('确定清除已保存的校园网账号和密码？'))
			return Promise.resolve();

		this.setBusy(true);
		return forget().then(L.bind(function(r) {
			if (r && r.ok === true) {
				this.n('password').value = '';
				return this.syncConfig().then(L.bind(function() {
					this.notify('账号密码已清除，每日自动认证也已关闭', true);
				}, this));
			}
			this.notify(r && r.message || '清除失败', false);
		}, this)).catch(L.bind(function(e) {
			this.notify('清除凭据失败：' + (e.message || e), false);
		}, this)).finally(L.bind(function() { this.setBusy(false); }, this));
	},

	render: function(data) {
		var config = data[0] || {};
		var result = data[1] || {};
		var n = this._nodes = { hasSaved: !!config.has_password };
		n.portalUrl = E('input', {
			'id': 'drcom-portal-url', 'type': 'url', 'class': 'cbi-input-text',
			'value': normalizePortalAddress(config.login_url),
			'placeholder': 'http://认证网关地址',
			'maxlength': 500, 'autocomplete': 'url'
		});
		n.username = E('input', {
			'id': 'drcom-user', 'type': 'text', 'class': 'cbi-input-text',
			'value': config.username || '', 'placeholder': '校园网账号',
			'maxlength': 128, 'autocomplete': 'username'
		});
		n.password = E('input', {
			'id': 'drcom-password', 'type': 'password', 'class': 'cbi-input-password',
			'value': '', 'placeholder': config.has_password ? '已保存密码，可留空' : '校园网密码',
			'maxlength': 256, 'autocomplete': 'off'
		});
		n.remember = E('input', { 'id': 'drcom-remember', 'type': 'checkbox',
			'class': 'cbi-input-checkbox', 'checked': !!config.remember });
		n.auto = E('input', { 'id': 'drcom-auto', 'type': 'checkbox',
			'class': 'cbi-input-checkbox', 'checked': !!config.auto });
		n.connection = E('strong', '读取中');
		n.response = E('span', '正在读取状态…');
		n.saved = E('div', { 'class': 'cbi-value-description' },
			config.has_password ? '已保存密码，留空可直接认证。' : '目前没有保存密码。');
		n.autoStatus = E('span', config.auto ? '已启用，每天 00:00 执行' : '未启用');

		n.saveUrls = button('保存认证地址', L.bind(this.doSaveUrls, this), 'cbi-button-apply');
		n.login = button('连接校园网', L.bind(this.doLogin, this), 'cbi-button-action');
		n.logout = button('注销认证', L.bind(this.doLogout, this), 'cbi-button-reset');
		n.refresh = button('检查状态', L.bind(this.doRefresh, this));
		n.forget = button('清除已保存的账号密码', L.bind(this.doForget, this), 'cbi-button-reset');
		n.setAuto = button('保存自动认证设置', L.bind(this.doAuto, this), 'cbi-button-apply');

		var root = E('div', { 'class': 'cbi-map' }, [
			E('h2', '校园网认证（Dr.COM）'),
			E('div', { 'class': 'cbi-map-descr' },
				'通过 WAN 接口进行校园网认证，支持手动登录、注销和自动认证。'),
			E('div', { 'class': 'cbi-section' }, [
				E('h3', '认证状态'),
				E('table', { 'class': 'table' }, [
					E('tr', { 'class': 'tr' }, [ E('td', { 'class': 'td left' }, '当前状态'),
						E('td', { 'class': 'td' }, n.connection) ]),
					E('tr', { 'class': 'tr' }, [ E('td', { 'class': 'td left' }, '网关返回'),
						E('td', { 'class': 'td' }, n.response) ])
				]),
				E('div', { 'class': 'cbi-page-actions' }, [n.refresh])
			]),
			E('div', { 'class': 'cbi-section' }, [
				E('h3', '账号认证'),
				E('div', { 'class': 'cbi-section-descr' },
					'只需填写网关基础地址，登录和注销接口将分别使用 /0.htm 与 /F.htm。'),
				field('认证地址', n.portalUrl),
				field('用户名', n.username),
				field('密码', n.password, 'HTTP 认证会明文传输密码。'),
				E('div', { 'class': 'cbi-value' }, [
					E('label', { 'class': 'cbi-value-title', 'for': 'drcom-remember' }, '记住账号密码'),
					E('div', { 'class': 'cbi-value-field' }, [
						n.remember, E('div', {}, n.saved)
					])
				]),
				E('div', { 'class': 'cbi-page-actions' }, [
					n.saveUrls, n.forget, n.logout, n.login
				])
			]),
			E('div', { 'class': 'cbi-section' }, [
				E('h3', '自动认证'),
				E('div', { 'class': 'cbi-section-descr' },
					'保存账号密码后，可设置每天 00:00 自动认证。按路由器本地时间执行。'),
				E('div', { 'class': 'cbi-value' }, [
					E('label', { 'class': 'cbi-value-title', 'for': 'drcom-auto' }, '每天零点认证'),
					E('div', { 'class': 'cbi-value-field' }, [ n.auto, '　', n.autoStatus ])
				]),
				E('div', { 'class': 'cbi-page-actions' }, [n.setAuto])
			]),

		]);
		this.showStatus(result);
		return root;
	}
});
