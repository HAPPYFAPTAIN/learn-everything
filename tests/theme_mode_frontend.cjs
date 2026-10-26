const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('learning_ext/assets/theme_mode.js', 'utf8');

function element() {
  const classes = new Set();
  return {dataset:{}, style:{}, classList:{toggle(name,on){ on ? classes.add(name) : classes.delete(name); }, contains(name){return classes.has(name);}},
    append(){}, remove(){}, sheet:{cssRules:[]}, querySelectorAll(){return [];} };
}
function load(saved = null, dark = false, fails = false) {
  const root = element(), body = element(), container = element(), listeners = {}, documentListeners = {}, emitted = [], stored = [];
  let calls = 0;
  const preference = {matches:dark, addEventListener(type, callback){ listeners.media = callback; }};
  const doc = {documentElement:root, body, head:element(), readyState:'loading', createElement:element,
    querySelectorAll(){return [container];}, addEventListener(type, callback){documentListeners[type] = callback;},
    dispatchEvent(event){emitted.push(event);}};
  const context = {document:doc, window:{matchMedia(){return preference;}, addEventListener(type, callback){listeners[type] = callback;}},
    localStorage:{getItem(){return saved;}, setItem(key,value){stored.push([key,value]);}}, CustomEvent: class {constructor(type,options){this.type=type;this.detail=options.detail;}},
    fetch(){calls++; return fails && calls === 1 ? Promise.reject(new Error('offline')) : Promise.resolve({ok:true,text(){return Promise.resolve('');}});}, setTimeout, Date };
  const exported = source.replace(/\}\)\(\);\s*$/, 'globalThis.testTheme={apply,splitSelectors,scopeSelector,scopeRules,loadDarkCss};\n})();');
  vm.runInNewContext(exported, context);
  return {root, body, container, listeners, emitted, stored, preference, api:context.testTheme, calls:()=>calls};
}
(async () => {
  const system = load(null, true);
  assert(system.root.classList.contains('le-dark'));
  assert.equal(system.root.dataset.leThemeMode, 'system');
  system.preference.matches = false; system.listeners.media();
  assert(system.container.classList.contains('le-light'));
  assert.equal(system.stored.length, 0);
  system.api.apply('dark');
  system.preference.matches = false; system.listeners.media();
  assert(system.root.classList.contains('le-dark'));
  assert.deepEqual(system.stored[0], ['le.theme.mode', 'dark']);
  system.listeners.storage({key:'le.theme.mode',newValue:'light'});
  assert(system.root.classList.contains('le-light'));
  system.listeners.storage({key:null,newValue:null});
  assert.equal(system.root.dataset.leThemeMode, 'system');
  const legacy = load('light', true);
  assert(legacy.root.classList.contains('le-light'));
  assert.equal(legacy.root.style.colorScheme, 'light');
  assert.equal(legacy.calls(), 0);

  const selector = '#le-app-tabs :is(p,li,label,small), .gradio-container [data-name="x,y"]:not(:is(a,b))';
  const split = Array.from(legacy.api.splitSelectors(selector));
  assert.equal(split.length, 2);
  const rules = [{selectorText:selector}, {cssRules:[{selectorText:'.gradio-container :is(input,textarea)::placeholder'}]}];
  legacy.api.scopeRules(rules);
  assert.equal((rules[0].selectorText.match(/gradio-container\.le-dark/g)||[]).length, 2);
  assert(rules[0].selectorText.includes(':is(p,li,label,small)'));
  assert(rules[1].cssRules[0].selectorText.includes(':is(input,textarea)::placeholder'));

  const retry = load('dark', true, true);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(retry.root.dataset.leThemeStatus, 'retry');
  await retry.api.loadDarkCss();
  assert.equal(retry.calls(), 2);
  assert.equal(retry.root.dataset.leThemeStatus, 'ready');
  retry.api.apply('light');
  assert(retry.root.classList.contains('le-light'));
  assert.equal(retry.emitted.at(-1).detail.resolved, 'light');
  console.log('Theme behavior: system, legacy preference, storage sync, selector scoping, CSS retry passed.');
})();
