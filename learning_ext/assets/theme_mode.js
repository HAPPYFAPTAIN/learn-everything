(() => {
  const STORAGE_KEY = 'le.theme.mode';
  const ASSETS_BASE = '__LE_ASSETS__';
  const DARK_URL = ASSETS_BASE + '/dark_theme.css';
  const root = document.documentElement;
  const preference = window.matchMedia('(prefers-color-scheme: dark)');
  const modes = ['light', 'dark', 'system'];
  const labels = {light: '白日模式', dark: '暗黑模式', system: '跟随系统'};
  let mode = 'system';
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (modes.includes(saved)) mode = saved;
  } catch (_) {}

  const icons = {
    light: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    dark: '<path d="M20.4 14.1A8 8 0 0 1 9.9 3.6 8.5 8.5 0 1 0 20.4 14Z"/>',
    system: '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8M12 17v4"/>',
  };
  const icon = name => '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + icons[name] + '</svg>';
  const darkStyle = document.createElement('style');
  darkStyle.id = 'le-dark-theme';
  document.head.append(darkStyle);
  const DARK_SCOPE = '.gradio-container.le-dark.le-dark.le-dark';
  let darkCssPromise = null;
  let button, menu;

  function splitSelectors(selectorText) {
    const selectors = [];
    let start = 0, depth = 0, quote = '', escaped = false;
    for (let index = 0; index < selectorText.length; index++) {
      const char = selectorText[index];
      if (escaped) { escaped = false; continue; }
      if (char === '\\') { escaped = true; continue; }
      if (quote) { if (char === quote) quote = ''; continue; }
      if (char === '"' || char === "'") { quote = char; continue; }
      if (char === '(' || char === '[') depth++;
      else if (char === ')' || char === ']') depth--;
      else if (char === ',' && depth === 0) { selectors.push(selectorText.slice(start, index)); start = index + 1; }
    }
    selectors.push(selectorText.slice(start));
    return selectors;
  }

  function scopeSelector(selector) {
    const value = selector.trim();
    if (!value) return value;
    if (value === ':root' || value === 'html' || value.startsWith('html.')) return 'html.le-dark';
    if (value === 'body' || value.startsWith('body ') || value.startsWith('body:') || value.startsWith('html ')) {
      return 'html.le-dark ' + (value.startsWith('html ') ? value.slice(5) : value);
    }
    if (value.startsWith('#le-global-assistant') || value.startsWith('#le-assistant') || value.startsWith('.le-assistant')) return 'html.le-dark ' + value;
    if (value.startsWith('.gradio-container')) return DARK_SCOPE + value.slice('.gradio-container'.length);
    return DARK_SCOPE + ' ' + value;
  }

  function scopeRules(rules) {
    for (const rule of rules) {
      if (rule.selectorText !== undefined) rule.selectorText = splitSelectors(rule.selectorText).map(scopeSelector).join(',');
      else if (rule.cssRules) scopeRules(rule.cssRules);
    }
  }

  function scopeDarkCss(css) {
    const parsed = document.createElement('style');
    parsed.media = 'not all';
    parsed.textContent = css;
    document.head.append(parsed);
    try {
      scopeRules(parsed.sheet.cssRules);
      return Array.from(parsed.sheet.cssRules, rule => rule.cssText).join('\n').replaceAll('__ASSETS__', ASSETS_BASE);
    } finally { parsed.remove(); }
  }

  function loadDarkCss() {
    if (!darkCssPromise) {
      darkCssPromise = fetch(DARK_URL + '?v=' + Date.now(), {cache: 'no-store'}).then(response => {
        if (!response.ok) throw new Error('HTTP ' + response.status);
        return response.text();
      }).then(scopeDarkCss).then(css => {
        darkStyle.textContent = css;
        root.dataset.leThemeStatus = 'ready';
      }).catch(() => {
        darkCssPromise = null;
        root.dataset.leThemeStatus = 'retry';
      });
    }
    return darkCssPromise;
  }

  const isDark = () => mode === 'dark' || (mode === 'system' && preference.matches);

  function syncContainers() {
    document.querySelectorAll('.gradio-container').forEach(element => {
      element.classList.toggle('le-dark', isDark());
      element.classList.toggle('le-light', !isDark());
    });
  }

  function apply(nextMode, persist = true) {
    mode = modes.includes(nextMode) ? nextMode : 'system';
    const dark = isDark();
    root.classList.toggle('le-dark', dark);
    root.classList.toggle('le-light', !dark);
    root.dataset.leThemeMode = mode;
    root.style.colorScheme = dark ? 'dark' : 'light';
    if (document.body) {
      document.body.classList.toggle('le-dark', dark);
      document.body.classList.toggle('le-light', !dark);
    }
    syncContainers();
    if (dark) loadDarkCss();
    if (button) {
      button.innerHTML = icon(mode);
      button.setAttribute('aria-label', '显示模式：' + labels[mode]);
      button.title = '显示模式 · ' + labels[mode];
    }
    if (menu) menu.querySelectorAll('[data-theme]').forEach(item => item.setAttribute('aria-checked', String(item.dataset.theme === mode)));
    if (persist) {
      try { localStorage.setItem(STORAGE_KEY, mode); } catch (_) {}
    }
    document.dispatchEvent(new CustomEvent('le:theme-change', {detail: {mode, resolved: dark ? 'dark' : 'light'}}));
  }

  function closeMenu(restoreFocus = false) {
    if (!menu || menu.hidden) return;
    menu.hidden = true;
    button.setAttribute('aria-expanded', 'false');
    if (restoreFocus) button.focus();
  }

  function placeMenu() {
    if (!menu || menu.hidden) return;
    const rect = button.getBoundingClientRect();
    const width = menu.offsetWidth;
    const height = menu.offsetHeight;
    const left = Math.max(10, Math.min(rect.right - width, window.innerWidth - width - 10));
    const top = rect.bottom + height + 10 < window.innerHeight ? rect.bottom + 8 : Math.max(10, rect.top - height - 8);
    menu.style.left = left + 'px';
    menu.style.top = top + 'px';
  }

  function openMenu(last = false) {
    menu.hidden = false;
    button.setAttribute('aria-expanded', 'true');
    placeMenu();
    const options = menu.querySelectorAll('[data-theme]');
    (last ? options[options.length - 1] : menu.querySelector('[aria-checked="true"]') || options[0]).focus();
  }

  let retries = 0;
  function mount() {
    syncContainers();
    const topbar = document.querySelector('.le-topbar');
    if (!topbar) {
      if (retries++ < 100) setTimeout(mount, 100);
      return;
    }
    if (document.getElementById('le-theme-toggle')) return;
    button = document.createElement('button');
    button.id = 'le-theme-toggle';
    button.type = 'button';
    button.setAttribute('aria-haspopup', 'menu');
    button.setAttribute('aria-expanded', 'false');
    button.setAttribute('aria-controls', 'le-theme-menu');
    menu = document.createElement('div');
    menu.id = 'le-theme-menu';
    menu.hidden = true;
    menu.setAttribute('role', 'menu');
    menu.setAttribute('aria-label', '显示模式');
    menu.innerHTML = modes.map(value => '<button type="button" role="menuitemradio" data-theme="' + value + '">' + icon(value) + '<span>' + labels[value] + '</span><span class="le-theme-check" aria-hidden="true">✓</span></button>').join('');
    menu.addEventListener('click', event => {
      const item = event.target.closest('[data-theme]');
      if (item) { apply(item.dataset.theme); closeMenu(true); }
    });
    button.addEventListener('click', () => menu.hidden ? openMenu() : closeMenu());
    button.addEventListener('keydown', event => {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); openMenu(event.key === 'ArrowUp'); }
    });
    menu.addEventListener('keydown', event => {
      const options = Array.from(menu.querySelectorAll('[data-theme]'));
      const current = options.indexOf(document.activeElement);
      let next = current;
      if (event.key === 'ArrowDown') next = (current + 1) % options.length;
      else if (event.key === 'ArrowUp') next = (current - 1 + options.length) % options.length;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = options.length - 1;
      else if (event.key === 'Escape') { event.preventDefault(); closeMenu(true); return; }
      else if (event.key === 'Tab') { closeMenu(true); return; }
      else return;
      event.preventDefault();
      options[next].focus();
    });
    document.addEventListener('pointerdown', event => { if (!button.contains(event.target) && !menu.contains(event.target)) closeMenu(); });
    document.addEventListener('focusin', event => { if (!button.contains(event.target) && !menu.contains(event.target)) closeMenu(); });
    window.addEventListener('resize', placeMenu, {passive: true});
    document.addEventListener('scroll', placeMenu, {passive: true, capture: true});
    const local = topbar.querySelector('.le-local');
    if (local) local.after(button); else topbar.append(button);
    document.body.append(menu, darkStyle);
    apply(mode, false);
  }

  preference.addEventListener('change', () => { if (mode === 'system') apply(mode, false); });
  window.addEventListener('storage', event => { if (event.key === STORAGE_KEY || event.key === null) apply(event.newValue || 'system', false); });
  apply(mode, false);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once: true});
  else mount();
})();
