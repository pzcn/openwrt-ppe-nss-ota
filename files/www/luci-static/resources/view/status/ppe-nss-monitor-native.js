'use strict';
'require view';
'require rpc';
'require poll';

const getStatus = rpc.declare({
	object: 'luci.ppe-nss-monitor',
	method: 'get_status',
	expect: {}
});

function formatCount(value) {
	return typeof value === 'number' && isFinite(value)
		? value.toLocaleString('zh-CN') : '—';
}

function row(label, slot, description) {
	return E('tr', { 'class': 'tr' }, [
		E('td', { 'class': 'td left' }, label),
		E('td', { 'class': 'td' }, E('strong', { 'data-nss': slot }, '—')),
		E('td', { 'class': 'td left', 'data-nss': 'hint-' + slot }, description || '')
	]);
}

function shortTrend(history) {
	if (!history.length)
		return '等待采样…';
	var max = Math.max.apply(null, history.map(function(v) { return v.count; }));
	var blocks = '▁▂▃▄▅▆▇█';
	return history.map(function(v) {
		return blocks.charAt(max > 0 ? Math.min(7, Math.floor(v.count / max * 7)) : 0);
	}).join('');
}

return view.extend({
	handleSave: null,
	handleSaveApply: null,
	handleReset: null,
	_root: null,
	_history: null,
	_paused: false,
	_busy: false,
	_poller: null,

	load: function() {
		return L.resolveDefault(getStatus(), null);
	},

	setText: function(slot, value) {
		var node = this._root && this._root.querySelector('[data-nss="' + slot + '"]');
		if (node)
			node.textContent = value;
	},

	apply: function(data) {
		if (!data || data.schema !== 1) {
			this.setText('connection', '采集接口不可用');
			this.setText('summary', '无法读取监控数据，请检查 rpcd 和权限配置');
			return;
		}

		var conn = data.conntrack || {};
		var ppe = data.ppe || {};
		var nss = data.nss || {};
		var available = conn.available === true && typeof conn.hardware === 'number';

		this.setText('connection', '正常');
		this.setText('updated', new Date().toLocaleTimeString('zh-CN', { hour12: false }));
		this.setText('hw', available ? formatCount(conn.hardware) : '—');
		this.setText('sw', conn.available ? formatCount(conn.software) : '—');
		this.setText('ct', conn.available ? formatCount(conn.total) : '—');
		this.setText('core', nss.visible_cores > 0
			? formatCount(nss.running_cores) + ' / ' + formatCount(nss.visible_cores) : '—');

		this.setText('hint-hw', available ? '标记为 HW_OFFLOAD 的连接' : 'conntrack 统计不可用');
		this.setText('hint-sw', conn.available ? '仅标记 OFFLOAD 的连接' : '统计不可用');
		this.setText('hint-ct', conn.available ? '当前连接跟踪记录' : '统计不可用');
		this.setText('hint-core', nss.visible_cores > 0 ? '驱动报告的运行核心数量' : 'NSS 启动信息不可用');

		this.setText('ppe-state', ppe.hw_setting === true ? '已启用' : ppe.hw_setting === false ? '未启用' : '未知');
		this.setText('ppe-detail', ppe.hw_setting === true
			? (available && conn.hardware > 0 ? '已发现实际硬件卸载连接' : '硬件卸载已配置，尚未发现硬件连接')
			: '请检查网络 → 防火墙 → 硬件流量卸载');
		this.setText('wifi-state', nss.wifi_active === true ? 'NSS 路径' : nss.wifi_active === false ? '主机路径' : '未知');
		this.setText('wifi-detail', nss.wifi_active === true ? 'ath11k 已启用 NSS 数据路径' : 'ath11k NSS 路径未启用或不可读取');
		this.setText('nss-state', nss.core_active === true ? '运行中' : nss.core_active === false ? '未运行' : '未知');
		this.setText('nss-detail', nss.visible_cores > 0
			? '已检测 ' + formatCount(nss.visible_cores) + ' 个核心'
			: 'NSS boot 数据不可用');

		this.setText('summary', available && conn.hardware > 0
			? '当前检测到 ' + formatCount(conn.hardware) + ' 条硬件卸载连接'
			: available ? '尚未检测到硬件卸载连接' : '连接统计源暂不可用');

		this.setText('ppe-debug', ppe.offload_stats ||
			'没有找到 PPE offload debugfs 统计接口。');
		this.setText('nss-debug', [
			'ath11k NSS：' + (nss.wifi_active === true ? '启用' : nss.wifi_active === false ? '关闭' : '未知'),
			'NSS 配置：' + (nss.wifi_config == null ? '不可用' : nss.wifi_config),
			'NSS 运行核心：' + (nss.visible_cores > 0 ? nss.running_cores + ' / ' + nss.visible_cores : '不可用'),
			'NSS flows 接口：' + (nss.flows_found ? '可用' : '不存在'),
			'PPE offload 接口：' + (ppe.debugfs_found ? '存在' : '不存在')
		].join('\n'));

		if (available) {
			this._history.push({ time: new Date(), count: conn.hardware });
			if (this._history.length > 24)
				this._history.shift();
		}
		this.setText('trend', shortTrend(this._history));
		this.setText('samples', this._history.length + ' / 24 次采样');
	},

	refresh: function() {
		if (this._busy || this._paused)
			return Promise.resolve();
		if (!this._root || !this._root.isConnected) {
			if (this._poller)
				poll.remove(this._poller);
			return Promise.resolve();
		}

		this._busy = true;
		return getStatus().then(L.bind(this.apply, this)).catch(L.bind(function() {
			this.setText('connection', '通信异常');
			this.setText('updated', '刷新失败');
			this.setText('summary', '无法联系监控接口，请稍后重试');
		}, this)).finally(L.bind(function() { this._busy = false; }, this));
	},

	manualRefresh: function() {
		var paused = this._paused;
		this._paused = false;
		return this.refresh().finally(L.bind(function() { this._paused = paused; }, this));
	},

	togglePause: function() {
		this._paused = !this._paused;
		this.setText('pause-label', this._paused ? '继续自动刷新' : '暂停自动刷新');
		this.setText('connection', this._paused ? '已暂停' : '正常');
	},

	render: function(data) {
		this._history = [];
		this._paused = false;
		this._busy = false;

		this._root = E('div', { 'class': 'cbi-map' }, [
			E('h2', 'PPE / NSS 硬件加速'),
			E('div', { 'class': 'cbi-map-descr' },
				'查看 PPE 硬件卸载连接、NSS 运行状态和内核统计。'),
			E('div', { 'class': 'cbi-section' }, [
				E('h3', '监控状态'),
				E('div', { 'class': 'cbi-section-descr', 'data-nss': 'summary' }, '正在读取…'),
				E('table', { 'class': 'table' }, [
					row('连接状态', 'connection', '每 8 秒自动刷新'),
					row('上次更新', 'updated', '浏览器本地时间')
				]),
				E('div', { 'class': 'cbi-page-actions' }, [
					E('button', { 'class': 'btn cbi-button', 'type': 'button',
						'click': L.bind(this.togglePause, this) },
						E('span', { 'data-nss': 'pause-label' }, '暂停自动刷新')),
					E('button', { 'class': 'btn cbi-button cbi-button-action', 'type': 'button',
						'click': L.bind(this.manualRefresh, this) }, '立即刷新')
				])
			]),
			E('div', { 'class': 'cbi-section' }, [
				E('h3', '连接统计'),
				E('table', { 'class': 'table' }, [
					E('tr', { 'class': 'tr table-titles' }, [
						E('th', { 'class': 'th' }, '指标'),
						E('th', { 'class': 'th' }, '数值'),
						E('th', { 'class': 'th' }, '说明')
					]),
					row('PPE 硬件卸载连接', 'hw', 'HW_OFFLOAD'),
					row('软件流表连接', 'sw', 'OFFLOAD'),
					row('Conntrack 连接总数', 'ct', '当前记录总量'),
					row('NSS 运行核心', 'core', '运行 / 已检测')
				]),
				E('p', { 'class': 'cbi-section-descr' },
					'统计值表示当前连接数。')
			]),
			E('div', { 'class': 'cbi-section' }, [
				E('h3', '最近 24 次采样'),
				E('div', { 'class': 'cbi-section-descr' }, '仅记录当前页面打开期间的硬件卸载连接数。'),
				E('p', {}, [
					E('code', { 'data-nss': 'trend', 'aria-label': '硬件连接数量趋势' }, '等待采样…'),
					'　',
					E('span', { 'data-nss': 'samples' }, '0 / 24 次采样')
				])
			]),
			E('div', { 'class': 'cbi-section' }, [
				E('h3', '加速引擎状态'),
				E('table', { 'class': 'table' }, [
					E('tr', { 'class': 'tr table-titles' }, [
						E('th', { 'class': 'th' }, '组件'),
						E('th', { 'class': 'th' }, '状态'),
						E('th', { 'class': 'th' }, '说明')
					]),
					row('PPE 硬件流量卸载', 'ppe-state', ''),
					row('NSS Wi-Fi 数据路径', 'wifi-state', ''),
					row('NSS 处理核心', 'nss-state', '')
				]),
				E('div', { 'class': 'cbi-section-descr' }, [
					E('p', { 'data-nss': 'ppe-detail' }, ''),
					E('p', { 'data-nss': 'wifi-detail' }, ''),
					E('p', { 'data-nss': 'nss-detail' }, '')
				])
			]),
			E('div', { 'class': 'cbi-section' }, [
				E('h3', '内核诊断'),
				E('div', { 'class': 'cbi-section-descr' }, '点击条目展开驱动统计和接口可用性信息。'),
				E('details', {}, [
					E('summary', 'PPE offload 统计'),
					E('pre', { 'data-nss': 'ppe-debug',
						'style': 'white-space:pre-wrap;overflow-wrap:anywhere;max-height:20em;overflow:auto' }, '正在读取…')
				]),
				E('details', {}, [
					E('summary', 'NSS 诊断信息'),
					E('pre', { 'data-nss': 'nss-debug',
						'style': 'white-space:pre-wrap;overflow-wrap:anywhere;max-height:20em;overflow:auto' }, '正在读取…')
				])
			])
		]);
		this.apply(data);
		this._poller = L.bind(this.refresh, this);
		poll.add(this._poller, 8);
		return this._root;
	}
});
