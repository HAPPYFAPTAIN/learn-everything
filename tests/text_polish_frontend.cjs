const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const timers = new Map();
let timerId = 0;
class Element {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase(); this.children = []; this.listeners = {}; this.attributes = {};
    this.dataset = {}; this.style = {}; this.isConnected = true; this.hidden = false; this.disabled = false;
    this.readOnly = false; this.type = ''; this.textContent = ''; this.innerHTML = ''; this.className = '';
  }
  get classList() { return this.className.split(' '); }
  append(...nodes) { nodes.forEach(node => { this.children.push(node); node.parentElement = this; node.isConnected = true; }); }
  after(node) { this.parentElement.append(node); }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(type, callback) { (this.listeners[type] ||= []).push(callback); }
  removeEventListener(type, callback) { this.listeners[type] = (this.listeners[type] || []).filter(item => item !== callback); }
  dispatchEvent(event) { event.target = this; (this.listeners[event.type] || []).slice().forEach(callback => callback(event)); }
  click() { this.dispatchEvent(new Event('click')); }
  matches(selector) { return selector.split(',').some(item => item.toUpperCase() === this.tagName); }
  closest(selector) {
    if (selector.includes('#le-polish-bridge')) return null;
    if (selector.includes('.le-polish-tools') && this.className.includes('le-polish-tools')) return this;
    return null;
  }
  querySelectorAll(selector) {
    const items = this.children.flatMap(child => [child, ...child.querySelectorAll('*')]);
    if (selector === '*') return items;
    if (selector.includes('button')) return items.filter(item => item.tagName === 'BUTTON' || (selector.includes('tabindex') && item.tabIndex === 0));
    if (selector.includes('textarea')) return items.filter(item => item.tagName === 'TEXTAREA' || item.tagName === 'INPUT');
    return [];
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  getClientRects() { return this.hidden ? [] : [this.getBoundingClientRect()]; }
  getBoundingClientRect() { return { left: 20, right: 100, top: 20, bottom: 50, width: 80, height: 30 }; }
  focus() { document.activeElement = this; }
  contains(node) { return node === this || this.querySelectorAll('*').includes(node); }
  showModal() { this.open = true; }
  close() { this.open = false; }
  remove() { this.isConnected = false; if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(node => node !== this); }
  setSelectionRange() {}
}
class Textarea extends Element {
  constructor() { super('textarea'); this._value = ''; }
  get value() { return this._value; }
  set value(value) { this._value = value; }
}
class Input extends Textarea { constructor() { super(); this.tagName = 'INPUT'; this.type = 'text'; } }
class Event {
  constructor(type) { this.type = type; }
  preventDefault() {}
  stopPropagation() {}
}
const container = new Element();
const bridgeRequest = new Textarea();
const bridgeTrigger = new Element('button');
const ids = { 'le-polish-request': bridgeRequest, 'le-polish-trigger': bridgeTrigger };
const document = {
  documentElement: new Element(), body: container, activeElement: null, events: {},
  querySelector(selector) { return selector === '.gradio-container' ? container : null; },
  querySelectorAll() { return []; },
  getElementById(id) { return ids[id] || null; },
  createElement(tag) { return new Element(tag); },
  addEventListener(type, callback) { (this.events[type] ||= []).push(callback); },
};
const window = { addEventListener() {} };
let captured = [];
bridgeTrigger.addEventListener('click', () => { captured.push(JSON.parse(bridgeRequest.value)); });
let source = fs.readFileSync(path.join(__dirname, '../learning_ext/assets/text_polish.js'), 'utf8');
source = source.replace('\n})();', '\n window.__polishTest = { install, begin, receive, apply, undo, sync, invalidate, closeView, unchanged, kindFor, records, record: field => bound.get(field), pending: () => pending, view: () => view };\n})();');
vm.runInNewContext(source, {
  document, window, Event, HTMLTextAreaElement: Textarea, HTMLInputElement: Input,
  innerWidth: 1024, innerHeight: 768,
  getComputedStyle: () => ({ visibility: 'visible' }),
  requestAnimationFrame: () => 1,
  setTimeout(callback, delay) { const id = ++timerId; timers.set(id, { callback, delay }); return id; },
  clearTimeout(id) { timers.delete(id); },
  MutationObserver: class { observe() {} },
});
const api = window.__polishTest;
function flush(delay) {
  [...timers].filter(([, item]) => item.delay === delay).forEach(([id, item]) => { timers.delete(id); item.callback(); });
}
function fixture(value = '请帮我理解 @资料一 的概念') {
  const root = new Element(); root.className = 'le-polishable le-polish-kind-message';
  const field = new Textarea(); field.value = value;
  const file = new Element('input'); file.type = 'file'; file.files = [{ name: 'private.pdf', metadata: 'do not send' }];
  root.append(field, file); container.append(root); api.install(root, field);
  return { root, field, file, record: api.record(field) };
}
function start(record) { api.begin(record); const item = api.view(); flush(80); return item; }
function reply(item, text = '请解释 @资料一 中的概念。') { api.receive({ id: item.id, ok: true, text, changed: true }); }
function edit(field, value) { field.value = value; field.dispatchEvent(new Event('input')); }
const results = {};

