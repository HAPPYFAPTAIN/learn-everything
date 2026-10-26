(() => {
  if (window.LEWorkspaceDisplay) return;
  const root = document.documentElement;
  const icon = path => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
  const searchIcon = icon('<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/>');
  const displayIcon = icon('<path d="M4 7h9m4 0h3M4 17h3m4 0h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>');
  const expandIcon = icon('<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/>');
  const focusIcon = icon('<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M8 4v16"/>');
  let menu, dialog, toolbar, opener, toastTimer;
  let choice = 0, matches = [];
  const visible = el => !!el && !el.closest('[hidden],[aria-hidden="true"]') && el.getClientRects().length > 0;
  function readSize() {
    try { return [16,18,20].includes(Number(localStorage.getItem('le.reading.size'))) ? Number(localStorage.getItem('le.reading.size')) : 18; }
    catch (_) { return 18; }
  }
  function setSize(value) {
    root.style.setProperty('--le-reading-size', `${value}px`);
    try { localStorage.setItem('le.reading.size', String(value)); } catch (_) {}
    menu?.querySelectorAll('[data-reading-size]').forEach(el => el.setAttribute('aria-pressed', String(Number(el.dataset.readingSize) === value)));
  }
  setSize(readSize());
  function announce(message) {
    let status = document.getElementById('le-workspace-status');
    if (!status) {
      status = document.createElement('div'); status.id = 'le-workspace-status'; status.setAttribute('role','status'); document.body.append(status);
    }
    status.textContent = message; status.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { status.hidden = true; }, 2600);
  }
  function focusLayout(value) {
    root.classList.toggle('le-focus-layout', value);
    menu?.querySelector('[data-focus-layout]')?.setAttribute('aria-checked', String(value));
    window.dispatchEvent(new Event('resize'));
  }
  function closeMenu(restore = true) {
    if (!menu || menu.hidden) return;
    menu.hidden = true;
    document.getElementById('le-display-trigger')?.setAttribute('aria-expanded','false');
    if (restore) document.getElementById('le-display-trigger')?.focus({preventScroll:true});
  }
  function positionMenu() {
    if (!menu || menu.hidden) return;
    const rect = document.getElementById('le-display-trigger').getBoundingClientRect();
    menu.style.top = `${rect.bottom + 9}px`;
    menu.style.left = `${Math.max(10, Math.min(innerWidth - menu.offsetWidth - 10, rect.right - menu.offsetWidth))}px`;
  }
  function openMenu() {
    menu.hidden = false;
    const reading = visible(document.getElementById('le-guide-md')) || visible(document.getElementById('le-action-learning'));
    menu.querySelector('[data-reading-options]').hidden = !reading;
    menu.querySelector('[data-focus-layout]').setAttribute('aria-checked', String(root.classList.contains('le-focus-layout')));
    menu.querySelector('[data-browser-fullscreen] span').textContent = document.fullscreenElement ? '退出全屏' : '进入全屏';
    document.getElementById('le-display-trigger').setAttribute('aria-expanded','true');
    setSize(readSize()); positionMenu();
    menu.querySelector('button').focus({preventScroll:true});
    window.LEMotion?.play(menu, 'popover');
  }
  async function fullscreen() {
    closeMenu();
    if (document.fullscreenElement) { await document.exitFullscreen?.(); return; }
    try {
      if (!document.documentElement.requestFullscreen) throw new Error('unavailable');
      await document.documentElement.requestFullscreen();
    } catch (_) { announce('当前窗口不支持浏览器全屏'); }
  }
  function entries() {
    const aliases = { 'learning-workbench-tab-button':'课程 阅读 实践 笔记 workbench', 'chat-tab-button':'聊天 提问 chat', 'indices-tab-button':'文件 文档 library', 'quick-setup-tab-button':'API 平台 模型 settings', 'learning-review-tab-button':'卡片 review', 'learning-quiz-tab-button':'考试 quiz' };
    return Array.from(document.querySelectorAll('#le-app-tabs > .tab-nav > button[id$="-tab-button"]'))
      .filter(el => !el.disabled)
      .map(el => ({ id:el.id, title:(el.textContent || '').trim(), alias:aliases[el.id] || '', active:el.getAttribute('aria-selected')==='true', svg:el.querySelector('svg')?.outerHTML || '' }));
  }
  function highlightChoice() {
    dialog.querySelectorAll('[data-page-id]').forEach((button, i) => {
      button.dataset.active = String(i === choice);
      button.setAttribute('aria-selected', String(i === choice));
    });
    const selected = dialog.querySelectorAll('[data-page-id]')[choice];
    const input = dialog.querySelector('input');
    if (selected) { input.setAttribute('aria-activedescendant', selected.id); selected.scrollIntoView({block:'nearest'}); }
    else input.removeAttribute('aria-activedescendant');
  }
  function renderResults() {
    const query = dialog.querySelector('input').value.trim().toLowerCase();
    matches = entries().filter(item => `${item.title} ${item.alias}`.toLowerCase().includes(query));
    choice = 0;
    const list = dialog.querySelector('[role=listbox]'); list.replaceChildren();
    matches.forEach((item, i) => {
      const button = document.createElement('button'); button.type='button'; button.id=`le-jump-option-${i}`;
      button.dataset.pageId=item.id; button.setAttribute('role','option'); button.tabIndex=-1;
      const glyph=document.createElement('span'); glyph.className='le-jump-icon'; glyph.innerHTML=item.svg || searchIcon;
      const label=document.createElement('span'); label.textContent=item.title;
      const state=document.createElement('small'); state.textContent=item.active ? '当前页面' : '↗';
      button.append(glyph,label,state); list.append(button);
    });
    dialog.querySelector('[data-no-results]').hidden=!!matches.length;
    highlightChoice();
  }
  function closeJump() { if (dialog?.open) dialog.close(); }
  function openJump() {
    if (!dialog) return;
    closeMenu(false); opener=document.activeElement;
    dialog.querySelector('input').value=''; dialog.showModal(); renderResults();
    dialog.querySelector('input').focus(); window.LEMotion?.play(dialog, 'popover');
  }
  function activate(id) {
    const target=document.getElementById(id); opener=target;
    closeJump();
    target?.click(); target?.focus({preventScroll:true});
  }
  function mount() {
    const bar=document.querySelector('.le-topbar'); if (!bar || document.getElementById('le-workspace-tools')) return;
    toolbar=document.createElement('div'); toolbar.id='le-workspace-tools'; toolbar.setAttribute('aria-label','工作空间工具');
    toolbar.innerHTML=`<button type="button" id="le-jump-trigger" title="搜索页面 · Ctrl K" aria-label="搜索页面" aria-haspopup="dialog">${searchIcon}<span>搜索页面</span><kbd>Ctrl K</kbd></button><button type="button" id="le-display-trigger" title="显示设置" aria-label="显示设置" aria-expanded="false" aria-controls="le-display-menu">${displayIcon}</button>`;
    const anchor=bar.querySelector('#le-theme-toggle'); anchor ? anchor.before(toolbar) : bar.append(toolbar);
    menu=document.createElement('section'); menu.id='le-display-menu'; menu.hidden=true; menu.setAttribute('aria-label','显示设置');
    menu.innerHTML=`<div class="le-display-caption">工作空间</div><button type="button" data-focus-layout role="switch" aria-checked="false">${focusIcon}<span>专注布局</span><i aria-hidden="true"></i></button><button type="button" data-browser-fullscreen>${expandIcon}<span>进入全屏</span><kbd>Esc</kbd></button><div data-reading-options><div class="le-display-caption">阅读字号</div><div class="le-reading-options"><button type="button" data-reading-size="16" aria-pressed="true">标准</button><button type="button" data-reading-size="18" aria-pressed="false">舒适</button><button type="button" data-reading-size="20" aria-pressed="false">大字</button></div></div>`;
    document.body.append(menu);
    dialog=document.createElement('dialog'); dialog.id='le-jump-dialog'; dialog.setAttribute('aria-label','搜索页面');
    dialog.innerHTML=`<div class="le-jump-search">${searchIcon}<input type="search" placeholder="搜索页面，如课程、资料、模型" aria-label="搜索页面或功能" role="combobox" aria-autocomplete="list" aria-controls="le-jump-results" aria-expanded="true" autocomplete="off"><button type="button" data-jump-close aria-label="关闭搜索页面"><kbd>Esc</kbd></button></div><div id="le-jump-results" role="listbox" aria-label="页面"></div><p data-no-results hidden>没有找到，试试「课程」「资料」或「模型」。</p><footer><span>↑ ↓ 选择</span><span>Enter 前往</span></footer>`;
    document.body.append(dialog);
    toolbar.querySelector('#le-jump-trigger').addEventListener('click',openJump);
    toolbar.querySelector('#le-display-trigger').addEventListener('click',()=>menu.hidden?openMenu():closeMenu());
    menu.querySelector('[data-focus-layout]').addEventListener('click',()=>focusLayout(!root.classList.contains('le-focus-layout')));
    menu.querySelector('[data-browser-fullscreen]').addEventListener('click',fullscreen);
    menu.querySelectorAll('[data-reading-size]').forEach(button=>button.addEventListener('click',()=>setSize(Number(button.dataset.readingSize))));
    dialog.querySelector('input').addEventListener('input',renderResults);
    dialog.addEventListener('click',event=>{const button=event.target.closest('[data-page-id]'); if(button) activate(button.dataset.pageId); if(event.target.closest('[data-jump-close]') || event.target===dialog) closeJump();});
    dialog.addEventListener('close',()=>opener?.isConnected&&opener.focus({preventScroll:true}));
    dialog.addEventListener('keydown',event=>{
      if(event.isComposing || event.target !== dialog.querySelector('input')) return;
      if(event.key==='ArrowDown'||event.key==='ArrowUp'){ event.preventDefault(); choice=Math.max(0,Math.min(matches.length-1,choice+(event.key==='ArrowDown'?1:-1))); highlightChoice(); }
      if(event.key==='Enter'&&matches[choice]){event.preventDefault();activate(matches[choice].id);}
    });
    menu.addEventListener('keydown',event=>{
      if(event.key==='Tab'){ const buttons=[...menu.querySelectorAll('button')].filter(visible); const i=buttons.indexOf(document.activeElement); if((event.shiftKey&&i===0)||(!event.shiftKey&&i===buttons.length-1)){event.preventDefault();buttons[event.shiftKey?buttons.length-1:0]?.focus();} }
    });
  }
  document.addEventListener('click',event=>{if(!menu?.hidden&&!menu?.contains(event.target)&&!event.target.closest('#le-display-trigger'))closeMenu(false);});
  document.addEventListener('click',event=>{
    if(event.target.closest('#le-nav-toggle') && root.classList.contains('le-focus-layout')){
      event.preventDefault(); event.stopImmediatePropagation(); focusLayout(false);
    }
  }, true);
  document.addEventListener('focusin',event=>{
    if(menu&&!menu.hidden&&!menu.contains(event.target)&&!event.target.closest('#le-display-trigger'))closeMenu(false);
  });
  document.addEventListener('keydown',event=>{
    if(event.isComposing || event.defaultPrevented) return;
    if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'){
      if([...document.querySelectorAll('dialog[open],[aria-modal="true"]')].some(el=>el!==dialog&&visible(el))) return;
      event.preventDefault(); dialog?.open?closeJump():openJump(); return;
    }
    if(event.key!=='Escape'||event.defaultPrevented||dialog?.open)return;
    if(menu&&!menu.hidden){event.preventDefault();closeMenu();return;}
    if([...document.querySelectorAll('dialog[open],.le-settings-deck:not([hidden]),#le-theme-menu:not([hidden])')].some(visible))return;
    if(root.classList.contains('le-focus-layout')){event.preventDefault();focusLayout(false);}
  });
  window.addEventListener('resize',positionMenu);
  window.addEventListener('storage',event=>{if(event.key==='le.reading.size')setSize(readSize());});
  window.LEWorkspaceDisplay={focus:focusLayout};
  const boot=()=>{mount();new MutationObserver(()=>{if(!document.getElementById('le-workspace-tools'))mount();}).observe(document.body,{childList:true,subtree:true});};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
