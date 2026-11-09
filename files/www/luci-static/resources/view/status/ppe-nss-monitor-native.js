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

function formatMbps(value, previous, seconds) {
	if (typeof value !== 'number' || !isFinite(value))
		return '—';
	if (typeof previous !== 'number' || !isFinite(previous) ||
		seconds < 1 || seconds > 60 || value < previous)
		return '采样中';
	var mbps = (value - previous) * 8 / seconds / 1000000;
	return mbps >= 1000
		? (mbps / 1000).toFixed(2) + ' Gb/s'
		: mbps.toFixed(2) + ' Mb/s';
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
	_lastAt: 0,
	_lastCounters: null,

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
			[
				'ppe-state', 'wifi-state', 'nss-state', 'ppe-live',
				'nss-live', 'nss-bridged', 'ppe-offloaded', 'nss-pushed',
				'ppe-rate', 'wifi-rate', 'wifi-rx', 'wifi-tx', 'hw', 'sw',
				'ct', 'ppe-debug', 'nss-debug'
			].forEach(L.bind(function(slot) {
				this.setText(slot, '—');
			}, this));
			[ 'ppe-state', 'wifi-state', 'nss-state' ].forEach(L.bind(function(slot) {
				this.setText(slot, '读取失败');
			}, this));
			this._lastAt = 0;
			this._lastCounters = null;
			return;
		}

		var ct = data.conntrack || {};
		var ppe = data.ppe || {};
		var nss = data.nss || {};
		var metrics = data.telemetry || {};
		var hp = metrics.ppe || {};
		var ports = metrics.ppe_ports || {};
		var nf = metrics.nss || {};
		var wf = metrics.wifi || {};

		this.setText('ppe-state', ppe.hw_setting === true ? '已启用（配置）'
			: ppe.hw_setting === false ? '未启用（配置）' : '未知');
		this.setText('wifi-state', nss.wifi_active === true ? '已启用（模块参数）'
			: nss.wifi_active === false ? '未启用（模块参数）'
			: wf.vdevs > 0 ? '参数未知，有驱动计数' : '未知');
		this.setText('nss-state', nss.visible_cores > 0
			? formatCount(nss.running_cores) + ' / ' + formatCount(nss.visible_cores) + ' 运行'
			: '未知');

		// Driver-maintained active entries, not inferred from conntrack marks.
		this.setText('ppe-live', formatCount(hp.live_entries));
		this.setText('nss-live', formatCount(nf.installed));
		this.setText('nss-bridged', formatCount(nf.bridged_installed));
		this.setText('ppe-offloaded', formatCount(hp.offloaded_total));
		this.setText('nss-pushed', formatCount(nf.pushed_total));

		// Only consecutive monotone samples are suitable for rates.
		// Egress bytes count switch ports, NOT only offloaded flow traffic.
		var now = Date.now();
		var seconds = this._lastAt ? (now - this._lastAt) / 1000 : 0;
		var previous = this._lastCounters || {};
		this.setText('ppe-rate', formatMbps(ports.bytes, previous.portBytes, seconds));
		this.setText('wifi-rate', formatMbps(wf.rx_bytes, previous.wifiRxBytes, seconds));
		this._lastAt = now;
		this._lastCounters = {
			portBytes: ports.bytes,
			wifiRxBytes: wf.rx_bytes
		};

		this.setText('wifi-rx', formatCount(wf.rx_packets));
		this.setText('wifi-tx', formatCount(wf.tx_packets));
		// These are conntrack flags, not proof the PPE or NSS is inactive.
		this.setText('hw', ct.available ? formatCount(ct.hardware) : '—');
		this.setText('sw', ct.available ? formatCount(ct.software) : '—');
		this.setText('ct', ct.available ? formatCount(ct.total) : '—');

		this.setText('ppe-debug', [
			'PPE 活跃硬件流表项：' + formatCount(hp.live_entries),
			'PPE 已安装规则（累计）：' + formatCount(hp.offloaded_total),
			'PPE 拒绝次数（累计）：' + formatCount(hp.rejected_total),
			'PPE 表满次数：' + formatCount(hp.table_full),
			'PPE 发送丢弃次数：' + formatCount(hp.xmit_drop),
			'PPE 端口丢包总数：' + formatCount(ports.drop_packets),
			'注意：PPE 端口速率包含普通交换流量，不等于硬件流卸载速率。',
			'',
			'驱动原始 offload 摘要：',
			ppe.offload_stats || '暂无 PPE offload 统计'
		].join('\n'));

		this.setText('nss-debug', [
			'NSS Wi-Fi 参数：' + (nss.wifi_active === true ? '1'
				: nss.wifi_active === false ? '0' : '未知'),
			'NSS 配置：' + (nss.wifi_config == null ? '未知' : nss.wifi_config),
			'NSS 核心：' + (nss.visible_cores > 0
				? formatCount(nss.running_cores) + ' / ' + formatCount(nss.visible_cores) : '未知'),
			'NSS 已下发规则（累计）：' + formatCount(nf.pushed_total),
			'NSS 桥接规则（内核状态）：' + formatCount(nf.bridged_active),
			'NSS Wi-Fi 虚拟接口：' + formatCount(wf.vdevs),
			'NSS Wi-Fi 接收入队失败：' + formatCount(wf.rx_enqueue_fail),
			'NSS Wi-Fi 待发包丢弃：' + formatCount(wf.tx_dropped),
			'NSS Wi-Fi 硬件环满：' + formatCount(wf.tx_ring_full),
			'NSS flows 接口：' + (nss.flows_found ? '可用' : '不可用'),
			'PPE offload 接口：' + (ppe.debugfs_found ? '可用' : '不可用'),
			'注意：NSS 接收速率仅反映 Wi-Fi vdev RX 入队字节数。'
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
		this._lastAt = 0;
		this._lastCounters = null;

		this._root = E('div', { 'class': 'cbi-map' }, [
			E('h2', 'PPE / NSS 硬件加速'),
			E('div', { 'class': 'cbi-map-descr' },
				'每 8 秒采样一次驱动计数器。无流量时为 0；接口不可读时显示「—」。'),
			E('div', { 'class': 'cbi-section' }, [
				E('h3', '加速引擎'),
				E('table', { 'class': 'table' }, [
					row('PPE 硬件卸载设置', 'ppe-state'),
					row('NSS Wi-Fi 数据路径', 'wifi-state'),
					row('NSS 处理核心', 'nss-state'),
					row('PPE 活跃硬件流表项', 'ppe-live'),
					row('NSS 已安装流表规则', 'nss-live'),
					row('NSS 已安装桥接规则', 'nss-bridged')
				])
			]),
			E('div', { 'class': 'cbi-section' }, [
				E('h3', '连接统计'),
				E('table', { 'class': 'table' }, [
					row('PPE 历史成功安装规则', 'ppe-offloaded'),
					row('NSS 历史下发固件规则', 'nss-pushed'),
					row('PPE 端口出口速率（含普通流量）', 'ppe-rate'),
					row('NSS Wi-Fi 接收速率', 'wifi-rate'),
					row('NSS Wi-Fi 收包（累计）', 'wifi-rx'),
					row('NSS Wi-Fi 待发包（累计）', 'wifi-tx'),
					row('Conntrack HW_OFFLOAD 标记', 'hw'),
					row('Conntrack OFFLOAD 标记', 'sw'),
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
