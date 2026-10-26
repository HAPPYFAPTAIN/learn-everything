(() => {
  const bound = new WeakMap(), decks = new Map();
  const paths = {
    tune: '<path d="M4 7h7m4 0h5M4 17h3m4 0h9"/><circle cx="13" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
    upload: '<path d="M12 16V3m-4 4 4-4 4 4M4 15v5h16v-5"/>',
    graph: '<circle cx="6" cy="6" r="3"/><circle cx="18" cy="8" r="3"/><circle cx="10" cy="19" r="3"/><path d="m9 6 6 1M7 9l2 7m3 1 4-6"/>',
    feedback: '<path d="M5 4h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H9l-5 3V6a2 2 0 0 1 1-2Z"/><path d="M8 9h9m-9 4h6"/>',
    link: '<path d="m10 14 4-4m-6 6-1 1a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0m2 1 1-1a4 4 0 1 1 6 6l-4 4a4 4 0 0 1-6 0"/>',
    refresh: '<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 6a8 8 0 0 1 13 3M5 15a8 8 0 0 0 13 3"/>',
    book: '<path d="M3 4h7l2 2 2-2h7v15h-7l-2 2-2-2H3Zm9 2v15"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l4 2"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v1"/>',
    chevron: '<path d="m9 5 7 7-7 7"/>',
  };
  function icon(name) { return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.tune}</svg>`; }
  function place(panel, anchor, side='bottom', preferredWidth=340) {
    const rect = anchor.getBoundingClientRect ? anchor.getBoundingClientRect() : anchor;
    const viewportWidth=document.documentElement.clientWidth || innerWidth;
    const viewportHeight=document.documentElement.clientHeight || innerHeight;
    const edge = 12, gap = 6, width = Math.min(preferredWidth, viewportWidth-edge*2);
    panel.style.setProperty('width',width+'px','important');
    panel.style.setProperty('max-height',(viewportHeight-edge*2)+'px','important');
    panel.style.setProperty('right','auto','important');
    panel.style.setProperty('bottom','auto','important');
    const height = Math.min(panel.getBoundingClientRect().height,viewportHeight-edge*2);
    let left = rect.left, top = rect.bottom+gap;
    if(side==='side' && rect.right+gap+width <= viewportWidth-edge) { left=rect.right+gap; top=rect.top; }
    else if(side==='side' && rect.left-gap-width >= edge) { left=rect.left-gap-width; top=rect.top; }
    else if(top+height > viewportHeight-edge && rect.top-gap-height >= edge) top=rect.top-gap-height;
    panel.style.setProperty('left',Math.max(edge,Math.min(left,viewportWidth-width-edge))+'px','important');
    panel.style.setProperty('top',Math.max(edge,Math.min(top,viewportHeight-height-edge))+'px','important');
  }
  function scopeFor(root) { return root.closest('#chat-tab,#quick-setup-tab,#le-guided-home,#indices-tab,#learning-path-tab') || document.getElementById('le-app-tabs'); }
  function deckFor(scope) {
    if (decks.has(scope)) return decks.get(scope);
    const dialog = document.createElement('dialog');
    dialog.className = 'le-settings-deck';
    dialog.innerHTML = '<header class="le-panel-header"><button type="button" class="le-panel-back" aria-label="返回上一级">←</button><h2></h2><button type="button" class="le-panel-close" aria-label="关闭设置">×</button></header><div class="le-panel-body"></div>';
    scope.append(dialog);
    const body = dialog.querySelector('.le-panel-body'), back = dialog.querySelector('.le-panel-back');
    let stack = [], anchor = null, opener = null;
    function position() {
      if (!dialog.open || !anchor) return;
      const currentAnchor = opener?.isConnected && opener.getBoundingClientRect().width ? opener : anchor;
      place(dialog,currentAnchor,stack[0]?.side || 'bottom',stack.at(-1)?.width || 340);
    }
    function restore(item) { item.root.classList.remove('le-panel-current'); item.entry.after(item.root); item.entry.setAttribute('aria-expanded','false'); }
    function paint() {
      const item = stack.at(-1);
      stack.forEach(record => record.root.classList.toggle('le-panel-current',record === item));
      dialog.querySelector('h2').textContent = item.title;
      dialog.setAttribute('aria-label',item.title);
      dialog.dataset.panel = item.root.id || '';
      back.hidden = stack.length < 2;
      body.scrollTop = 0;
      position();
    }
    function close() {
      while(stack.length) restore(stack.pop());
      if(dialog.open) dialog.close();
      opener?.focus({preventScroll:true});
    }
    function previous() {
      if(stack.length < 2) return close();
      const item = stack.pop(); restore(item); paint(); item.entry.focus({preventScroll:true});
    }
    const controller = { open(item) {
      if(stack.some(record => record === item)) return;
      if(!dialog.open) { opener = item.entry; anchor = item.entry.getBoundingClientRect(); }
      if(item.root.tagName === 'DETAILS') item.root.open = true;
      else if(item.header && !item.header.classList.contains('open')) item.header.click();
      stack.push(item); body.append(item.root); item.entry.setAttribute('aria-expanded','true');
      item.root.classList.add('le-panel-current');
      if(!dialog.open) dialog.showModal();
      paint(); dialog.querySelector('.le-panel-close').focus({preventScroll:true});
    }, close };
    back.addEventListener('click',previous);
    dialog.querySelector('.le-panel-close').addEventListener('click',close);
    dialog.addEventListener('cancel',event=>{event.preventDefault();previous();});
    dialog.addEventListener('keydown',event=>{if(event.key === 'Escape')event.stopPropagation();});
    dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)close();}});
    new ResizeObserver(position).observe(body);
    window.addEventListener('resize',position);
    window.addEventListener('scroll',event=>{if(!dialog.contains(event.target))position();},true);
    decks.set(scope,controller);
    return controller;
  }
  function register(root, title, symbol='tune') {
    if(!root) return;
    if(bound.has(root)) return bound.get(root);
    const scope = scopeFor(root); if(!scope) return;
    const header = root.querySelector(':scope > button.label-wrap');
    const entry = document.createElement('button');
    entry.type='button'; entry.className='le-settings-entry'; entry.setAttribute('aria-haspopup','dialog'); entry.setAttribute('aria-expanded','false');
    entry.innerHTML = `<span class="le-entry-icon">${icon(symbol)}</span><span class="le-entry-title"></span><span class="le-entry-chevron">${icon('chevron')}</span>`;
    entry.querySelector('.le-entry-title').textContent=title;
    root.before(entry); root.classList.add('le-panel-source');
    if(root.id==='le-course-admin')entry.id='le-course-admin-trigger';
    if(root.id==='le-route-history')entry.id='le-route-picker-trigger';
    const widths = {'le-env-setup':420,'le-course-add':420,'le-route-history':420,'le-route-files':420,'le-route-management':420,'le-route-save-progress':420};
    const item = {root,entry,header,title,width:widths[root.id],side:root.closest('#le-chat-flyout,.le-settings-deck')?'side':'bottom'}; bound.set(root,item);
    entry.addEventListener('click',()=>deckFor(scope).open(item));
    if(root.id==='le-route-history')root.addEventListener('change',event=>{
      if(event.target.closest('#le-route-picker'))deckFor(scope).close();
    });
    if(root.classList.contains('le-library-nav')) root.addEventListener('click',event=>{
      if(event.target.closest('[role=tab]')) deckFor(scope).close();
    });
    return item;
  }
  document.addEventListener('click',event=>{
    if(event.target.closest('#le-adapt-open'))decks.forEach(deck=>deck.close());
  });
  window.LEPanels = {register,icon,place};
  function modelPicker() {
    const root=document.getElementById('le-chat-connection-controls');
    if(!root || (!bound.has(root) && !root.closest('#le-chat-model-header')))return;
    const item=register(root,'切换模型','tune');
    if(!item)return;
    const entry=item.entry;
    if(!entry.id){
      entry.id='le-chat-model-trigger';
      const provider=document.createElement('span');provider.className='le-model-provider';
      entry.querySelector('.le-entry-title').after(provider);
      root.addEventListener('input',schedule);root.addEventListener('change',schedule);
    }
    const model=root.querySelector('input[aria-label="回答模型"]')?.value || '默认模型';
    const provider=root.querySelector('input[aria-label="回答平台"]')?.value || '默认连接';
    const label=entry.querySelector('.le-entry-title'),badge=entry.querySelector('.le-model-provider');
    if(label.textContent!==model)label.textContent=model;
    if(badge.textContent!==provider)badge.textContent=provider;
    const catalog=JSON.parse(document.getElementById('le-platform-filter')?.dataset.catalog || '{}');
    const brand=Object.values(catalog).find(item=>provider===item.name || provider.startsWith(item.name+' · ')) || catalog.custom;
    const mark=entry.querySelector('.le-entry-icon');
    if(brand?.icon && mark.dataset.brand!==brand.icon){
      const image=document.createElement('img');image.src=brand.icon;image.alt='';image.width=24;image.height=24;
      mark.replaceChildren(image);mark.dataset.brand=brand.icon;
    }
    const accessible='切换模型：'+model+'，'+provider;
    if(entry.getAttribute('aria-label')!==accessible)entry.setAttribute('aria-label',accessible);
    entry.title=model+' · '+provider;
  }
  const definitions = [
    ['#le-course-admin','课程管理','tune'],
    ['#le-env-setup','学习环境','tune'],
    ['#le-course-add','添加课程','book'],
    ['#le-course-add-options','编号与难度','tune'],
    ['#le-course-maintenance','内容维护','tune'],
    ['#le-project-settings','项目设置','tune'],
    ['#le-route-history','我的学习路线','book'],
    ['#le-route-files','导入路线','upload'],
    ['#le-route-management','批量管理路线','tune'],
    ['#le-route-save-progress','课程准备状态','info'],
    ['#le-chat-add-source','添加资料','upload'],
    ['#index-1','图谱检索','graph'],['#index-2','关联检索','link'],['#report-accordion','回答反馈','feedback'],
    ['#le-learning-preferences','我的学习节奏','clock'],
    ['#le-connection-advanced','连接与检索设置','tune'],['#le-endpoint-options','连接地址','link'],
    ['#le-embedding-options','资料检索','book'],['#le-platform-help','平台使用说明','info'],
    ['.le-import-options','更新已有资料','tune'],
    ['.le-file-requirements','支持的格式与大小','info'],
    ['.le-goal-disclosure','我的学习初衷','book'],
  ];
  let frame;
  function install() {
    modelPicker();
    document.querySelectorAll('#le-course-refresh-actions button,#le-adapt-open,#le-course-reload').forEach(button=>{
      if(button.querySelector('.le-entry-icon'))return;
      button.classList.add('le-course-command');
      const mark=document.createElement('span');mark.className='le-entry-icon';
      mark.innerHTML=icon(button.id==='le-adapt-open'?'tune':'refresh');button.prepend(mark);
    });
    document.querySelectorAll('#le-route-picker label > span').forEach(label=>{
      if(label.querySelector('.le-route-option-title'))return;
      const lines=label.textContent.trim().split('\n');
      if(lines.length<2)return;
      const title=document.createElement('strong'), progress=document.createElement('small');
      title.className='le-route-option-title';title.textContent=lines.slice(0,-1).join(' ');
      progress.className='le-route-option-progress';progress.textContent=lines.at(-1);
      label.replaceChildren(title,progress);
    });
    definitions.forEach(([selector,title,symbol])=>document.querySelectorAll(selector).forEach(root=>{
      if(root.id==='le-route-save-progress') {
        const ready=!!root.querySelector('.le-prep-panel');
        if(bound.has(root)) bound.get(root).entry.hidden=!ready;
        if(!ready) return;
      }
      register(root,title,symbol);
    }));
    document.querySelectorAll('[data-le-panel]').forEach(root=>register(root,root.dataset.lePanel,root.dataset.leIcon));
    document.querySelectorAll('#le-chat-tool-menu [data-chat-menu]').forEach(button=>{
      if(button.querySelector('svg'))return;
      const el=document.createElement('span');el.className='le-tool-icon';el.innerHTML=icon({sources:'book',answer:'tune',citation:'link',mindmap:'graph'}[button.dataset.chatMenu]);button.prepend(el);
    });
  }
  function schedule(){cancelAnimationFrame(frame);frame=requestAnimationFrame(install);}
  new MutationObserver(mutations=>{
    if(mutations.some(mutation=>{
      const target=mutation.target.nodeType===1?mutation.target:mutation.target.parentElement;
      return !target?.closest('#le-coach-transcript,#le-coach-stream');
    }))schedule();
  }).observe(document.documentElement,{childList:true,subtree:true});schedule();
  document.addEventListener('click',event=>{if(event.target.closest('#le-app-tabs > .tab-nav > button'))decks.forEach(deck=>deck.close());});
})();
