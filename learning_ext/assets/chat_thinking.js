(() => {
  const STORE_KEY = 'le.chat.thinking.v1';
  const TOKEN_PREFIX = 'saved-connection:';
  const ROOT_ID = 'le-chat-connection-controls';
  const SECTION_ID = 'le-chat-thinking';
  const EFFORTS = ['low', 'high', 'max'];
  const LABELS = {low: 'Low', high: 'High', max: 'Max'};
  const THINKING_MODELS = ['kimi-k3.1', 'glm-5.3'];
  const DEFAULTS = {effort: 'low', show_thinking: false};
  const DEFAULT_VALUES = ['(default)', 'default', '默认', '默认模型'];
  const SETTLE = [80, 220, 480, 900, 1500];

  let memory = null, timers = [], retries = 0, frame = 0;

  function readStore() {
    try {
      const raw = localStorage.getItem(STORE_KEY);
      if (raw === null) return memory || {};
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
    } catch (error) {
      return memory || {};
    }
  }
  function clean(value) {
    if (!value || typeof value !== 'object') return {};
    const result = {};
    if (EFFORTS.includes(value.effort)) result.effort = value.effort;
    if (typeof value.show_thinking === 'boolean') result.show_thinking = value.show_thinking;
    return result;
  }
  function prefsFor(key) {
    const saved = clean(readStore()[key]);
    return {
      effort: saved.effort || DEFAULTS.effort,
      show_thinking: typeof saved.show_thinking === 'boolean' ? saved.show_thinking : DEFAULTS.show_thinking,
    };
  }
  function savePrefs(key, patch) {
    if (!key || key.length > 120) return;
    const store = readStore(), next = {};
    Object.keys(store).filter(name => name && name !== key && name.length <= 120).slice(-30).forEach(name => {
      const saved = clean(store[name]);
      if (Object.keys(saved).length) next[name] = saved;
    });
    next[key] = Object.assign(prefsFor(key), clean(patch));
    memory = next;
    try { localStorage.setItem(STORE_KEY, JSON.stringify(next)); } catch (error) {}
  }

  function bare(value) {
    const text = typeof value === 'string' ? value.trim().toLowerCase() : '';
    if (!text || DEFAULT_VALUES.includes(text)) return '';
    const segment = text.split('/').pop().split(':')[0].trim().replace(/[._+-]+$/, '');
    return /^[a-z0-9][a-z0-9._+-]*$/.test(segment) ? segment : '';
  }
  function keyOf(value) {
    const match = String(value || '').match(/(?:kimi-k3\.1|glm-5\.3)[a-z0-9._-]*/i);
    return match ? bare(match[0]) : bare(value);
  }
  function lookup(value) {
    return keyOf(value) || keyOf(String(value || '').replace(/\s+/g, '-'));
  }
  function capable(key) {
    return !!key && THINKING_MODELS.some(prefix => key.startsWith(prefix));
  }
  function modelField(root) {
    return root.querySelector('input[aria-label="回答模型"], textarea[aria-label="回答模型"]');
  }
  function defaultKey() {
    const host = document.getElementById('le-chat-default-model');
    if (!host) return '';
    const field = host.matches('input,textarea') ? host : host.querySelector('input,textarea');
    return lookup(field ? field.value : host.textContent);
  }
  function currentKey(root) {
    const field = modelField(root);
    const value = field ? String(field.value || '').trim() : '';
    if (value && !DEFAULT_VALUES.includes(value.toLowerCase())) return lookup(value);
    const fieldToken = tokenField(root);
    const token = decodeToken(fieldToken ? fieldToken.value : '');
    if (token && typeof token[0] === 'string' && token[0]) return token[1] ? lookup(token[1]) : '';
    return defaultKey();
  }

  function decodeToken(raw) {
    if (typeof raw !== 'string' || !raw.startsWith(TOKEN_PREFIX)) return null;
    try {
      const base64 = raw.slice(TOKEN_PREFIX.length).replace(/-/g, '+').replace(/_/g, '/');
      const padded = base64 + '='.repeat((4 - base64.length % 4) % 4);
      const binary = atob(padded);
      const bytes = Uint8Array.from(binary, character => character.charCodeAt(0));
      const parsed = JSON.parse(new TextDecoder().decode(bytes));
      return Array.isArray(parsed) && parsed.length >= 2 ? parsed : null;
    } catch (error) {
      return null;
    }
  }
  function encodeToken(record, model, prefs) {
    const bytes = new TextEncoder().encode(JSON.stringify([record, model, prefs]));
    let binary = '';
    bytes.forEach(byte => { binary += String.fromCharCode(byte); });
    return TOKEN_PREFIX + btoa(binary).replace(/\+/g, '-').replace(/\//g, '_');
  }
  function tokenField(root) {
    const host = document.getElementById('le-chat-model-token');
    if (host) {
      const field = host.matches('input,textarea') ? host : host.querySelector('input,textarea');
      if (field) return field;
    }
    for (const field of document.querySelectorAll('#chat-tab input[aria-label="回答模型"], #chat-tab textarea[aria-label="回答模型"]')) {
      if (!root.contains(field) && String(field.value || '').startsWith(TOKEN_PREFIX)) return field;
    }
    return null;
  }
  function writeToken(field, value) {
    const proto = field.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
    if (setter) setter.call(field, value); else field.value = value;
    field.dispatchEvent(new Event('input', {bubbles: true}));
    field.dispatchEvent(new Event('change', {bubbles: true}));
    // Gradio 的 Dropdown 只在 blur 时把自定义值写回组件状态。
    field.dispatchEvent(new Event('blur'));
  }

  function attribute(node, name, value) {
    if (node.getAttribute(name) !== value) node.setAttribute(name, value);
  }
  function paint(section, prefs) {
    section.querySelectorAll('[role=radio]').forEach(button => {
      const active = button.dataset.leEffort === prefs.effort;
      attribute(button, 'aria-checked', active ? 'true' : 'false');
      const tabIndex = active ? 0 : -1;
      if (button.tabIndex !== tabIndex) button.tabIndex = tabIndex;
    });
    attribute(section.querySelector('[role=switch]'), 'aria-checked', prefs.show_thinking ? 'true' : 'false');
  }
  function choose(section, effort) {
    if (!EFFORTS.includes(effort)) return;
    const root = section.closest('#' + ROOT_ID);
    if (!root) return;
    const key = currentKey(root);
    if (!capable(key)) return;
    savePrefs(key, {effort});
    sync();
  }
  function toggleThinking(section) {
    const root = section.closest('#' + ROOT_ID);
    if (!root) return;
    const key = currentKey(root);
    if (!capable(key)) return;
    savePrefs(key, {show_thinking: !prefsFor(key).show_thinking});
    sync();
  }
  function build() {
    const section = document.createElement('div');
    section.id = SECTION_ID;
    section.className = 'le-thinking';
    section.hidden = true;
    section.innerHTML = '<div class="le-thinking-row"><span class="le-thinking-label" id="le-chat-thinking-effort-label">思考</span><div class="le-thinking-seg" role="radiogroup" aria-labelledby="le-chat-thinking-effort-label">'
      + EFFORTS.map(effort => `<button type="button" role="radio" data-le-effort="${effort}" aria-checked="false" tabindex="-1">${LABELS[effort]}</button>`).join('')
      + '</div></div><div class="le-thinking-row"><span class="le-thinking-label" id="le-chat-thinking-display-label">思考过程</span><button type="button" class="le-thinking-switch" role="switch" aria-checked="false" aria-labelledby="le-chat-thinking-display-label"><span aria-hidden="true"></span></button></div>';
    section.addEventListener('click', event => {
      event.stopPropagation();
      const button = event.target.closest('button');
      if (!button) return;
      if (button.dataset.leEffort) choose(section, button.dataset.leEffort);
      else if (button.getAttribute('role') === 'switch') toggleThinking(section);
    });
    section.addEventListener('input', event => event.stopPropagation());
    section.addEventListener('change', event => event.stopPropagation());
    section.addEventListener('keydown', event => {
      const radio = event.target.closest('[role=radio]');
      if (!radio) return;
      const step = {ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1}[event.key];
      let index = null;
      if (step) index = (EFFORTS.indexOf(radio.dataset.leEffort) + step + EFFORTS.length) % EFFORTS.length;
      else if (event.key === 'Home') index = 0;
      else if (event.key === 'End') index = EFFORTS.length - 1;
      if (index === null) return;
      event.preventDefault();
      event.stopPropagation();
      const buttons = radio.parentElement.querySelectorAll('[role=radio]');
      choose(section, buttons[index].dataset.leEffort);
      buttons[index].focus();
    });
    return section;
  }
  function sectionFor(root) {
    let section = document.getElementById(SECTION_ID);
    if (!section) section = build();
    if (root.lastElementChild !== section) root.append(section);
    return section;
  }

  function samePrefs(value, prefs) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
    return Object.keys(value).every(key => key === 'effort' || key === 'show_thinking')
      && value.effort === prefs.effort
      && value.show_thinking === prefs.show_thinking;
  }
  function sync() {
    const root = document.getElementById(ROOT_ID);
    if (!root) return;
    const section = sectionFor(root);
    const key = currentKey(root);
    const supported = capable(key);
    if (section.hidden === supported) section.hidden = !supported;
    if (!supported) {
      if (section.contains(document.activeElement)) modelField(root)?.focus();
      retries = 0;
      return;
    }
    const prefs = prefsFor(key);
    paint(section, prefs);
    const field = tokenField(root);
    if (!field) return;
    const token = decodeToken(field.value);
    const tokenModel = token && typeof token[1] === 'string' ? token[1] : '';
    if (tokenModel && bare(tokenModel) !== key) {
      if (retries < 8) {
        retries += 1;
        setTimeout(sync, 350);
      }
      return;
    }
    retries = 0;
    const record = token && typeof token[0] === 'string' ? token[0] : '';
    const preferences = {effort: prefs.effort, show_thinking: prefs.show_thinking};
    if (token && token[0] === record && token[1] === tokenModel && samePrefs(token[2], preferences)) return;
    const next = encodeToken(record, tokenModel, preferences);
    if (field.value !== next) {
      writeToken(field, next);
      setTimeout(sync, 600);
    }
  }
  function schedule() {
    timers.forEach(clearTimeout);
    timers = SETTLE.map(delay => setTimeout(sync, delay));
  }
  function queueSync() {
    if (frame) return;
    frame = requestAnimationFrame(() => { frame = 0; sync(); });
  }

  const observer = new MutationObserver(records => {
    const root = document.getElementById(ROOT_ID);
    for (const record of records) {
      if (record.type !== 'childList') continue;
      if (root && (record.target === root || root.contains(record.target))) { queueSync(); return; }
      const nodes = Array.from(record.addedNodes).concat(Array.from(record.removedNodes));
      if (nodes.some(node => node.nodeType === 1 && (node.id === ROOT_ID || node.id === SECTION_ID || node.querySelector?.('#' + ROOT_ID)))) {
        queueSync();
        return;
      }
    }
  });
  observer.observe(document.documentElement, {childList: true, subtree: true});
  document.addEventListener('input', event => {
    const root = document.getElementById(ROOT_ID);
    if (!root || !root.contains(event.target) || event.target.closest('#' + SECTION_ID)) return;
    retries = 0;
    schedule();
  });
  document.addEventListener('change', event => {
    const root = document.getElementById(ROOT_ID);
    if (!root || !root.contains(event.target) || event.target.closest('#' + SECTION_ID)) return;
    schedule();
  });
  window.addEventListener('storage', event => { if (event.key === STORE_KEY) queueSync(); });
  setInterval(() => {
    const deck = document.querySelector('.le-settings-deck[open]');
    if (!deck || !deck.querySelector('#' + ROOT_ID)) return;
    sync();
  }, 800);
  sync();
})();

