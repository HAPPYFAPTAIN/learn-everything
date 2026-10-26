(() => {
  let root, area, feed, stream, latest, observer, resizeObserver;
  let following = true, scheduled = false, layoutDirty = true, session = '', sequence = 0;
  const rendered = new Map();
  const nearBottom = () => area.scrollHeight - area.scrollTop - area.clientHeight < 72;
  function updateLatest() {
    const visible = !following && !nearBottom() && !root.classList.contains('le-empty');
    if (latest.hidden === visible) latest.hidden = !visible;
  }
  function setProperty(name, value) {
    if (root.style.getPropertyValue(name) !== value) root.style.setProperty(name, value);
  }
  function dimensions() {
    if (!root?.getClientRects().length) return;
    const box = root.getBoundingClientRect();
    setProperty('--le-coach-height', `${Math.floor(Math.max(320, window.innerHeight - box.top - 18))}px`);
    const composer = root.querySelector('#le-coach-composer');
    if (composer) setProperty('--le-coach-bottom', `${Math.max(60, root.getBoundingClientRect().bottom - composer.getBoundingClientRect().top + 12)}px`);
  }
  function refresh() {
    scheduled = false;
    if (!root?.isConnected) return;
    const empty = !feed.children.length;
    if (root.classList.contains('le-empty') !== empty) { root.classList.toggle('le-empty', empty); layoutDirty = true; }
    if (empty) following = true;
    if (layoutDirty) { dimensions(); layoutDirty = false; }
    if (following && root.getClientRects().length) area.scrollTop = area.scrollHeight;
    updateLatest();
  }
  function schedule(resized = false) {
    layoutDirty ||= resized;
    if (!scheduled) { scheduled = true; requestAnimationFrame(refresh); }
  }
  // Keep message roots and unchanged descendants alive, including selection,
  // keyboard focus, code scroll offsets and native disclosure open state.
  function patch(current, next) {
    if (current.nodeType !== next.nodeType || current.nodeName !== next.nodeName) {
      current.replaceWith(next.cloneNode(true)); return;
    }
    if (current.nodeType === Node.TEXT_NODE) {
      if (current.data !== next.data) current.data = next.data;
      return;
    }
    if (current.nodeType !== Node.ELEMENT_NODE) return;
    const keepOpen = current.tagName === 'DETAILS';
    for (const attr of [...current.attributes]) {
      if (keepOpen && attr.name === 'open') continue;
      if (!next.hasAttribute(attr.name)) current.removeAttribute(attr.name);
    }
    for (const attr of next.attributes) {
      if (keepOpen && attr.name === 'open') continue;
      if (current.getAttribute(attr.name) !== attr.value) current.setAttribute(attr.name, attr.value);
    }
    for (let i = 0; i < next.childNodes.length; i++) {
      if (current.childNodes[i]) patch(current.childNodes[i], next.childNodes[i]);
      else current.append(next.childNodes[i].cloneNode(true));
    }
    while (current.childNodes.length > next.childNodes.length) current.lastChild.remove();
  }
  function consume() {
    const frame = stream.querySelector('[data-coach-frame]');
    if (!frame) return;
    const seq = Number(frame.dataset.seq);
    if (!Number.isFinite(seq) || seq <= sequence) return;
    let messages;
    try { messages = JSON.parse(frame.textContent); } catch { return; }
    if (!messages || typeof messages !== 'object' || Array.isArray(messages)) return;
    const order = Object.keys(messages);
    if (session !== frame.dataset.session) {
      session = frame.dataset.session; rendered.clear(); feed.replaceChildren(); following = true;
    }
    sequence = seq;
    const nodes = new Map([...feed.children].map(node => [node.dataset.messageId, node]));
    for (const [key, html] of Object.entries(messages)) {
      const current = nodes.get(key);
      if (current && rendered.get(key) === html) continue;
      const template = document.createElement('template');
      template.innerHTML = html;
      const next = template.content.firstElementChild;
      if (!next || next.dataset.messageId !== key) continue;
      if (!current) {
        const node = next.cloneNode(true); nodes.set(key, node);
        if (node.classList.contains('le-me')) following = true;
      } else if (rendered.get(key) !== html) patch(current, next);
      rendered.set(key, html);
    }
    const wanted = new Set(order);
    for (const [key, node] of nodes) if (!wanted.has(key)) { node.remove(); rendered.delete(key); }
    let cursor = feed.firstElementChild;
    for (const key of order) {
      const node = nodes.get(key);
      if (!node) continue;
      if (node === cursor) cursor = cursor.nextElementSibling;
      else feed.insertBefore(node, cursor);
    }
    if (feed.getAttribute('aria-busy') !== frame.dataset.busy) feed.setAttribute('aria-busy', frame.dataset.busy);
    schedule();
  }
  function bind() {
    const found = document.getElementById('le-coach-root');
    if (!found || found === root) return;
    const nextArea = found.querySelector('#le-coach-scroll');
    const nextFeed = found.querySelector('#le-coach-transcript .le-coach-feed');
    const nextStream = found.querySelector('#le-coach-stream');
    if (!nextArea || !nextFeed || !nextStream) return;
    observer?.disconnect(); resizeObserver?.disconnect();
    root = found; area = nextArea; feed = nextFeed; stream = nextStream;
    following = true; session = ''; sequence = 0; rendered.clear();
    latest = document.createElement('button');
    latest.type = 'button'; latest.className = 'le-coach-latest'; latest.textContent = '↓ 最新进展'; latest.hidden = true;
    root.append(latest);
    latest.addEventListener('click', () => { following = true; area.scrollTop = area.scrollHeight; updateLatest(); });
    area.addEventListener('scroll', () => { following = nearBottom(); updateLatest(); }, {passive: true});
    root.addEventListener('toggle', event => {
      if (event.target.matches?.('details[data-call-id]')) {
        if (event.target.open) following = false;
        schedule();
      }
    }, true);
    root.addEventListener('keydown', event => {
      if (event.key === 'Escape') root.querySelectorAll('details[open]').forEach(detail => { detail.open = false; });
    });
    root.addEventListener('click', event => {
      if (event.target.closest('#le-coach-suggestions')) requestAnimationFrame(() => root.querySelector('textarea')?.focus({preventScroll: true}));
    });
    observer = new MutationObserver(consume);
    observer.observe(stream, {childList: true, subtree: true, characterData: true});
    resizeObserver = new ResizeObserver(() => schedule(true));
    for (const target of [root, ...root.querySelectorAll('#le-coach-composer,#le-coach-question,#le-coach-approve,#le-coach-plan')]) resizeObserver.observe(target);
    consume(); schedule(true);
  }
  new MutationObserver(records => {
    if (root?.isConnected && records.every(record => {
      const target = record.target.nodeType === 1 ? record.target : record.target.parentElement;
      return target?.closest('#le-coach-transcript,#le-coach-stream');
    })) return;
    bind();
  }).observe(document.documentElement, {childList: true, subtree: true});
  window.addEventListener('resize', () => { if (root) schedule(true); }, {passive: true});
  document.addEventListener('click', event => { if (event.target.closest?.('#learning-coach-tab-button') && root) schedule(true); });
  bind();
})();

