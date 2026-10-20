/* 动手学的界面行为：空态判定、自动滚到底、切页后聚焦输入框。 */
(() => {
  const root = () => document.getElementById('le-coach-root');
  const scrollBox = () => document.getElementById('le-coach-scroll');
  const feed = () => document.querySelector('#le-coach-transcript .le-coach-feed');
  const inputBox = () => document.querySelector('#le-coach-input textarea');

  let lastHeight = 0;

  function hasContent() {
    const node = feed();
    if (!node) return false;
    return !!node.querySelector('.le-msg, .le-tool, .le-note');
  }

  function syncEmpty() {
    const box = root();
    if (!box) return false;
    box.classList.toggle('le-empty', !hasContent());
    return true;
  }

  function toBottom(force) {
    const area = scrollBox();
    if (!area) return;
    const gap = area.scrollHeight - area.scrollTop - area.clientHeight;
    if (force || gap < 180) area.scrollTop = area.scrollHeight;
  }

  function focusInput() {
    const box = inputBox();
    if (box && document.activeElement !== box) {
      try {
        box.focus({ preventScroll: true });
      } catch (e) {
        box.focus();
      }
    }
  }

  let queued = false;
  function refresh(forceScroll) {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      const ready = syncEmpty();
      const area = scrollBox();
      const grew = area ? area.scrollHeight > lastHeight : false;
      if (area) lastHeight = area.scrollHeight;
      if (ready) toBottom(forceScroll || grew);
    });
  }

  // 转写区每次更新都会整体替换内容，盯 documentElement 的子树变化就够
  const observer = new MutationObserver(() => refresh(false));

  function boot() {
    syncEmpty();
    observer.observe(document.documentElement, { childList: true, subtree: true });
    refresh(true);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }

  // 切到「动手学」页签时把光标放回输入框
  document.addEventListener(
    'click',
    (event) => {
      if (event.target.closest('#learning-coach-tab-button')) setTimeout(focusInput, 320);
    },
    true
  );

  // Esc 收起所有已展开的工具输出
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    document
      .querySelectorAll('#le-coach-transcript details[open]')
      .forEach((node) => node.removeAttribute('open'));
  });
})();
