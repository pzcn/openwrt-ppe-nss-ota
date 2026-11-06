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

function makeView(file, store) {
	const elements = [];
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
			value: attributes.value ?? '',
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
			get: (pkg, section, key) => store[key] ?? null,
			set: (pkg, section, key, value) => { store[key] = value; },
			save: async () => {},
			apply: async () => {}
		},
		rpc: {
			declare: ({ method }) => {
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
			addNotification: () => {}
		}
	};

	const src = fs.readFileSync(path.join(root, file), 'utf8');
	const methods = vm.runInNewContext('(function() {\n' + src + '\n})()', sandbox, { filename: file });
	return { methods, elements };
}

function only(elements, predicate) {
	const matched = elements.filter(predicate);
	assert.equal(matched.length, 1, 'expected exactly one control, found ' + matched.length);
	return matched[0];
}

async function testOta() {
	const store = { auto: '0', hour: '9', delay: '2' };
	const file = 'files/www/luci-static/resources/view/system/flash.js';
	const { methods, elements } = makeView(file, store);
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
