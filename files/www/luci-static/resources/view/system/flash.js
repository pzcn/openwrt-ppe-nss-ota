'use strict';
'require view';
'require dom';
'require form';
'require rpc';
'require fs';
'require ui';
'require uci';


// This build adds the custom OTA as an extra native LuCI action section.
// The backup, restore, image upload, sysupgrade and configuration editors
// in this upstream flash view are intentionally left unchanged.
function customOTARow(label, value) {
	return E('tr', { 'class': 'tr' }, [
		E('td', { 'class': 'td left', 'width': '32%' }, label),
		E('td', { 'class': 'td left', 'style': 'overflow-wrap:anywhere' }, value)
	]);
}
function fmtOTARelease(t) {
	return t ? new Date(t * 1000).toLocaleString('zh-CN') : '—';
}
function fmtOTABytes(n) {
	const value = Number(n);
	if (!Number.isFinite(value) || value < 0)
		return '—';
	if (value < 1024)
		return Math.round(value) + ' B';
	if (value < 1024 * 1024)
		return (value / 1024).toFixed(1) + ' KiB';
	return (value / (1024 * 1024)).toFixed(2) + ' MiB';
}
function otaErrorHelp(reason) {
	const s = String(reason || '');
	if (/not enough free space/i.test(s))
		return '路由器临时空间不足，检查 /tmp 可用空间，清理临时文件后重试。';
	if (/download failed|cannot reach.*GitHub|连接失败|下载失败|下载信息下载失败/i.test(s))
		return '网络下载失败。请检查互联网连接，或更换下方的 GitHub 代理并重试。';
	if (/SHA256|checksum|校验和/i.test(s))
		return '文件完整性校验不通过。已停止升级，请重新下载，不要强制刷写。';
	if (/sysupgrade rejected|固件信息或设备不匹配|layout mismatch|preflight failed|metadata|设备不匹配/i.test(s))
		return '设备或固件兼容性检查未通过。请确认固件对应当前设备，勿使用 -F 强刷。';
	if (/no ImmortalWrt firmware|暂无可用固件/i.test(s))
		return '当前设备渠道没有可用的正式 Release，请检查发布状态。';
	if (/already running|已在运行/i.test(s))
		return '已有升级进程在执行，请在原页面查看进度，避免重复启动。';
	return '请展开详细日志查看原因；若问题发生在下载阶段，可尝试切换 GitHub 代理。';
}

const isReadonlyView = !L.hasViewPermission();

// A schedule setting does not need the global UCI apply/rollback operation.
// Commit only the OTA configuration. rpcd emits config.change for procd to
// refresh the ppe-update cron entry.
const commitOtaConfig = rpc.declare({
	object: 'uci',
	method: 'commit',
	params: [ 'config' ],
	reject: true
});

const callSystemValidateFirmwareImage = rpc.declare({
	object: 'system',
	method: 'validate_firmware_image',
	params: [ 'path' ],
	expect: { '': { valid: false, forceable: true } }
});

function findStorageSize(procmtd, procpart) {
	let kernsize = 0, rootsize = 0, wholesize = 0;

	procmtd.split(/\n/).forEach(function(ln) {
		const match = ln.match(/^mtd\d+: ([0-9a-f]+) [0-9a-f]+ "(.+)"$/);
		const size = match ? parseInt(match[1], 16) : 0;

		switch (match ? match[2] : '') {
		case 'linux':
		case 'firmware':
			if (size > wholesize)
				wholesize = size;
			break;

		case 'kernel':
		case 'kernel0':
			kernsize = size;
			break;

		case 'rootfs':
		case 'rootfs0':
		case 'ubi':
		case 'ubi0':
			rootsize = size;
			break;
		}
	});

	if (wholesize > 0)
		return wholesize;
	else if (kernsize > 0 && rootsize > kernsize)
		return kernsize + rootsize;

	procpart.split(/\n/).forEach(function(ln) {
		const match = ln.match(/^\s*\d+\s+\d+\s+(\d+)\s+(\S+)$/);
		if (match) {
			const size = parseInt(match[1], 10);

			if (!match[2].match(/\d/) && size > 2048 && wholesize == 0)
				wholesize = size * 1024;
		}
	});

	return wholesize;
}


const mapdata = { actions: {}, config: {} };

