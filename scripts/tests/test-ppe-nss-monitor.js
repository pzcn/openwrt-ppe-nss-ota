#!/usr/bin/env node
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '../..');
const source = fs.readFileSync(path.join(root,
	'files/www/luci-static/resources/view/status/ppe-nss-monitor-native.js'), 'utf8');

function E(tag, props, children) {
	if (typeof props !== 'object' || !props || Array.isArray(props)) {
		children = props;
		props = {};
	}
	const node = {
		tag, props, children, textContent: typeof children === 'string' ? children : '',
		isConnected: true,
		querySelector(selector) {
			const match = selector.match(/^\[data-nss="([^"]+)"\]$/);
			if (!match)
				throw new Error('Unexpected selector ' + selector);
			return walk(this).find(item => item.props['data-nss'] === match[1]) || null;
		}
	};
	return node;
}

function walk(tree) {
	const nodes = [];
	function visit(node) {
		if (Array.isArray(node))
			node.forEach(visit);
		else if (node && typeof node === 'object' && node.tag) {
			nodes.push(node);
			visit(node.children);
		}
	}
	visit(tree);
	return nodes;
}

const sample = {
	schema: 1,
	conntrack: { available: true, hardware: 35, software: 12, total: 190 },
	ppe: { hw_setting: true, offload_stats: 'rx 1234', debugfs_found: true },
	nss: { wifi_active: true, visible_cores: 2, running_cores: 2,
		wifi_config: '1', flows_found: true },
	telemetry: {
		ppe: { live_entries: 5, offloaded_total: 87, table_full: 3,
			rejected_total: 16, xmit_drop: 1 },
		ppe_ports: { ports: 2, packets: 300, bytes: 220000, drop_packets: 1 },
		nss: { installed: 2, bridged_installed: 1, pushed_total: 29,
			bridged_active: 2 },
		wifi: { vdevs: 2, reports: 42, rx_bytes: 750000,
			rx_packets: 125, tx_packets: 112, rx_enqueue_fail: 3,
			tx_dropped: 4, tx_ring_full: 1 }
	}
};
let poller = null, frequency = null, status = sample, clock = 100000;
const sandbox = {
	E,
	view: { extend: methods => methods },
	rpc: { declare: () => () => Promise.resolve(status) },
	poll: {
		add(fn, period) { poller = fn; frequency = period; },
		remove(fn) { assert.equal(fn, poller); poller = null; }
	},
	L: {
		resolveDefault: promise => promise,
		bind: (fn, ctx, ...args) => fn.bind(ctx, ...args)
	},
	Date: { now: () => clock }, Promise, isFinite
};

const methods = vm.runInNewContext('(function() {\n' + source + '\n})()', sandbox);
const page = Object.create(methods);
const tree = page.render(sample);
const nodes = walk(tree);
const text = nodes.map(n => n.textContent).filter(Boolean);
const value = name => tree.querySelector('[data-nss="' + name + '"]')?.textContent;

assert(text.includes('PPE / NSS 硬件加速'));
assert(text.includes('加速引擎'));
assert(text.includes('连接统计'));
assert(text.includes('内核诊断'));
assert(!text.includes('监控状态'));
assert(!text.includes('最近 24 次采样'));
assert(!text.includes('暂停自动刷新'));
assert(!text.includes('立即刷新'));
assert.equal(nodes.filter(n => n.tag === 'table').length, 2);
assert.equal(nodes.filter(n => n.tag === 'details').length, 1);
assert.equal(nodes.filter(n => n.tag === 'button').length, 0);
assert.equal(frequency, 8);
assert.equal(typeof poller, 'function');

assert.equal(value('ppe-state'), '已启用（配置）');
assert.equal(value('wifi-state'), '已启用（模块参数）');
assert.equal(value('nss-state'), '2 / 2 运行');
assert.equal(value('ppe-live'), '5');
assert.equal(value('nss-live'), '2');
assert.equal(value('nss-bridged'), '1');
assert.equal(value('ppe-offloaded'), '87');
assert.equal(value('nss-pushed'), '29');
assert.equal(value('ppe-rate'), '采样中');
assert.equal(value('wifi-rate'), '采样中');
assert.equal(value('wifi-rx'), '125');
assert.equal(value('wifi-tx'), '112');
assert.equal(value('hw'), '35');
assert.equal(value('sw'), '12');
assert.equal(value('ct'), '190');
assert(value('ppe-debug').includes('rx 1234'));
assert(value('nss-debug').includes('NSS Wi-Fi 虚拟接口'));
clock += 8000;
page.apply({
	...sample,
	telemetry: {
		...sample.telemetry,
		ppe_ports: { ...sample.telemetry.ppe_ports, bytes: 1220000 },
		wifi: { ...sample.telemetry.wifi, rx_bytes: 1750000 }
	}
});
assert.equal(value('ppe-rate'), '1.00 Mb/s');
assert.equal(value('wifi-rate'), '1.00 Mb/s');

// A 32-bit counter wrap/reboot must NOT display a negative/fictitious rate.
clock += 8000;
page.apply({
	...sample,
	telemetry: {
		...sample.telemetry,
		ppe_ports: { ...sample.telemetry.ppe_ports, bytes: 100 },
		wifi: { ...sample.telemetry.wifi, rx_bytes: 100 }
	}
});
assert.equal(value('ppe-rate'), '采样中');
assert.equal(value('wifi-rate'), '采样中');

page.apply({
	schema: 1,
	conntrack: { available: false },
	ppe: { hw_setting: false },
	nss: { wifi_active: false, visible_cores: 0 }
});
assert.equal(value('ppe-state'), '未启用（配置）');
assert.equal(value('wifi-state'), '未启用（模块参数）');
assert.equal(value('hw'), '—');
assert.equal(value('ppe-live'), '—');
assert.equal(value('nss-state'), '未知');

page.apply(null);
assert.equal(value('ppe-state'), '读取失败');
assert.equal(value('ct'), '—');

(async () => {
	status = sample;
	await poller();
	assert.equal(value('hw'), '35');

	status = null;
	await poller();
	assert.equal(value('ppe-state'), '读取失败');

	tree.isConnected = false;
	await poller();
	assert.equal(poller, null);
	console.log('PASS: compact PPE / NSS dashboard, polling, values and unavailable states');
})().catch(e => { console.error(e); process.exitCode = 1; });
