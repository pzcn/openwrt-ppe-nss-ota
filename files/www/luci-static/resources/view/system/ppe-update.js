'use strict';
'require view';
'require form';
'require fs';
'require ui';

/*
 * Custom edition of the upstream ppe-update LuCI view.
 * No force-upgrade button. No ambiguous upstream update target.
 */
function fmtTime(t) {
	return t ? new Date(t * 1000).toLocaleString('zh-CN') : '—';
}

return view.extend({
	load: function() {
		return fs.exec_direct('/usr/sbin/ppe-update', [ 'status' ], 'json')
			.catch(function(e) { return { error: e.message }; });
	},

	pollLog: function() {
		return fs.read('/tmp/ppe-update.log').catch(function() { return ''; })
			.then(L.bind(function(log) {
				var box = document.getElementById('ppe-update-log');
				if (box)
					box.textContent = log;
				if (/flashing /.test(log))
					return ui.awaitReconnect();
				if (/^exit [1-9]/m.test(log)) {
					ui.addNotification(null, E('p', '更新已停止，具体原因见日志。'), 'error');
					return ui.hideModal();
				}
				return new Promise(function(resolve) {
					window.setTimeout(resolve, 2000);
				}).then(L.bind(this.pollLog, this));
			}, this));
	},

	startUpdate: function(st) {
		// This check also protects against stale UI state after a failed preflight.
		if (!st.update || st.checked !== true || st.missing)
			return ui.addNotification(null, E('p', '软件包兼容性尚未通过检查，已阻止更新。'), 'error');

		ui.showModal('正在安装 pzcn 定制固件', [
			E('p', '升级包将从 pzcn/openwrt-ppe-nss-ota 下载、核对 SHA256 并进行兼容性检查。标准 sysupgrade 将尝试保留配置；请确保已自行备份配置。'),
			E('p', [ '目标版本：', E('strong', st.latest) ]),
			E('pre', {
				'id': 'ppe-update-log',
				'style': 'max-height:16em;overflow:auto;white-space:pre-wrap'
			})
		]);
		return fs.exec('/usr/sbin/ppe-update', [ 'start' ])
			.then(L.bind(this.pollLog, this));
	},

	render: function(st) {
		var rows = [
			['固件来源', 'pzcn/openwrt-ppe-nss-ota（定制版）'],
			['设备', st.board || '—'],
			['当前版本', st.current || '未识别'],
			['当前构建号', st.build != null ? String(st.build) : '—']
		];

		if (st.latest) {
			rows.push(['最新版本', st.latest]);
			rows.push(['构建发布时间', fmtTime(st.latest_time)]);
			if (st.extras)
				rows.push(['尝试保留的额外软件包', st.extras]);
			if (st.missing)
				rows.push(['新版本缺失的软件包', E('strong', {
					'style': 'color:#cb4b4b'
				}, st.missing)]);
			if (st.pending)
				rows.push(['上次未完成安装的包', st.pending]);
		}
		if (st.error)
			rows.push(['检查失败', E('strong', st.error)]);

		var button = null;
		if (st.update === true && st.checked === true && !st.missing) {
			button = E('button', {
				'class': 'btn cbi-button cbi-button-apply',
				'click': ui.createHandlerFn(this, 'startUpdate', st)
			}, '下载并安装定制更新');
		}
		else if (st.update === true) {
			button = E('em', {
				'style': 'color:#bd873b'
			}, '当前未通过升级前检查。为避免丢失额外软件包，已禁用一键刷机。');
		}
		else {
			button = E('em', st.error ? '暂时无法检查更新，请稍后再试。' : '当前已是最新的定制固件。');
		}

		var status = E('div', { 'class': 'cbi-section' }, [
			E('h2', 'pzcn 定制固件 OTA'),
			E('p', { 'class': 'cbi-section-descr' },
				'只检查此仓库的 GitHub Releases，不会安装未经定制的 PPE+NSS 上游固件。固件更新会校验设备、构建序号、软件包清单和 SHA256。'),
			E('table', { 'class': 'table' }, rows.map(function(row) {
				return E('tr', { 'class': 'tr' }, [
					E('td', { 'class': 'td left', 'width': '32%' }, row[0]),
					E('td', { 'class': 'td left', 'style': 'overflow-wrap:anywhere' }, row[1])
				]);
			})),
			E('p', {
				'class': 'cbi-section-descr',
				'style': 'padding:10px 0'
			}, '升级前请先将配置备份到电脑；保留配置与额外软件包是尽力迁移，并非绝对无损。自动更新初始为关闭状态。'),
			E('div', { 'class': 'right', 'style': 'margin:14px 0' }, [
				E('a', {
					'href': 'https://github.com/pzcn/openwrt-ppe-nss-ota/releases',
					'target': '_blank',
					'rel': 'noopener noreferrer',
					'style': 'margin-right:18px'
				}, '查看 GitHub Releases'),
				button
			])
		]);

		var m = new form.Map('ppe-update');
		var section = m.section(form.NamedSection, 'main', 'ppe-update', '自动更新');
		var o = section.option(form.Flag, 'auto', '启用自动更新',
			'每天检查同一仓库的定制版本，符合等待时间且额外软件包检查通过时才会刷写。建议先手动验证一次 OTA。');
		o.rmempty = false;
		o = section.option(form.ListValue, 'hour', '每天检查的小时');
		for (var hour = 0; hour < 24; hour++)
			o.value(String(hour), '%02d:00'.format(hour));
		o.default = '4';
		o.depends('auto', '1');
		o = section.option(form.Value, 'delay', '发布后等待天数');
		o.datatype = 'uinteger';
		o.default = '1';
		o.depends('auto', '1');

		return m.render().then(function(node) {
			return E([], [status, node]);
		});
	}
});
