(() => {
  if (window.LETextPolish) return;
  const selector = '.le-polishable,[data-le-polish-kind],#coach-goal,#coach-criteria';
  const navigation = '#le-app-tabs > .tab-nav button,[role="tab"],#le-project-picker,#le-course-picker,[data-coach-course],#le-action-previous,#le-action-next,#le-action-close';
  const records = new Set(), bound = new WeakMap();
  let pending = null, view = null, epoch = 0, serial = 0, frame = 0;
  const timeout = 90000;
  const spark = '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m10 2 1.9 5.6L17.5 9.5l-5.6 1.9L10 17l-1.9-5.6-5.6-1.9 5.6-1.9L10 2Z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="m16 2 .7 2.3L19 5l-2.3.7L16 8l-.7-2.3L13 5l2.3-.7L16 2Z" fill="currentColor"/></svg>';

  function editable(field) {
    if (!field?.isConnected || field.disabled || field.readOnly || field.hidden) return false;
    if (field.tagName !== 'TEXTAREA' && !(field.tagName === 'INPUT' && (!field.type || field.type === 'text'))) return false;
    if (field.closest('#le-polish-bridge,[hidden],[aria-hidden="true"],[inert]')) return false;
    return !!field.getClientRects().length && getComputedStyle(field).visibility !== 'hidden';
  }

  function kindFor(root) {
    return root.dataset.lePolishKind || [...root.classList].find(name => name.startsWith('le-polish-kind-'))?.slice(15)
      || (root.id === 'coach-goal' ? 'goal' : root.id === 'coach-criteria' ? 'instruction' : 'general');
  }

  function setValue(field, value) {
    const proto = field.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(field, value);
    field.dispatchEvent(new Event('input', { bubbles: true }));
    field.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function unchanged(item) {
    return item.epoch === epoch && item.kind === kindFor(item.record.root) && records.has(item.record) && editable(item.record.field)
      && item.record.field.value === item.original && item.record.revision === item.revision;
  }

  function undoable(record) {
    const undo = record.undo;
    return !!undo && undo.epoch === epoch && undo.kind === kindFor(record.root) && undo.revision === record.revision
      && record.field.value === undo.applied && editable(record.field);
  }

  function update(record) {
    const available = editable(record.field);
    record.tools.hidden = !available;
    record.button.disabled = !available || !record.field.value.trim() || !!pending;
    record.button.title = pending ? '正在润色，请稍候' : '使用已配置的模型润色，预览后再采纳';
    record.undoButton.hidden = !undoable(record);
    record.button.setAttribute('aria-expanded', String(view?.record === record));
    record.button.setAttribute('aria-busy', String(pending?.record === record));
  }

  function updateAll() { records.forEach(update); }

  function position() {
    if (!view?.panel.open) return;
    if (!editable(view.record.field) || !view.record.button.getClientRects().length) {
      closeView(false);
      return;
    }
    const panel = view.panel, anchor = view.record.button;
    if (window.LEPanels?.place) window.LEPanels.place(panel, anchor, 'side', 360);
    else {
      const rect = anchor.getBoundingClientRect(), width = Math.min(360, innerWidth - 24);
      panel.style.width = width + 'px';
      panel.style.maxHeight = Math.max(80, innerHeight - 24) + 'px';
      const height = panel.getBoundingClientRect().height;
      panel.style.left = Math.max(12, Math.min(rect.left, innerWidth - width - 12)) + 'px';
      panel.style.top = Math.max(12, Math.min(rect.bottom + 6, innerHeight - height - 12)) + 'px';
    }
    const viewport = window.visualViewport;
    if (viewport) {
      panel.style.maxHeight = Math.max(80, viewport.height - 24) + 'px';
      const rect = panel.getBoundingClientRect();
      panel.style.top = Math.max(viewport.offsetTop + 12, Math.min(rect.top, viewport.offsetTop + viewport.height - rect.height - 12)) + 'px';
    }
  }

  function release(item) {
    clearTimeout(item.timer);
    clearTimeout(item.dispatchTimer);
    if (pending === item) pending = null;
    updateAll();
  }

  function closeView(restore = true) {
    if (!view) return;
    const item = view;
    view = null;
    item.cancelled = true;
    if (pending === item && !item.sent) release(item);
    if (item.panel.open) item.panel.close();
    item.panel.remove();
    if (restore && editable(item.record.field)) item.record.button.focus({ preventScroll: true });
    updateAll();
  }

  function button(label, className, action) {
    const node = document.createElement('button');
    node.type = 'button'; node.className = className; node.textContent = label;
    node.addEventListener('click', event => { event.preventDefault(); event.stopPropagation(); action(); });
    return node;
  }

  function makePanel(item) {
    const panel = document.createElement('dialog');
    panel.className = 'le-polish-popover';
    panel.id = 'le-polish-preview';
    panel.setAttribute('aria-labelledby', 'le-polish-preview-title');
    panel.setAttribute('aria-describedby', 'le-polish-preview-status');
    const header = document.createElement('div'); header.className = 'le-polish-heading';
    const title = document.createElement('strong'); title.id = 'le-polish-preview-title'; title.textContent = '润色预览';
    const close = button('×', 'le-polish-close', () => closeView()); close.setAttribute('aria-label', '关闭润色预览');
    header.append(title, close);
    const status = document.createElement('p'); status.id = 'le-polish-preview-status'; status.className = 'le-polish-status';
    status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    const preview = document.createElement('div'); preview.className = 'le-polish-text'; preview.hidden = true; preview.tabIndex = 0;
    const actions = document.createElement('div'); actions.className = 'le-polish-actions';
    const cancel = button('取消', 'le-polish-cancel', () => closeView());
    const retry = button('重试', 'le-polish-retry', () => { const record = item.record; closeView(false); begin(record); }); retry.hidden = true;
    const accept = button('采纳', 'le-polish-accept', () => apply(item)); accept.hidden = true;
    actions.append(cancel, retry, accept); panel.append(header, status, preview, actions);
    item.panel = panel; item.status = status; item.preview = preview; item.retry = retry; item.accept = accept;
    panel.addEventListener('cancel', event => { event.preventDefault(); closeView(); });
    panel.addEventListener('click', event => {
      if (event.target !== panel) return;
      const rect = panel.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) closeView();
    });
    (document.querySelector('.gradio-container') || document.body).append(panel);
    panel.showModal(); position(); close.focus({ preventScroll: true });
  }

  function render(item, state, message) {
    if (view !== item) return;
    item.panel.dataset.state = state;
    item.status.textContent = message;
    item.panel.setAttribute('aria-busy', String(state === 'busy'));
    item.preview.hidden = state !== 'ready';
    item.accept.hidden = state !== 'ready';
    item.retry.hidden = state !== 'error';
    if (state === 'ready') item.preview.textContent = item.result;
    position();
  }

  function begin(record) {
    if (pending || !records.has(record) || !editable(record.field) || !record.field.value.trim()) return;
    closeView(false);
    const item = {
      id: 'polish-' + Date.now().toString(36) + '-' + (++serial).toString(36), record,
      original: record.field.value, revision: record.revision, kind: kindFor(record.root), epoch, sent: false, cancelled: false,
    };
    view = item; pending = item; makePanel(item); render(item, 'busy', '正在整理表达，原文会保留。'); updateAll();
    const requestRoot = document.getElementById('le-polish-request');
    const request = requestRoot?.matches('textarea,input') ? requestRoot : requestRoot?.querySelector('textarea,input');
    const triggerRoot = document.getElementById('le-polish-trigger');
    const trigger = triggerRoot?.matches('button') ? triggerRoot : triggerRoot?.querySelector('button');
    if (!request || !trigger || trigger.disabled) {
      release(item); render(item, 'error', '润色暂时没有连接好，请稍后重试。'); return;
    }
    setValue(request, JSON.stringify({ id: item.id, text: item.original, kind: item.kind }));
    item.dispatchTimer = setTimeout(() => {
      if (pending !== item || view !== item || !unchanged(item) || !trigger.isConnected || trigger.disabled) {
        release(item); if (view === item) closeView(false); return;
      }
      item.sent = true;
      trigger.click();
    }, 80);
    item.timer = setTimeout(() => {
      if (pending !== item) return;
      release(item);
      if (view === item && unchanged(item)) render(item, 'error', '这次等待有些久，原文仍保留。请稍后重试。');
      else if (view === item) closeView(false);
    }, timeout);
  }

  function receive(response) {
    const item = pending;
    if (!item || response?.id !== item.id || !item.sent) return;
    release(item);
    if (view !== item || item.cancelled) return;
    if (!unchanged(item)) { closeView(false); return; }
    if (response.ok !== true || typeof response.text !== 'string' || !response.text.trim()) {
      render(item, 'error', typeof response.error === 'string' && response.error.trim()
        ? response.error.slice(0, 240) : '这次没有完成润色，原文仍保留。请稍后重试。');
      return;
    }
    item.result = response.text;
    render(item, 'ready', item.result === item.original ? '原文已经很顺畅，建议保留。' : '已保留原意，采纳后写回输入框。');
    item.accept.disabled = item.result === item.original;
  }

  function apply(item) {
    if (view !== item || !unchanged(item) || typeof item.result !== 'string' || item.result === item.original) {
      if (view === item) closeView(false);
      return;
    }
    const record = item.record;
    closeView(false);
    record.writing = true;
    try { setValue(record.field, item.result); } finally { record.writing = false; }
    record.revision += 1;
    record.undo = { original: item.original, applied: item.result, revision: record.revision, kind: item.kind, epoch };
    update(record);
    if (editable(record.field)) {
      record.field.focus({ preventScroll: true });
      record.field.setSelectionRange(record.field.value.length, record.field.value.length);
    }
  }

  function undo(record) {
    if (!undoable(record)) { record.undo = null; update(record); return; }
    const original = record.undo.original;
    if (view?.record === record) closeView(false);
    record.undo = null; record.writing = true;
    try { setValue(record.field, original); } finally { record.writing = false; }
    record.revision += 1; update(record); record.field.focus({ preventScroll: true });
  }

  function install(root, field) {
    if (bound.has(field) || !editable(field)) return;
    const tools = document.createElement('div'); tools.className = 'le-polish-tools';
    const record = { root, field, tools, revision: 0, undo: null, writing: false };
    const entry = button('', 'le-polish-button', () => begin(record));
    entry.innerHTML = spark + '<span>润色</span>';
    entry.setAttribute('aria-label', '润色这段文字'); entry.setAttribute('aria-haspopup', 'dialog');
    entry.setAttribute('aria-controls', 'le-polish-preview');
    const revert = button('撤销润色', 'le-polish-undo', () => undo(record)); revert.hidden = true;
    tools.append(revert, entry);
    record.button = entry; record.undoButton = revert;
    record.onEdit = () => {
      if (record.writing) return;
      record.revision += 1; record.undo = null;
      if (view?.record === record) closeView(false);
      update(record);
    };
    field.addEventListener('input', record.onEdit); field.addEventListener('change', record.onEdit);
    if (root === field) field.after(tools); else root.append(tools);
    bound.set(field, record); records.add(record); update(record);
  }

  function dispose(record) {
    if (view?.record === record) closeView(false);
    record.field.removeEventListener('input', record.onEdit); record.field.removeEventListener('change', record.onEdit);
    record.tools.remove(); records.delete(record); bound.delete(record.field);
    record.undo = null;
  }

  function sync() {
    frame = 0;
    records.forEach(record => {
      if (!record.field.isConnected || !record.root.isConnected || !record.tools.isConnected) dispose(record);
      else update(record);
    });
    if (view && !unchanged(view)) closeView(false);
    document.querySelectorAll(selector).forEach(root => {
      const fields = root.matches('textarea,input') ? [root] : root.querySelectorAll('textarea,input');
      fields.forEach(field => {
        if (field.closest(selector) === root) install(root, field);
      });
    });
    const resultRoot = document.getElementById('le-polish-result');
    const result = resultRoot?.querySelector('[data-le-polish-response]') || resultRoot;
    if (pending && result) {
      try { receive(JSON.parse(result.textContent || '')); } catch (_) {}
    }
    position();
  }

  function schedule() { if (!frame) frame = requestAnimationFrame(sync); }

  function invalidate() {
    epoch += 1; closeView(false);
    records.forEach(record => { record.undo = null; });
    updateAll();
  }

  new MutationObserver(mutations => {
    // Streaming content owns its rendering. Root mount/removal still has an
    // outside parent as its target, so newly mounted controls remain discoverable.
    if (mutations.some(mutation => {
      const target = mutation.target.nodeType === 1 ? mutation.target : mutation.target.parentElement;
      return !target?.closest('.le-polish-tools,.le-polish-popover,#le-coach-transcript,#le-coach-stream');
    })) schedule();
  }).observe(document.documentElement, {
    subtree: true, childList: true, characterData: true, attributes: true,
    attributeFilter: ['class', 'style', 'hidden', 'disabled', 'readonly', 'inert', 'aria-hidden', 'data-le-polish-kind'],
  });
  document.addEventListener('click', event => { if (event.target.closest?.(navigation)) invalidate(); }, true);
  document.addEventListener('change', event => { if (event.target.closest?.('#le-project-picker,#le-course-picker')) invalidate(); }, true);
  document.addEventListener('le:polish-invalidate', invalidate);
  window.addEventListener('popstate', invalidate);
  window.addEventListener('hashchange', invalidate);
  window.addEventListener('pagehide', invalidate);
  window.addEventListener('resize', position);
  window.addEventListener('scroll', event => { if (!view?.panel.contains(event.target)) position(); }, true);
  window.visualViewport?.addEventListener('resize', position);
  window.addEventListener('keydown', event => {
    if (!view?.panel.open || !['Escape', 'Tab'].includes(event.key)) return;
    event.preventDefault(); event.stopPropagation();
    if (event.key === 'Escape') { closeView(); return; }
    const nodes = [...view.panel.querySelectorAll('button,[tabindex="0"]')].filter(node => !node.disabled && !node.hidden && node.getClientRects().length);
    const index = nodes.indexOf(document.activeElement), delta = event.shiftKey ? -1 : 1;
    nodes[(index + delta + nodes.length) % nodes.length]?.focus({ preventScroll: true });
  }, true);
  window.LETextPolish = { refresh: schedule, invalidate };
  schedule();
})();
