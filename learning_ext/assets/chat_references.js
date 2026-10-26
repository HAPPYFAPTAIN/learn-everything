(() => {
  let active;
  function install() {
    const bot = document.getElementById('main-chat-bot');
    const evidence = document.getElementById('chat-info-panel');
    const tab = document.getElementById('chat-tab');
    if (active?.bot === bot && active?.evidence === evidence) return;
    active?.dispose();
    active = null;
    if (!bot || !evidence || !tab) return;
    const events = new AbortController();
    const home = document.createComment('answer sources');
    evidence.before(home);
    const dialog = document.createElement('dialog');
    dialog.id = 'le-chat-reference-dialog';
    dialog.setAttribute('aria-labelledby', 'le-chat-reference-title');
    dialog.innerHTML = '<header><h2 id="le-chat-reference-title">引用与来源</h2><button type="button" aria-label="关闭引用资料">×</button></header><div class="le-reference-body"></div>';
    dialog.querySelector('.le-reference-body').append(evidence);
    tab.append(dialog);
    const trigger = document.createElement('button');
    trigger.id = 'le-answer-reference-trigger';
    trigger.type = 'button';
    trigger.hidden = true;
    trigger.setAttribute('aria-haspopup', 'dialog');
    trigger.setAttribute('aria-controls', dialog.id);
    trigger.setAttribute('aria-expanded', 'false');
    trigger.innerHTML = '<svg viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M3 4h5l2 2 2-2h5v12h-5l-2 2-2-2H3Zm7 2v12"/></svg><span>查看来源</span>';
    let selected, opener, frame, pendingCitation = null, fresh = true, expectedIndex = null;
    let payload = document.getElementById('html-info-panel')?.innerHTML || '';
    const rows = () => [...bot.querySelectorAll('.message-row.bot-row')];
    function close(restore = true) {
      pendingCitation = null;
      if (dialog.open) dialog.close();
      const pdf = evidence.querySelector('#pdf-modal');
      if (pdf) pdf.style.display = 'none';
      const content = document.getElementById('html-info-panel');
      if (content) content.style.removeProperty('display');
      trigger.setAttribute('aria-expanded', 'false');
      if (restore && opener?.isConnected) opener.focus({preventScroll:true});
    }
    function place() {
      if (!dialog.open) return;
      const anchor = opener?.isConnected && opener.getBoundingClientRect().width ? opener : trigger;
      if (dialog.classList.contains('le-reference-preview')) {
        const width = Math.min(960, document.documentElement.clientWidth - 32);
        dialog.style.setProperty('width', width + 'px', 'important');
        dialog.style.setProperty('left', (document.documentElement.clientWidth - width) / 2 + 'px', 'important');
        dialog.style.setProperty('top', '24px', 'important');
        dialog.style.setProperty('max-height', 'calc(100dvh - 48px)', 'important');
      } else window.LEPanels?.place(dialog, anchor, 'side', 440);
    }
    function open(anchor = trigger) {
      opener = anchor;
      if (!dialog.open) dialog.showModal();
      trigger.setAttribute('aria-expanded', 'true');
      place();
      dialog.querySelector('header button').focus({preventScroll:true});
      requestAnimationFrame(() => { if (dialog.open) window.dispatchEvent(new Event('resize')); });
    }
    function translate(content) {
      content?.querySelectorAll('summary').forEach(summary => {
        const walk = document.createTreeWalker(summary, NodeFilter.SHOW_TEXT);
        while (walk.nextNode()) {
          const node = walk.currentNode;
          let text = node.textContent;
          if (node.parentElement?.tagName === 'I') text = text.replace(/^Image from /, '图片 · ').replace(/^Table from /, '表格 · ').replace(/^(图片 · |表格 · )?\[Page (\d+)\]/, '$1第 $2 页 ·');
          else if (node.parentElement?.closest('a.pdf-link') && text.trim() === '[Preview]') text = '查看原页';
          else if (text.trim() === 'Relevance score') text = '相关度详情';
          else if (/^\s*\[score: [\d.]+\]\s*$/.test(text)) text = text.replace(/\[score: ([\d.]+)\]/, ' · 相关度 $1');
          if (text !== node.textContent) node.textContent = text;
        }
      });
    }
    function sync() {
      const answers = rows();
      if (expectedIndex === null || !selected?.isConnected) selected = answers.at(-1);
      const content = document.getElementById('html-info-panel');
      translate(content);
      dialog.classList.toggle('le-reference-preview', evidence.querySelector('#pdf-modal')?.style.display === 'block');
      const sources = [...(content?.querySelectorAll('details.evidence, .evidence-content') || [])]
        .filter(node => !node.querySelector('.markmap') && !node.closest('.markmap') && (node.textContent.trim() || node.querySelector('img, svg, canvas')));
      const map = content?.querySelector('.markmap');
      const hasMap = !!map && !!(map.textContent.trim() || map.querySelector('svg, path, circle'));
      const plot = [...evidence.querySelectorAll('.js-plotly-plot, .vega-embed, .plot-container svg')]
        .some(node => !node.closest('.hidden, [hidden]'));
      const busy = bot.getAttribute('aria-busy') === 'true' || !!bot.querySelector(':scope > .wrap:not(.hide):not(.error)');
      const available = fresh && !!selected && !busy && !!(sources.length || hasMap || plot);
      trigger.hidden = !available;
      const label = sources.length ? '查看来源' : hasMap ? '思维导图' : '查看图表';
      if (trigger.querySelector('span').textContent !== label) trigger.querySelector('span').textContent = label;
      if (dialog.querySelector('h2').textContent !== label) dialog.querySelector('h2').textContent = label;
      if (selected) {
        const actions = selected.nextElementSibling?.matches('.message-buttons') ? selected.nextElementSibling : selected;
        if (trigger.parentElement !== actions) actions.append(trigger);
      }
      if (!available && dialog.open) close(false);
      if (dialog.open) place();
      if (available && pendingCitation) {
        const link = pendingCitation;
        pendingCitation = null;
        open(link);
        const target = [...evidence.querySelectorAll('mark[id]')].find(node => node.id === link.id);
        if (target) {
          for (let parent = target.parentElement; parent && parent !== evidence; parent = parent.parentElement) {
            if (parent.tagName === 'DETAILS') parent.open = true;
          }
          target.scrollIntoView({block:'center', behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
        }
      }
    }
    function schedule() { cancelAnimationFrame(frame); frame = requestAnimationFrame(sync); }
    function reset() {
      close(false);
      selected = null;
      expectedIndex = null;
      fresh = false;
      trigger.hidden = true;
    }
    trigger.addEventListener('click', event => { event.stopPropagation(); open(); });
    dialog.querySelector('header button').addEventListener('click', () => close());
    dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
    dialog.addEventListener('keydown', event => { if (event.key === 'Escape') event.stopPropagation(); });
    dialog.addEventListener('click', event => {
      if (event.target !== dialog) return;
      const rect = dialog.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) close();
    });
    bot.addEventListener('click', event => {
      if (event.target.closest('.message-buttons, #le-answer-reference-trigger')) return;
      const row = event.target.closest('.message-row');
      if (!row) return;
      const answer = row.matches('.bot-row') ? row : rows()[[...bot.querySelectorAll('.user-row')].indexOf(row)];
      expectedIndex = rows().indexOf(answer);
      if (answer !== selected) {
        close(false);
        selected = answer;
        fresh = false;
        trigger.hidden = true;
      }
      const citation = event.target.closest('a.citation');
      if (citation) {
        event.preventDefault();
        event.stopImmediatePropagation();
        citation.closest('button[data-testid]')?.click();
        pendingCitation = citation;
        schedule();
      }
    }, {capture:true, signal:events.signal});
    document.addEventListener('click', event => {
      if (event.target.closest('#new-conv-button, #conversation-dropdown [role="option"], #le-composer .submit-button')) reset();
      if (event.target.closest('#le-app-tabs > .tab-nav > button')) close(false);
    }, {capture:true, signal:events.signal});
    document.addEventListener('change', event => { if (event.target.closest('#conversation-dropdown')) reset(); }, {signal:events.signal});
    document.addEventListener('keydown', event => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.target.closest('#chat-input textarea, #conversation-dropdown')) reset();
    }, {capture:true, signal:events.signal});
    const observer = new MutationObserver(records => {
      const next = document.getElementById('html-info-panel')?.innerHTML || '';
      if (next !== payload) {
        payload = next;
        const stamp = next.match(/<!--le-reference-selection:(\d+):[a-z\d-]+-->/);
        if (stamp ? Number(stamp[1]) === expectedIndex : expectedIndex === null) fresh = true;
        else fresh = false;
      }
      if (records.some(record => !trigger.contains(record.target))) schedule();
    });
    observer.observe(evidence, {subtree:true, childList:true, characterData:true, attributes:true, attributeFilter:['class', 'style']});
    observer.observe(bot, {subtree:true, childList:true, characterData:true, attributes:true, attributeFilter:['aria-busy']});
    window.addEventListener('resize', place, {signal:events.signal});
    active = {bot, evidence, dispose() {
      close(false);
      cancelAnimationFrame(frame);
      events.abort();
      observer.disconnect();
      home.replaceWith(evidence);
      trigger.remove();
      dialog.remove();
    }};
    sync();
  }
  let frame;
  new MutationObserver(() => { cancelAnimationFrame(frame); frame = requestAnimationFrame(install); })
    .observe(document.documentElement, {subtree:true, childList:true});
  install();
})();
