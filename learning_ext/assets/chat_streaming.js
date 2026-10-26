(() => {
  let active;
  function install() {
    const bot = document.getElementById('main-chat-bot');
    const composer = document.getElementById('le-composer');
    if (active?.bot === bot && active?.composer === composer) return;
    active?.dispose();
    active = null;
    if (!bot || !composer) return;
    const events = new AbortController();
    const status = document.createElement('div');
    status.id = 'le-chat-stream-status';
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    status.innerHTML = '<i aria-hidden="true"></i><span></span>';
    status.hidden = true;
    composer.before(status);
    const latest = document.createElement('button');
    latest.id = 'le-chat-follow-latest';
    latest.type = 'button';
    latest.hidden = true;
    latest.setAttribute('aria-controls', 'main-chat-bot');
    latest.setAttribute('aria-label', '回到最新回答');
    latest.innerHTML = '<svg viewBox="0 0 20 20" width="16" height="16" fill="none" aria-hidden="true"><path d="M10 3v13m-5-5 5 5 5-5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg><span>回到最新</span><i aria-hidden="true"></i>';
    bot.append(latest);
    let frame, scrollbox, viewportEvents;
    let following = true, unread = false, userCount = 0, firstUser = '';
    let lastText = '', lastScrollTop = 0, touchY = null;
    const nearBottom = () => !scrollbox || scrollbox.scrollHeight - scrollbox.scrollTop - scrollbox.clientHeight < 56;
    function renderLatest() {
      latest.hidden = !scrollbox?.clientHeight || following || nearBottom();
      latest.classList.toggle('le-has-new-answer', unread);
      latest.querySelector('span').textContent = unread ? '有新内容 · 回到最新' : '回到最新';
      latest.setAttribute('aria-label', unread ? '有新的回答内容，回到最新回答' : '回到最新回答');
    }
    function follow() {
      following = true;
      unread = false;
      if (scrollbox?.clientHeight) {
        scrollbox.scrollTop = scrollbox.scrollHeight;
        lastScrollTop = scrollbox.scrollTop;
      }
      renderLatest();
    }
    function pause() { following = false; renderLatest(); }
    function reset() {
      following = true;
      unread = false;
      lastText = '';
      schedule();
    }
    latest.addEventListener('click', follow, {signal: events.signal});
    document.addEventListener('click', event => {
      if (event.target.closest('#new-conv-button, #conversation-dropdown [role="option"]')) reset();
    }, {capture: true, signal: events.signal});
    document.addEventListener('change', event => {
      if (event.target.closest('#conversation-dropdown')) reset();
    }, {signal: events.signal});
    document.addEventListener('keydown', event => {
      if (event.key === 'Enter' && event.target.closest('#conversation-dropdown')) reset();
    }, {signal: events.signal});
    function sync() {
      bot.querySelectorAll('.message > button[data-testid]').forEach(button => { button.tabIndex = -1; });
      bot.querySelectorAll('.message-buttons button').forEach(button => {
        const label = button.classList.contains('like-button') ? '有帮助'
          : button.classList.contains('dislike-button') ? '需要改进'
          : button.classList.contains('action') ? (button.closest('.message-buttons-right') ? '复制消息' : '复制回答') : null;
        if (label && button.getAttribute('aria-label') !== label) button.setAttribute('aria-label', label);
      });
      const send = composer.querySelector('.submit-button');
      if (send && !send.getAttribute('aria-label')) { send.setAttribute('aria-label', '发送消息'); send.title = '发送消息'; }
      const viewport = bot.querySelector('.bubble-wrap');
      if (viewport && viewport !== scrollbox) {
        viewportEvents?.abort();
        viewportEvents = new AbortController();
        scrollbox = viewport;
        lastScrollTop = viewport.scrollTop;
        const options = {passive: true, signal: viewportEvents.signal};
        viewport.addEventListener('scroll', () => {
          // Content growing changes the distance to the bottom, not the reader's intent.
          if (viewport.scrollTop < lastScrollTop - 1) following = false;
          else if (nearBottom()) { following = true; unread = false; }
          lastScrollTop = viewport.scrollTop;
          renderLatest();
        }, options);
        viewport.addEventListener('wheel', event => { if (event.deltaY < 0) pause(); }, options);
        viewport.addEventListener('touchstart', event => { touchY = event.touches[0]?.clientY ?? null; }, options);
        viewport.addEventListener('touchmove', event => {
          const nextY = event.touches[0]?.clientY;
          if (touchY !== null && nextY > touchY + 2) pause();
          touchY = nextY ?? null;
        }, options);
        viewport.addEventListener('keydown', event => {
          if (event.target.closest('input, textarea, [contenteditable="true"]')) return;
          if (['ArrowUp', 'PageUp', 'Home'].includes(event.key) || (event.key === ' ' && event.shiftKey)) pause();
        }, {signal: viewportEvents.signal});
      }
      const users = bot.querySelectorAll('.user-row');
      const first = users[0]?.textContent || '';
      if (users.length !== userCount || first !== firstUser) {
        following = true;
        unread = false;
        lastText = '';
        userCount = users.length;
        firstUser = first;
      }
      const busy = !!bot.querySelector(':scope > .wrap:not(.hide):not(.error)');
      const rows = bot.querySelectorAll('.message-row.bot-row');
      const last = rows[rows.length - 1];
      const text = last?.querySelector('.prose')?.textContent.trim() || '';
      const waiting = !text || /^(Thinking\s*\.{0,3}|正在思考\s*[.…]*)$/i.test(text);
      if (!following && text !== lastText && !waiting) unread = true;
      lastText = text;
      rows.forEach(row => row.classList.toggle('le-answer-waiting', row === last && busy && waiting));
      rows.forEach(row => row.classList.toggle('le-streaming', row === last && busy && !waiting));
      const label = busy ? (waiting ? '正在思考…' : '正在回答…') : '';
      if (status.querySelector('span').textContent !== label) status.querySelector('span').textContent = label;
      status.hidden = !busy;
      bot.setAttribute('aria-busy', String(busy));
      if (following) follow();
      else renderLatest();
    }
    function schedule() { cancelAnimationFrame(frame); frame = requestAnimationFrame(sync); }
    const messages = new MutationObserver(records => {
      if (records.some(record => !latest.contains(record.target) && (record.type !== 'attributes' || record.target.matches('.wrap')))) schedule();
    });
    messages.observe(bot, {subtree:true, childList:true, characterData:true, attributes:true, attributeFilter:['class']});
    const resize = new ResizeObserver(schedule);
    resize.observe(bot);
    active = {bot, composer, dispose() {
      cancelAnimationFrame(frame);
      events.abort();
      viewportEvents?.abort();
      messages.disconnect();
      resize.disconnect();
      latest.remove();
      status.remove();
    }};
    sync();
  }
  let frame;
  new MutationObserver(() => { cancelAnimationFrame(frame); frame = requestAnimationFrame(install); })
    .observe(document.documentElement, {childList:true, subtree:true});
  install();
})();
