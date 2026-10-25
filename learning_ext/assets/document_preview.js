(() => {
  function syncControls(panel) {
    if (!panel) return;
    const zoom = Number(panel.querySelector('.le-original-canvas img')?.dataset.zoom || 100);
    panel.querySelectorAll('[data-preview-zoom]').forEach(button => {
      button.disabled = button.dataset.previewZoom === 'out' ? zoom <= 50 : button.dataset.previewZoom === 'in' ? zoom >= 250 : false;
      if (button.dataset.previewZoom === 'fit') button.title = `当前缩放 ${zoom}% · 适合宽度`;
    });
    panel.querySelectorAll('[data-preview-fullscreen]').forEach(button => {
      const active = document.fullscreenElement === panel;
      const label = active ? '退出全屏' : '全屏阅读';
      button.setAttribute('aria-label', label);
      button.setAttribute('aria-pressed', String(active));
      button.title = label;
    });
  }
  document.addEventListener('fullscreenchange', () => document.querySelectorAll('.le-source-original').forEach(syncControls));
  new MutationObserver(records => {
    if (records.some(record => record.target.closest?.('.le-source-original') || [...record.addedNodes].some(node => node.nodeType === 1 && (node.matches('.le-source-original') || node.querySelector('.le-source-original'))))) {
      document.querySelectorAll('.le-source-original').forEach(syncControls);
    }
  }).observe(document.documentElement, { childList: true, subtree: true });
  document.querySelectorAll('.le-source-original').forEach(syncControls);
  document.addEventListener('click', event => {
    const action = event.target.closest('[data-preview-zoom], [data-preview-fullscreen]');
    if (!action) return;
    const panel = action.closest('.le-source-original');
    if (!panel) return;
    if (action.hasAttribute('data-preview-fullscreen')) {
      const request = document.fullscreenElement ? document.exitFullscreen() : panel.requestFullscreen?.();
      request?.catch(() => { action.title = '当前环境无法全屏，请调整窗口阅读'; });
      return;
    }
    const image = panel.querySelector('.le-original-canvas img');
    if (!image) return;
    const prior = Number(image.dataset.zoom || 100);
    const zoom = action.dataset.previewZoom === 'fit' ? 100 : Math.max(50, Math.min(250, prior + (action.dataset.previewZoom === 'in' ? 25 : -25)));
    image.dataset.zoom = String(zoom);
    image.style.width = zoom + '%';
    image.style.maxWidth = 'none';
    syncControls(panel);
  });
})();
