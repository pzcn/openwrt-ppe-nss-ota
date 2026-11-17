#!/usr/bin/env node
'use strict';

// Exercise the actual LuCI OTA settings renderer and UCI save callback.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(path.resolve(__dirname,
  '../../files/www/luci-static/resources/view/system/flash.js'), 'utf8');
const options = {
  auto: '0', hour: '4', delay: '1',
  github_proxy: 'direct', github_proxy_url: '',
};
const notifications = [];

function E(tag, attrs, data) {
  const attributes = attrs && typeof attrs === 'object' && !Array.isArray(attrs) ? attrs : {};
  const contents = data === undefined ? (Array.isArray(attrs) ? attrs :
    (typeof attrs === 'string' ? [attrs] : [])) :
    (Array.isArray(data) ? data : [data]);
  const listeners = {};
  const node = {
    tag, attrs: attributes, children: contents, listeners, hidden: false,
    value: attributes.value || '',
    checked: attributes.checked != null,
    disabled: !!attributes.disabled,
    addEventListener(event, fn) { listeners[event] = fn; },
    appendChild(child) { contents.push(child); },
    replaceChildren(...children) { this.children = children; },
  };
  if (tag === 'select') {
    const chosen = contents.find(x => x && x.attrs && x.attrs.selected != null);
    node.value = chosen?.attrs.value || '';
  }
  return node;
}
function collect(node, pred, out = []) {
  if (node && typeof node === 'object') {
    if (pred(node)) out.push(node);
    for (const child of node.children || []) collect(child, pred, out);
  }
  return out;
}
const uci = {
  get(_pkg, _section, key) { return options[key]; },
  set(_pkg, _section, key, value) { options[key] = value; },
  save() { return Promise.resolve(); },
  load() { return Promise.resolve(); },
  unload() {},
};
const ui = {
  createHandlerFn(self, cb) { return typeof cb === 'function' ? cb.bind(self) : self[cb].bind(self); },
  addNotification(_title, element, level) { notifications.push({ element, level }); },
};
const rpc = { declare() { return () => Promise.resolve(); } };
const dependencies = [
  { extend: v => v }, {}, {}, rpc, {}, ui, uci, E,
  { hasViewPermission() { return true; } }, x => x
];
const view = new Function('view', 'dom', 'form', 'rpc', 'fs', 'ui', 'uci',
  'E', 'L', '_', source)(...dependencies);
view.otaRefresh = () => Promise.resolve();

(async () => {
  const panel = view.otaScheduleWidget();
  const mode = collect(panel, n => n.tag === 'select' &&
    collect(n, x => x.tag === 'option' && x.attrs.value === 'ghfast').length > 0)[0];
  const custom = collect(panel, n => n.tag === 'input' &&
    n.attrs.placeholder === 'https://proxy.example.com')[0];
  const save = collect(panel, n => n.tag === 'button' &&
    n.children.includes('保存设置'))[0];
  assert.ok(mode && custom && save);
  const values = collect(mode, n => n.tag === 'option').map(n => n.attrs.value);
  assert.deepEqual(values, ['direct', 'ghfast', 'ghproxy', 'gh_proxy', 'custom']);
  assert.equal(mode.value, 'direct');

  mode.value = 'ghproxy';
  mode.listeners.change();
  await save.attrs.click();
  assert.equal(options.github_proxy, 'ghproxy');
  assert.equal(options.github_proxy_url, '');

  mode.value = 'custom';
  mode.listeners.change();
  custom.value = 'https://my-proxy.example/gh/';
  await save.attrs.click();
  assert.equal(options.github_proxy, 'custom');
  assert.equal(options.github_proxy_url, 'https://my-proxy.example/gh');

  custom.value = 'http://unsafe.example';
  await save.attrs.click();
  assert.equal(options.github_proxy_url, 'https://my-proxy.example/gh');
  assert.equal(notifications.at(-1).level, 'error');

  // Download progress is measured from actual bytes, not parsed curl text.
  ui.showModal = function(title, body) { assert.equal(title, '在线固件更新'); };
  ui.hideModal = function() {};
  view._otaInstallButton = { disabled: false };
  view._otaStatus = { update: true };
  view.otaOpenProgressModal();
  assert.equal(view._otaRunning, true);
  assert.equal(view._otaInstallButton.disabled, true);
  const now = Date.now;
  let timestamp = 10000;
  Date.now = function() { return timestamp; };
  try {
    view.otaUpdateProgress({
      stage: 'downloading', downloaded: 1024 * 1024, total: 4 * 1024 * 1024,
      message: '正在下载'
    }, '正在下载固件');
    assert.equal(view._otaMeter.value, 25);
    assert.equal(view._otaMeter.hidden, false);
    timestamp += 1500;
    view.otaUpdateProgress({
      stage: 'downloading', downloaded: 2 * 1024 * 1024, total: 4 * 1024 * 1024
    }, '');
    assert.equal(view._otaMeter.value, 50);
    assert.match(view._otaNumbers.textContent, /MiB\/s/);
    view.otaUpdateProgress({ stage: 'verifying', downloaded: 4 * 1024 * 1024,
      total: 4 * 1024 * 1024 }, '');
    assert.equal(view._otaMeter.value, 100);
    assert.match(view._otaPhaseText.textContent, /校验/);
    view.otaShowFailure('image SHA256 mismatch', '');
    assert.equal(view._otaRunning, false);
    assert.match(view._otaStageHelp.textContent, /完整性校验/);
  }
  finally {
    Date.now = now;
  }
  console.log('PASS: LuCI OTA proxy presets, custom URL validation and UCI commit');
})().catch(e => { console.error(e); process.exitCode = 1; });
