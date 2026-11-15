#!/usr/bin/env node
'use strict';

// Test the actual LuCI view's render() without a running router. The OTA
// section must be inserted into the rendered Backup/Flash Actions tab.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '../..');
const source = fs.readFileSync(path.join(root,
  'files/www/luci-static/resources/view/system/flash.js'), 'utf8');
assert.ok(!source.includes("s.option(form.SectionValue, 'online_upgrade'"),
  'OTA must not depend on nested SectionValue rendering');
assert.ok(!source.includes('[data-tab="actions"]'),
  'The Actions tab identifier may be localized and is not safe for DOM lookup');

function E(tag, attributes, contents) {
  const attrs = (attributes && typeof attributes === 'object' &&
    !Array.isArray(attributes)) ? attributes : {};
  const child = contents === undefined ? (
    typeof attributes === 'string' ? attributes : []
  ) : contents;
  return {
    tag, attrs, children: Array.isArray(child) ? child : [child],
    addEventListener() {},
    appendChild(value) { this.children.push(value); return value; },
  };
}

function section() {
  return {
    option() { return { subsection: section(), value() {} }; },
    render() { return Promise.resolve(E('div', {})); },
  };
}

let localizedActions = false;
class FakeJSONMap {
  section(type, id, sectionType) {
    if (id === 'actions') {
      assert.equal(sectionType, '操作',
        'The real LuCI NamedSection has a localized section type');
      localizedActions = true;
    }
    return section();
  }
  render() { return Promise.resolve(renderRoot); }
}

const actions = E('div', { 'data-section-id': 'actions' }, []);
const requestedSelectors = [];
const renderRoot = {
  querySelector(selector) {
    requestedSelectors.push(selector);
    // Real LuCI can render data-tab="操作" or data-tab="Actions".
    // A literal data-tab="actions" MUST NOT find the target.
    if (selector.includes('[data-tab='))
      return null;
    return selector.includes('[data-section-id="actions"]') ? actions : null;
  },
};
const L = {
  hasViewPermission() { return true; },
  bind(fn, self, ...args) { return fn.bind(self, ...args); },
};
const deps = [
  { extend(view) { return view; } }, // view
  {}, // dom
  { JSONMap: FakeJSONMap, NamedSection: {}, SectionValue: {},
    Button: {}, ListValue: {}, DummyValue: {}, TextValue: {} }, // form
  { declare() { return () => Promise.resolve({}); } }, // rpc
  {}, // fs
  { createHandlerFn() { return () => {}; } }, // ui
  { get(_cfg, _section, option) { return option === 'auto' ? '0' : ''; } }, // uci
  E, L,
];

const load = new Function('view', 'dom', 'form', 'rpc', 'fs', 'ui', 'uci',
  'E', 'L', '_', source);
const page = load(...deps, x => x === 'Actions' ? '操作' : x);
let calls = 0;
page.otaRefresh = function() { calls++; return Promise.resolve(); };

function collect(node, match, output = []) {
  if (node && typeof node === 'object') {
    if (match(node)) output.push(node);
    for (const child of node.children || []) collect(child, match, output);
  }
  return output;
}

(async () => {
  await page.render([{ type: 'file' }, 'mx4200', '', '', '']);
  assert.equal(calls, 1, 'OTA refresh must run after rendering');
  assert.equal(localizedActions, true, 'Chinese LuCI section must be exercised');
  assert.ok(requestedSelectors.every(x => !x.includes('[data-tab=')),
    'The DOM selector must not depend on a translated tab ID');
  assert.equal(actions.children.length, 1,
    'One OTA section must be inserted in the Actions tab');
  const panel = actions.children[0];
  assert.equal(panel.attrs.id, 'native-integrated-ota');
  assert.ok(collect(panel, n => n.tag === 'h3' &&
    n.children.includes('在线固件更新')).length);
  assert.ok(collect(panel, n => n.children?.includes('重新检查')).length);
  assert.ok(collect(panel, n => n.children?.includes('下载并安装新版本')).length);
  assert.ok(page._otaInfo && page._otaInstallButton,
    'Status and install controls must be attached to the live view');
  console.log('PASS: native Backup/Flash OTA panel rendered exactly once');
})().catch(err => { console.error(err); process.exitCode = 1; });
