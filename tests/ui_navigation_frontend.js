document.addEventListener('DOMContentLoaded', async () => {
  const checks = [];
  const check = (condition, name) => { if (!condition) throw new Error(name); checks.push(name); };
  const $ = id => document.getElementById(id);
  const wait = (ms = 25) => new Promise(resolve => setTimeout(resolve, ms));
  const press = (element, key) => {
    const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
    element.dispatchEvent(event);
    return event;
  };
  const dropdown = (inputId, optionsId) => {
    const input = $(inputId), options = $(optionsId);
    let closed = 0;
    input.addEventListener('keydown', event => {
      if (event.key === 'Escape' && !options.hidden) {
        options.hidden = true;
        input.setAttribute('aria-expanded', 'false');
        closed += 1;
      }
    });
    return { input, options, get closed() { return closed; }, open() {
      options.hidden = false; input.setAttribute('aria-expanded', 'true'); input.focus();
    } };
  };
  try {
    await wait();
    const plus = $('le-chat-plus'), menu = $('le-chat-tool-menu'), flyout = $('le-chat-flyout');
    const items = Array.from(menu.querySelectorAll('[data-chat-menu]'));
    plus.focus(); press(plus, 'ArrowDown');
    check(!menu.hidden && document.activeElement === items[0], 'ArrowDown opens menu and focuses first item');
    press(items[0], 'ArrowUp');
    check(document.activeElement === items.at(-1), 'ArrowUp wraps to last item');
    press(items.at(-1), 'ArrowDown');
    check(document.activeElement === items[0], 'ArrowDown wraps to first item');
    press(items[0], 'End');
    check(document.activeElement === items.at(-1), 'End focuses last item');
    press(items.at(-1), 'Home');
    check(document.activeElement === items[0], 'Home focuses first item');
    press(items[0], 'ArrowDown'); press(items[1], 'ArrowRight');
    check(!flyout.hidden && flyout.dataset.panel === 'answer' && document.activeElement.hasAttribute('data-flyout-back'), 'ArrowRight opens selected submenu and moves focus');
    press(document.activeElement, 'Escape');
    check(flyout.hidden && !menu.hidden && document.activeElement === items[1], 'first Escape returns to submenu opener');
    press(document.activeElement, 'Escape');
    check(menu.hidden && document.activeElement === plus && plus.getAttribute('aria-expanded') === 'false', 'second Escape closes menu and restores plus focus');

    plus.click(); items[0].focus();
    items[0].dispatchEvent(new PointerEvent('pointerover', { bubbles: true, pointerType: 'mouse' }));
    press(items[0], 'ArrowDown'); await wait(180);
    check(flyout.hidden && document.activeElement === items[1], 'keyboard menu navigation cancels pending hover submenu');
    items[0].dispatchEvent(new PointerEvent('pointerover', { bubbles: true, pointerType: 'mouse' }));
    plus.focus(); press(plus, 'ArrowUp'); await wait(180);
    check(flyout.hidden && document.activeElement === items.at(-1), 'plus keyboard navigation also cancels pending hover');
    press(items.at(-1), 'Escape');

    const source = document.querySelector('.le-source-shortcut');
    source.click();
    check(!flyout.hidden && menu.hidden && source.getAttribute('aria-expanded') === 'true', 'direct source shortcut opens only its own flyout');
    const files = dropdown('files-input', 'files-options'); files.open();
    const filesEscape = press(files.input, 'Escape');
    check(filesEscape.defaultPrevented && files.closed === 1 && files.options.hidden && !flyout.hidden, 'dropdown Escape closes options while preserving flyout');
    press(files.input, 'Escape');
    check(flyout.hidden && document.activeElement === source, 'next Escape returns from direct source flyout');

    source.click();
    const nestedEntry = $('le-chat-add-source').previousElementSibling;
    nestedEntry.click(); await wait();
    const dialog = document.querySelector('.le-settings-deck[open]');
    check(Boolean(dialog) && !flyout.hidden, 'nested settings opens a dialog over its flyout');
    const nested = dropdown('nested-input', 'nested-options'); nested.open();
    const nestedEscape = press(nested.input, 'Escape');
    check(nestedEscape.defaultPrevented && nested.closed === 1 && dialog.open && !flyout.hidden, 'nested dropdown prevents native dialog Escape default and still handles its own key');
    dialog.querySelector('.le-panel-close').click();
    check(!dialog.open && document.activeElement === nestedEntry && !flyout.hidden, 'closing nested settings restores opener without dismissing flyout');
    press(nestedEntry, 'Escape');

    const history = $('le-chat-history'), historyDropdown = dropdown('history-input', 'history-options');
    history.open = true; historyDropdown.open(); await wait();
    const historyEscape = press(historyDropdown.input, 'Escape');
    check(historyEscape.defaultPrevented && historyDropdown.closed === 1 && history.open, 'history dropdown Escape preserves its parent disclosure');
    press(historyDropdown.input, 'Escape');
    check(!history.open && document.activeElement === history.querySelector('summary'), 'next history Escape closes and restores summary focus');

    const panel = $('preview-panel'), image = panel.querySelector('img');
    const out = panel.querySelector('[data-preview-zoom="out"]'), fit = panel.querySelector('[data-preview-zoom="fit"]'), inside = panel.querySelector('[data-preview-zoom="in"]');
    out.click();
    check(image.dataset.zoom === '75' && image.style.width === '75%' && !out.disabled, 'preview zoom changes rendered image width');
    out.click(); out.click();
    check(image.dataset.zoom === '50' && out.disabled && !inside.disabled, 'minimum zoom clamps and disables zoom out');
    fit.click();
    check(image.dataset.zoom === '100' && !out.disabled && fit.title.includes('100%'), 'fit width resets scale and reenables zoom out');
    for (let i = 0; i < 8; i++) inside.click();
    check(image.dataset.zoom === '250' && inside.disabled && !out.disabled, 'maximum zoom clamps and disables zoom in');
    out.click();
    check(image.dataset.zoom === '225' && !inside.disabled, 'moving away from zoom boundary reenables controls');

    let fullscreen = null, requested = 0, exited = 0;
    Object.defineProperty(document, 'fullscreenElement', { configurable: true, get: () => fullscreen });
    panel.requestFullscreen = () => { requested += 1; fullscreen = panel; document.dispatchEvent(new Event('fullscreenchange')); return Promise.resolve(); };
    document.exitFullscreen = () => { exited += 1; fullscreen = null; document.dispatchEvent(new Event('fullscreenchange')); return Promise.resolve(); };
    let full = panel.querySelector('[data-preview-fullscreen]');
    const other = $('other-preview').querySelector('button');
    full.click();
    check(requested === 1 && full.getAttribute('aria-pressed') === 'true' && full.getAttribute('aria-label') === '退出全屏' && other.getAttribute('aria-pressed') === 'false', 'fullscreen entry synchronizes only the active preview');
    const previousFull = full;
    panel.innerHTML = '<div class="le-original-toolbar"><button data-preview-zoom="out">Out</button><button data-preview-zoom="fit">Fit</button><button data-preview-zoom="in">In</button><button data-preview-fullscreen aria-label="全屏阅读">Fullscreen</button></div><div class="le-original-canvas"><img alt="Next page" width="100" height="100"></div>';
    full = panel.querySelector('[data-preview-fullscreen]');
    await wait();
    check(!previousFull.isConnected && fullscreen === panel && full.getAttribute('aria-pressed') === 'true' && full.getAttribute('aria-label') === '退出全屏' && full.title === '退出全屏', 'replacing page controls while fullscreen preserves exit state without another fullscreenchange');
    check(panel.querySelector('[data-preview-zoom="fit"]').title.includes('100%') && !panel.querySelector('[data-preview-zoom="out"]').disabled && !panel.querySelector('[data-preview-zoom="in"]').disabled, 'new page controls initialize to fresh image scale after replacement');
    fullscreen = null; document.dispatchEvent(new Event('fullscreenchange'));
    check(full.getAttribute('aria-pressed') === 'false' && full.getAttribute('aria-label') === '全屏阅读', 'external fullscreen exit restores accessible button state');
    full.click(); full.click();
    check(exited === 1 && fullscreen === null && full.title === '全屏阅读', 'fullscreen toggle exits through document API');
    panel.requestFullscreen = () => Promise.reject(new Error('Permission denied'));
    full.click(); await wait();
    check(full.title.includes('无法全屏') && full.getAttribute('aria-pressed') === 'false', 'denied fullscreen request reports fallback without false active state');
    check(!window.testUnhandledRejection, 'rejected fullscreen request is handled');
    const output = document.createElement('pre'); output.id = 'results'; output.textContent = JSON.stringify({ checks }); document.body.append(output);
  } catch (error) {
    const output = document.createElement('pre'); output.id = 'results'; output.textContent = JSON.stringify({ checks, error: error.stack }); document.body.append(output);
  }
});
window.addEventListener('unhandledrejection', () => { window.testUnhandledRejection = true; });
