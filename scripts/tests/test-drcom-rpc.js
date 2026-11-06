#!/usr/bin/env node
/*
 * Execute the Dr.COM RPC's URL-save logic with a mock UCI backend.
 * Only the two Ucode-specific constructs are adapted to JavaScript.
 * This complements static checks; it is not a native ucode VM test.
 */
'use strict';

const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

const root = path.resolve(__dirname, '../..');
const backend = path.join(root, 'files/usr/share/rpcd/ucode/luci.drcom');
let source = fs.readFileSync(backend, 'utf8');
source = source.replace(/^#![^\n]*\n/, '');
source = source.replace(/^import \{[^}]*\} from '[^']+';\s*$/gm, '');
source = source.replace(/for \(let key in keys\(changes\)\)/g,
	'for (let key of Object.keys(changes))');
source = source.replace(
	/return \{ 'luci\.drcom': methods \};\s*$/,
	'globalThis.__methods = methods;'
);
assert(!source.includes("import {"));
assert(source.includes("globalThis.__methods = methods;"));

const state = {
	disk: { login_url: '', logout_url: '', remember: '0', auto: '0' },
	failSet: false, throwSet: false, failCommit: false, failChmod: false, failLoad: false
};

function cursor() {
	let local = { ...state.disk };
	return {
		load(name) {
			assert.strictEqual(name, 'drcom');
			return !state.failLoad;
		},
		get(pkg, section, key) {
			assert.strictEqual(pkg, 'drcom');
			assert.strictEqual(section, 'main');
			return local[key] ?? null;
		},
		set(pkg, section, key, value) {
			assert.strictEqual(pkg, 'drcom');
			assert.strictEqual(section, 'main');
			if (state.throwSet) throw new Error('Synthetic UCI write exception');
			if (state.failSet) return null;
			if (value === '') delete local[key];
			else local[key] = value;
			return true;
		},
		delete(pkg, section, key) {
			delete local[key];
			return true;
		},
		commit(pkg) {
			assert.strictEqual(pkg, 'drcom');
			if (state.failCommit) return null;
			state.disk = { ...local };
			return true;
		},
		unload(name) { assert.strictEqual(name, 'drcom'); return true; }
	};
}

const context = {
	cursor,
	chmod: () => !state.failChmod,
	match: (value, pattern) => value.match(pattern),
	length: (value) => value.length,
	type: (value) => typeof value === 'boolean' ? 'bool' : typeof value,
	keys: (value) => Object.keys(value),
	readfile: () => null, open: () => null, unlink: () => true,
	popen: () => null, sprintf: () => '',
	trim: (s) => s.trim(),
	system: () => 0,
};
vm.runInNewContext(source, context, { filename: 'luci.drcom' });
const methods = context.__methods;
assert(methods && methods.save_urls && methods.save_credentials && methods.get_config);

function save(login_url, logout_url) {
	return methods.save_urls.call({ args: { login_url, logout_url } });
}
function get() { return methods.get_config.call(); }

const url1 = 'http://192.168.15.1:8800/0.htm';
const url2 = 'http://192.168.15.1:8800/F.htm';
const result = save(url1, url2);
assert.strictEqual(result.ok, true, JSON.stringify(result));
assert.strictEqual(result.backend_revision, 'drcom-rpc12');
assert.strictEqual(result.login_url, url1);
assert.strictEqual(result.logout_url, url2);
assert.strictEqual(state.disk.login_url, url1);
assert.strictEqual(get().login_url, url1);

const url3 = 'http://gate.example.edu/0.htm';
const url4 = 'http://gate.example.edu/F.htm?session=1';
const updated = save(url3, url4);
assert.strictEqual(updated.ok, true, JSON.stringify(updated));
assert.strictEqual(get().logout_url, url4);
assert.strictEqual(state.disk.login_url, url3);

const bad = save('foo', url4);
assert.strictEqual(bad.ok, false);
assert.strictEqual(bad.code, 'invalid_url');
assert.strictEqual(get().login_url, url3);

