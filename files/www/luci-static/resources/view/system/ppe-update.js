'use strict';
'require view';
'require form';
'require fs';

// Advanced schedule settings. Manual updates have moved to the native
// Backup / Flash Firmware page as a sibling of image-upload upgrade.
return view.extend({
	load: function() {
		return fs.exec_direct('/usr/sbin/ppe-update', [ 'status' ], 'json')
			.catch(function(e) { return { error: e.message }; });
	},
	render: function(st) {
		var status = E('div', { 'class': 'cbi-section' }, [
			E('h2', '定制 OTA 设置'),
			E('p', { 'class': 'cbi-section-descr' },
				'手动在线更新现已放到「系统 → 备份/升级」页面，和本地刷写固件并列。'),
			E('table', { 'class': 'table' }, [
				E('tr', { 'class': 'tr' }, [
					E('td', { 'class': 'td left', 'width': '32%' }, '当前版本'),
					E('td', { 'class': 'td left' }, st.current || '无法读取')
				]),
				E('tr', { 'class': 'tr' }, [
					E('td', { 'class': 'td left' }, '最新版本'),
					E('td', { 'class': 'td left' }, st.latest || st.error || '无法检查')
				])
			]),
			E('p', { 'class': 'cbi-section-descr' },
				'手动 OTA 不会因为无法模拟额外 APK 包安装而阻止更新，但可能有软件包需要升级后重新安装。设备与镜像校验始终执行。'),
			E('div', { 'class': 'cbi-page-actions' }, [
				E('a', {
					'class': 'btn cbi-button cbi-button-action',
					'href': L.url('admin', 'system', 'flash')
				}, '前往备份/升级页面')
			])
		]);

		var m = new form.Map('ppe-update');
		var section = m.section(form.NamedSection, 'main', 'ppe-update', '自动更新');
		var o = section.option(form.Flag, 'auto', '启用无人值守更新',
			'自动更新仍会检查额外软件包兼容性；模拟检查失败则暂缓，以免无人值守升级后功能缺失。');
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
			return E([], [ status, node ]);
		});
	}
});