(() => {
  const BOT_ID = 'main-chat-bot';
  const REASONING = 'details.le-reasoning';
  const MAX_KEYS = 400;
  const states = new Map();
  let bot = null, observer = null, frame = 0;

  function hash(text) {
    let value = 5381;
    for (let index = 0; index < text.length; index += 1) {
      value = ((value << 5) + value + text.charCodeAt(index)) | 0;
    }
    return (value >>> 0).toString(36);
  }
  function questionOf(row) {
    let node = row.previousElementSibling;
    while (node) {
      if (node.classList && node.classList.contains('user-row')) {
        const message = node.querySelector('.message.user');
        return String((message || node).textContent || '').replace(/\s+/g, ' ').trim().slice(0, 500);
      }
      node = node.previousElementSibling;
    }
    return '';
  }
  function keyFor(row, index) {
    return index + ':' + hash(questionOf(row));
  }
  function blocksOf(row) {
    return Array.from(row.querySelectorAll(REASONING));
  }
  function save(details) {
    if (!bot || !bot.contains(details)) return;
    const row = details.closest('.message-row.bot-row');
    if (!row) return;
    const rows = Array.from(bot.querySelectorAll('.message-row.bot-row'));
    const index = rows.indexOf(row), ordinal = blocksOf(row).indexOf(details);
    if (index < 0 || ordinal < 0) return;
    const key = keyFor(row, index), list = states.get(key) || [];
    list[ordinal] = details.open;
    states.delete(key);
    states.set(key, list);
    while (states.size > MAX_KEYS) states.delete(states.keys().next().value);
  }
  function restore() {
    if (!bot) return;
    const rows = Array.from(bot.querySelectorAll('.message-row.bot-row'));
    rows.forEach((row, index) => {
      const list = states.get(keyFor(row, index));
      if (!list) return;
      blocksOf(row).forEach((details, ordinal) => {
        if (list[ordinal] === true && !details.open) details.open = true;
      });
    });
  }
  function onToggle(event) {
    const details = event.target;
    if (!details || details.tagName !== 'DETAILS' || !details.classList.contains('le-reasoning')) return;
    save(details);
  }
  function schedule() {
    if (frame) return;
    frame = requestAnimationFrame(() => { frame = 0; restore(); });
  }
  function bind() {
    const next = document.getElementById(BOT_ID);
    if (!next) {
      if (bot) {
        observer?.disconnect();
        observer = null;
        bot = null;
      }
      return;
    }
    if (next === bot) {
      restore();
      return;
    }
    observer?.disconnect();
    bot = next;
    observer = new MutationObserver(schedule);
    observer.observe(bot, {childList: true, subtree: true});
    bot.addEventListener('toggle', onToggle, true);
    restore();
  }

  new MutationObserver(() => { if (!bot || !bot.isConnected) bind(); })
    .observe(document.documentElement, {childList: true, subtree: true});
  bind();
})();
