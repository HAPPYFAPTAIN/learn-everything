(() => {
  let scheduled = false;
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    const options = event.target.closest?.('.wrap')?.querySelector('ul.options[role="listbox"]');
    if (options?.getClientRects().length) event.preventDefault();
  }, true);
  function decorate() {
    scheduled = false;
    document.querySelectorAll('ul.options[role="listbox"]').forEach(menu => {
      const input = menu.parentElement.querySelector('input[role="listbox"]');
      const room = menu.style.maxHeight || '48dvh';
      if (menu.style.getPropertyValue('--le-menu-room') !== room) menu.style.setProperty('--le-menu-room', room);
      const hint = input && !input.readOnly && !input.disabled ? '输入关键词筛选 · ↑↓ 选择 / Enter 确认' : '↑↓ 选择 · Enter 确认';
      if (menu.dataset.leHint !== hint) menu.dataset.leHint = hint;
      menu.querySelectorAll('[role="option"]').forEach(option => {
        const label = option.getAttribute('aria-label');
        if (label && option.title !== label) option.title = label;
      });
    });
  }
  function schedule() {
    if (!scheduled) { scheduled = true; requestAnimationFrame(decorate); }
  }
  function start() {
    new MutationObserver(mutations => {
      if (mutations.some(mutation => {
        const target = mutation.target.nodeType === 1 ? mutation.target : mutation.target.parentElement;
        return !target?.closest('#le-coach-transcript,#le-coach-stream');
      })) schedule();
    }).observe(document.body, {childList:true, subtree:true, attributes:true, attributeFilter:['style','aria-expanded','aria-label']});
    schedule();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once:true});
  else start();
})();
