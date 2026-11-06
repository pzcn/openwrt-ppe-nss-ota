'use strict';
'require view';
'require rpc';
'require poll';

const getStatus = rpc.declare({
	object: 'luci.ppe-nss-monitor',
	method: 'get_status',
	expect: {}
});

function fmt(value) {
	return typeof value === 'number' && isFinite(value)
		? value.toLocaleString('zh-CN')
		: '—';
}

function statCard(code, label, hint, accent) {
	return E('div', { 'class': 'pn-metric pn-metric-' + accent }, [
		E('div', { 'class': 'pn-metric-head' }, [
			E('span', { 'class': 'pn-metric-symbol' }, code),
			E('span', { 'class': 'pn-metric-arrow', 'aria-hidden': 'true' }, '↗')
		]),
		E('div', { 'class': 'pn-metric-value', 'data-pn': 'value-' + code }, '—'),
		E('div', { 'class': 'pn-metric-title' }, label),
		E('div', { 'class': 'pn-metric-hint', 'data-pn': 'hint-' + code }, hint)
	]);
}

function signal(code, name, detail) {
	return E('div', { 'class': 'pn-signal' }, [
		E('div', { 'class': 'pn-signal-orb pn-signal-orb-' + code }, [
			E('span', code === 'nss' ? 'N' : code === 'wifi' ? 'W' : 'P')
		]),
		E('div', { 'class': 'pn-signal-text' }, [
			E('div', { 'class': 'pn-signal-name' }, name),
			E('div', { 'class': 'pn-signal-description', 'data-pn': 'detail-' + code }, detail)
		]),
		E('span', { 'class': 'pn-pill pn-pill-idle', 'data-pn': 'pill-' + code }, '检测中')
	]);
}

