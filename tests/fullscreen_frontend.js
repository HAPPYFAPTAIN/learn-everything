document.addEventListener('DOMContentLoaded', async () => {
  const checks = [];
  const check = (condition, name) => { if (!condition) throw new Error(name); checks.push(name); };
  const $ = id => document.getElementById(id);
  const wait = (ms = 30) => new Promise(resolve => setTimeout(resolve, ms));
  const press = (element, key, options = {}) => {
    const event = new KeyboardEvent('keydown', {key, bubbles: true, cancelable: true, ...options});
    element.dispatchEvent(event);
    return event;
  };
  const root = document.documentElement;
  const navState = () => ({
    saved: localStorage.getItem('le.nav.collapsed'),
    collapsed: root.classList.contains('le-nav-collapsed'),
    width: root.style.getPropertyValue('--le-nav-w'),
  });
  const sameNav = before => JSON.stringify(before) === JSON.stringify(navState());
  let navigations = [];
  document.querySelectorAll('#le-app-tabs > .tab-nav > button').forEach(button => {
    button.addEventListener('click', () => {
      navigations.push(button.id);
      button.hidden = false;
      document.querySelectorAll('#le-app-tabs > .tab-nav > button').forEach(item => {
        item.setAttribute('aria-selected', String(item === button));
        item.classList.toggle('selected', item === button);
      });
    });
  });
  try {
    press(document.body, 'k', {ctrlKey: true});
    check(!window.testErrors.length && !$('le-jump-dialog'), 'Ctrl K before the delayed topbar is mounted is harmless');
    $('le-brand-bar').innerHTML = '<div class="le-topbar"><div class="le-brand">Learn Everything</div><div class="le-app-title">学习<span>工作台</span></div><button id="le-theme-toggle">主题</button></div>';
    await wait();
    const dialog = $('le-jump-dialog'), menu = $('le-display-menu');
    const jump = $('le-jump-trigger'), display = $('le-display-trigger');
    const focus = menu.querySelector('[data-focus-layout]'), input = dialog.querySelector('input');
    check(!!jump && !!$('le-nav-toggle') && document.querySelectorAll('#le-workspace-tools').length === 1, 'delayed topbar mounts workspace and navigation controls once');
    check(root.style.getPropertyValue('--le-reading-size') === '18px', 'saved reading size is applied on startup');

    jump.focus(); press(jump, 'k', {ctrlKey: true});
    check(dialog.open && document.activeElement === input, 'Ctrl K opens the palette and focuses its search');
    check(!dialog.querySelector('[data-page-id="unavailable-tab-button"]'), 'disabled pages are excluded');
    input.value = '资料'; input.dispatchEvent(new Event('input', {bubbles: true}));
    check($('indices-tab-button').hidden && !!dialog.querySelector('[data-page-id="indices-tab-button"]'), 'search includes library while its navigation entry is hidden under more');
    input.value = '聊天'; input.dispatchEvent(new Event('input', {bubbles: true}));
    check(!!dialog.querySelector('[data-page-id="chat-tab-button"]'), 'search matches aliases for hidden knowledge chat');
    input.value = '资料'; input.dispatchEvent(new Event('input', {bubbles: true}));
    const ime = press(input, 'Enter', {isComposing: true});
    check(!ime.defaultPrevented && dialog.open && navigations.length === 0, 'IME confirmation Enter does not navigate or close the palette');
    const composingDown = press(input, 'ArrowDown', {isComposing: true});
    check(!composingDown.defaultPrevented, 'IME candidate selection arrows are not intercepted');
    const close = dialog.querySelector('[data-jump-close]'); close.focus();
    const closeEnter = press(close, 'Enter');
    check(!closeEnter.defaultPrevented && navigations.length === 0 && dialog.open, 'Enter on the close button is left to native button activation, not result navigation');
    close.click(); await wait();
    check(!dialog.open && document.activeElement === jump && navigations.length === 0, 'close button dismisses the palette and restores its opener');

    jump.focus(); jump.click();
    const escape = press(input, 'Escape');
    check(!escape.defaultPrevented, 'Escape in the palette is delegated to native dialog cancellation');
    // Untrusted KeyboardEvents do not invoke browser defaults; requestClose exercises the native cancel/close lifecycle.
    dialog.requestClose(); await wait();
    check(!dialog.open && document.activeElement === jump, 'native dialog cancellation restores focus to the palette opener');

    jump.focus(); jump.click(); input.value = '资料'; input.dispatchEvent(new Event('input', {bubbles: true}));
    press(input, 'Enter'); await wait();
    check(!dialog.open && navigations.at(-1) === 'indices-tab-button', 'Enter activates the matching hidden page');
    check(document.activeElement === $('indices-tab-button'), 'navigation keeps focus on the selected page after the asynchronous close event');

    display.click();
    check(!menu.hidden && display.getAttribute('aria-expanded') === 'true', 'display settings opens beside its trigger');
    check(!menu.querySelector('[data-reading-options]').hidden && menu.querySelector('[data-reading-size="18"]').getAttribute('aria-pressed') === 'true', 'reading settings show and reflect the current size');
    menu.querySelector('[data-reading-size="20"]').click();
    check(root.style.getPropertyValue('--le-reading-size') === '20px' && localStorage.getItem('le.reading.size') === '20', 'reading size updates the live page and persistence');
    check(menu.querySelector('[data-reading-size="20"]').getAttribute('aria-pressed') === 'true' && menu.querySelector('[data-reading-size="18"]').getAttribute('aria-pressed') === 'false', 'reading size updates the selected state');
    press(menu.querySelector('[data-reading-size="20"]'), 'Escape');
    check(menu.hidden && document.activeElement === display && display.getAttribute('aria-expanded') === 'false', 'Escape dismisses display settings and restores trigger focus');
    $('le-guide-md').hidden = true; display.click();
    check(menu.querySelector('[data-reading-options]').hidden, 'reading controls are omitted when reading content is absent');
    $('outside-focus').focus();
    check(menu.hidden, 'moving keyboard focus away dismisses the display popover');
    $('le-guide-md').hidden = false;

    const savedNav = navState(); focus.click();
    check(root.classList.contains('le-focus-layout') && focus.getAttribute('aria-checked') === 'true' && sameNav(savedNav), 'focus layout hides navigation without changing its persistent preference');
    $('le-nav-toggle').click();
    check(!root.classList.contains('le-focus-layout') && sameNav(savedNav), 'navigation toggle exits focus without changing the original navigation preference');
    focus.click(); press(focus, 'Escape');
    check(!root.classList.contains('le-focus-layout') && focus.getAttribute('aria-checked') === 'false' && sameNav(savedNav), 'Escape restores focus layout while preserving expanded or collapsed navigation');

    $('custom-modal').hidden = false; $('modal-focus').focus();
    const blocked = press($('modal-focus'), 'k', {ctrlKey: true});
    check(!dialog.open && !blocked.defaultPrevented && document.activeElement === $('modal-focus'), 'visible aria-modal dialog blocks Ctrl K without stealing its focus');
    $('custom-modal').hidden = true; jump.focus();
    document.addEventListener('keydown', event => event.preventDefault(), {capture: true, once: true});
    const consumed = press(jump, 'k', {ctrlKey: true});
    check(consumed.defaultPrevented && !dialog.open, 'a shortcut consumed by an active component is not intercepted again');
    press(jump, 'k', {ctrlKey: true});
    check(dialog.open, 'a hidden aria-modal dialog does not block Ctrl K');
    press(input, 'k', {ctrlKey: true}); await wait();
    check(!dialog.open && document.activeElement === jump, 'Ctrl K toggles its own palette closed and restores focus');

    let fullscreenElement = null;
    Object.defineProperty(document, 'fullscreenElement', {configurable: true, get: () => fullscreenElement});
    root.requestFullscreen = () => { fullscreenElement = root; document.dispatchEvent(new Event('fullscreenchange')); return Promise.resolve(); };
    document.exitFullscreen = () => { fullscreenElement = null; document.dispatchEvent(new Event('fullscreenchange')); return Promise.resolve(); };
    focus.click(); display.click(); menu.querySelector('[data-browser-fullscreen]').click(); await wait();
    check(fullscreenElement === root && root.classList.contains('le-focus-layout'), 'browser fullscreen enters while an existing focus layout is active');
    await document.exitFullscreen();
    check(root.classList.contains('le-focus-layout') && sameNav(savedNav), 'browser fullscreen exit restores a previously active focus layout');
    focus.click(); display.click(); menu.querySelector('[data-browser-fullscreen]').click(); await wait();
    await document.exitFullscreen();
    check(!root.classList.contains('le-focus-layout') && sameNav(savedNav), 'browser fullscreen exit restores a previously normal layout');
    check(document.querySelectorAll('#le-workspace-tools').length === 1 && document.querySelectorAll('#le-jump-dialog').length === 1, 'streamed DOM updates do not duplicate mounted controls');
    check(window.testErrors.length === 0, 'workspace interactions produce no uncaught errors or promise rejections');
    const result = document.createElement('pre'); result.id = 'results'; result.textContent = JSON.stringify({checks}); document.body.append(result);
  } catch (error) {
    const result = document.createElement('pre'); result.id = 'results'; result.textContent = JSON.stringify({checks, error: error.stack, browserErrors: window.testErrors}); document.body.append(result);
  }
});
