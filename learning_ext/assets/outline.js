(() => {
  const KEY_W = 'le.toc.w';
  const KEY_C = 'le.toc.collapsed';
  const MIN_W = 150;
  const MAX_W = 460;
  const DEF_W = 220;

  const root = document.documentElement;

  const row = () => document.getElementById('le-workbench-row');
  const outline = () => document.getElementById('le-lesson-outline');
  const center = () => document.getElementById('le-center-col');
  const gutter = () => document.getElementById('le-toc-gutter');
  const rail = () => document.getElementById('le-scroll-rail');
  const thumb = () => document.getElementById('le-scroll-thumb');

  function readNum(key, fallback) {
    const v = parseFloat(localStorage.getItem(key) || '');
    return Number.isFinite(v) ? v : fallback;
  }
  function readFlag(key) {
    try { return localStorage.getItem(key) === '1'; } catch (e) { return false; }
  }
  function save(key, value) {
    try { localStorage.setItem(key, value); } catch (e) { /* 隐私模式忽略 */ }
  }

  /* ---------- 宽度 ---------- */
  function applyWidth(w) {
    const v = Math.min(MAX_W, Math.max(MIN_W, Math.round(w)));
    root.style.setProperty('--le-toc-w', v + 'px');
    return v;
  }

  function currentWidth() {
    const ol = outline();
    if (!ol) return readNum(KEY_W, DEF_W);
    const w = ol.getBoundingClientRect().width;
    return w > 0 ? w : readNum(KEY_W, DEF_W);
  }

  /* ---------- 收起 ---------- */
  function applyCollapsed(collapsed) {
    const r = row();
    if (!r) return;
    r.classList.toggle('le-toc-collapsed', collapsed);
    const btn = document.getElementById('le-toc-toggle');
    if (btn) {
      btn.textContent = collapsed ? '›' : '‹';
      btn.title = collapsed ? '展开目录' : '收起目录';
      btn.setAttribute('aria-expanded', String(!collapsed));
      btn.setAttribute('aria-label', collapsed ? '展开目录' : '收起目录');
    }
    // 收起时的列宽由 CSS 控制，这里只保证展开态用回用户拖过的宽度
    if (!collapsed) applyWidth(readNum(KEY_W, DEF_W));
    updateThumb();
  }

  /* ---------- 正文滚动指示 ---------- */
  function scrollTopNow() {
    return window.scrollY || document.documentElement.scrollTop || 0;
  }
  function scrollRange() {
    return Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
  }

  function updateThumb() {
    const r = rail();
    const t = thumb();
    if (!r || !t) return;
    const railH = r.clientHeight;
    const totalH = document.documentElement.scrollHeight;
    const viewH = window.innerHeight;
    if (railH <= 0 || totalH <= 0) return;
    const h = Math.max(32, Math.round(railH * Math.min(1, viewH / totalH)));
    t.style.height = h + 'px';
    const maxTop = Math.max(0, railH - h);
    const ratio = scrollRange() > 0 ? Math.min(1, Math.max(0, scrollTopNow() / scrollRange())) : 0;
    t.style.top = Math.round(maxTop * ratio) + 'px';
  }

  function scrollToRatio(ratio) {
    const range = scrollRange();
    const top = Math.min(1, Math.max(0, ratio)) * range;
    window.scrollTo(0, Math.round(top));
  }

  /* ---------- 挂载 ---------- */
  function mount() {
    const r = row();
    const ol = outline();
    if (!r || !ol) return false;
    if (gutter()) return true;

    const g = document.createElement('div');
    g.id = 'le-toc-gutter';
    g.innerHTML =
      '<div id="le-toc-resizer" title="拖动调整目录宽度"></div>' +
      '<div id="le-scroll-rail"><div id="le-scroll-thumb"></div></div>' +
      '<button id="le-toc-toggle" type="button" aria-label="收起目录">‹</button>';

    const c = center();
    if (c) r.insertBefore(g, c);
    else r.appendChild(g);

    bindResizer(g.querySelector('#le-toc-resizer'));
    bindThumb(g.querySelector('#le-scroll-thumb'));
    bindRail(g.querySelector('#le-scroll-rail'));
    bindToggle(g.querySelector('#le-toc-toggle'));

    applyCollapsed(readFlag(KEY_C));
    if (!readFlag(KEY_C)) applyWidth(readNum(KEY_W, DEF_W));
    updateThumb();
    return true;
  }

  function bindResizer(el) {
    if (!el || el.dataset.leBound === '1') return;
    el.dataset.leBound = '1';
    el.addEventListener('pointerdown', (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      const startX = event.clientX;
      const startW = currentWidth();
      el.setPointerCapture(event.pointerId);

      const onMove = (e) => {
        applyWidth(startW + (e.clientX - startX));
        updateThumb();
      };
      const onUp = () => {
        el.removeEventListener('pointermove', onMove);
        el.removeEventListener('pointerup', onUp);
        el.removeEventListener('pointercancel', onUp);
        save(KEY_W, String(Math.round(currentWidth())));
      };
      el.addEventListener('pointermove', onMove);
      el.addEventListener('pointerup', onUp);
      el.addEventListener('pointercancel', onUp);
    });
  }

  function bindThumb(el) {
    if (!el || el.dataset.leBound === '1') return;
    el.dataset.leBound = '1';
    el.addEventListener('pointerdown', (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      event.stopPropagation();
      const r = rail();
      if (!r) return;
      const railH = r.clientHeight;
      const thumbH = el.offsetHeight;
      const maxTop = Math.max(1, railH - thumbH);
      const startY = event.clientY;
      const startTop = el.offsetTop;

      el.classList.add('le-dragging');
      el.setPointerCapture(event.pointerId);

      const onMove = (e) => {
        const top = Math.min(maxTop, Math.max(0, startTop + (e.clientY - startY)));
        scrollToRatio(top / maxTop);
        updateThumb();
      };
      const onUp = () => {
        el.removeEventListener('pointermove', onMove);
        el.removeEventListener('pointerup', onUp);
        el.removeEventListener('pointercancel', onUp);
        el.classList.remove('le-dragging');
      };
      el.addEventListener('pointermove', onMove);
      el.addEventListener('pointerup', onUp);
      el.addEventListener('pointercancel', onUp);
    });
  }

  function bindRail(el) {
    if (!el || el.dataset.leBound === '1') return;
    el.dataset.leBound = '1';
    // 点轨道空白处：把滑块挪过来
    el.addEventListener('pointerdown', (event) => {
      if (event.button !== 0) return;
      if (event.target && event.target.id === 'le-scroll-thumb') return;
      const t = thumb();
      if (!t) return;
      const rect = el.getBoundingClientRect();
      const maxTop = Math.max(1, el.clientHeight - t.offsetHeight);
      const top = Math.min(maxTop, Math.max(0, event.clientY - rect.top - t.offsetHeight / 2));
      scrollToRatio(top / maxTop);
      updateThumb();
    });
  }

  function bindToggle(el) {
    if (!el || el.dataset.leBound === '1') return;
    el.dataset.leBound = '1';
    el.addEventListener('click', (event) => {
      event.preventDefault();
      const r = row();
      if (!r) return;
      const next = !r.classList.contains('le-toc-collapsed');
      applyCollapsed(next);
      save(KEY_C, next ? '1' : '0');
    });
  }

  /* ---------- 启动 ---------- */
  function boot() {
    mount();
    window.addEventListener('scroll', updateThumb, { passive: true });
    window.addEventListener('resize', () => {
      updateThumb();
      if (!thumb()) mount();
    });
    // 正文内容变化（切换课程、Gradio 重绘）后同步一次
    const centerEl = center();
    if (centerEl && centerEl.dataset.leOutlineBound !== '1') {
      centerEl.dataset.leOutlineBound = '1';
      new MutationObserver(() => updateThumb()).observe(centerEl, {
        childList: true,
        subtree: true,
      });
    }
    new MutationObserver(() => {
      if (!gutter()) mount();
      updateThumb();
    }).observe(document.body, { childList: true, subtree: true });
    updateThumb();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }
})();
