(() => {
  const KEY = 'le.nav.collapsed';
  const root = document.documentElement;
  const CHEVRON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 5l-7 7 7 7"/></svg>';

  // 折叠态走 CSS 变量：样式表由 gr.Blocks(css=...) 注入，会被 Gradio 加前缀，
  // 任何以 html.xxx 打头的选择器都会失配，所以状态只改变量，不改选择器层级。
  const OPEN = {
    '--le-nav-w': '226px',
    '--le-nav-x': '0px',
    '--le-brand-w': '226px',
    '--le-brand-pl': '4px',
    '--le-brand-img': '172px',
    '--le-divider-o': '1',
    '--le-toggle-rot': '0deg',
  };
  const CLOSED = {
    '--le-nav-w': '72px',
    '--le-nav-x': '0px',
    '--le-brand-w': '72px',
    '--le-brand-pl': '4px',
    '--le-brand-img': '172px',
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
    const label = collapsed ? '展开导航' : '折叠为图标';
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
    nav.querySelectorAll(':scope > button').forEach(item => {
      const name = item.textContent.trim();
      if (item.title !== name) item.title = name;
      if (item.getAttribute('aria-label') !== name) item.setAttribute('aria-label', name);
    });
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

  // 切回「学习首页」时，点一下屏幕外的刷新桥，让后端重算「有没有课程」——
  // 没有课程时首页不该出现「进入学习工作台」这个入口，建完路线回来才该出现。
  // 走桥不依赖 Gradio 的 tab 事件：4.44 的 Tab.select / Tabs.change 前端都不派发。
  function bindHomeRefresh() {
    if (bindHomeRefresh.done) return;
    bindHomeRefresh.done = true;
    document.addEventListener(
      'click',
      (ev) => {
        const el = ev.target;
        if (!el || !el.closest) return;
        const btn = el.closest('#le-app-tabs > .tab-nav > button');
        if (!btn || !/学习首页/.test(btn.textContent || '')) return;
        setTimeout(() => {
          const trigger = document.getElementById('le-home-refresh');
          if (trigger) trigger.click();
        }, 80);
      },
      true
    );
  }
  bindHomeRefresh();

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }
})();

(() => {
  let entry, panel;
  function close() {
    if (!panel) return;
    panel.hidden = true;
    entry.setAttribute('aria-expanded', 'false');
  }
  async function refreshIdentity() {
    try {
      const response = await fetch('/api/v1/account/context', {cache: 'no-store'});
      if (!response.ok) throw new Error('identity unavailable');
      const data = await response.json();
      const identity = data.identity;
      if (!identity?.user || !identity?.workspace) throw new Error('identity unavailable');
      const name = identity.user.display_name || '用户';
      entry.querySelector('strong').textContent = name;
      entry.querySelector('small').textContent = identity.workspace.name;
      entry.setAttribute('aria-label', name + ' · 账户信息');
      panel.querySelector('[data-account-name]').textContent = name;
      panel.querySelector('[data-account-workspace]').textContent = identity.workspace.name;
      panel.querySelector('[data-account-mode]').textContent = data.mode === 'local' ? '本机保存' : '服务器账户';
      panel.querySelector('[data-account-sync]').textContent = identity.capabilities?.cloud_sync ? '已启用' : '未启用';
    } catch (_) {
      entry.querySelector('strong').textContent = '账户信息';
      entry.querySelector('small').textContent = '暂时无法读取';
      panel.querySelector('[data-account-name]').textContent = '暂时无法读取账户';
      panel.querySelector('[data-account-workspace]').textContent = '—';
      panel.querySelector('[data-account-mode]').textContent = '未连接';
      panel.querySelector('[data-account-sync]').textContent = '—';
    }
  }
  function mount() {
    if (!document.getElementById('le-app-tabs') || document.getElementById('le-account-entry')) return;
    entry = document.createElement('button');
    entry.id = 'le-account-entry'; entry.type = 'button';
    entry.setAttribute('aria-label', '账户信息'); entry.title = '账户信息';
    entry.setAttribute('aria-expanded', 'false'); entry.setAttribute('aria-controls', 'le-account-panel');
    entry.innerHTML = '<span class="le-account-avatar" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/></svg></span><span class="le-account-copy"><strong>账户信息</strong><small>正在读取</small></span>';
    panel = document.createElement('section'); panel.id = 'le-account-panel'; panel.hidden = true;
    panel.setAttribute('aria-label', '账户信息');
    panel.innerHTML = '<header><strong data-account-name>账户信息</strong><button type="button" aria-label="关闭账户信息">×</button></header><dl><div><dt>工作空间</dt><dd data-account-workspace>—</dd></div><div><dt>数据保存</dt><dd data-account-mode>—</dd></div><div><dt>云同步</dt><dd data-account-sync>—</dd></div></dl><button type="button" data-account-refresh>刷新账户信息</button>';
    document.body.append(entry, panel);
    entry.addEventListener('click', () => {
      if (!panel.hidden) { close(); return; }
      panel.hidden = false; entry.setAttribute('aria-expanded', 'true');
      const rect = entry.getBoundingClientRect();
      panel.style.left = Math.min(rect.left, innerWidth - 292) + 'px';
      panel.style.bottom = (innerHeight - rect.top + 8) + 'px';
    });
    panel.querySelector('header button').addEventListener('click', () => { close(); entry.focus(); });
    panel.querySelector('[data-account-refresh]').addEventListener('click', refreshIdentity);
    refreshIdentity();
  }
  document.addEventListener('pointerdown', e => { if (!entry?.contains(e.target) && !panel?.contains(e.target)) close(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && panel && !panel.hidden) { close(); entry.focus(); } });
  window.addEventListener('resize', close);
  window.addEventListener('le:account-changed', () => { if (entry) refreshIdentity(); });
  const start = () => { mount(); new MutationObserver(() => { if (!entry?.isConnected) mount(); }).observe(document.body, {childList:true, subtree:true}); };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once:true}); else start();
})();
