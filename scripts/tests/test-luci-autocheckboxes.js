#!/usr/bin/env node
/* Regression test for LuCI boolean attributes: checked=false is still
 * considered present in HTML; disabled/selected follow the same rule.
 * Mock E() as HTML attribute presence and test both sides of persistence.
 */
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '../..');

function makeView(file, store, options = {}) {
	const elements = [], notices = [], events = [];
	const cached = { ...store }, changes = {}, staged = {};

	function E(tag, attributes, children) {
		if (Array.isArray(tag))
			return { tag: 'fragment', children: tag };

		if (!attributes || typeof attributes !== 'object' || Array.isArray(attributes)) {
			children = attributes;
			attributes = {};
		}

		const node = {
			tag, attributes, children,
			id: attributes.id ?? '',
			value: attributes.value ?? (tag === 'select' && Array.isArray(children)
				? children.find(option => option.selected)?.value ?? '' : ''),
			textContent: typeof children === 'string' ? children : '',
			checked: attributes.checked != null,
			selected: attributes.selected != null,
			disabled: attributes.disabled != null,
			listeners: {},
			addEventListener(type, fn) { this.listeners[type] = fn; }
		};
		elements.push(node);
		return node;
	}

	const sandbox = {
		E,
		L: {
			hasViewPermission: () => true,
			bind: (fn, self, ...args) => fn.bind(self, ...args),
			resolveDefault: (promise) => promise
		},
		view: { extend: (methods) => methods },
		form: {},
		fs: {},
		uci: {
			get: (pkg, section, key) => cached[key] ?? null,
			set: (pkg, section, key, value) => {
				assert.equal(pkg, 'ppe-update');
				assert.equal(section, 'main');
				if (cached[key] !== value) {
					cached[key] = value;
					changes[key] = value;
				}
			},
			save: async () => {
				events.push('save');
				Object.assign(staged, changes);
				for (const key of Object.keys(changes)) delete changes[key];
			},
			unload: config => {
				assert.equal(config, 'ppe-update');
				events.push('unload');
				for (const key of Object.keys(cached)) delete cached[key];
			},
			load: async config => {
				assert.equal(config, 'ppe-update');
				events.push('load');
				Object.assign(cached, store);
				return [config];
			},
			apply: async () => { throw Error('Global UCI apply must not be called'); }
		},
		rpc: {
			declare: ({ object, method }) => {
				if (object === 'uci' && method === 'commit')
					return async config => {
						assert.equal(config, 'ppe-update');
						events.push('commit');
						if (options.failCommit)
							throw new Error('UCI commit failed');
						if (!options.skipPersistence)
							Object.assign(store, staged);
						for (const key of Object.keys(staged)) delete staged[key];
						return {};
					};
				if (method === 'get_config')
					return async () => ({
						backend_revision: 'drcom-rpc12',
						login_url: 'http://10.0.0.1/0.htm',
						logout_url: 'http://10.0.0.1/F.htm',
						username: 'student',
						has_password: true,
						remember: true,
						auto: store.auto === '1'
					});
				if (method === 'set_auto')
					return async (enabled) => {
						store.auto = enabled ? '1' : '0';
						return { ok: true, auto: enabled };
					};
				return async () => ({ ok: true });
			}
		},
		ui: {
			createHandlerFn: (ctx, fn) => (...args) =>
				(typeof fn === 'function' ? fn : ctx[fn]).apply(ctx, args),
			addNotification: (_title, node, level) => {
				notices.push({ text: node?.textContent ?? '', level });
			}
		}
	};

	const src = fs.readFileSync(path.join(root, file), 'utf8');
	const methods = vm.runInNewContext('(function() {\n' + src + '\n})()', sandbox, { filename: file });
	return { methods, elements, events, notices };
}

function only(elements, predicate) {
	const matched = elements.filter(predicate);
	assert.equal(matched.length, 1, 'expected exactly one control, found ' + matched.length);
	return matched[0];
}

