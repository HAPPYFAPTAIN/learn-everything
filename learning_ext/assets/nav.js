(() => {
  const KEY = 'le.nav.collapsed';
  const root = document.documentElement;
  const CHEVRON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 5l-7 7 7 7"/></svg>';

  // 折叠态走 CSS 变量：样式表由 gr.Blocks(css=...) 注入，会被 Gradio 加前缀，
  // 任何以 html.xxx 打头的选择器都会失配，所以状态只改变量，不改选择器层级。
  const OPEN = {
    '--le-nav-w': '216px',
    '--le-nav-x': '0px',
    '--le-brand-w': '216px',
    '--le-brand-pl': '16px',
    '--le-brand-img': '148px',
    '--le-divider-o': '1',
    '--le-toggle-rot': '0deg',
  };
  const CLOSED = {
    '--le-nav-w': '0px',
    '--le-nav-x': '216px',
    '--le-brand-w': '176px',
    '--le-brand-pl': '12px',
    '--le-brand-img': '116px',
    '--le-divider-o': '0',
    '--le-toggle-rot': '180deg',
  };

  const navEl = () => document.querySelector('#le-app-tabs > .tab-nav');

  function readState() {
    try { return localStorage.getItem(KEY) === '1'; } catch (e) { return false; }
  }
  function saveState(collapsed) {
    try { localStorage.setItem(KEY, collapsed ? '1' : '0'); } catch (e) { /* 隐私模式忽略 */ }
  }

  let button = null;

  function syncButton(collapsed) {
    if (!button) return;
    button.setAttribute('aria-expanded', String(!collapsed));
    const label = collapsed ? '展开菜单' : '收起菜单';
    button.setAttribute('aria-label', label);
    button.setAttribute('title', label);
  }

  function apply(collapsed) {
    const vars = collapsed ? CLOSED : OPEN;
    Object.keys(vars).forEach((name) => root.style.setProperty(name, vars[name]));
    root.classList.toggle('le-nav-collapsed', collapsed);
    syncButton(collapsed);
  }

  function toggle() {
    const next = !root.classList.contains('le-nav-collapsed');
    apply(next);
    saveState(next);
    if (next && button) button.focus({ preventScroll: true });
  }

  function mountToggle() {
    const brand = document.querySelector('#le-brand-bar .le-brand');
    if (!brand) return false;
    const existing = brand.querySelector('#le-nav-toggle');
    if (existing) {
      button = existing;
      syncButton(root.classList.contains('le-nav-collapsed'));
      return true;
    }
    button = document.createElement('button');
    button.id = 'le-nav-toggle';
    button.type = 'button';
    button.innerHTML = CHEVRON;
    button.addEventListener('click', toggle);
    brand.appendChild(button);
    syncButton(root.classList.contains('le-nav-collapsed'));
    return true;
  }

  // 顶栏面包屑跟着当前标签走，切页时 Gradio 只改按钮的 class，所以盯 class 变化
  let crumbObserver = null;

  function syncBreadcrumb() {
    const nav = navEl();
    const span = document.querySelector('.le-app-title span');
    if (!nav || !span) return false;
    const btn = nav.querySelector(':scope > button.selected') || nav.querySelector(':scope > button');
    if (!btn) return false;
    const label = (btn.textContent || '').replace(/\s+/g, ' ').trim();
    if (!label) return false;
    const next = '/ ' + label;
    if (span.textContent.trim() !== next) span.textContent = next;
    return true;
  }

  function mountBreadcrumb() {
    if (!document.querySelector('.le-app-title') || !navEl()) return false;
    if (crumbObserver) return syncBreadcrumb();
    crumbObserver = new MutationObserver(syncBreadcrumb);
    crumbObserver.observe(navEl(), {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['class'],
    });
    return syncBreadcrumb();
  }

  // 首屏解析时就落地，避免刷新闪一下展开态
  apply(readState());

  function boot() {
    const todo = () => {
      const jobs = [];
      if (!document.getElementById('le-nav-toggle')) jobs.push(mountToggle);
      if (!document.querySelector('.le-app-title span')) jobs.push(mountBreadcrumb);
      else if (!crumbObserver) jobs.push(mountBreadcrumb);
      return jobs;
    };

    let jobs = todo();
    if (!jobs.length) return;
    jobs.forEach((fn) => fn());

    let tries = 0;
    const timer = setInterval(() => {
      jobs = todo();
      if (!jobs.length || ++tries > 60) clearInterval(timer);
      else jobs.forEach((fn) => fn());
    }, 200);

    // Gradio 局部重绘后把按钮和面包屑补回来
    const observer = new MutationObserver(() => {
      const pending = todo();
      if (pending.length) pending.forEach((fn) => fn());
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }
})();