(() => {
  function dismiss(event) {
    const menu = document.getElementById('le-coach-model-menu');
    const trigger = menu?.querySelector(':scope > button.open');
    if (!trigger) return;
    if (event.type === 'keydown' && event.key === 'Escape') {
      trigger.click(); trigger.focus(); event.preventDefault();
    } else if (event.type === 'pointerdown' && !menu.contains(event.target)) {
      trigger.click();
    }
  }
  document.addEventListener('pointerdown', dismiss);
  document.addEventListener('keydown', dismiss);
})();

(() => {
  let menu, queued = false;
  function sync() {
    queued = false;
    const trigger = menu?.querySelector(':scope > .label-wrap');
    const metadata = menu?.querySelector('[data-default-icon]');
    if (!trigger || !metadata) return;
    let icon = trigger.querySelector('.le-coach-platform-icon');
    if (!icon) { icon = document.createElement('img'); icon.className = 'le-coach-platform-icon'; icon.alt = ''; icon.width = 22; icon.height = 22; trigger.prepend(icon); }
    let source = metadata.dataset.defaultIcon;
    const provider = menu.querySelector('#le-coach-connection input')?.value || '';
    try {
      const catalog = JSON.parse(document.getElementById('le-platform-filter')?.dataset.catalog || '{}');
      const brand = Object.values(catalog).find(item => provider === item.name || provider.startsWith(item.name + ' · '));
      if (brand?.icon) source = brand.icon;
    } catch (_) {}
    if (icon.getAttribute('src') !== source) icon.src = source;
    const name = trigger.textContent.trim();
    const label = '选择模型 · ' + name;
    if (trigger.getAttribute('aria-label') !== label) trigger.setAttribute('aria-label', label);
  }
  function schedule() { if (!queued) { queued = true; requestAnimationFrame(sync); } }
  function bind() {
    const found = document.getElementById('le-coach-model-menu');
    if (!found || found === menu) return;
    menu = found;
    new MutationObserver(schedule).observe(menu, {childList:true,subtree:true,characterData:true});
    menu.addEventListener('change', schedule);
    sync();
  }
  new MutationObserver(() => { if (!menu?.isConnected) bind(); }).observe(document.documentElement, {childList:true,subtree:true});
  bind();
})();