state.failSet = true;
const badSet = save(url1, url2);
assert.strictEqual(badSet.ok, false);
assert.strictEqual(badSet.code, 'uci_set');
state.failSet = false;

state.throwSet = true;
const thrownSet = save(url1, url2);
assert.strictEqual(thrownSet.ok, false);
assert.strictEqual(thrownSet.code, 'backend_exception_uci_set');
assert(!JSON.stringify(thrownSet).includes(url1), 'Backend exception must not include input URLs');
state.throwSet = false;

state.failCommit = true;
const badCommit = save(url1, url2);
assert.strictEqual(badCommit.ok, false);
assert.strictEqual(badCommit.code, 'uci_commit');
assert.strictEqual(get().login_url, url3);
state.failCommit = false;

state.failLoad = true;
const badLoad = save(url1, url2);
assert.strictEqual(badLoad.ok, false);
assert.strictEqual(badLoad.code, 'uci_load');
state.failLoad = false;

state.failChmod = true;
const badChmod = save(url1, url2);
assert.strictEqual(badChmod.ok, false);
assert.strictEqual(badChmod.code, 'chmod');
state.failChmod = false;

const final = save(url3, url4);
assert.strictEqual(final.ok, true);
assert.strictEqual(get().backend_revision, 'drcom-rpc12');

// The credential card must persist address, username and password in one action.
function saveCredentials(login_url, logout_url, username, password) {
	return methods.save_credentials.call({ args: { login_url, logout_url, username, password } });
}

const invalidUser = saveCredentials(url1, url2, '', 'private123');
assert.strictEqual(invalidUser.ok, false);
assert.strictEqual(invalidUser.code, 'invalid_username');

const password1 = 's3cr3tPassword123';
const account1 = saveCredentials(url1, url2, 'student_a', password1);
assert.strictEqual(account1.ok, true, JSON.stringify(account1));
assert.strictEqual(account1.username, 'student_a');
assert.strictEqual(account1.has_password, true);
assert.strictEqual(account1.login_url, url1);
assert.strictEqual(state.disk.login_url, url1);
assert.strictEqual(state.disk.logout_url, url2);
assert.strictEqual(state.disk.username, 'student_a');
assert.strictEqual(state.disk.password, password1);
assert.strictEqual(state.disk.remember, '1');
assert.strictEqual(get().username, 'student_a');
assert.strictEqual(get().has_password, true);
assert(!JSON.stringify(account1).includes(password1), 'Save response must never expose the password');
assert(!JSON.stringify(get()).includes(password1), 'Get response must never expose the password');

// Editing the gateway with an empty password keeps the same user's password.
const updateAddress = saveCredentials(url3, url4, 'student_a', '');
assert.strictEqual(updateAddress.ok, true);
assert.strictEqual(state.disk.login_url, url3);
assert.strictEqual(state.disk.password, password1);

// Changing the username without a new password must not reuse someone else's secret.
const changeWithoutPassword = saveCredentials(url3, url4, 'student_b', '');
assert.strictEqual(changeWithoutPassword.ok, false);
assert.strictEqual(changeWithoutPassword.code, 'invalid_password');
assert.strictEqual(state.disk.username, 'student_a');

const password2 = 'newPassword456';
const replaced = saveCredentials(url3, url4, 'student_b', password2);
assert.strictEqual(replaced.ok, true);
assert.strictEqual(state.disk.username, 'student_b');
assert.strictEqual(state.disk.password, password2);
assert(!JSON.stringify(replaced).includes(password2));
assert.strictEqual(get().username, 'student_b');

state.failCommit = true;
const failedCredSave = saveCredentials(url1, url2, 'student_b', 'updatedPass');
assert.strictEqual(failedCredSave.ok, false);
assert.strictEqual(failedCredSave.code, 'uci_save');
assert.strictEqual(state.disk.password, password2);
state.failCommit = false;

console.log('PASS: Dr.COM RPC persists URLs and credentials, preserves unchanged passwords, and hides secrets');
