(function () {
  function installWordLookup() {
    if (window.__leWordLookupInstalled) return;
    window.__leWordLookupInstalled = true;
    let activeTerm = '';
    let panel = null;
    let timeout = null;
    let observer = null;
    let observed = null;

    function close() {
      activeTerm = '';
      clearTimeout(timeout);
      if (panel) panel.remove();
      panel = null;
    }

    function fit() {
      const bar = document.getElementById('le-sel-bar');
      if (!bar || bar.hidden) return;
      const r = bar.getBoundingClientRect();
      bar.style.left = Math.max(12, Math.min(r.left, innerWidth - r.width - 12)) + 'px';
      bar.style.top = Math.max(12, Math.min(r.top, innerHeight - r.height - 12)) + 'px';
    }

    function observeOutput() {
      const output = document.getElementById('le-term-output');
      if (!output || output === observed) return;
      if (observer) observer.disconnect();
      observed = output;
      observer = new MutationObserver(() => {
        if (!activeTerm || !panel) return;
        const content = output.querySelector('[data-le-explained-term]');
        if (!content || !content.textContent.trim() || output.querySelector('.wrap:not(.hide)')) return;
        if (content.dataset.leExplainedTerm !== activeTerm) return;
        clearTimeout(timeout);
        const copy = content.cloneNode(true);
        copy.querySelectorAll('h1,h2,h3,h4,h5,h6').forEach(heading => {
          if (heading.textContent.replace(/^🔍\s*/, '').trim() === activeTerm) heading.remove();
        });
        panel.querySelector('.le-lookup-result').replaceChildren(...copy.childNodes);
        panel.removeAttribute('aria-busy');
        fit();
      });
      observer.observe(output, { childList: true, subtree: true, characterData: true });
    }

    window.__leCloseExplanation = close;
    window.__leExplainSelection = function (term, bar) {
      if (activeTerm) return;
      close();
      observeOutput();
      panel = document.createElement('section');
      panel.id = 'le-lookup-popup';
      panel.setAttribute('aria-label', '名词解释');
      panel.setAttribute('aria-busy', 'true');
      const header = document.createElement('header');
      const identity = document.createElement('div');
      identity.className = 'le-lookup-identity';
      const eyebrow = document.createElement('span');
      eyebrow.className = 'le-lookup-eyebrow';
      eyebrow.textContent = '✦ 随读解惑';
      const title = document.createElement('strong');
      title.textContent = term;
      const dismiss = document.createElement('button');
      dismiss.type = 'button';
      dismiss.textContent = '×';
      dismiss.setAttribute('aria-label', '收起解释');
      dismiss.onclick = close;
      identity.append(eyebrow, title);
      header.append(identity, dismiss);
      const result = document.createElement('div');
      result.className = 'le-lookup-result';
      result.setAttribute('role', 'status');
      result.innerHTML = '<div class="le-lookup-loading"><span>正在整理关键点…</span><i></i><i></i><i></i></div>';
      panel.append(header, result);
      bar.appendChild(panel);
      fit();
      const input = document.querySelector('#le-selected-term textarea, #le-selected-term input');
      if (!input) {
        panel.removeAttribute('aria-busy');
        result.textContent = '请先打开一节课程，再解释选中的内容。';
        return;
      }
      activeTerm = term;
      const proto = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
      function set(value) {
        setter.call(input, value);
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
      }
      set('');
      setTimeout(() => { if (activeTerm === term) set(term); }, 30);
      timeout = setTimeout(() => {
        if (!panel) return;
        activeTerm = '';
        panel.removeAttribute('aria-busy');
        result.textContent = '暂时没有收到解释，请稍后重试。';
      }, 90000);
    };
    window.addEventListener('resize', fit, { passive: true });
  }
  window.__leInstallWordLookup = installWordLookup;
  installWordLookup();
})();
