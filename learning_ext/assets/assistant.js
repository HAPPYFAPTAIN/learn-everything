(() => {
  const FAB_KEY = 'le.assistant.fab';
  const WIN_KEY = 'le.assistant.win';
  const FAB_SIZE = 58;
  const MIN_W = 320;
  const MIN_H = 320;
  const EDGE = 12;
  // 这三个页面使用课程、卡片或题目作为专属上下文
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
  function focusFab() {
    window.setTimeout(() => {
      const fab = fabEl();
      if (fab && !isOpen() && !fab.classList.contains('le-fab-off')) fab.focus();
    }, 0);
  }
  function setOpen(open, restoreFocus = false) {
    const wasOpen = isOpen();
    document.body.classList.toggle('le-assistant-open', Boolean(open));
    const fab = fabEl();
    if (fab) {
      fab.classList.toggle('le-fab-hidden', Boolean(open));
      fab.setAttribute('aria-expanded', String(Boolean(open)));
    }
    if (open) {
      ensureRect();
      mountPanelExtras();
      syncEmptyState();
      window.setTimeout(() => {
        const ta = document.querySelector('#le-global-assistant #le-chat-compose textarea');
        if (ta) ta.focus();
      }, 60);
    } else if (wasOpen && restoreFocus) {
      focusFab();
    }
  }
  function toggleOpen() {
    const open = !isOpen();
    setOpen(open, !open);
  }

  /* ---------- 悬浮球与顶栏入口 ---------- */
  function placeFab() {
    const fab = fabEl();
    if (!fab || fab.classList.contains('le-dragging')) return;
    const topbar = document.querySelector('.le-topbar');
    const docked = vw() <= 800 || !isAllowedTab();
    if (docked && topbar) {
      if (fab.parentElement !== topbar) topbar.appendChild(fab);
      fab.classList.add('le-fab-docked');
      fab.style.removeProperty('left');
      fab.style.removeProperty('top');
      fab.style.removeProperty('right');
      fab.style.removeProperty('bottom');
      return;
    }
    fab.classList.remove('le-fab-docked');
    if (fab.parentElement !== document.body) document.body.appendChild(fab);
    const saved = read(FAB_KEY);
    const w = fab.offsetWidth || FAB_SIZE;
    const h = fab.offsetHeight || FAB_SIZE;
    const savedX = saved && Number.isFinite(saved.x) ? saved.x : vw() - w - 28;
    const savedY = saved && Number.isFinite(saved.y) ? saved.y : vh() - h - 28;
    const x = clamp(savedX, EDGE, vw() - w - EDGE);
    const y = clamp(savedY, EDGE, vh() - h - EDGE);
    fab.style.left = x + 'px';
    fab.style.top = y + 'px';
    fab.style.right = 'auto';
    fab.style.bottom = 'auto';
  }

  function syncFabVisibility() {
    const fab = fabEl();
    if (!fab) return;
    placeFab();
    fab.classList.remove('le-fab-off');
    syncEmptyState();
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
    fab.title = '以太小助';
    fab.setAttribute('aria-label', '以太小助');
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
      if (event.button !== 0 || vw() <= 800 || fab.classList.contains('le-fab-docked')) return;
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
  function dialogLimits() {
    const maxW = Math.max(0, vw() - EDGE * 2);
    const maxH = Math.max(0, vh() - EDGE * 2);
    return { maxW, maxH, minW: Math.min(MIN_W, maxW), minH: Math.min(MIN_H, maxH) };
  }

  function defaultRect() {
    const { maxW, maxH, minH } = dialogLimits();
    const w = Math.min(420, maxW);
    const h = Math.min(560, Math.max(minH, vh() - 140), maxH);
    const x = clamp(vw() - w - 24, EDGE, vw() - w - EDGE);
    const y = clamp(96, EDGE, vh() - h - EDGE);
    return { x, y, w, h };
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
    const { maxW, maxH, minW, minH } = dialogLimits();
    const savedW = saved && Number.isFinite(saved.w) ? saved.w : fallback.w;
    const savedH = saved && Number.isFinite(saved.h) ? saved.h : fallback.h;
    const savedX = saved && Number.isFinite(saved.x) ? saved.x : fallback.x;
    const savedY = saved && Number.isFinite(saved.y) ? saved.y : fallback.y;
    const w = clamp(savedW, minW, maxW);
    const h = clamp(savedH, minH, maxH);
    const x = clamp(savedX, EDGE, vw() - w - EDGE);
    const y = clamp(savedY, EDGE, vh() - h - EDGE);
    applyRect({ x, y, w, h });
    return { x, y, w, h };
  }

  function mountPanelExtras() {
    const el = panel();
    if (!el) return false;
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-label', '以太小助');
    if (!document.getElementById('le-assistant-resize')) {
      const handle = document.createElement('div');
      handle.id = 'le-assistant-resize';
      handle.setAttribute('aria-hidden', 'true');
      el.appendChild(handle);
      bindResize(handle);
    }
    bindDialogDrag(el);
    syncEmptyState();
    return true;
  }

  function bindDialogDrag(el) {
    const bar = el.querySelector('.le-assistant-heading');
    if (!bar || bar.dataset.leBound === '1') return;
    bar.dataset.leBound = '1';

    bar.addEventListener('pointerdown', (event) => {
      if (event.button !== 0 || vw() <= 800) return;
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
      if (event.button !== 0 || vw() <= 800) return;
      event.preventDefault();
      const rect = currentRect();
      const startX = event.clientX;
      const startY = event.clientY;
      const baseW = rect.w;
      const baseH = rect.h;

      handle.setPointerCapture(event.pointerId);

      const onMove = (e) => {
        const { minW, minH } = dialogLimits();
        const maxW = Math.max(minW, vw() - rect.x - EDGE);
        const maxH = Math.max(minH, vh() - rect.y - EDGE);
        const w = clamp(baseW + (e.clientX - startX), minW, maxW);
        const h = clamp(baseH + (e.clientY - startY), minH, maxH);
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

  function cleanText(value, limit = 180) {
    const text = String(value || '').replace(/\s+/g, ' ').trim();
    return text.length > limit ? text.slice(0, limit - 1) + '…' : text;
  }

  function domText(selector, limit) {
    const el = document.querySelector(selector);
    return el ? cleanText(el.textContent, limit) : '';
  }

  function domValue(selector) {
    const el = document.querySelector(selector);
    return el && typeof el.value === 'string' ? cleanText(el.value, 120) : '';
  }

  function emptyContext() {
    const tab = activeTabId();
    if (tab === 'learning-review-tab') {
      const card = domText('#le-review-card', 180);
      const stats = domText('#le-review-stats', 100);
      return {
        label: '间隔复习 · 当前卡片',
        title: card || '还没有打开复习卡片',
        detail: stats,
        questions: ['给我一点回忆提示', '这张卡容易和什么概念混淆？', '帮我用一句话记住它'],
      };
    }
    if (tab === 'learning-quiz-tab') {
      const question = domText('#le-quiz-question', 200);
      return {
        label: '查漏测验 · 当前题目',
        title: question || '还没有开始测验',
        detail: '',
        questions: ['给我一点解题提示', '这道题在考哪个知识点？', '我答完后，帮我分析思路'],
      };
    }
    if (tab !== 'learning-workbench-tab') {
      return {
        label: '以太小助 · 学习助手',
        title: '学习规划、理解与复习',
        detail: '',
        questions: ['帮我拆解一个学习目标', '怎样安排今天的学习？', '帮我检查自己的理解'],
      };
    }
    const course = domText('#le-center-content h3', 140) || domValue('#le-course-picker input');
    const project = domValue('#le-project-picker input');
    return {
      label: '学习工作台 · 当前课程',
      title: course || '还没有选择课程',
      detail: project ? `学习项目：${project}` : '',
      questions: ['用简单的例子解释这一节', '这一节最需要记住什么？', '出一个问题检查我的理解'],
    };
  }

  function syncEmptyState() {
    const empty = document.getElementById('le-assistant-empty');
    const chat = document.getElementById('le-assistant-chat');
    if (!empty || !chat) return;
    const hasMessages = Boolean(chat.querySelector('.message-wrap > .message-row'));
    empty.hidden = hasMessages;
    chat.classList.toggle('le-assistant-chat-empty', !hasMessages);
    chat.setAttribute('aria-hidden', String(!hasMessages));
    if (hasMessages) return;
    const context = emptyContext();
    ['label', 'title', 'detail'].forEach((name) => {
      const el = empty.querySelector(`[data-le-assistant-context-${name}]`);
      if (!el) return;
      el.hidden = name === 'detail' && !context[name];
      if (el.textContent !== context[name]) el.textContent = context[name];
    });
    const buttons = empty.querySelectorAll('[data-le-assistant-suggestion]');
    buttons.forEach((button, index) => {
      const question = context.questions[index] || '';
      button.hidden = !question;
      if (button.textContent !== question) button.textContent = question;
      button.dataset.leAssistantSuggestion = question;
    });
  }

  function fillAssistantInput(question) {
    const input = document.querySelector('#le-global-assistant #le-chat-compose textarea');
    if (!input) return;
    input.value = cleanText(question, 500);
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.focus();
    const end = input.value.length;
    if (input.setSelectionRange) input.setSelectionRange(end, end);
  }

  /* ---------- 外部交互 ---------- */
  function bindGlobal() {
    document.addEventListener('click', (event) => {
      const suggestion = event.target.closest('#le-assistant-empty [data-le-assistant-suggestion]');
      if (suggestion) {
        event.preventDefault();
        fillAssistantInput(suggestion.dataset.leAssistantSuggestion || suggestion.textContent);
        return;
      }
      if (event.target.closest('[data-le-assistant-close]')) {
        event.preventDefault();
        setOpen(false, true);
      }
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && isOpen()) {
        event.preventDefault();
        setOpen(false, true);
      }
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