async function testOta() {
	const store = { auto: '0', hour: '9', delay: '2' };
	const file = 'files/www/luci-static/resources/view/system/flash.js';
	const { methods, elements, events, notices } = makeView(file, store);
	methods.otaRefresh = async () => {};
	methods.otaScheduleWidget();

	const box = only(elements, n => n.tag === 'input' && n.attributes.type === 'checkbox');
	assert.equal(box.checked, false, 'OTA disabled in UCI must render unchecked');
	assert(elements.some(n => n.children === '启用自动更新'), 'OTA label not updated');
	let options = elements.filter(n => n.tag === 'option');
	assert.equal(options.filter(n => n.selected).length, 1, 'only one check hour may be selected');
	assert.equal(options.find(n => n.selected).value, '9');

	const button = only(elements, n => n.tag === 'button' && n.children === '保存自动更新设置');
	box.checked = true;
	await button.attributes.click();
	assert.equal(store.auto, '1');
	assert.equal(store.hour, '9');
	assert.equal(store.delay, '2');
	assert.deepEqual(events, ['save', 'commit', 'unload', 'load']);
	assert(notices.some(n => n.text === '自动更新设置已保存'));
	assert.equal(makeView(file, store).methods.otaScheduleWidget !== undefined, true);
	const afterEnable = makeView(file, store);
	afterEnable.methods.otaScheduleWidget();
	assert.equal(only(afterEnable.elements, n => n.tag === 'input' && n.attributes.type === 'checkbox').checked, true);

	box.checked = false;
	await button.attributes.click();
	assert.equal(store.auto, '0');
	const afterDisable = makeView(file, store);
	afterDisable.methods.otaScheduleWidget();
	assert.equal(only(afterDisable.elements, n => n.tag === 'input' && n.attributes.type === 'checkbox').checked, false,
		'OTA must stay unchecked after save + page reload');

	// Repeated saving of the same values is successful even when the
	// remote session has no staged UCI changes (uci/apply used to error 5).
	const count = notices.length;
	await button.attributes.click();
	assert.equal(events.filter(x => x === 'commit').length, 3);
	assert.equal(notices.length, count + 1);
	assert.equal(notices.at(-1).text, '自动更新设置已保存');

	// A rejected UCI commit must not be reported as a successful save.
	const failed = makeView(file, store, { failCommit: true });
	failed.methods.otaRefresh = async () => {};
	failed.methods.otaScheduleWidget();
	const failedBox = only(failed.elements, n => n.tag === 'input' && n.attributes.type === 'checkbox');
	failedBox.checked = true;
	const failedButton = only(failed.elements, n => n.tag === 'button' && n.children === '保存自动更新设置');
	await failedButton.attributes.click();
	assert.equal(store.auto, '0');
	assert(failed.notices.some(n => n.level === 'error' && n.text.includes('UCI commit failed')));
	assert(!failed.notices.some(n => n.text === '自动更新设置已保存'));

	// RPC returns success but an altered/missing persisted setting is detected.
	const corrupted = makeView(file, store, { skipPersistence: true });
	corrupted.methods.otaRefresh = async () => {};
	corrupted.methods.otaScheduleWidget();
	const badBox = only(corrupted.elements, n => n.tag === 'input' && n.attributes.type === 'checkbox');
	badBox.checked = true;
	const badButton = only(corrupted.elements, n => n.tag === 'button' && n.children === '保存自动更新设置');
	await badButton.attributes.click();
	assert.equal(store.auto, '0');
	assert(corrupted.notices.some(n => n.level === 'error' && n.text.includes('保存后的配置与填写内容不一致')));

	// A later status refresh can be unavailable while the UCI save succeeded.
	const unavailable = makeView(file, store);
	unavailable.methods.otaRefresh = async () => { throw Error('GitHub unavailable'); };
	unavailable.methods.otaScheduleWidget();
	const offlineSave = only(unavailable.elements, n => n.tag === 'button' && n.children === '保存自动更新设置');
	await offlineSave.attributes.click();
	assert(unavailable.notices.some(n => n.text === '自动更新设置已保存'));
	assert(!unavailable.notices.some(n => n.level === 'error'));
}

async function testDrcom() {
	const file = 'files/www/luci-static/resources/view/network/drcom-native.js';
	const store = { auto: '0' };
	const first = makeView(file, store);
	const view = Object.create(first.methods);
	const config = { auto: false, username: 'student', has_password: true, remember: true,
		login_url: 'http://10.0.0.1/0.htm' };
	view.render([config, { ok: false }]);
	assert.equal(view.n('auto').checked, false, 'Dr.COM disabled in UCI must render unchecked');
	assert(first.elements.some(n => n.children === '启用0点自动认证'), 'Dr.COM label not updated');

	view.n('auto').checked = true;
	await view.doAuto();
	assert.equal(store.auto, '1');
	assert.equal(view.n('auto').checked, true);
	const afterEnable = makeView(file, store);
	const enabled = Object.create(afterEnable.methods);
	enabled.render([{ ...config, auto: true }, { ok: false }]);
	assert.equal(enabled.n('auto').checked, true);

	enabled.n('auto').checked = false;
	await enabled.doAuto();
	assert.equal(store.auto, '0');
	const afterDisable = makeView(file, store);
	const disabled = Object.create(afterDisable.methods);
	disabled.render([{ ...config, auto: false }, { ok: false }]);
	assert.equal(disabled.n('auto').checked, false,
		'Dr.COM must stay unchecked after save + page reload');
}

(async () => {
	await testOta();
	await testDrcom();
	console.log('PASS: OTA and Dr.COM checkboxes reflect saved UCI state after reload');
})().catch(error => { console.error(error); process.exitCode = 1; });
