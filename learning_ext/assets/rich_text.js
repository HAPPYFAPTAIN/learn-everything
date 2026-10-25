(() => {
  async function copy(text) {
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(text);
      return true;
    } catch (_) {
      const active = document.activeElement;
      const input = document.createElement('textarea');
      input.value = text;
      input.setAttribute('readonly', '');
      input.style.cssText = 'position:fixed;top:0;left:-9999px;opacity:0';
      document.body.append(input);
      input.select();
      let copied = false;
      try { copied = document.execCommand('copy'); } catch (_) {}
      input.remove();
      active?.focus({preventScroll:true});
      return copied;
    }
  }
  document.addEventListener('click', async event => {
    const button = event.target.closest?.('.le-code-copy');
    if (!button || button.getAttribute('aria-disabled') === 'true') return;
    const code = button.closest('.le-code-block')?.querySelector('pre code');
    if (!code) return;
    button.setAttribute('aria-disabled', 'true');
    const copied = await copy(code.textContent);
    if (!button.isConnected) return;
    const label = button.querySelector('span');
    label.textContent = copied ? '已复制' : '请选中后复制';
    button.dataset.copied = String(copied);
    button.setAttribute('aria-label', copied ? '代码已复制' : '复制失败，请选中代码后复制');
    if (!copied) {
      code.parentElement.focus({preventScroll:true});
      const range = document.createRange();
      range.selectNodeContents(code);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
    }
    setTimeout(() => {
      button.removeAttribute('aria-disabled');
      delete button.dataset.copied;
      label.textContent = '复制';
      button.setAttribute('aria-label', '复制代码');
    }, 1800);
  });
})();