return view.extend({
	load() {
		const tasks = [
			L.resolveDefault(fs.stat('/lib/upgrade/platform.sh'), {}),
			fs.trimmed('/proc/sys/kernel/hostname'),
			fs.trimmed('/proc/mtd'),
			fs.trimmed('/proc/partitions'),
			fs.trimmed('/proc/mounts'),
			L.resolveDefault(uci.load('ppe-update'), null)
		];

		return Promise.all(tasks);
	},


	otaScheduleWidget() {
		const view = this;
		const auto = E('input', {
			'type': 'checkbox', 'class': 'cbi-input-checkbox',
			'checked': uci.get('ppe-update', 'main', 'auto') == '1' ? '' : null,
			'disabled': isReadonlyView || null
		});
		const hour = E('select', { 'class': 'cbi-input-select', 'disabled': isReadonlyView || null },
			Array.from({ length: 24 }, function(_, i) {
				return E('option', {
					'value': String(i),
					'selected': (uci.get('ppe-update', 'main', 'hour') || '4') == String(i) ? '' : null
				}, ('0' + i).slice(-2) + ':00');
			}));
		const delay = E('input', {
			'type': 'number', 'class': 'cbi-input-text',
			'min': '0', 'max': '3650', 'step': '1',
			'value': uci.get('ppe-update', 'main', 'delay') || '1',
			'disabled': isReadonlyView || null
		});
		const modes = [
			[ 'direct', '直连 GitHub' ],
			[ 'ghfast', 'GHFast (ghfast.top)' ],
			[ 'ghproxy', 'GHProxy (ghproxy.net)' ],
			[ 'gh_proxy', 'GH-Proxy (gh-proxy.com)' ],
			[ 'custom', '自定义' ]
		];
		const savedMode = uci.get('ppe-update', 'main', 'github_proxy') || 'direct';
		const proxy = E('select', { 'class': 'cbi-input-select', 'disabled': isReadonlyView || null },
			modes.map(function(item) {
				return E('option', {
					'value': item[0],
					'selected': savedMode === item[0] ? '' : null
				}, item[1]);
			}));
		const customProxy = E('input', {
			'type': 'url', 'class': 'cbi-input-text',
			'placeholder': 'https://proxy.example.com',
			'value': uci.get('ppe-update', 'main', 'github_proxy_url') || '',
			'disabled': isReadonlyView || null
		});
		const row = function(label, element) {
			return E('div', { 'class': 'cbi-value' }, [
				E('label', { 'class': 'cbi-value-title' }, label),
				E('div', { 'class': 'cbi-value-field' }, element)
			]);
		};
		const customRow = row('代理地址', customProxy);
		const toggleAuto = function() {
			hour.disabled = delay.disabled = isReadonlyView || !auto.checked;
		};
		const toggleProxy = function() {
			customRow.hidden = proxy.value !== 'custom';
		};
		auto.addEventListener('change', toggleAuto);
		proxy.addEventListener('change', toggleProxy);
		toggleAuto();
		toggleProxy();
		const save = E('button', {
			'type': 'button', 'class': 'btn cbi-button cbi-button-apply',
			'disabled': isReadonlyView || null,
			'click': ui.createHandlerFn(this, function() {
				const days = Number(delay.value);
				if (!Number.isInteger(days) || days < 0 || days > 3650) {
					ui.addNotification(null, E('p', '等待天数无效'), 'error');
					return;
				}
				const settings = {
					auto: auto.checked ? '1' : '0',
					hour: hour.value,
					delay: String(days),
					github_proxy: proxy.value,
					github_proxy_url: customProxy.value.trim().replace(/\/+$/, '')
				};
				if (settings.github_proxy === 'custom') {
					let parsed;
					try { parsed = new URL(settings.github_proxy_url); }
					catch (_) {
						ui.addNotification(null, E('p', '请输入 HTTPS 代理地址'), 'error');
						return;
					}
					if (parsed.protocol !== 'https:' || !parsed.hostname ||
						parsed.username || parsed.password || parsed.search || parsed.hash ||
						settings.github_proxy_url.length > 200 ||
						!/^https:\/\/[A-Za-z0-9][A-Za-z0-9.-]*(?::[0-9]{1,5})?(?:\/[A-Za-z0-9._~\/-]*)?$/.test(settings.github_proxy_url)) {
						ui.addNotification(null, E('p', '请输入有效的 HTTPS 代理前缀'), 'error');
						return;
					}
				}
				save.disabled = true;
				Object.keys(settings).forEach(function(key) {
					uci.set('ppe-update', 'main', key, settings[key]);
				});
				return uci.save()
					.then(function() { return commitOtaConfig('ppe-update'); })
					.then(function() {
						uci.unload('ppe-update');
						return uci.load('ppe-update');
					}).then(function() {
						if (Object.keys(settings).some(function(key) {
							return (uci.get('ppe-update', 'main', key) || '') !== settings[key];
						}))
							throw new Error('保存后的配置与填写内容不一致');
						auto.checked = settings.auto === '1';
						hour.value = settings.hour;
						delay.value = settings.delay;
						proxy.value = settings.github_proxy;
						customProxy.value = settings.github_proxy_url;
						toggleAuto();
						toggleProxy();
						ui.addNotification(null, E('p', '设置已保存'), 'info');
						view.otaRefresh().catch(function() {});
					}).catch(function(e) {
						ui.addNotification(null, E('p', '保存失败：' + (e.message || e)), 'error');
					}).finally(function() { save.disabled = isReadonlyView; });
			})
		}, '保存设置');
		return E('div', [
			row('启用自动更新', auto),
			row('检查时间', hour),
			row('延迟天数', delay),
			row('GitHub 代理', proxy),
			customRow,
			E('div', { 'class': 'cbi-page-actions' }, save)
		]);
	},


	otaShow(info) {
		const root = this._otaInfo;
		if (!root)
			return;
		this._otaStatus = info || {};
		const st = this._otaStatus;
		if (this._otaInstallButton)
			this._otaInstallButton.disabled = isReadonlyView || this._otaRunning === true ||
				st.update !== true;

		const rows = [
			customOTARow('当前版本', st.current || '—'),
			customOTARow('最新版本', st.latest || '—')
		];
		if (st.latest_time)
			rows.push(customOTARow('发布时间', fmtOTARelease(st.latest_time)));
		if (st.size)
			rows.push(customOTARow('固件大小', fmtOTABytes(st.size)));
		rows.push(customOTARow('状态',
			st.error || (st.update === true ? '发现新版本，可手动下载并安装' : '已是最新版本')));
		if (st.error)
			rows.push(customOTARow('处理建议', otaErrorHelp(st.error)));
		if (st.pending)
			rows.push(customOTARow('待恢复软件包', st.pending));
		root.replaceChildren(E('table', { 'class': 'table' }, rows));
	},

	otaRefresh() {
		this._otaStatus = null;
		if (this._otaInstallButton)
			this._otaInstallButton.disabled = true;
		if (this._otaInfo)
			this._otaInfo.textContent = '正在检查固件更新…';

		return fs.exec_direct('/usr/sbin/ppe-update', [ 'status' ], 'json')
			.then(L.bind(this.otaShow, this))
			.catch(L.bind(function(e) {
				this.otaShow({ error: e.message || '状态查询失败' });
			}, this));
	},

	otaOpenProgressModal() {
		this._otaRunning = true;
		this._otaHistory = [];
		this._otaLastStage = 'starting';
		if (this._otaInstallButton)
			this._otaInstallButton.disabled = true;
		this._otaPhaseText = E('strong', '正在连接升级服务…');
		this._otaStageHelp = E('p', '固件下载完成后会自动校验、安装并重启，无需再次点击确认。');
		this._otaMeter = E('progress', {
			'max': '100', 'value': '0',
			'style': 'width:100%;height:1.1em;',
			'hidden': true
		});
		this._otaNumbers = E('div', { 'class': 'cbi-value-description' }, '');
		this._otaLog = E('pre', {
			'id': 'ppe-ota-progress-log',
			'style': 'white-space:pre-wrap;max-height:15em;overflow:auto;overflow-wrap:anywhere'
		}, '正在启动升级任务…');
		this._otaActions = E('div', { 'class': 'cbi-page-actions' });
		ui.showModal('在线固件更新', [
			E('p', this._otaPhaseText),
			this._otaStageHelp,
			this._otaMeter,
			this._otaNumbers,
			E('p', { 'class': 'cbi-value-description' },
				'刷写开始后路由器会自动重启，管理页面短暂断开是正常现象。此时请勿断电、断网或手动重启，等待设备重新上线。'),
			E('details', { 'style': 'margin-top:0.8em' }, [
				E('summary', '详细日志（发生错误时请展开）'),
				this._otaLog
			]),
			this._otaActions
		]);
	},

	otaUpdateProgress(progress, log) {
		const stage = String(progress.stage || 'starting');
		const labels = {
			starting: '正在启动升级任务',
			checking: '正在检查固件版本和设备信息',
			downloading: '正在下载固件',
			verifying: '正在校验下载的固件',
			preparing: '正在保存升级配置',
			flashing: '正在刷写，设备即将自动重启',
			failed: '固件更新未完成'
		};
		this._otaLastStage = stage;
		this._otaPhaseText.textContent = labels[stage] || '正在处理固件更新';
		this._otaStageHelp.textContent = progress.message ||
			'下载完成后将自动校验、安装并重启，无需再次确认。';
		this._otaLog.textContent = log ? log.slice(-8000) : '暂无详细日志';

		const total = Math.max(0, Number(progress.total) || 0);
		const done = Math.max(0, Number(progress.downloaded) || 0);
		if (stage === 'downloading' && total > 0) {
			const now = Date.now();
			if (this._otaHistory.length &&
				done < this._otaHistory[this._otaHistory.length - 1].bytes)
				this._otaHistory = []; // curl retried a URL; its file was reset
			this._otaHistory.push({ time: now, bytes: done });
			this._otaHistory = this._otaHistory.filter(function(x) {
				return now - x.time <= 5000;
			});
			const first = this._otaHistory[0];
			const seconds = (now - first.time) / 1000;
			const rate = seconds > 0 ? Math.max(0, (done - first.bytes) / seconds) : 0;
			const percent = Math.min(100, Math.floor(100 * done / total));
			this._otaMeter.hidden = false;
			this._otaMeter.value = percent;
			let label = percent + '% · ' + fmtOTABytes(done) + ' / ' +
				fmtOTABytes(total) + ' · ';
			label += rate > 0 ? '近几秒速度 ' + fmtOTABytes(rate) + '/s' : '正在测速或等待数据…';
			if (rate > 1024 && done < total)
				label += ' · 预计剩余约 ' + Math.ceil((total - done) / rate) + ' 秒';
			this._otaNumbers.textContent = label;
		}
		else if (stage === 'verifying' || stage === 'preparing') {
			this._otaMeter.hidden = false;
			this._otaMeter.value = 100;
			this._otaNumbers.textContent = '固件已下载完成（' + fmtOTABytes(total) +
				'），正在执行后续步骤…';
			this._otaHistory = [];
		}
		else {
			this._otaMeter.hidden = true;
			this._otaNumbers.textContent = stage === 'flashing' ?
				'固件已交由系统刷写。之后自动重启，页面断开属于正常过程。' : '';
			this._otaHistory = [];
		}
	},

	otaShowFailure(reason, log) {
		this._otaRunning = false;
		this._otaPhaseText.textContent = '固件更新失败';
		this._otaStageHelp.textContent = (reason ? reason + '。' : '') +
			otaErrorHelp(reason);
		this._otaMeter.hidden = true;
		if (log)
			this._otaLog.textContent = log.slice(-8000);
		if (this._otaInstallButton)
			this._otaInstallButton.disabled = isReadonlyView || !this._otaStatus ||
				this._otaStatus.update !== true;
		this._otaActions.replaceChildren(
			E('button', {
				'type': 'button', 'class': 'btn cbi-button',
				'click': ui.hideModal
			}, '关闭'),
			' ',
			E('button', {
				'type': 'button', 'class': 'btn cbi-button-action',
				'click': ui.createHandlerFn(this, 'otaConfirmInstall')
			}, '重新尝试下载并安装')
		);
	},

	otaPollLog() {
		if (!document.getElementById('ppe-ota-progress-log'))
			return Promise.resolve();

		return Promise.all([
			L.resolveDefault(fs.exec_direct('/usr/sbin/ppe-update', [ 'progress' ], 'json'), { stage: 'unknown' }),
			L.resolveDefault(fs.read('/tmp/ppe-update.log'), '')
		]).then(L.bind(function(result) {
			const progress = result[0] || {};
			const log = result[1] || '';
			this.otaUpdateProgress(progress, log);
			if (progress.stage === 'failed' || /^exit [1-9][0-9]*$/m.test(log)) {
				this.otaShowFailure(progress.message || '升级进程已中止', log);
				return;
			}
			if (progress.stage === 'flashing' || /开始刷写固件/.test(log)) {
				this._otaPhaseText.textContent = '正在安装固件并等待设备重启';
				this._otaStageHelp.textContent =
					'系统已接管刷写，之后会自动重启。连接暂时中断是正常现象，请勿断电；若地址变化，需重新连接路由器。';
				return ui.awaitReconnect(window.location.host);
			}
			if (/^exit 0$/m.test(log)) {
				this._otaPhaseText.textContent = '升级命令已返回';
				this._otaStageHelp.textContent =
					'升级命令已执行，未检测到重启。请查看详细日志确认结果。';
				this._otaActions.replaceChildren(E('button', {
					'type': 'button', 'class': 'btn',
					'click': ui.hideModal
				}, '关闭'));
				return;
			}
			return new Promise(function(resolve) {
				window.setTimeout(resolve, 1500);
			}).then(L.bind(this.otaPollLog, this));
		}, this)).catch(L.bind(function(e) {
			// Disconnection after sysupgrade takes over is expected.
			if (this._otaLastStage !== 'flashing')
				this.otaShowFailure('读取更新进度失败：' + (e.message || e), '');
		}, this));
	},

	otaConfirmInstall() {
		this.otaOpenProgressModal();
		return fs.exec('/usr/sbin/ppe-update', [ 'start' ]).then(L.bind(function(res) {
			if (res.code !== 0) {
				this.otaShowFailure((res.stderr || 'OTA 更新任务启动失败').trim(), '');
				return;
			}
			return this.otaPollLog();
		}, this)).catch(L.bind(function(e) {
			this.otaShowFailure('OTA 无法执行：' + (e.message || e), '');
		}, this));
	},

	otaResumeProgress() {
		return fs.exec_direct('/usr/sbin/ppe-update', [ 'progress' ], 'json')
			.then(L.bind(function(st) {
				if (!this._otaRunning && st && [ 'starting', 'checking', 'downloading', 'verifying',
					'preparing', 'flashing' ].indexOf(st.stage) >= 0) {
					this.otaOpenProgressModal();
					return this.otaPollLog();
				}
			}, this));
	},

	otaAskInstall() {
		const st = this._otaStatus;
		if (!st || st.update !== true) {
			ui.addNotification(null, E('p', '目前没有可手动安装的新版本，请点击“重新检查”。'), 'info');
			return;
		}
		if (isReadonlyView) {
			ui.addNotification(null, E('p', '当前账户没有固件升级权限。'), 'error');
			return;
		}
		const extraInfo = st.extras ? '升级后将尝试恢复额外安装的软件包。' : null;

		ui.showModal('确认在线固件更新', [
			E('p', ['目标版本：', E('strong', st.latest)]),
			E('p', '固件大小：' + fmtOTABytes(st.size)),
			E('p', '点击确认后，将自动完成下载 → SHA256 校验 → 设备兼容性检查 → 固件安装 → 重启，不再进行第二次确认。'),
			E('p', '下载或校验失败会停止，不会继续刷写。刷写及重启阶段请勿断电，建议先备份配置。'),
			extraInfo ? E('p', extraInfo) : '',
			E('div', { 'class': 'right' }, [
				E('button', {
					'class': 'btn',
					'click': ui.hideModal
				}, '取消'), ' ',
				E('button', {
					'class': 'btn cbi-button-action important',
					'click': ui.createHandlerFn(this, 'otaConfirmInstall')
				}, '确认下载、安装并重启')
			])
		]);
	},

	// Native LuCI CBI section inside System > Backup / Flash. Using
	// direct DOM rendering here avoids the nested SectionValue subtree and
	// does not interfere with upstream Backup, Restore or sysupgrade forms.
	renderOTAPanel() {
		const row = function(label, widget) {
			return E('div', { 'class': 'cbi-value' }, [
				E('label', { 'class': 'cbi-value-title' }, label),
				E('div', { 'class': 'cbi-value-field' }, widget)
			]);
		};

		this._otaInfo = E('div', '准备检查…');
		this._otaInstallButton = E('button', {
			'type': 'button',
			'class': 'cbi-button cbi-button-apply important',
			'disabled': true,
			'click': ui.createHandlerFn(this, 'otaAskInstall')
		}, '下载并安装新版本');

		return E('div', {
			'id': 'native-integrated-ota',
			'class': 'cbi-section'
		}, [
			E('h3', '在线固件更新'),
			E('p', { 'class': 'cbi-value-description' },
				'人工确认后自动完成下载、校验、刷写和重启；若设备支持，也可在下方管理定时自动更新。'),
			E('div', { 'class': 'cbi-section-node' }, [
				this._otaInfo,
				E('div', { 'class': 'cbi-page-actions' }, [
					E('button', {
						'type': 'button',
						'class': 'cbi-button cbi-button-action',
						'disabled': isReadonlyView || null,
						'click': ui.createHandlerFn(this, 'otaRefresh')
					}, '重新检查'), ' ', this._otaInstallButton
				]),
				this.otaScheduleWidget()
			])
		]);
	},

	handleBackup(ev) {
		const form = E('form', {
			method: 'post',
			action: L.env.cgi_base + '/cgi-backup',
			enctype: 'application/x-www-form-urlencoded'
		}, E('input', { type: 'hidden', name: 'sessionid', value: rpc.getSessionID() }));

		ev.currentTarget.parentNode.appendChild(form);

		form.submit();
		form.parentNode.removeChild(form);
	},

	handleFirstboot(ev) {
		if (!confirm(_('Do you really want to erase all settings?')))
			return;

		ui.showModal(_('Erasing...'), [
			E('p', { 'class': 'spinning' }, _('The system is erasing the configuration partition now and will reboot itself when finished.'))
		]);

		/* Currently the sysupgrade rpc call will not return, hence no promise handling */
		fs.exec('/sbin/firstboot', [ '-r', '-y' ]);

		ui.awaitReconnect('192.168.1.1', 'openwrt.lan');
	},

	handleRestore(ev) {
		return ui.uploadFile('/tmp/backup.tar.gz', ev.target)
			.then(L.bind(function(btn, res) {
				btn.firstChild.data = _('Checking archive…');
				return fs.exec('/bin/tar', [ '-tzf', '/tmp/backup.tar.gz' ]);
			}, this, ev.target))
			.then(L.bind(function(btn, res) {
				if (res.code != 0) {
					ui.addNotification(null, E('p', _('The uploaded backup archive is not readable')));
					return fs.remove('/tmp/backup.tar.gz');
				}

				ui.showModal(_('Apply backup?'), [
					E('p', _('The uploaded backup archive appears to be valid and contains the files listed below. Press "Continue" to restore the backup and reboot, or "Cancel" to abort the operation.')),
					E('pre', {}, [ res.stdout ]),
					E('div', { 'class': 'right' }, [
						E('button', {
							'class': 'btn',
							'click': ui.createHandlerFn(this, function(ev) {
								return fs.remove('/tmp/backup.tar.gz').finally(ui.hideModal);
							})
						}, [ _('Cancel') ]), ' ',
						E('button', {
							'class': 'btn cbi-button-action important',
							'click': ui.createHandlerFn(this, 'handleRestoreConfirm', btn)
						}, [ _('Continue') ])
					])
				]);
			}, this, ev.target))
			.catch(function(e) { ui.addNotification(null, E('p', e.message)) })
			.finally(L.bind(function(btn, input) {
				btn.firstChild.data = _('Upload archive...');
			}, this, ev.target));
	},

	handleRestoreConfirm(btn, ev) {
		return fs.exec('/sbin/sysupgrade', [ '--restore-backup', '/tmp/backup.tar.gz' ])
			.then(L.bind(function(btn, res) {
				if (res.code != 0) {
					ui.addNotification(null, [
						E('p', _('The restore command failed with code %d').format(res.code)),
						res.stderr ? E('pre', {}, [ res.stderr ]) : ''
					]);
					L.raise('Error', 'Unpack failed');
				}

				btn.firstChild.data = _('Rebooting…');
				return fs.exec('/sbin/reboot');
			}, this, ev.target))
			.then(L.bind(function(res) {
				if (res.code != 0) {
					ui.addNotification(null, E('p', _('The reboot command failed with code %d').format(res.code)));
					L.raise('Error', 'Reboot failed');
				}

				ui.showModal(_('Rebooting…'), [
					E('p', { 'class': 'spinning' }, _('The system is rebooting now. If the restored configuration changed the current LAN IP address, you might need to reconnect manually.'))
				]);

				ui.awaitReconnect(window.location.host, '192.168.1.1', 'openwrt.lan');
			}, this))
			.catch(function(e) { ui.addNotification(null, E('p', e.message)) })
			.finally(function() { btn.firstChild.data = _('Upload archive...') });
	},

	handleBlock(hostname, ev) {
		const mtdblock = dom.parent(ev.target, '.cbi-section').querySelector('[data-name="mtdselect"] select');
		const mtdnumber = mtdblock.value;
		const mtdname = mtdblock.selectedOptions[0].text.replace(/([^a-zA-Z0-9]+)/g, '-');
		const form = E('form', {
			'method': 'post',
			'action': L.env.cgi_base + '/cgi-download',
			'enctype': 'application/x-www-form-urlencoded'
		}, [
			E('input', { 'type': 'hidden', 'name': 'sessionid', 'value': rpc.getSessionID() }),
			E('input', { 'type': 'hidden', 'name': 'path',      'value': '/dev/mtdblock%d'.format(mtdnumber) }),
			E('input', { 'type': 'hidden', 'name': 'filename',  'value': '%s.mtd%d.%s.bin'.format(hostname, mtdnumber, mtdname) })
		]);

		ev.currentTarget.parentNode.appendChild(form);

		form.submit();
		form.parentNode.removeChild(form);
	},

	handleSysupgrade(storage_size, has_rootfs_data, ev) {
		return ui.uploadFile('/tmp/firmware.bin', ev.target.firstChild)
			.then(L.bind(function(btn, reply) {
				btn.firstChild.data = _('Checking image…');

				ui.showModal(_('Checking image…'), [
					E('span', { 'class': 'spinning' }, _('Verifying the uploaded image file.'))
				]);

				return callSystemValidateFirmwareImage('/tmp/firmware.bin')
					.then(function(res) { return [ reply, res ]; });
			}, this, ev.target))
			.then(L.bind(function(btn, reply) {
				return fs.exec('/sbin/sysupgrade', [ '--test', '/tmp/firmware.bin' ])
					.then(function(res) { reply.push(res); return reply; });
			}, this, ev.target))
			.then(L.bind(function(btn, res) {
				/* sysupgrade opts table  [0]:checkbox element [1]:check condition [2]:args to pass */
				const opts = {
				    keep : [ E('input', { type: 'checkbox' }), false, '-n' ],
				    force : [ E('input', { type: 'checkbox' }), true, '--force' ],
				    skip_orig : [ E('input', { type: 'checkbox' }), true, '-u' ],
				    backup_pkgs : [ E('input', { type: 'checkbox' }), true, '-k' ],
				    },
				    is_valid = res[1].valid,
				    is_forceable = res[1].forceable,
				    allow_backup = res[1].allow_backup,
				    is_too_big = (storage_size > 0 && res[0].size > storage_size),
				    body = [];

				body.push(E('p', _("The flash image was uploaded. Below is the checksum and file size listed, compare them with the original file to ensure data integrity. <br /> Click 'Continue' below to start the flash procedure.")));
				body.push(E('ul', {}, [
					res[0].size ? E('li', {}, '%s: %1024.2mB'.format(_('Size'), res[0].size)) : '',
					res[0].checksum ? E('li', {}, '%s: %s'.format(_('MD5'), res[0].checksum)) : '',
					res[0].sha256sum ? E('li', {}, '%s: %s'.format(_('SHA256'), res[0].sha256sum)) : ''
				]));

				body.push(E('p', {}, E('label', { 'class': 'btn' }, [
					opts.keep[0], ' ', _('Keep settings and retain the current configuration')
				])));

				if (!is_valid || is_too_big)
					body.push(E('hr'));

				if (is_too_big)
					body.push(E('p', { 'class': 'alert-message' }, [
						_('It appears that you are trying to flash an image that does not fit into the flash memory, please verify the image file!')
					]));

				if (!is_valid)
					body.push(E('p', { 'class': 'alert-message' }, [
						res[2].stderr ? res[2].stderr : '',
						res[2].stderr ? E('br') : '',
						res[2].stderr ? E('br') : '',
						_('The uploaded image file does not contain a supported format. Make sure that you choose the generic image format for your platform.')
					]));

				if (!allow_backup) {
					body.push(E('p', { 'class': 'alert-message' }, [
						_('The uploaded firmware does not allow keeping current configuration.')
					]));
					opts.keep[0].disabled = true;
				} else {
					opts.keep[0].checked = true;

					if (has_rootfs_data) {
						body.push(E('p', {}, E('label', { 'class': 'btn' }, [
							opts.skip_orig[0], ' ', _('Skip from backup files that are equal to those in /rom')
						])));
					}

					body.push(E('p', {}, E('label', { 'class': 'btn' }, [
						opts.backup_pkgs[0], ' ', _('Include in backup a list of current installed packages at /etc/backup/installed_packages.txt')
					])));
				};

				const cntbtn = E('button', {
					'class': 'btn cbi-button-action important',
					'click': ui.createHandlerFn(this, 'handleSysupgradeConfirm', btn, opts),
				}, [ _('Continue') ]);

				if (res[2].code != 0) {
					body.push(E('p', { 'class': 'alert-message danger' }, E('label', {}, [
						_('Image check failed:'),
						E('br'), E('br'),
						res[2].stderr
					])));
				};

				if ((!is_valid || is_too_big || res[2].code != 0) && is_forceable) {
					body.push(E('p', {}, E('label', { 'class': 'btn alert-message danger' }, [
						opts.force[0], ' ', _('Force upgrade'),
						E('br'), E('br'),
						_('Select \'Force upgrade\' to flash the image even if the image format check fails. Use only if you are sure that the firmware is correct and meant for your device!')
					])));
					cntbtn.disabled = true;
				};


				body.push(E('div', { 'class': 'right' }, [
					E('button', {
						'class': 'btn',
						'click': ui.createHandlerFn(this, function(ev) {
							return fs.remove('/tmp/firmware.bin').finally(ui.hideModal);
						})
					}, [ _('Cancel') ]), ' ', cntbtn
				]));

				opts.force[0].addEventListener('change', function(ev) {
					cntbtn.disabled = !ev.target.checked;
				});

				opts.keep[0].addEventListener('change', function(ev) {
					opts.skip_orig[0].disabled = !ev.target.checked;
					opts.backup_pkgs[0].disabled = !ev.target.checked;

				});

				ui.showModal(_('Flash image?'), body);
			}, this, ev.target))
			.catch(function(e) { ui.addNotification(null, E('p', e.message)) })
			.finally(L.bind(function(btn) {
				btn.firstChild.data = _('Flash image...');
			}, this, ev.target));
	},

	handleSysupgradeConfirm(btn, opts, ev) {
		btn.firstChild.data = _('Flashing…');

		ui.showModal(_('Flashing…'), [
			E('p', { 'class': 'spinning' }, _('The system is flashing now.<br /> DO NOT POWER OFF THE DEVICE!<br /> Wait a few minutes before you try to reconnect. It might be necessary to renew the address of your computer to reach the device again, depending on your settings.'))
		]);

		const args = [];

		for (let key in opts)
			/* if checkbox == condition add args to sysupgrade */
			if (opts[key][0].checked == opts[key][1])
				args.push(opts[key][2]);

		args.push('/tmp/firmware.bin');

		/* Currently the sysupgrade rpc call will not return, hence no promise handling */
		fs.exec('/sbin/sysupgrade', args);

		if (opts['keep'][0].checked)
			ui.awaitReconnect(window.location.host);
		else
			ui.awaitReconnect(window.location.host, '192.168.1.1', 'openwrt.lan');
	},

	handleBackupList(ev) {
		return fs.exec('/sbin/sysupgrade', [ '--list-backup' ]).then(function(res) {
			if (res.code != 0) {
				ui.addNotification(null, [
					E('p', _('The sysupgrade command failed with code %d').format(res.code)),
					res.stderr ? E('pre', {}, [ res.stderr ]) : ''
				]);
				L.raise('Error', 'Sysupgrade failed');
			}

			ui.showModal(_('Backup file list'), [
				E('p', _('Below is the determined list of files to backup. It consists of changed configuration files marked by opkg, essential base files and the user defined backup patterns.')),
				E('ul', {}, (res.stdout || '').trim().split(/\n/).map(function(ln) { return E('li', {}, ln) })),
				E('div', { 'class': 'right' }, [
					E('button', {
						'class': 'btn',
						'click': ui.hideModal
					}, [ _('Dismiss') ])
				])
			], 'cbi-modal');
		});
	},

	handleBackupSave(m, ev) {
		return m.save(function() {
			return fs.write('/etc/sysupgrade.conf', mapdata.config.editlist.trim().replace(/\r\n/g, '\n') + '\n');
		}).then(function() {
			ui.addNotification(null, E('p', _('Contents have been saved.')), 'info');
		}).catch(function(e) {
			ui.addNotification(null, E('p', _('Unable to save contents: %s').format(e)));
		});
	},

	render([p_fstat, hostname, procmtd, procpart, procmounts]) {
		const has_sysupgrade = (p_fstat.type == 'file');
		const has_rootfs_data = (procmtd.match(/"rootfs_data"/) != null) || (procmounts.match("overlayfs:/overlay / ") != null);
		const storage_size = findStorageSize(procmtd, procpart);
		let m, s, o, ss;

		m = new form.JSONMap(mapdata, _('Flash operations'));
		m.tabbed = true;
		m.readonly = isReadonlyView;

		s = m.section(form.NamedSection, 'actions', _('Actions'));


		o = s.option(form.SectionValue, 'actions', form.NamedSection, 'actions', 'actions', _('Backup'), _('Click "Generate archive" to download a tar archive of the current configuration files.'));
		ss = o.subsection;

		o = ss.option(form.Button, 'dl_backup', _('Download backup'));
		o.inputstyle = 'action important';
		o.inputtitle = _('Generate archive');
		o.onclick = this.handleBackup;


		o = s.option(form.SectionValue, 'actions', form.NamedSection, 'actions', 'actions', _('Restore'), _('To restore configuration files, you can upload a previously generated backup archive here. To reset the firmware to its initial state, click "Perform reset" (only possible with squashfs images).'));
		ss = o.subsection;

		if (has_rootfs_data) {
			o = ss.option(form.Button, 'reset', _('Reset to defaults'));
			o.inputstyle = 'negative important';
			o.inputtitle = _('Perform reset');
			o.onclick = this.handleFirstboot;
		}

		o = ss.option(form.Button, 'restore', _('Restore backup'), _('Custom files (certificates, scripts) may remain on the system. To prevent this, perform a factory-reset first.'));
		o.inputstyle = 'action important';
		o.inputtitle = _('Upload archive...');
		o.onclick = L.bind(this.handleRestore, this);


		const mtdblocks = [];
		procmtd.split(/\n/).forEach(function(ln) {
			const match = ln.match(/^mtd(\d+): .+ "(.+?)"$/);
			if (match)
				mtdblocks.push(match[1], match[2]);
		});

		if (mtdblocks.length) {
			o = s.option(form.SectionValue, 'actions', form.NamedSection, 'actions', 'actions', _('Save mtdblock contents'), _('Click "Save mtdblock" to download specified mtdblock file. (NOTE: THIS FEATURE IS FOR PROFESSIONALS! )'));
			ss = o.subsection;

			o = ss.option(form.ListValue, 'mtdselect', _('Choose mtdblock'));

			for (var i = 0; i < mtdblocks.length; i += 2)
				o.value(mtdblocks[i], mtdblocks[i+1]);

			o = ss.option(form.Button, 'mtddownload', _('Download mtdblock'));
			o.inputstyle = 'action important';
			o.inputtitle = _('Save mtdblock');
			o.onclick = L.bind(this.handleBlock, this, hostname);
		}


		o = s.option(form.SectionValue, 'actions', form.NamedSection, 'actions', 'actions', _('Flash new firmware image'),
			has_sysupgrade
				? _('Upload a sysupgrade-compatible image here to replace the running firmware.')
				: _('Sorry, there is no sysupgrade support present; a new firmware image must be flashed manually. Please refer to the wiki for device specific install instructions.'));

		ss = o.subsection;

		if (has_sysupgrade) {
			o = ss.option(form.Button, 'sysupgrade', _('Image'));
			o.inputstyle = 'action important';
			o.inputtitle = _('Flash image...');
			o.onclick = L.bind(this.handleSysupgrade, this, storage_size, has_rootfs_data);
		}



		// The OTA panel is attached to the rendered Actions tab after LuCI
		// builds the form. No nested SectionValue or second menu is needed.

		s = m.section(form.NamedSection, 'config', 'config', _('Configuration'), _('This is a list of shell glob patterns for matching files and directories to include during sysupgrade. Modified files in /etc/config/ and certain other configurations are automatically preserved.'));
		s.render = L.bind(function(view /*, ... */) {
			return form.NamedSection.prototype.render.apply(this, this.varargs(arguments, 1))
				.then(L.bind(function(node) {
					node.appendChild(E('div', { 'class': 'cbi-page-actions' }, [
						E('button', {
							'class': 'cbi-button cbi-button-save',
							'click': ui.createHandlerFn(view, 'handleBackupSave', this.map),
							'disabled': isReadonlyView || null
						}, [ _('Save') ])
					]));

					return node;
				}, this));
		}, s, this);

		o = s.option(form.Button, 'showlist', _('Show current backup file list'));
		o.inputstyle = 'action';
		o.inputtitle = _('Open list...');
		o.onclick = L.bind(this.handleBackupList, this);

		o = s.option(form.TextValue, 'editlist');
		o.forcewrite = true;
		o.rows = 30;
		o.load = function(section_id) {
			return L.resolveDefault(fs.read('/etc/sysupgrade.conf'), '');
		};


		return m.render().then(L.bind(function(node) {
			// The CBI "Actions" tab has finished rendering. Insert the OTA
			// panel into its visible section rather than a nested widget.
			// LuCI's NamedSection receives a translated section type
			// (_('Actions')), so data-tab is locale-dependent ("操作" on
			// Chinese installations). The stable section ID is "actions".
			const actions = node.querySelector(
				'.cbi-map-tabbed > .cbi-section > .cbi-section-node[data-section-id="actions"]'
			) || node.querySelector('.cbi-section-node[data-section-id="actions"]');
			if (!actions)
				throw new Error('Cannot locate the LuCI flash Actions section');
			actions.appendChild(this.renderOTAPanel());
			// GitHub requests remain async and cannot block page rendering.
			this.otaRefresh();
			// Reattach the progress modal after a page refresh during download.
			Promise.resolve().then(L.bind(this.otaResumeProgress, this)).catch(function() {});
			return node;
		}, this));
	},

	handleSaveApply: null,
	handleSave: null,
	handleReset: null
});
