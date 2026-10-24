(() => {
  const FAB_KEY = 'le.assistant.fab';
  const WIN_KEY = 'le.assistant.win';
  const FAB_SIZE = 58;
  const MIN_W = 320;
  const MIN_H = 320;
  const EDGE = 12;
  // 只有这三个页面出现助教
  const ALLOWED_TABS = [
    'learning-workbench-tab',
    'learning-review-tab',
    'learning-quiz-tab',
  ];

  const root = document.documentElement;
  const clamp = (v, min, max) => Math.min(Math.max(v, min), Math.max(min, max));
  const vw = () => window.innerWidth;
  const vh = () => window.innerHeight;

  function read(key) {
    try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch (e) { return null; }
  }
  function write(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* 隐私模式忽略 */ }
  }

  const panel = () => document.getElementById('le-global-assistant');
  const fabEl = () => document.getElementById('le-assistant-fab');

  /* ---------- 当前标签 ---------- */
  function activeTabId() {
    const b = document.querySelector('#le-app-tabs > .tab-nav > button.selected');
    if (!b) return null;
    return b.id.replace(/-button$/, '');
  }
  function isAllowedTab() {
    return ALLOWED_TABS.includes(activeTabId());
  }

  /* ---------- 开合 ---------- */
  function isOpen() {
    return document.body.classList.contains('le-assistant-open');
  }
  function setOpen(open) {
    document.body.classList.toggle('le-assistant-open', Boolean(open));
    const fab = fabEl();
    if (fab) {
      fab.classList.toggle('le-fab-hidden', Boolean(open));
      fab.setAttribute('aria-expanded', String(Boolean(open)));
    }
    if (open) {
      ensureRect();
      mountPanelExtras();
      window.setTimeout(() => {
        const ta = document.querySelector('#le-global-assistant #le-chat-compose textarea');
        if (ta) ta.focus();
      }, 60);
    }
  }
  function toggleOpen() { setOpen(!isOpen()); }

  /* ---------- 悬浮球 ---------- */
  function placeFab() {
    const fab = fabEl();
    if (!fab) return;
    const saved = read(FAB_KEY);
    const w = fab.offsetWidth || FAB_SIZE;
    const h = fab.offsetHeight || FAB_SIZE;
    const x = clamp(saved ? saved.x : vw() - w - 28, EDGE, vw() - w - EDGE);
    const y = clamp(saved ? saved.y : vh() - h - 28, EDGE, vh() - h - EDGE);
    fab.style.left = x + 'px';
    fab.style.top = y + 'px';
    fab.style.right = 'auto';
    fab.style.bottom = 'auto';
  }

  function syncFabVisibility() {
    const fab = fabEl();
    if (!fab) return;
    const allowed = isAllowedTab();
    fab.classList.toggle('le-fab-off', !allowed);
    if (!allowed && isOpen()) setOpen(false);
  }

  function mountFab() {
    let fab = fabEl();
    if (fab) {
      placeFab();
      syncFabVisibility();
      fab.classList.toggle('le-fab-hidden', isOpen());
      return true;
    }
    fab = document.createElement('button');
    fab.id = 'le-assistant-fab';
    fab.type = 'button';
    // 图标由 CSS 背景图提供（Q 版助教），这里不再放文字
    fab.title = 'AI 助教';
    fab.setAttribute('aria-label', 'AI 助教');
    fab.setAttribute('aria-controls', 'le-global-assistant');
    fab.setAttribute('aria-expanded', 'false');
    // 挂到 body 级：脱离工作台容器的层叠上下文，避免被侧栏盖住
    document.body.appendChild(fab);
    placeFab();
    syncFabVisibility();
    fab.classList.toggle('le-fab-hidden', isOpen());
    bindFabEvents(fab);
    return true;
  }

  function bindFabEvents(fab) {
    fab.addEventListener('click', (event) => {
      event.preventDefault();
      toggleOpen();
    });

    fab.addEventListener('pointerdown', (event) => {
      if (event.button !== 0) return;
      const rect = fab.getBoundingClientRect();
      const offsetX = event.clientX - rect.left;
      const offsetY = event.clientY - rect.top;
      const startX = event.clientX;
      const startY = event.clientY;
      let moved = false;

      fab.setPointerCapture(event.pointerId);

      const onMove = (e) => {
        if (!moved && Math.abs(e.clientX - startX) < 4 && Math.abs(e.clientY - startY) < 4) return;
        moved = true;
        fab.classList.add('le-dragging');
        const x = clamp(e.clientX - offsetX, EDGE, vw() - rect.width - EDGE);
        const y = clamp(e.clientY - offsetY, EDGE, vh() - rect.height - EDGE);
        fab.style.left = x + 'px';
        fab.style.top = y + 'px';
      };

      const onUp = () => {
        fab.removeEventListener('pointermove', onMove);
        fab.removeEventListener('pointerup', onUp);
        fab.removeEventListener('pointercancel', onUp);
        fab.classList.remove('le-dragging');
        if (!moved) return;
        write(FAB_KEY, { x: parseFloat(fab.style.left), y: parseFloat(fab.style.top) });
        // 拖动结束会补发一次 click，吞掉它，免得顺手把对话框打开
        window.addEventListener('click', (e) => {
          e.stopPropagation();
          e.preventDefault();
        }, { capture: true, once: true });
      };

      fab.addEventListener('pointermove', onMove);
      fab.addEventListener('pointerup', onUp);
      fab.addEventListener('pointercancel', onUp);
    });
  }

  /* ---------- 对话框：位置与尺寸 ---------- */
  function defaultRect() {
    const w = Math.min(420, vw() - 48);
    const h = Math.min(560, Math.max(MIN_H, vh() - 140));
    return { x: vw() - w - 24, y: 96, w, h };
  }

  function applyRect(rect) {
    root.style.setProperty('--le-dlg-x', Math.round(rect.x) + 'px');
    root.style.setProperty('--le-dlg-y', Math.round(rect.y) + 'px');
    root.style.setProperty('--le-dlg-w', Math.round(rect.w) + 'px');
    root.style.setProperty('--le-dlg-h', Math.round(rect.h) + 'px');
  }

  function currentRect() {
    const el = panel();
    if (!el) return defaultRect();
    const r = el.getBoundingClientRect();
    return { x: r.left, y: r.top, w: r.width, h: r.height };
  }

  function ensureRect() {
    const fallback = defaultRect();
    const saved = read(WIN_KEY);
    const w = clamp(saved && saved.w ? saved.w : fallback.w, MIN_W, vw() - EDGE * 2);
    const h = clamp(saved && saved.h ? saved.h : fallback.h, MIN_H, vh() - EDGE * 2);
    const x = clamp(saved && typeof saved.x === 'number' ? saved.x : fallback.x, EDGE, vw() - w - EDGE);
    const y = clamp(saved && typeof saved.y === 'number' ? saved.y : fallback.y, EDGE, vh() - h - EDGE);
    applyRect({ x, y, w, h });
    return { x, y, w, h };
  }

  function mountPanelExtras() {
    const el = panel();
    if (!el) return false;
    if (!document.getElementById('le-assistant-resize')) {
      const handle = document.createElement('div');
      handle.id = 'le-assistant-resize';
      handle.setAttribute('aria-hidden', 'true');
      el.appendChild(handle);
      bindResize(handle);
    }
    bindDialogDrag(el);
    return true;
  }

  function bindDialogDrag(el) {
    const bar = el.querySelector('.le-assistant-heading');
    if (!bar || bar.dataset.leBound === '1') return;
    bar.dataset.leBound = '1';

    bar.addEventListener('pointerdown', (event) => {
      if (event.button !== 0) return;
      if (event.target.closest('button')) return;
      const rect = currentRect();
      const offsetX = event.clientX - rect.x;
      const offsetY = event.clientY - rect.y;
      let moved = false;

      bar.setPointerCapture(event.pointerId);

      const onMove = (e) => {
        moved = true;
        bar.classList.add('le-dragging');
        const x = clamp(e.clientX - offsetX, EDGE, vw() - rect.w - EDGE);
        const y = clamp(e.clientY - offsetY, EDGE, vh() - rect.h - EDGE);
        rect.x = x;
        rect.y = y;
        applyRect(rect);
      };

      const onUp = () => {
        bar.removeEventListener('pointermove', onMove);
        bar.removeEventListener('pointerup', onUp);
        bar.removeEventListener('pointercancel', onUp);
        bar.classList.remove('le-dragging');
        if (moved) write(WIN_KEY, currentRect());
      };

      bar.addEventListener('pointermove', onMove);
      bar.addEventListener('pointerup', onUp);
      bar.addEventListener('pointercancel', onUp);
    });
  }

  function bindResize(handle) {
    handle.addEventListener('pointerdown', (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      const rect = currentRect();
      const startX = event.clientX;
      const startY = event.clientY;
      const baseW = rect.w;
      const baseH = rect.h;

      handle.setPointerCapture(event.pointerId);

      const onMove = (e) => {
        const w = clamp(baseW + (e.clientX - startX), MIN_W, vw() - rect.x - EDGE);
        const h = clamp(baseH + (e.clientY - startY), MIN_H, vh() - rect.y - EDGE);
        applyRect({ x: rect.x, y: rect.y, w, h });
      };

      const onUp = () => {
        handle.removeEventListener('pointermove', onMove);
        handle.removeEventListener('pointerup', onUp);
        handle.removeEventListener('pointercancel', onUp);
        write(WIN_KEY, currentRect());
      };

      handle.addEventListener('pointermove', onMove);
      handle.addEventListener('pointerup', onUp);
      handle.addEventListener('pointercancel', onUp);
    });
  }

  /* ---------- 外部交互 ---------- */
  function bindGlobal() {
    document.addEventListener('click', (event) => {
      if (event.target.closest('[data-le-assistant-close]')) {
        event.preventDefault();
        setOpen(false);
      }
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && isOpen()) setOpen(false);
    });
    // 回车直接发送（Shift+回车才换行）。
    // 输入框是 lines=2 的多行框，Gradio 默认让回车换行，所以这里拦下来手动触发发送。
    document.addEventListener(
      'keydown',
      (event) => {
        if (event.key !== 'Enter') return;
        if (event.shiftKey || event.altKey || event.ctrlKey || event.metaKey) return;
        // 中文输入法正在组词时不要抢回车
        if (event.isComposing || event.keyCode === 229) return;
        const box = event.target && event.target.closest
          ? event.target.closest('#le-chat-compose textarea, #le-chat-input textarea')
          : null;
        if (!box) return;
        event.preventDefault();
        const send = document.getElementById('le-chat-send');
        if (send) send.click();
      },
      true
    );
    window.addEventListener('resize', () => {
      placeFab();
      if (isOpen()) ensureRect();
    });
  }

  /* ---------- 标签切换监听 ---------- */
  function observeTabs() {
    const nav = document.querySelector('#le-app-tabs > .tab-nav');
    if (!nav) return false;
    if (nav.dataset.leFabObserved === '1') return true;
    nav.dataset.leFabObserved = '1';
    // Gradio 切标签时可能只改 class，也可能整个替换按钮节点，所以两种都要盯
    new MutationObserver(() => syncFabVisibility()).observe(nav, {
      attributes: true,
      attributeFilter: ['class'],
      childList: true,
      subtree: true,
    });
    return true;
  }

  /* ---------- 启动 ---------- */
  function boot() {
    mountFab();
    observeTabs();
    syncFabVisibility();
    bindGlobal();
    new MutationObserver(() => {
      if (!fabEl()) mountFab();
      observeTabs();
      syncFabVisibility();
    }).observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }
})();
