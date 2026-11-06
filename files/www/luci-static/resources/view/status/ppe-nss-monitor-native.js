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

function row(label, slot) {
	return E('tr', { 'class': 'tr' }, [
		E('td', { 'class': 'td left' }, label),
		E('td', { 'class': 'td' }, E('strong', { 'data-nss': slot }, '—'))
	]);
}

return view.extend({
	handleSave: null,
	handleSaveApply: null,
	handleReset: null,
	_root: null,
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
			[ 'ppe-state', 'wifi-state', 'nss-state' ].forEach(L.bind(function(slot) {
				this.setText(slot, '读取失败');
			}, this));
			[ 'hw', 'sw', 'ct', 'ppe-debug', 'nss-debug' ].forEach(L.bind(function(slot) {
				this.setText(slot, '—');
			}, this));
			return;
		}

		var conn = data.conntrack || {};
		var ppe = data.ppe || {};
		var nss = data.nss || {};

		this.setText('ppe-state', ppe.hw_setting === true ? '已启用'
			: ppe.hw_setting === false ? '未启用' : '未知');
		this.setText('wifi-state', nss.wifi_active === true ? '已启用'
			: nss.wifi_active === false ? '未启用' : '未知');
		this.setText('nss-state', nss.visible_cores > 0
			? formatCount(nss.running_cores) + ' / ' + formatCount(nss.visible_cores) + ' 运行'
			: '未知');

		this.setText('hw', conn.available ? formatCount(conn.hardware) : '—');
		this.setText('sw', conn.available ? formatCount(conn.software) : '—');
		this.setText('ct', conn.available ? formatCount(conn.total) : '—');

		this.setText('ppe-debug', ppe.offload_stats || '暂无 PPE offload 统计');
		this.setText('nss-debug', [
			'ath11k NSS：' + (nss.wifi_active === true ? '启用' : nss.wifi_active === false ? '关闭' : '未知'),
			'NSS 配置：' + (nss.wifi_config == null ? '未知' : nss.wifi_config),
			'NSS 核心：' + (nss.visible_cores > 0
				? formatCount(nss.running_cores) + ' / ' + formatCount(nss.visible_cores) : '未知'),
			'NSS flows 接口：' + (nss.flows_found ? '可用' : '未知'),
			'PPE offload 接口：' + (ppe.debugfs_found ? '可用' : '未知')
		].join('\n'));
	},

	refresh: function() {
		if (this._busy)
			return Promise.resolve();
		if (!this._root || !this._root.isConnected) {
			if (this._poller)
				poll.remove(this._poller);
			return Promise.resolve();
		}

		this._busy = true;
		return getStatus().then(L.bind(this.apply, this))
			.catch(L.bind(function() { this.apply(null); }, this))
			.finally(L.bind(function() { this._busy = false; }, this));
	},

	render: function(data) {
		this._busy = false;

		this._root = E('div', { 'class': 'cbi-map' }, [
			E('h2', 'PPE / NSS 硬件加速'),
			E('div', { 'class': 'cbi-map-descr' }, '每 8 秒自动更新'),
			E('div', { 'class': 'cbi-section' }, [
				E('h3', '加速引擎'),
				E('table', { 'class': 'table' }, [
					row('PPE 硬件流量卸载', 'ppe-state'),
					row('NSS Wi-Fi 加速', 'wifi-state'),
					row('NSS 处理核心', 'nss-state')
				])
			]),
			E('div', { 'class': 'cbi-section' }, [
				E('h3', '连接统计'),
				E('table', { 'class': 'table' }, [
					row('PPE 硬件卸载连接', 'hw'),
					row('软件卸载连接', 'sw'),
					row('Conntrack 总连接', 'ct')
				])
			]),
			E('div', { 'class': 'cbi-section' }, [
				E('details', {}, [
					E('summary', '内核诊断'),
					E('h4', 'PPE offload'),
					E('pre', { 'data-nss': 'ppe-debug',
						'style': 'white-space:pre-wrap;overflow-wrap:anywhere;max-height:20em;overflow:auto' }, '—'),
					E('h4', 'NSS'),
					E('pre', { 'data-nss': 'nss-debug',
						'style': 'white-space:pre-wrap;overflow-wrap:anywhere;max-height:20em;overflow:auto' }, '—')
				])
			])
		]);
		this.apply(data);
		this._poller = L.bind(this.refresh, this);
		poll.add(this._poller, 8);
		return this._root;
	}
});
