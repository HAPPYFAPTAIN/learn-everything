(() => {
  const mounted = new WeakSet();
  function install() {
    const bot = document.getElementById('main-chat-bot');
    const composer = document.getElementById('le-composer');
    if (!bot || !composer || mounted.has(bot)) return;
    mounted.add(bot);
    const status = document.createElement('div');
    status.id = 'le-chat-stream-status';
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    status.innerHTML = '<i aria-hidden="true"></i><span></span>';
    status.hidden = true;
    composer.before(status);
    let frame, following = true, userCount = 0, scrollbox;
    function sync() {
      const viewport = bot.querySelector('.bubble-wrap');
      if (viewport && viewport !== scrollbox) {
        scrollbox = viewport;
        viewport.addEventListener('scroll', () => {
          following = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight < 80;
        }, {passive:true});
      }
      const count = bot.querySelectorAll('.user-row').length;
      if (count !== userCount) { following = true; userCount = count; }
      const busy = !!bot.querySelector(':scope > .wrap:not(.hide):not(.error)');
      const rows = bot.querySelectorAll('.message-row.bot-row');
      const last = rows[rows.length - 1];
      const text = last?.querySelector('.prose')?.textContent.trim() || '';
      const waiting = !text || /^(Thinking\s*\.{0,3}|正在思考\s*[.…]*)$/i.test(text);
      rows.forEach(row => row.classList.toggle('le-answer-waiting', row === last && busy && waiting));
      const label = busy ? (waiting ? '正在思考…' : '正在回答…') : '';
      if (status.querySelector('span').textContent !== label) status.querySelector('span').textContent = label;
      status.hidden = !busy;
      bot.setAttribute('aria-busy', String(busy));
      if (following && scrollbox?.clientHeight) scrollbox.scrollTop = scrollbox.scrollHeight;
    }
    function schedule() { cancelAnimationFrame(frame); frame = requestAnimationFrame(sync); }
    new MutationObserver(records => {
      if (records.some(record => record.type !== 'attributes' || record.target.matches('.wrap'))) schedule();
    }).observe(bot, {subtree:true, childList:true, characterData:true, attributes:true, attributeFilter:['class']});
    new ResizeObserver(schedule).observe(bot);
    sync();
  }
  let frame;
  new MutationObserver(() => { cancelAnimationFrame(frame); frame = requestAnimationFrame(install); })
    .observe(document.documentElement, {childList:true, subtree:true});
  install();
})();
