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
const saveCredentials = rpc.declare({
	object: 'luci.drcom', method: 'save_credentials',
	params: [ 'login_url', 'logout_url', 'username', 'password' ], expect: {}, reject: true
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
		[ 'saveConfig', 'login', 'logout', 'refresh', 'forget', 'setAuto' ].forEach(L.bind(function(key) {
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

	applyConfig: function(c) {
		if (!c || typeof c !== 'object' || c.error)
			throw new Error(c && c.error || '获取校园网配置失败');
		this.n('portalUrl').value = normalizePortalAddress(c.login_url);
		this.n('username').value = c.username || '';
		this.n('password').value = '';
		this.n('password').placeholder = c.has_password
			? '••••••••（已保存）' : '校园网密码';
		this.n('auto').checked = !!c.auto;
		this._nodes.hasSaved = !!c.has_password;
		this._nodes.savedUsername = c.username || '';
		this.setText('saved', c.has_password
			? '密码已保存，留空可继续使用。HTTP 认证会明文传输密码。'
			: '填写密码并保存，刷新后以掩码显示。HTTP 认证会明文传输密码。');
		this.setText('autoStatus', c.auto ? '已启用，每天 00:00 执行' : '未启用');
		return c;
	},

	syncConfig: function() {
		return getConfig().then(L.bind(this.applyConfig, this));
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

	doSaveConfig: function() {
		if (this._busy)
			return Promise.resolve();
		var target = this.validateAddresses();
		if (!target)
			return Promise.resolve();

		var user = this.n('username').value.trim();
		var secret = this.n('password').value;
		if (!user || (!secret && !(this._nodes.hasSaved && user === this._nodes.savedUsername))) {
			this.notify('请输入用户名和密码；已保存密码且用户名不变时可以留空密码。', false);
			return Promise.resolve();
		}

		this.setBusy(true);
		return saveCredentials(target.login, target.logout, user, secret)
			.then(L.bind(function(result) {
				if (!result || typeof result !== 'object')
					throw new Error('RPC 未返回有效结果，请检查 luci.drcom 服务');
				if (result.ok !== true)
					throw new Error((result.message || '后端拒绝保存') +
						(result.code ? '（' + result.code + '）' : ''));
				if (result.backend_revision !== 'drcom-rpc12')
					throw new Error('浏览器页面和 rpcd 后端版本不一致，请刷新 LuCI');
				if (result.login_url !== target.login || result.logout_url !== target.logout ||
					result.username !== user || result.has_password !== true)
					throw new Error('后端返回的认证信息与输入不一致');

				return getConfig().then(L.bind(function(c) {
					if (!c || c.error)
						throw new Error(c && c.error || '无法读取已保存的配置');
					if (c.backend_revision !== 'drcom-rpc12')
						throw new Error('rpcd 后端版本不匹配，请重启 rpcd');
					if (c.login_url !== target.login || c.logout_url !== target.logout ||
						c.username !== user || !c.has_password || !c.remember)
						throw new Error('认证信息读回结果不一致，请检查配置持久化');
					this.applyConfig(c);
					this.notify('认证地址、用户名和密码已保存', true);
				}, this));
			}, this))
			.catch(L.bind(function(e) {
				this.notify('认证信息保存失败：' + (e.message || e), false);
			}, this))
			.finally(L.bind(function() { this.setBusy(false); }, this));
	},

	doLogin: function() {
		if (this._busy)
			return Promise.resolve();
		var urls = this.validateAddresses();
		if (!urls)
			return Promise.resolve();
		var user = this.n('username').value.trim();
		var secret = this.n('password').value;
		if (!user || (!secret && !(this._nodes.hasSaved && user === this._nodes.savedUsername))) {
			this.notify('请输入账号和密码。', false);
			return Promise.resolve();
		}

		this.setBusy(true);
		this.setText('response', '正在通过 WAN 发起认证…');
		return login(user, secret, true, urls.login, urls.logout).then(L.bind(function(result) {
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
		var n = this._nodes = {
			hasSaved: !!config.has_password,
			savedUsername: config.username || ''
		};
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
			'value': '', 'placeholder': config.has_password ? '••••••••（已保存）' : '校园网密码',
			'maxlength': 256, 'autocomplete': 'off'
		});
		n.auto = E('input', { 'id': 'drcom-auto', 'type': 'checkbox',
			'class': 'cbi-input-checkbox', 'checked': !!config.auto });
		n.connection = E('strong', '读取中');
		n.response = E('span', '正在读取状态…');
		n.saved = E('span', config.has_password
			? '密码已保存，留空可继续使用。HTTP 认证会明文传输密码。'
			: '填写密码并保存，刷新后以掩码显示。HTTP 认证会明文传输密码。');
		n.autoStatus = E('span', config.auto ? '已启用，每天 00:00 执行' : '未启用');

		n.saveConfig = button('保存认证信息', L.bind(this.doSaveConfig, this), 'cbi-button-apply');
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
					'填写认证地址、用户名和密码后点击保存；登录与注销接口自动使用 /0.htm 和 /F.htm。'),
				field('认证地址', n.portalUrl),
				field('用户名', n.username),
				field('密码', n.password, n.saved),
				E('div', { 'class': 'cbi-page-actions' }, [
					n.saveConfig, n.forget, n.logout, n.login
				])
			]),
			E('div', { 'class': 'cbi-section' }, [
				E('h3', '自动认证'),
				E('div', { 'class': 'cbi-section-descr' },
					'保存认证信息后，可设置每天 00:00 自动认证。按路由器本地时间执行。'),
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
