'use strict';
'require view';
'require fs';
'require ui';

function simpleRow(label, value) {
	return E('div', { 'class': 'cbi-value' }, [
		E('label', { 'class': 'cbi-value-title' }, label),
		E('div', { 'class': 'cbi-value-field' }, value)
	]);
}

return view.extend({
	load() {
		return L.resolveDefault(
			fs.exec_direct('/usr/sbin/wma301-ota', [ 'status' ], 'json'),
			{ error: 'OTA 后端暂不可用', update: false }
		);
	},

	showStatus(status) {
		this._otaStatus = status || {};
		const state = this._otaStatus, rows = [
			simpleRow('设备专属渠道', 'WMA301 v2.0 / 单 UBI'),
			simpleRow('当前构建编号', String(state.current || '—')),
			simpleRow('最新发布', state.latest || '暂未发布'),
			simpleRow('升级模式', '仅人工操作，自动升级始终关闭')
		];

		if (state.size)
			rows.push(simpleRow('固件大小', (state.size / 1048576).toFixed(1) + ' MiB'));
		if (state.error)
			rows.push(simpleRow('检查结果', E('span', { 'class': 'error' }, state.error)));
		else
			rows.push(simpleRow('检查结果', state.update ? '发现新固件' : '当前没有可用的更新'));
		if (state.update)
			rows.push(simpleRow('下载状态', state.downloaded ? '已下载，可重新校验' : '尚未下载'));

		this._otaInfo.replaceChildren(...rows);
		this._download.disabled = !state.update;
		// A separate explicit SSH/UCI opt-in is required after hardware testing.
		this._install.disabled = !(state.update && state.downloaded && state.flash_enabled);
	},

	handleRefresh() {
		this._refresh.disabled = true;
		return fs.exec_direct('/usr/sbin/wma301-ota', [ 'status' ], 'json')
			.then(L.bind(function(result) {
				this.showStatus(result);
			}, this)).catch(L.bind(function(err) {
				this.showStatus({ error: err.message || '检查失败' });
			}, this)).finally(L.bind(function() {
				this._refresh.disabled = false;
			}, this));
	},

	handleDownload() {
		this._download.disabled = true;
		ui.showModal('WMA301 OTA', [
			E('p', {}, '正在下载并核对 SHA256 与 sysupgrade -T，过程中不会刷写设备。'),
			E('div', { 'class': 'spinning' }, '下载及验证中…')
		]);
		return fs.exec('/usr/sbin/wma301-ota', [ 'download' ])
			.then(L.bind(function(res) {
				ui.hideModal();
				if (res.code !== 0)
					throw new Error(res.stderr || '下载或校验失败');
				ui.addNotification(null, E('p', {}, '固件已下载并通过 SHA256 和 sysupgrade -T 验证。'));
				return this.handleRefresh();
			}, this)).catch(L.bind(function(err) {
				ui.hideModal();
				ui.addNotification(null, E('p', {}, err.message || '下载失败'), 'error');
				return this.handleRefresh();
			}, this));
	},

	handleInstall() {
		const current = this._otaStatus || {};
		if (!(current.update && current.downloaded && current.flash_enabled))
			return;
		ui.showModal('确认手动升级 WMA301', [
			E('p', {}, '仅适用于已迁移为单 UBI 四卷布局的 WMA301 v2.0。'),
			E('p', {}, '固件将再次校验，且必须检测到 fit / ubootenv / ubootenv2 / rootfs_data。升级期间请勿断电。'),
			E('p', {}, '此功能未通过实机升级验证。确认已备份并验证恢复方式后才可执行。'),
			E('div', { 'class': 'right' }, [
				E('button', {
					'class': 'btn cbi-button-neutral',
					'click': ui.createHandlerFn(this, 'handleCancel')
				}, '取消'),
				' ',
				E('button', {
					'class': 'btn cbi-button-negative',
					'click': ui.createHandlerFn(this, 'handleInstallConfirmed')
				}, '确认开始升级')
			])
		]);
	},

	handleCancel() {
		ui.hideModal();
	},

	handleInstallConfirmed() {
		this._install.disabled = true;
		ui.hideModal();
		return fs.exec('/usr/sbin/wma301-ota', [ 'start' ])
			.then(function(result) {
				if (result.code !== 0)
					throw new Error(result.stderr || '升级被 OTA 保护条件拒绝');
				ui.showModal('WMA301 手动 OTA', [
					E('p', {}, '升级进程已启动。设备可能断开连接，请勿断电。'),
					E('p', {}, '如果升级没有启动，请通过 SSH 查看 /tmp/wma301-ota/update.log。')
				]);
			}).catch(function(err) {
				ui.addNotification(null, E('p', {}, err.message || '升级未启动'), 'error');
			});
	},

	render(data) {
		this._otaInfo = E('div', {});
		this._refresh = E('button', {
			'class': 'btn cbi-button',
			'click': ui.createHandlerFn(this, 'handleRefresh')
		}, '检查更新');
		this._download = E('button', {
			'class': 'btn cbi-button-action',
			'click': ui.createHandlerFn(this, 'handleDownload')
		}, '下载并验证');
		this._install = E('button', {
			'class': 'btn cbi-button-negative',
			'click': ui.createHandlerFn(this, 'handleInstall')
		}, '手动安装');

		const root = E('div', { 'class': 'cbi-map' }, [
			E('h2', {}, 'WMA301 专属 OTA'),
			E('div', { 'class': 'cbi-section' }, [
				E('p', {}, '独立于原生固件刷写页面，仅接受本设备唯一 OTA 固件源的已校验 FIT。默认禁止实际刷写。'),
				this._otaInfo,
				E('div', { 'class': 'cbi-page-actions' }, [
					this._refresh, ' ', this._download, ' ', this._install
				])
			]),
			E('div', { 'class': 'cbi-section' }, [
				E('h3', {}, '安全策略'),
				E('p', {}, '常规检查与下载无需启用刷写。实机完成 UBI 环境卷、保留配置和恢复验证后，管理员才能手动启用安装：'),
				E('pre', {}, "uci set wma301-ota.main.enable_flash='1'\nuci commit wma301-ota"),
				E('p', {}, '只有一个 OTA 固件源：快速构建通过后自动发布。设备不会自动下载或安装更新。')
			])
		]);
		this.showStatus(data);
		return root;
	}
});