const a = fixture();
const originalField = a.field, originalFile = a.file, originalFiles = a.file.files;
let inputEvents = 0, changeEvents = 0;
a.field.addEventListener('input', () => inputEvents++);
a.field.addEventListener('change', () => changeEvents++);
api.begin(a.record);
const initial = api.view();
assert.equal(captured.length, 0);
const payload = JSON.parse(bridgeRequest.value);
assert.deepEqual(Object.keys(payload).sort(), ['id', 'kind', 'text']);
assert.equal(payload.text, a.field.value); assert.equal(payload.kind, 'message');
flush(80); assert.equal(captured.length, 1); results.bridgeDelay = true;
const htmlText = '请解释 @资料一 的概念。<img src=x onerror=alert(1)>';
reply(initial, htmlText);
assert.equal(a.field.value, initial.original); assert.equal(inputEvents, 0);
assert.equal(initial.preview.textContent, htmlText); assert.equal(initial.preview.innerHTML, '');
results.plainTextPreview = true;
api.apply(initial);
assert.equal(a.field.value, htmlText); assert.equal(inputEvents, 1); assert.equal(changeEvents, 1);
results.explicitAdoption = true;
assert.equal(a.root.children[0], originalField); assert.equal(a.root.children[1], originalFile); assert.equal(a.file.files, originalFiles);
assert.equal(captured[0].text.includes('private.pdf'), false); results.attachmentIdentity = true;
api.undo(a.record); assert.equal(a.field.value, initial.original);
let item = start(a.record); reply(item); api.apply(item);
edit(a.field, '用户继续补充的新内容'); api.undo(a.record);
assert.equal(a.field.value, '用户继续补充的新内容'); results.safeUndo = true;

item = start(a.record); const snapshot = a.field.value;
edit(a.field, '临时修改'); edit(a.field, snapshot);
reply(item, '不应覆盖'); api.apply(item);
assert.equal(a.field.value, snapshot); assert.equal(api.view(), null); results.staleEdit = true;

item = start(a.record); api.invalidate(); reply(item, '旧课程结果'); api.apply(item);
assert.equal(a.field.value, snapshot); assert.equal(a.record.undo, null); results.navigation = true;

item = start(a.record); flush(90000);
assert.equal(api.pending(), null); assert.equal(item.panel.dataset.state, 'error');
const retry = start(a.record);
api.receive({ id: item.id, ok: true, text: '过期回复' }); assert.equal(api.pending(), retry);
reply(retry, '重试结果'); api.closeView(); results.timeout = true;

const b = fixture('另一个字段');
item = start(a.record); const calls = captured.length;
api.closeView(); api.begin(b.record); flush(80);
assert.equal(captured.length, calls); assert.equal(api.pending(), item);
reply(item); assert.equal(api.pending(), null); assert.equal(a.field.value, snapshot);
api.begin(b.record); const beforeSend = api.view(); api.closeView(); flush(80);
assert.equal(captured.length, calls); assert.equal(api.pending(), null); assert.equal(beforeSend.sent, false);
results.singleFlight = true;

item = start(b.record); b.field.isConnected = false; api.sync();
assert.equal(api.record(b.field), undefined); assert.equal(b.field.listeners.input.length, 0);
assert.equal(b.record.tools.isConnected, false); reply(item, '已分离字段'); assert.equal(b.field.value, '另一个字段');
results.detachedCleanup = true;

item = start(a.record); a.root.dataset.lePolishKind = 'note'; api.sync();
assert.equal(api.view(), null); reply(item, '旧用途'); assert.equal(a.field.value, snapshot);
item = start(a.record); assert.equal(captured.at(-1).kind, 'note'); reply(item); api.closeView(); results.dynamicKind = true;

const sensitiveRoot = new Element();
for (const type of ['password', 'email', 'url', 'number', 'file', 'search']) {
  const input = new Input(); input.type = type; sensitiveRoot.append(input); api.install(sensitiveRoot, input);
  assert.equal(api.record(input), undefined);
}
const locked = new Textarea(); locked.readOnly = true; sensitiveRoot.append(locked); api.install(sensitiveRoot, locked);
assert.equal(api.record(locked), undefined);
const blank = fixture('   '); api.begin(blank.record); assert.equal(api.pending(), null);
results.sensitiveInputsExcluded = true;
process.stdout.write(JSON.stringify(results));