return view.extend({
	_history: null,
	_paused: false,
	_busy: false,
	_root: null,
	_poller: null,

	handleSave: null,
	handleSaveApply: null,
	handleReset: null,

	load: function() {
		return L.resolveDefault(getStatus(), null);
	},

	find: function(slot) {
		return this._root ? this._root.querySelector('[data-pn="' + slot + '"]') : null;
	},

	text: function(slot, value) {
		var node = this.find(slot);
		if (node)
			node.textContent = value;
	},

	pill: function(slot, label, state) {
		var node = this.find('pill-' + slot);
		if (node) {
			node.className = 'pn-pill pn-pill-' + state;
			node.textContent = label;
		}
	},

	updateChart: function() {
		var rows = this._history || [];
		var values = rows.map(function(s) { return s.count; });
		var max = Math.max(1, ...values);
		var grid = this.find('chart');
		if (!grid)
			return;

		var bars = grid.children;
		for (var i = 0; i < bars.length; i++) {
			var s = rows[i];
			var bar = bars[i];
			var percent = s ? (s.count > 0 ? Math.max(5, (s.count / max) * 100) : 3) : 3;
			bar.style.height = percent + '%';
			bar.className = 'pn-chart-bar' + (s ? ' pn-chart-bar-live' : '');
			bar.title = s ? ('硬件连接 ' + fmt(s.count) + ' · ' + s.time) : '等待采样';
		}
		this.text('chart-max', values.length ? fmt(max) : '—');
		this.text('chart-latest', values.length ? fmt(values[values.length - 1]) : '—');
		this.text('chart-count', rows.length + ' / 24 样本');
		this.text('chart-empty', rows.length ? '当前只展示浏览本页面期间采集的数据' : '尚无有效样本，等待采集…');
	},

	apply: function(data) {
		if (!data || data.schema !== 1) {
			this.text('updated', '采集接口不可用');
			this.pill('connection', '通信异常', 'down');
			this.text('banner-status', '无法读取设备指标，请确认 rpcd ACL 与服务状态');
			return;
		}

		var conn = data.conntrack || {};
		var ppe = data.ppe || {};
		var nss = data.nss || {};
		var available = conn.available === true && typeof conn.hardware === 'number';
		var hw = available ? conn.hardware : null;

		this.pill('connection', '实时连接', 'good');
		this.text('updated', '更新于 ' + new Date().toLocaleTimeString('zh-CN', { hour12: false }));
		this.text('value-hw', fmt(hw));
		this.text('value-sw', conn.available ? fmt(conn.software) : '—');
		this.text('value-ct', conn.available ? fmt(conn.total) : '—');
		this.text('value-core', nss.visible_cores > 0 ? fmt(nss.running_cores) + ' / ' + fmt(nss.visible_cores) : '—');
		this.text('hint-hw', available ? '已标记 HW_OFFLOAD 的连接' : 'nf_conntrack 接口不可用');
		this.text('hint-sw', conn.available ? '只有 OFFLOAD 标记的连接' : '无法读取软件流表标记');
		this.text('hint-ct', conn.available ? '当前 conntrack 记录总量' : '统计源暂不可用');
		this.text('hint-core', nss.visible_cores > 0 ? 'debugfs 已确认运行的核心' : 'NSS boot 统计不可用');

		if (ppe.hw_setting === true)
			this.pill('ppe', '已配置', 'good');
		else if (ppe.hw_setting === false)
			this.pill('ppe', '未启用', 'warn');
		else
			this.pill('ppe', '配置未知', 'idle');

		this.text('detail-ppe', ppe.hw_setting === true
			? (available && hw > 0 ? '已发现真实 HW_OFFLOAD 连接' : '硬件 Flow Offloading 已开启；暂无已确认的硬件连接')
			: (ppe.hw_setting === false ? '请在网络 → 防火墙中确认硬件流量卸载设置' : '未能从 firewall 配置确认开关'));

		if (nss.wifi_active === true)
			this.pill('wifi', 'NSS 路径', 'good');
		else if (nss.wifi_active === false)
			this.pill('wifi', '主机路径', 'warn');
		else
			this.pill('wifi', '状态未知', 'idle');

		this.text('detail-wifi', nss.wifi_active === true
			? 'ath11k 已报告 Wi-Fi NSS 数据路径启用'
			: (nss.wifi_active === false ? 'ath11k 当前未启用 NSS 数据路径' : 'ath11k 未提供可解析的 nss_offload 参数'));

		if (nss.core_active === true)
			this.pill('nss', '运行中', 'good');
		else if (nss.core_active === false)
			this.pill('nss', '未运行', 'warn');
		else
			this.pill('nss', '未检测到', 'idle');

		this.text('detail-nss', nss.visible_cores > 0
			? ('已检测 ' + nss.visible_cores + ' 个核心，运行 ' + nss.running_cores + ' 个')
			: 'NSS 启动状态未暴露或 debugfs 尚未挂载');

		if (available && hw > 0) {
			this.text('banner-status', 'PPE 已发现 ' + fmt(hw) + ' 条硬件卸载连接');
		} else if (available) {
			this.text('banner-status', '加速状态可观测 · 暂未发现硬件卸载连接');
		} else {
			this.text('banner-status', '加速监控在线 · 连接统计暂不可用');
		}

		this.text('ppe-debug', ppe.offload_stats || '未发现 *.ppe/offload 接口。请检查 debugfs 是否挂载、PPE 驱动是否已初始化。');
		this.text('nss-debug', [
			'ath11k NSS：' + (nss.wifi_active === true ? '1（已启用）' : nss.wifi_active === false ? '0（未启用）' : '不可读取'),
			'NSS 配置：' + (nss.wifi_config == null ? '未提供' : nss.wifi_config),
			'NSS 核心：' + (nss.visible_cores > 0 ? (nss.running_cores + ' / ' + nss.visible_cores) : '不可读取'),
			'NSS flows 接口：' + (nss.flows_found ? '已发现（不读取敏感流表内容）' : '未发现'),
			'PPE offload 接口：' + (ppe.debugfs_found ? '已发现' : '未发现')
		].join('\n'));

		if (available) {
			this._history.push({
				time: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
				count: hw
			});
			if (this._history.length > 24)
				this._history.shift();
		}
		this.updateChart();
	},

	refresh: function() {
		if (this._busy)
			return Promise.resolve();
		if (!this._root || !this._root.isConnected) {
			if (this._poller)
				poll.remove(this._poller);
			return Promise.resolve();
		}
		if (this._paused)
			return Promise.resolve();

		this._busy = true;
		return getStatus().then(L.bind(function(data) {
			this.apply(data);
		}, this)).catch(L.bind(function(err) {
			this.pill('connection', '通信中断', 'down');
			this.text('updated', '更新失败');
			this.text('banner-status', '监控连接中断，点击刷新重试');
		}, this)).finally(L.bind(function() {
			this._busy = false;
		}, this));
	},

	manualRefresh: function() {
		var wasPaused = this._paused;
		this._paused = false;
		return this.refresh().finally(L.bind(function() {
			this._paused = wasPaused;
		}, this));
	},

	togglePause: function() {
		this._paused = !this._paused;
		this.text('pause-text', this._paused ? '继续监控' : '暂停');
		this.pill('connection', this._paused ? '已暂停' : '实时连接', this._paused ? 'idle' : 'good');
	},

	render: function(data) {
		this._history = [];
		this._paused = false;
		this._busy = false;

		var bars = [];
		for (var i = 0; i < 24; i++)
			bars.push(E('i', { 'class': 'pn-chart-bar', 'aria-hidden': 'true' }));

		var pauseButton = E('button', {
			'type': 'button', 'class': 'pn-button pn-button-subtle',
			'click': L.bind(this.togglePause, this)
		}, [E('span', { 'data-pn': 'pause-text' }, '暂停')]);

		var refreshButton = E('button', {
			'type': 'button', 'class': 'pn-button pn-button-primary',
			'click': L.bind(this.manualRefresh, this)
		}, ['↻  立即刷新']);

		this._root = E('div', { 'class': 'pn-dashboard', 'id': 'pn-dashboard-root' }, [
			E('link', { 'rel': 'stylesheet', 'href': L.resource('ppe-nss-monitor.css') }),
			E('header', { 'class': 'pn-hero' }, [
				E('div', { 'class': 'pn-hero-overline' }, [
					E('span', { 'class': 'pn-brand-glyph', 'aria-hidden': 'true' }, '◈'),
					E('span', { 'class': 'pn-brand-word' }, 'PPE / NSS'),
					E('span', { 'class': 'pn-hero-divider' }),
					E('span', { 'class': 'pn-overline-muted' }, 'QUALCOMM IPQ6018 · RE-SS-01')
				]),
				E('div', { 'class': 'pn-hero-body' }, [
					E('div', { 'class': 'pn-hero-copy' }, [
						E('div', { 'class': 'pn-eyebrow' }, 'HARDWARE ACCELERATION INTELLIGENCE'),
						E('h2', { 'class': 'pn-hero-title' }, ['让每一次转发，', E('span', '都看得见。')]),
						E('p', { 'class': 'pn-hero-description' },
							'PPE 有线硬件流表与 NSS 无线数据路径的实时观测。所有数据均直接来自设备内核，不预设性能数字。'),
						E('div', { 'class': 'pn-hero-state' }, [
							E('span', { 'class': 'pn-live-dot' }),
							E('span', { 'data-pn': 'banner-status' }, '正在同步硬件状态…')
						])
					]),
					E('div', { 'class': 'pn-hero-emblem', 'aria-hidden': 'true' }, [
						E('div', { 'class': 'pn-emblem-outer' }, [
							E('div', { 'class': 'pn-emblem-inner' }, 'NSS'),
							E('div', { 'class': 'pn-emblem-point pn-emblem-point-one' }),
							E('div', { 'class': 'pn-emblem-point pn-emblem-point-two' })
						]),
						E('span', 'PACKET PROCESSING ENGINE')
					])
				]),
				E('div', { 'class': 'pn-hero-controls' }, [
					E('div', { 'class': 'pn-control-status' }, [
						E('span', { 'class': 'pn-pill pn-pill-idle', 'data-pn': 'pill-connection' }, '检测中'),
						E('span', { 'class': 'pn-updated', 'data-pn': 'updated' }, '正在读取…'),
						E('span', { 'class': 'pn-interval' }, '每 8 秒采样')
					]),
					E('div', { 'class': 'pn-control-actions' }, [pauseButton, refreshButton])
				])
			]),
			E('main', { 'class': 'pn-main' }, [
				E('div', { 'class': 'pn-section-heading' }, [
					E('div', {}, [
						E('div', { 'class': 'pn-eyebrow' }, 'LIVE TELEMETRY'),
						E('h3', {}, '核心指标')
					]),
					E('span', { 'class': 'pn-caption' }, '硬件标记 · 内核级数据')
				]),
				E('section', { 'class': 'pn-metrics' }, [
					statCard('hw', '硬件卸载连接', '来自 HW_OFFLOAD 标记', 'cyan'),
					statCard('sw', '软件流表连接', '仅 OFFLOAD 标记', 'violet'),
					statCard('ct', 'Conntrack 连接总数', '当前活跃连接', 'blue'),
					statCard('core', 'NSS 运行核心', '固件核心状态', 'green')
				]),
				E('section', { 'class': 'pn-columns' }, [
					E('div', { 'class': 'pn-panel pn-chart-panel' }, [
						E('div', { 'class': 'pn-panel-head' }, [
							E('div', {}, [
								E('div', { 'class': 'pn-eyebrow' }, 'LIVE HISTORY'),
								E('h3', {}, '硬件卸载连接趋势')
							]),
							E('span', { 'class': 'pn-panel-badge' }, '8s · 近 24 次')
						]),
						E('div', { 'class': 'pn-chart-upper' }, [
							E('div', {}, [
								E('span', { 'class': 'pn-label' }, '最新样本'),
								E('strong', { 'class': 'pn-chart-latest', 'data-pn': 'chart-latest' }, '—'),
								E('span', { 'class': 'pn-unit' }, '条连接')
							]),
							E('span', { 'class': 'pn-chart-samples', 'data-pn': 'chart-count' }, '0 / 24 样本')
						]),
						E('div', { 'class': 'pn-chart-frame' }, [
							E('div', { 'class': 'pn-chart-lines' }, [E('i'), E('i'), E('i'), E('i')]),
							E('div', { 'class': 'pn-chart-bars', 'data-pn': 'chart', 'role': 'img', 'aria-label': '硬件卸载连接数量的最近24个采样柱状图' }, bars),
							E('div', { 'class': 'pn-axis-max', 'data-pn': 'chart-max' }, '—'),
							E('div', { 'class': 'pn-axis-zero' }, '0')
						]),
						E('div', { 'class': 'pn-chart-foot' }, [
							E('span', { 'class': 'pn-chart-legend' }, [E('i'), 'HW_OFFLOAD 连接数']),
							E('span', { 'data-pn': 'chart-empty' }, '尚无有效样本，等待采集…')
						])
					]),
					E('div', { 'class': 'pn-panel pn-health-panel' }, [
						E('div', { 'class': 'pn-panel-head' }, [
							E('div', {}, [
								E('div', { 'class': 'pn-eyebrow' }, 'ENGINE STATUS'),
								E('h3', {}, '加速引擎状态')
							]),
							E('span', { 'class': 'pn-panel-badge pn-panel-badge-green' }, 'READ ONLY')
						]),
						E('div', { 'class': 'pn-signals' }, [
							signal('ppe', 'PPE 硬件流量卸载', '正在读取防火墙配置…'),
							signal('wifi', 'NSS Wi-Fi 数据路径', '正在读取 ath11k 状态…'),
							signal('nss', 'NSS 处理核心', '正在读取驱动启动状态…')
						]),
						E('div', { 'class': 'pn-note-line' }, [
							E('span', { 'class': 'pn-note-line-icon' }, 'i'),
							E('span', '“已配置”与“正在加速”是不同概念；真实硬件连接由 HW_OFFLOAD 标记确认。')
						])
					])
				]),
				E('section', { 'class': 'pn-bottom' }, [
					E('div', { 'class': 'pn-panel pn-diagnostic' }, [
						E('div', { 'class': 'pn-panel-head' }, [
							E('div', {}, [
								E('div', { 'class': 'pn-eyebrow' }, 'KERNEL INSPECTOR'),
								E('h3', {}, '内核诊断')
							]),
							E('span', { 'class': 'pn-panel-badge' }, 'DEBUGFS / PROCFS')
						]),
						E('details', { 'class': 'pn-details', 'open': '' }, [
							E('summary', {}, ['PPE 卸载统计', E('span', 'qca_ppe / offload')]),
							E('pre', { 'data-pn': 'ppe-debug' }, '正在读取内核计数器…')
						]),
						E('details', { 'class': 'pn-details' }, [
							E('summary', {}, ['NSS 运行检查', E('span', 'ath11k / NSS')]),
							E('pre', { 'data-pn': 'nss-debug' }, '正在读取 NSS 状态…')
						])
					]),
					E('aside', { 'class': 'pn-panel pn-guide' }, [
						E('div', { 'class': 'pn-eyebrow' }, 'READ THE SIGNALS'),
						E('h3', {}, '如何理解这些数字？'),
						E('div', { 'class': 'pn-guide-item' }, [
							E('span', '01'),
							E('p', {}, [E('b', 'HW_OFFLOAD'), ' 表示连接已被标记为硬件卸载，不等于网速，也不是全网流量占比。'])
						]),
						E('div', { 'class': 'pn-guide-item' }, [
							E('span', '02'),
							E('p', {}, [E('b', 'NSS Wi-Fi'), ' 根据 ath11k 的实际参数判断；不能仅凭配置值认定加速生效。'])
						]),
						E('div', { 'class': 'pn-guide-item' }, [
							E('span', '03'),
							E('p', {}, ['数据只在当前页面暂存，离开后即清除。页面不会更改驱动、流表或防火墙设置。'])
						]),
						E('div', { 'class': 'pn-guide-mark' }, [
							E('span', 'IPQ60XX'), E('span', '·'), E('span', 'PPE + NSS')
						])
					])
				])
			]),
			E('footer', { 'class': 'pn-footer' }, [
				E('span', 'PPE / NSS MONITOR · CUSTOM EDITION'),
				E('span', '基于 OpenWrt LuCI · 实时只读')
			])
		]);

		this.apply(data);
		this._poller = L.bind(this.refresh, this);
		poll.add(this._poller, 8);
		return this._root;
	}
});
