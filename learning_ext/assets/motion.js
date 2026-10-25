(() => {
  if (window.LEMotion) return;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const running = new Map(), bindings = new Map(), pending = new Set();
  const pageTargets = '.le-editorial-copy,.le-editorial-art,.le-section-heading,.le-direction-card,.le-dashboard-next,.le-metric,.le-help-cards button,.le-chat-starters button,.coach-intro,.coach-courses button,.le-hero-copy,.le-generated-hero,#le-resume-row';
  const overlays = '.le-settings-deck,#le-chat-tool-menu,#le-chat-flyout,.le-library-dialog,.le-polish-popover';
  const mounts = '#le-app-tabs,.tab-nav,[role="tablist"],[role="tabpanel"],#le-action-learning,#le-coach,' + overlays;
  const streamContent = '#main-chat-bot,#chatbot,.chatbot,#le-coach-transcript,#le-action-help,#le-assistant-messages,#le-center-content,#le-guide-md,#le-term-output';
  const panelIds = ['learning-guide-tab','quick-setup-tab','learning-path-tab','learning-workbench-tab','learning-review-tab','learning-quiz-tab','learning-dashboard-tab','learning-coach-tab','chat-tab','indices-tab','help-tab','resources-tab'];
  let frame = 0, activePanel = null, actionDirection = 1;

  function cancel(element) {
    const animation = running.get(element);
    if (!animation) return;
    running.delete(element);
    animation.cancel();
  }
  function stop() { Array.from(running.keys()).forEach(cancel); }
  function visible(element) {
    if (!element?.isConnected || element.closest('[hidden],[aria-hidden="true"],dialog:not([open])')) return false;
    const style = getComputedStyle(element);
    if (style.display === 'none' || style.visibility === 'hidden' || style.visibility === 'collapse') return false;
    const rect = element.getBoundingClientRect();
    const viewport = window.visualViewport;
    const left = viewport?.offsetLeft || 0, top = viewport?.offsetTop || 0;
    return rect.width > 0 && rect.height > 0 && rect.right > left && rect.bottom > top
      && rect.left < left + (viewport?.width || innerWidth) && rect.top < top + (viewport?.height || innerHeight);
  }
  function play(element, preset = 'enter', options = {}) {
    cancel(element);
    if (reduced.matches || document.hidden || !visible(element) || !element.animate) return null;
    const direction = options.direction === -1 || options.direction === 'back' ? -1 : 1;
    const presets = {
      enter: [[{ opacity: .45, transform: 'translateY(8px)' }, { opacity: 1, transform: 'none' }], 180],
      popover: [[{ opacity: .45, transform: 'translateY(5px) scale(.99)' }, { opacity: 1, transform: 'none' }], 160],
      step: [[{ opacity: .55, transform: `translateX(${direction * 10}px)` }, { opacity: 1, transform: 'none' }], 180],
      press: [[{ transform: 'scale(.98)' }, { transform: 'none' }], 100],
      complete: [[{ opacity: .65, transform: 'scale(.985)' }, { opacity: 1, transform: 'none' }], 200],
      feedback: [[{ opacity: .55, transform: 'translateY(4px)' }, { opacity: 1, transform: 'none' }], 160],
    };
    const definition = presets[preset];
    if (!definition) return null;
    const delay = Math.max(0, Math.min(Number(options.delay) || 0, 96));
    const animation = element.animate(definition[0], {
      duration: definition[1], delay,
      easing: 'cubic-bezier(.2,.75,.25,1)', fill: delay ? 'backwards' : 'none',
    });
    running.set(element, animation);
    const release = () => { if (running.get(element) === animation) running.delete(element); };
    animation.finished.then(release, release);
    return animation;
  }
  window.LEMotion = { play, cancel, stop };
  reduced.addEventListener('change', stop);
  document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); });
  window.addEventListener('pagehide', stop);

  function queue(callback) {
    pending.add(callback);
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      const work = Array.from(pending);
      pending.clear();
      work.forEach(task => task());
    });
  }
  function watch(element, update, options) {
    if (bindings.has(element)) return;
    const observer = new MutationObserver(records => {
      if (update.accept && !records.some(update.accept)) return;
      queue(update);
    });
    observer.observe(element, options);
    bindings.set(element, { observer, update });
    queue(update);
  }
  function selectedPanel() {
    const root = document.getElementById('le-app-tabs');
    if (!root) return null;
    const panels = new Set(panelIds.map(id => document.getElementById(id)).filter(Boolean));
    root.querySelectorAll(':scope > [role="tabpanel"],:scope > .tabitem').forEach(panel => panels.add(panel));
    const controls = document.querySelectorAll('[role="tab"][aria-controls],.tab-nav button[aria-controls]');
    for (const panel of panels) {
      const labels = (panel.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean);
      const buttons = labels.map(id => document.getElementById(id));
      buttons.push(document.getElementById(panel.id + '-button'));
      controls.forEach(button => {
        if ((button.getAttribute('aria-controls') || '').split(/\s+/).includes(panel.id)) buttons.push(button);
      });
      if (buttons.some(button => button && (button.getAttribute('aria-selected') === 'true'
        || (button.getAttribute('aria-selected') !== 'false' && button.classList.contains('selected'))))) return panel;
    }
    return null;
  }
  function enterPage() {
    const panel = selectedPanel();
    if (!panel || panel === activePanel || !visible(panel)) return;
    activePanel = panel;
    stop();
    const candidates = Array.from(panel.querySelectorAll(pageTargets)).filter(visible);
    candidates.filter(element => !candidates.some(parent => parent !== element && parent.contains(element)))
      .slice(0, 6).forEach((element, index) => play(element, 'enter', { delay: Math.min(index * 24, 96) }));
  }
  function overlay(element) {
    let previous = '', state = '';
    const update = () => {
      const open = element.tagName === 'DIALOG' ? element.open : !element.hidden;
      const label = element.matches('.le-settings-deck') ? element.getAttribute('aria-label') : element.dataset.panel;
      const key = open ? 'open:' + (label || '') : '';
      const nextState = element.dataset.state || '';
      if (key !== previous) {
        if (open) play(element, previous ? 'step' : 'popover');
        else running.forEach((_, target) => { if (element === target || element.contains(target)) cancel(target); });
      } else if (open && nextState === 'ready' && state !== 'ready' && element.matches('.le-polish-popover') && !running.has(element)) {
        play(element.querySelector('.le-polish-accept'), 'complete');
      }
      previous = key;
      state = nextState;
    };
    watch(element, update, { attributes: true, attributeFilter: ['open','hidden','aria-hidden','aria-label','data-panel','data-state'] });
  }
  function action(element) {
    let key = '', index = null, previousCard = null;
    const update = () => {
      const card = element.querySelector('.le-action-card[data-le-step-active]');
      const next = card ? card.dataset.step + ':' + (card.querySelector('h2')?.textContent || '') : '';
      if (!next || !visible(card)) return;
      if (next !== key) {
        if (previousCard !== card) cancel(previousCard);
        const nextIndex = Number(card.dataset.step);
        const direction = index !== null && nextIndex !== index ? Math.sign(nextIndex - index) : actionDirection;
        play(card, key ? 'step' : 'enter', { direction });
        key = next;
        index = nextIndex;
        previousCard = card;
      }
    };
    update.accept = record => record.target === element || record.target.closest?.('.le-action-card')
      || Array.from(record.addedNodes || []).some(node => node.nodeType === 1 && (node.matches('.le-action-card') || node.querySelector('.le-action-card')));
    watch(element, update, { childList: true, subtree: true, attributes: true, attributeFilter: ['data-step','data-le-step-active','hidden','style','class'] });
  }
  function coach(element) {
    let step = '', feedback = '';
    const update = () => {
      const count = element.querySelector('#coach-count');
      const nextStep = count?.textContent.trim() || '';
      const changed = nextStep && nextStep !== step;
      if (changed) {
        const oldIndex = Number(step.match(/\d+/)?.[0]), nextIndex = Number(nextStep.match(/\d+/)?.[0]);
        const direction = step && nextIndex < oldIndex ? -1 : 1;
        element.querySelectorAll('.coach-instruction,.coach-stage').forEach(card => play(card, step ? 'step' : 'enter', { direction }));
        step = nextStep;
      }
      const target = element.querySelector('#coach-feedback');
      const type = target?.classList.contains('is-success') ? 'success' : target?.classList.contains('is-error') ? 'error' : '';
      const text = target?.textContent.trim() || '';
      const nextFeedback = type && text ? `${step}:${type}:${text}` : '';
      if (!changed && nextFeedback && nextFeedback !== feedback) play(target, type === 'success' ? 'complete' : 'feedback');
      feedback = nextFeedback;
    };
    update.accept = record => record.target.closest?.('#coach-count,#coach-feedback')
      || Array.from(record.addedNodes || []).some(node => node.nodeType === 1 && (node.matches('#coach-count,#coach-feedback') || node.querySelector('#coach-count,#coach-feedback')));
    watch(element, update, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['class'] });
  }
  function bind(element) {
    if (bindings.has(element)) return;
    if (element.matches(overlays)) overlay(element);
    else if (element.id === 'le-action-learning') action(element);
    else if (element.id === 'le-coach') coach(element);
    else if (element.matches('.tab-nav,[role="tablist"]')) {
      watch(element, enterPage, { subtree: true, attributes: true, childList: true, attributeFilter: ['aria-selected','class'] });
    } else {
      watch(element, enterPage, { attributes: true, childList: true, attributeFilter: ['hidden','style','class','aria-hidden'] });
    }
  }
  function discover(root) {
    if (root.nodeType !== 1) return;
    if (root.matches(mounts)) bind(root);
    root.querySelectorAll(mounts).forEach(bind);
  }
  function cleanup() {
    bindings.forEach((binding, element) => {
      if (element.isConnected) return;
      binding.observer.disconnect();
      pending.delete(binding.update);
      bindings.delete(element);
    });
    running.forEach((_, element) => { if (!element.isConnected) cancel(element); });
    if (!activePanel?.isConnected) activePanel = null;
  }
  function boot() {
    discover(document.documentElement);
    new MutationObserver(records => {
      let removed = false;
      for (const record of records) {
        if (record.target.closest?.(streamContent)) continue;
        for (const node of record.addedNodes) discover(node);
        if (record.removedNodes.length) removed = true;
      }
      if (removed) queue(cleanup);
    }).observe(document.documentElement, { childList: true, subtree: true });
    document.addEventListener('click', event => {
      const button = event.target.closest?.('#le-action-prev,#le-action-previous,#le-action-next');
      if (button && !button.disabled) actionDirection = button.id === 'le-action-next' ? 1 : -1;
    }, true);
    document.addEventListener('toggle', event => {
      const details = event.target;
      if (details.tagName !== 'DETAILS' || !details.open || !details.closest('.gradio-container') || details.closest(overlays + ',' + streamContent)) return;
      Array.from(details.children).filter(child => child.tagName !== 'SUMMARY').slice(0, 4)
        .forEach((child, index) => play(child, 'enter', { delay: index * 24 }));
    }, true);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();
})();
