(() => {
  const configs = [
    { overlay: 'le-gate-overlay', modal: 'le-gate-modal', close: 'le-gate-close', title: 'le-gate-title', fallback: 'le-master-btn' },
    { overlay: 'le-adapt-overlay', modal: 'le-adapt-modal', close: 'le-adapt-close', title: 'le-adapt-intro', fallback: 'le-adapt-open' },
  ];
  let active = null;
  let previousFocus = null;
  let inerted = [];

  const visible = (element) => Boolean(element && element.getClientRects().length);

  function focusable(root) {
    const selector = 'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])';
    return [...root.querySelectorAll(selector)].filter((element) => {
      return visible(element) && getComputedStyle(element).visibility !== 'hidden' && !element.closest('[inert]');
    });
  }

  function setBackground(overlay, inert) {
    if (inert) {
      inerted = [];
      const elements = [
        ...overlay.parentElement.children,
        document.querySelector('#le-brand-bar'),
        document.querySelector('#le-app-tabs > .tab-nav'),
      ];
      elements.forEach((element) => {
        if (!element || element === overlay || element.inert) return;
        element.inert = true;
        inerted.push(element);
      });
    } else {
      inerted.forEach((element) => { element.inert = false; });
      inerted = [];
    }
  }

  function open(overlay, config) {
    const modal = document.getElementById(config.modal) || overlay;
    previousFocus = document.activeElement;
    active = { overlay, config, modal };
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    modal.setAttribute('aria-labelledby', config.title);
    setBackground(overlay, true);
    requestAnimationFrame(() => {
      if (!active || active.overlay !== overlay) return;
      const target = document.getElementById(config.close) || focusable(modal)[0] || modal;
      if (target === modal) modal.tabIndex = -1;
      target.focus({ preventScroll: true });
    });
  }

  function close() {
    if (!active) return;
    const { overlay, config } = active;
    setBackground(overlay, false);
    active = null;
    const fallback = previousFocus && previousFocus.isConnected
      ? previousFocus
      : document.getElementById(config.fallback);
    if (fallback && fallback.isConnected) fallback.focus({ preventScroll: true });
    previousFocus = null;
  }

  function sync() {
    const current = configs
      .map((config) => ({ config, overlay: document.getElementById(config.overlay) }))
      .find((item) => visible(item.overlay));
    if (current && (!active || active.overlay !== current.overlay)) {
      if (active) close();
      open(current.overlay, current.config);
    } else if (!current && active) {
      close();
    }
  }

  document.addEventListener('keydown', (event) => {
    if (!active) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      document.getElementById(active.config.close)?.click();
      return;
    }
    if (event.key !== 'Tab') return;
    const items = focusable(active.overlay);
    event.preventDefault();
    event.stopPropagation();
    if (!items.length) {
      active.modal.focus();
      return;
    }
    const current = document.activeElement;
    const index = items.indexOf(current);
    const next = event.shiftKey
      ? (index <= 0 ? items.length - 1 : index - 1)
      : (index < 0 || index === items.length - 1 ? 0 : index + 1);
    items[next].focus();
  }, true);

  new MutationObserver(sync).observe(document.documentElement, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['class', 'style', 'hidden'],
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', sync, { once: true });
  } else {
    sync();
  }
})();
