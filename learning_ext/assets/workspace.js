(() => {
  document.documentElement.classList.remove('dark');
  function boot() {
    document.body.classList.remove('dark');
    document.addEventListener('click', event => {
      const link = event.target.closest('[data-le-nav]');
      if (link) {
        event.preventDefault();
        const tab = document.getElementById(link.dataset.leNav + '-button');
        if (tab) {tab.click(); tab.focus({preventScroll:true}); window.scrollTo({top:0,behavior:'instant'});}
      }
      const chatPanel = event.target.closest('[data-le-chat-panel]');
      if (chatPanel) {
        const container = document.getElementById('chat-tab');
        const isOpen = container?.classList.toggle('le-chat-' + chatPanel.dataset.leChatPanel + '-open');
        chatPanel.setAttribute('aria-expanded', String(Boolean(isOpen)));
      }
      if (event.target.closest('#le-app-tabs > .tab-nav > button')) window.scrollTo({top:0,behavior:'instant'});
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape') {
        document.getElementById('chat-tab')?.classList.remove('le-chat-sources-open','le-chat-evidence-open');
        document.querySelectorAll('[data-le-chat-panel]').forEach(b=>b.setAttribute('aria-expanded','false'));
      }
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded',boot,{once:true}); else boot();
})();

(() => {
  let step = 0, panel, previousFocus;
  const learningSteps = [
    {tab:'quick-setup-tab',target:'#le-settings-form',title:'先让 AI 连上',body:'选择平台，填好密钥和模型。点「测试连接」，成功后点「启用连接」。已保存的连接可以直接选择。'},
    {tab:'learning-guide-tab',target:'#le-onboarding-card',title:'告诉我们你的学习目标',body:'在首页填写目标，可选填基础与时间。确认学习安排后生成路线。'},
    {tab:'learning-path-tab',target:'#le-plan-preview',title:'看一眼路线，再保存',body:'等路线生成后，确认内容合适后点「就按这个学」。保存完成后点「打开这门课程」。'},
    {tab:'learning-workbench-tab',target:'#le-left-col',title:'选一节，开始学',body:'选中刚保存的项目和第一节课，在右侧阅读。不懂就点右下角的助教悬浮球，对话框可以随意拖动和缩放。学会后点「已掌握本节」。'}
  ];
  const tours = {
    learning: learningSteps,
    review: [
      {tab:'learning-review-tab',target:'#le-review-flow',title:'先回忆，再看答案',body:'选择学习项目，打开一张复习卡。先自己想一遍，再显示答案，按真实记忆情况评分。系统会安排下次复习。'},
      {tab:'learning-quiz-tab',target:'#le-quiz-settings',title:'用几道题检查理解',body:'选择项目和题目数量，生成一组测验。答完一题再查看解析，重点看看哪里还没弄懂。'},
      {tab:'learning-dashboard-tab',target:'#le-dashboard-toolbar',title:'看看最近的进展',body:'选择同一个项目查看进展。下方可以切换最近 3 天或 30 天的学习时长，也可以导出全部记录。'}
    ],
    documents: [
      {tab:'indices-tab',target:'#indices-tab',title:'先添加一份资料',body:'点「添加资料」，选择文件或网页，再点「加入资料库」。整理完成后就可以阅读原件，也可以用这份资料提问。'},
      {tab:'chat-tab',target:'#le-composer',title:'直接问你的问题',body:'在输入框写下问题并发送。用左侧加号选择参考资料；回答出现后，可在下方展开引用，核对原文。'}
    ]
  };
  let steps=learningSteps, initialPreview=false;
  let maskParts = [], maskFrame;
  function positionMask(){
    if(!panel)return;
    const target=document.querySelector(steps[step].target);
    const rect=target?.getBoundingClientRect();
    if(rect){
      const x=Math.max(0,rect.left-8), y=Math.max(0,rect.top-8);
      const right=Math.min(innerWidth,rect.right+8), bottom=Math.min(innerHeight,rect.bottom+8);
      const regions=[[0,0,innerWidth,y],[0,bottom,innerWidth,Math.max(0,innerHeight-bottom)],[0,y,x,Math.max(0,bottom-y)],[right,y,Math.max(0,innerWidth-right),Math.max(0,bottom-y)]];
      regions.forEach(([left,top,width,height],i)=>Object.assign(maskParts[i].style,{left:left+'px',top:top+'px',width:width+'px',height:height+'px'}));
    }
    maskFrame=requestAnimationFrame(positionMask);
  }
  function stop(){
    document.querySelectorAll('.le-tour-target').forEach(el=>el.classList.remove('le-tour-target'));
    cancelAnimationFrame(maskFrame);maskParts.forEach(el=>el.remove());maskParts=[];
    panel?.remove(); panel=null; document.body.classList.remove('le-tour-active');
    document.getElementById('le-planner')?.classList.toggle('le-show-preview',initialPreview);
    previousFocus?.focus({preventScroll:true});
  }
  function show(){
    const item=steps[step];
    if(item.target==='#le-plan-preview')document.getElementById('le-planner')?.classList.add('le-show-preview');
    if(item.target==='#le-plan-input')document.getElementById('le-planner')?.classList.remove('le-show-preview');
    document.querySelectorAll('.le-tour-target').forEach(el=>el.classList.remove('le-tour-target'));
    document.getElementById(item.tab+'-button')?.click();
    if(!panel){panel=document.createElement('aside');panel.id='le-guided-tour';panel.setAttribute('role','region');panel.setAttribute('aria-label','操作指引');document.body.appendChild(panel);document.body.classList.add('le-tour-active');maskParts=Array.from({length:4},()=>{const el=document.createElement('div');el.className='le-tour-mask';el.setAttribute('aria-hidden','true');document.body.appendChild(el);return el;});positionMask();}
    panel.innerHTML=`<div class="le-tour-meta"><span>操作指引 · ${step+1} / ${steps.length}</span><button data-tour-close aria-label="退出操作指引">退出</button></div><h2 tabindex="-1">${item.title}</h2><p>${item.body}</p><div class="le-tour-actions"><button data-tour-back ${step===0?'disabled':''}>上一步</button><button data-tour-next>${step===steps.length-1?'我知道了，开始学习':'下一步 →'}</button></div><small>这是操作提示，不会替你生成或保存内容。</small>`;
    requestAnimationFrame(()=>{
      const target=document.querySelector(item.target);
      target?.classList.add('le-tour-target');target?.scrollIntoView({block:'center',behavior:'smooth'});
      panel.querySelector('h2')?.focus({preventScroll:true});
    });
  }
  document.addEventListener('click',e=>{
    if(e.target.closest('[data-le-tour-start]')){previousFocus=e.target.closest('[data-le-tour-start]');steps=tours[previousFocus.dataset.leTourStart]||learningSteps;initialPreview=!!document.getElementById('le-planner')?.classList.contains('le-show-preview');step=0;show();}
    if(e.target.closest('[data-tour-close]'))stop();
    if(e.target.closest('[data-tour-back]')&&step>0){step--;show();}
    if(e.target.closest('[data-tour-next]')){if(step===steps.length-1)stop();else{step++;show();}}
  });
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&panel)stop();});
})();

(() => {
  function translateMindmap(){
    const root=document.getElementById('use-mindmap-checkbox');
    if(!root)return;
    root.querySelector('input[type=checkbox]')?.setAttribute('role','switch');
    const walk=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);
    while(walk.nextNode())if(/^Mindmap \(o(n|ff)\)$/.test(walk.currentNode.textContent.trim()))walk.currentNode.textContent='附带思维导图';
  }
  function install(){const root=document.getElementById('use-mindmap-checkbox');if(root){translateMindmap();new MutationObserver(translateMindmap).observe(root,{subtree:true,childList:true,characterData:true});}else setTimeout(install,300);}
  install();
})();



(() => {
  function install(){
    const area=document.getElementById('chat-area'),settings=document.getElementById('chat-settings-expand'),input=document.getElementById('chat-input'),bot=document.getElementById('main-chat-bot');
    if(!area||!settings||!input||!bot){setTimeout(install,300);return;}
    if(document.getElementById('le-composer'))return;
    const modelInput=settings.querySelector('input[aria-label="回答模型"]');
    const modelBlock=document.getElementById('le-chat-connection-controls') || modelInput?.closest('.block');
    if(modelBlock){
      const header=document.createElement('div');header.id='le-chat-model-header';
      document.getElementById('chat-tab').prepend(header);header.append(modelBlock);
      modelInput?.setAttribute('title','选择回答模型');
    }
    const title=document.createElement('div');title.id='le-chat-welcome';
    title.innerHTML='<div class="le-chat-hero-art" aria-hidden="true"></div><h1>今天想弄明白什么？</h1>';
    const starters=document.createElement('div');starters.className='le-chat-starters';
    starters.innerHTML='<button type="button" data-le-prompt="请用一个生活中的例子，帮我解释这个概念："><span aria-hidden="true">✦</span><strong>讲懂一个概念</strong><b aria-hidden="true">↗</b></button><button type="button" data-le-source-starter data-le-prompt="请帮我梳理已选资料中的核心观点，并标出对应来源。"><span aria-hidden="true">▤</span><strong>读懂一份资料</strong><b aria-hidden="true">↗</b></button><button type="button" data-le-prompt="我想检查自己的理解。请先问我一个问题，等我回答后再给反馈。主题是："><span aria-hidden="true">✓</span><strong>检验我的理解</strong><b aria-hidden="true">↗</b></button>';
    starters.addEventListener('click',event=>{
      const starter=event.target.closest('[data-le-prompt]');
      const textarea=input.querySelector('textarea');
      if(!starter||!textarea)return;
      if(textarea.value.trim()){textarea.focus();return;}
      textarea.value=starter.dataset.lePrompt;
      textarea.dispatchEvent(new Event('input',{bubbles:true}));
      textarea.focus();
      textarea.setSelectionRange(textarea.value.length,textarea.value.length);
      if(starter.hasAttribute('data-le-source-starter'))sourceButton.click();
    });
    const composer=document.createElement('div');composer.id='le-composer';input.before(composer);composer.append(input);composer.before(title);
    const suggestions=document.getElementById('le-chat-suggestions');
    area.append(title,composer,starters);
    const sourceTools=document.createElement('div');sourceTools.className='le-composer-tools';
    const sourceButton=document.createElement('button');sourceButton.type='button';sourceButton.className='le-source-shortcut';sourceButton.textContent='选择参考资料';sourceButton.setAttribute('aria-expanded','false');
    const libraryButton=document.createElement('button');libraryButton.type='button';libraryButton.className='le-library-shortcut';libraryButton.textContent='打开资料库 ↗';libraryButton.dataset.leNav='indices-tab';
    sourceTools.append(sourceButton,libraryButton);composer.append(sourceTools);
    if(suggestions)area.append(suggestions);
    document.querySelector('#suggest-chat-checkbox input')?.setAttribute('role','switch');
    const plus=document.createElement('button');plus.id='le-chat-plus';plus.type='button';plus.textContent='+';plus.setAttribute('aria-label','打开问答工具');plus.setAttribute('aria-expanded','false');sourceTools.prepend(plus);
    const submitButton=input.querySelector('.submit-button');
    if(submitButton)sourceTools.append(submitButton);
    const polishObserver=new MutationObserver(()=>{
      const polishTools=input.querySelector('.le-polish-tools');
      if(polishTools&&!sourceTools.contains(polishTools))sourceTools.insertBefore(polishTools,submitButton||null);
    });
    polishObserver.observe(input,{childList:true,subtree:true});
    const menu=document.createElement('div');menu.id='le-chat-tool-menu';menu.hidden=true;
    const options=[['sources','参考资料'],['answer','回答方式'],['citation','引用展示'],['mindmap','思维导图']];
    menu.innerHTML='<div class="le-menu-caption">问答工具</div>'+options.map(([key,label])=>`<button type="button" data-chat-menu="${key}"><span>${label}</span><span aria-hidden="true">›</span></button>`).join('');composer.append(menu);composer.append(settings);
    const flyout=document.createElement('section');flyout.id='le-chat-flyout';flyout.hidden=true;flyout.setAttribute('aria-label','问答工具设置');
    flyout.innerHTML='<div class="le-flyout-head"><button type="button" data-flyout-back>‹ 返回</button><strong></strong><button type="button" data-flyout-close aria-label="关闭工具菜单">×</button></div>';
    composer.append(flyout);
    const sources=document.getElementById('conv-settings-panel');
    [settings,sources].filter(Boolean).forEach(el=>flyout.append(el));
    if(sources){
      const history=document.createElement('details');history.id='le-chat-history';
      history.innerHTML='<summary>历史对话 <span aria-hidden="true">⌄</span></summary><section aria-label="管理历史对话"><h2>历史对话</h2></section>';
      document.getElementById('chat-tab').prepend(history);
      const historyPanel=history.querySelector('section');
      const conversation=document.getElementById('conversation-dropdown');
      if(conversation){
        historyPanel.append(conversation);
        const translateHistory=()=>conversation.querySelectorAll('input[placeholder="Browse conversation"]').forEach(el=>el.setAttribute('placeholder','选择历史对话'));
        translateHistory();
        new MutationObserver(translateHistory).observe(conversation,{subtree:true,childList:true,attributes:true,attributeFilter:['placeholder']});
      }
      const actions=document.createElement('div');actions.className='le-history-actions';
      const newButton=document.getElementById('new-conv-button');
      if(newButton){Array.from(newButton.parentElement.children).filter(el=>el.tagName==='BUTTON').forEach(el=>actions.append(el));}
      historyPanel.append(actions);
      const emptyHistory=document.createElement('p');emptyHistory.className='le-history-empty';emptyHistory.textContent='还没有历史对话';emptyHistory.hidden=true;
      historyPanel.insertBefore(emptyHistory,actions);
      let historyExpanded=false;
      function updateHistoryEmpty(){
        const expanded=conversation?.querySelector('input')?.getAttribute('aria-expanded')==='true';
        emptyHistory.hidden=!expanded||!!conversation?.querySelector('[role="option"]');
        if(historyExpanded&&!expanded)history.open=false;
        historyExpanded=expanded;
      }
      if(conversation)new MutationObserver(updateHistoryEmpty).observe(conversation,{subtree:true,childList:true,attributes:true,attributeFilter:['aria-expanded']});
      history.addEventListener('toggle',()=>{
        if(!history.open)return;
        const selector=conversation?.querySelector('input[role="listbox"]');
        if(selector&&selector.getAttribute('aria-expanded')!=='true')selector.focus({preventScroll:true});
        updateHistoryEmpty();
      });
      conversation?.addEventListener('click',event=>{
        if(event.target.closest('[role="option"]'))requestAnimationFrame(()=>{history.open=false;});
      },true);
      conversation?.addEventListener('change',()=>{history.open=false;});
      newButton?.addEventListener('click',()=>{history.open=false;});

      document.addEventListener('click',e=>{if(!e.composedPath().includes(history))history.open=false;});
      document.addEventListener('keydown',e=>{if(e.key==='Escape'&&history.open&&!e.defaultPrevented&&!document.querySelector('dialog[open]')){e.preventDefault();history.open=false;history.querySelector('summary').focus({preventScroll:true});}});
      const advanced=document.createElement('section');advanced.className='le-source-preferences';advanced.dataset.lePanel='检索偏好';advanced.dataset.leIcon='tune';
      sources.append(advanced);['index-1','index-2'].forEach(id=>{const el=document.getElementById(id);if(el)advanced.append(el);});
      const report=document.getElementById('report-accordion');if(report)sources.append(report);
      const suggestedQuestions=document.getElementById('suggest-chat-checkbox');
      if(suggestedQuestions)advanced.append(suggestedQuestions);
      function sourceSelection(){
        const files=document.getElementById('index-0');
        const mode=files?.querySelector('input[type="radio"]:checked')?.value;
        const chosen=[...(files?.querySelectorAll('.token > span')||[])].map(node=>node.textContent.trim());
        const text=mode==='all'?'参考资料 · 全部文件':mode==='select'&&chosen.length?`参考资料 · ${chosen.length} 份`:'选择参考资料';
        if(sourceButton.textContent!==text)sourceButton.textContent=text;
        sourceButton.title=mode==='select'&&chosen.length?chosen.join('、'):'选择回答时参考的资料';
      }
      let sourceFrame;
      const scheduleSourceSelection=()=>{cancelAnimationFrame(sourceFrame);sourceFrame=requestAnimationFrame(sourceSelection);};
      sources.addEventListener('change',scheduleSourceSelection);
      new MutationObserver(scheduleSourceSelection).observe(sources,{childList:true,subtree:true,attributes:true,attributeFilter:['aria-checked']});
      sourceSelection();
      const note=document.createElement('p');note.className='le-source-note';note.textContent='选择参考资料，回答会基于你的检索范围。';sources.prepend(note);
      function localize(){sources.querySelectorAll('input[placeholder="Browse conversation"]').forEach(el=>el.setAttribute('placeholder','选择历史对话'));const walk=document.createTreeWalker(sources,NodeFilter.SHOW_TEXT);const words={'Browse conversation':'选择历史对话','Search All':'全部资料','Search In File(s)':'指定文件','Drop File Here':'将文件拖到这里','Click to Upload':'点击上传'};while(walk.nextNode()){const key=walk.currentNode.textContent.trim();if(words[key])walk.currentNode.textContent=words[key];}}
      localize();new MutationObserver(localize).observe(sources,{subtree:true,childList:true,characterData:true});
    }
    let directSources=false;
    function position(){
      if(!window.LEPanels)return;
      if(!menu.hidden)window.LEPanels.place(menu,plus,'bottom',224);
      if(flyout.hidden)return;
      flyout.dataset.direct=String(directSources);
      const anchor=directSources?sourceButton:menu.querySelector('[aria-expanded="true"]') || menu;
      window.LEPanels.place(flyout,anchor,directSources?'bottom':'side',320);
    }
    new ResizeObserver(position).observe(flyout);
    let hoverTimer;
    function close(){clearTimeout(hoverTimer);menu.hidden=true;flyout.hidden=true;settings.dataset.menu='';plus.setAttribute('aria-expanded','false');sourceButton.setAttribute('aria-expanded','false');document.getElementById('chat-tab')?.classList.remove('le-chat-sources-open','le-chat-evidence-open');menu.querySelectorAll('button').forEach(el=>el.setAttribute('aria-expanded','false'));}
    function backSubmenu(){
      if(directSources){close();sourceButton.focus({preventScroll:true});return;}
      const opener=menu.querySelector('[aria-expanded="true"]');
      clearTimeout(hoverTimer);flyout.hidden=true;settings.dataset.menu='';
      menu.querySelectorAll('button').forEach(el=>el.setAttribute('aria-expanded','false'));
      (opener||plus).focus({preventScroll:true});
    }
    plus.setAttribute('aria-controls',menu.id);
    sourceButton.setAttribute('aria-controls',flyout.id);
    close();
    plus.addEventListener('click',()=>{const open=menu.hidden;close();directSources=false;menu.hidden=!open;plus.setAttribute('aria-expanded',String(open));position();});
    plus.addEventListener('keydown',event=>{
      if(!['ArrowDown','ArrowUp'].includes(event.key))return;
      event.preventDefault();
      clearTimeout(hoverTimer);
      if(menu.hidden)plus.click();
      const items=Array.from(menu.querySelectorAll('[data-chat-menu]'));
      (event.key==='ArrowUp'?items.at(-1):items[0])?.focus({preventScroll:true});
    });
    sourceButton.addEventListener('click',()=>{const open=flyout.hidden||!directSources;close();directSources=true;if(open){openSubmenu(menu.querySelector('[data-chat-menu="sources"]'));sourceButton.setAttribute('aria-expanded','true');}});
    function openSubmenu(button){clearTimeout(hoverTimer);if(!button||(menu.hidden&&!directSources))return;const kind=button.dataset.chatMenu;
      flyout.hidden=false;flyout.dataset.panel=kind;settings.dataset.menu=['sources','evidence'].includes(kind)?'':kind;
      flyout.querySelector('strong').textContent=options.find(item=>item[0]===kind)[1];
      menu.querySelectorAll('button').forEach(el=>el.setAttribute('aria-expanded',String(el===button)));
      const toggle=settings.querySelector(':scope>.label-wrap');if(toggle&&!toggle.classList.contains('open'))toggle.click();position();
    }
    menu.addEventListener('click',e=>openSubmenu(e.target.closest('[data-chat-menu]')));
    menu.addEventListener('pointerover',e=>{if(e.pointerType!=='mouse')return;const button=e.target.closest('[data-chat-menu]');if(!button||button.contains(e.relatedTarget))return;clearTimeout(hoverTimer);hoverTimer=setTimeout(()=>openSubmenu(button),140);});
    menu.addEventListener('pointerout',e=>{const button=e.target.closest('[data-chat-menu]');if(button&&!button.contains(e.relatedTarget))clearTimeout(hoverTimer);});
    menu.addEventListener('keydown',event=>{
      const items=Array.from(menu.querySelectorAll('[data-chat-menu]'));
      const button=event.target.closest('[data-chat-menu]');
      if(!button)return;
      if(event.key==='ArrowRight'){
        openSubmenu(button);flyout.querySelector('[data-flyout-back]').focus({preventScroll:true});event.preventDefault();return;
      }
      if(!['ArrowDown','ArrowUp','Home','End'].includes(event.key))return;
      event.preventDefault();
      clearTimeout(hoverTimer);
      const index=items.indexOf(button);
      const next=event.key==='Home'?0:event.key==='End'?items.length-1:(index+(event.key==='ArrowDown'?1:-1)+items.length)%items.length;
      if(!flyout.hidden){clearTimeout(hoverTimer);flyout.hidden=true;settings.dataset.menu='';items.forEach(item=>item.setAttribute('aria-expanded','false'));}
      items[next]?.focus({preventScroll:true});
    });
    flyout.querySelector('[data-flyout-close]').addEventListener('click',()=>{close();(directSources?sourceButton:plus).focus();});
    flyout.querySelector('[data-flyout-back]').addEventListener('click',backSubmenu);
    window.addEventListener('resize',position);window.addEventListener('scroll',position,true);
    function sync(){area.classList.toggle('le-chat-empty',!!bot.querySelector('.placeholder-container'));}
    new MutationObserver(sync).observe(bot,{subtree:true,childList:true});sync();
    document.addEventListener('click',e=>{if(!e.composedPath().includes(composer)&&!e.target.closest('[data-le-source-starter],.le-settings-deck'))close();});
    document.addEventListener('keydown',event=>{
      if(event.key!=='Escape'||event.defaultPrevented||document.querySelector('dialog[open]'))return;
      if(!flyout.hidden){event.preventDefault();backSubmenu();}
      else if(!menu.hidden){event.preventDefault();close();plus.focus({preventScroll:true});}
    });
  }
  install();
})();

/* 测验设置面板的收起箭头：看题时收起来，让题目区变宽。
   注意：paint 里绝不能改 innerHTML——那会触发下面这个 MutationObserver，
   回调又调 paint，主线程直接死循环（踩过一次，整页卡死）。 */
(function quizSettingsToggle(){
  const KEY = 'le-quiz-settings-collapsed';
  const ICONS =
    '<svg class="le-q-ico-left" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 6l-6 6 6 6"/></svg>' +
    '<svg class="le-q-ico-right" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>';

  const collapsed = () => {
    try { return localStorage.getItem(KEY) === '1'; } catch (e) { return false; }
  };

  function paint() {
    const flow = document.getElementById('le-quiz-flow');
    const btn = document.getElementById('le-quiz-toggle');
    if (!flow || !btn) return;
    const on = collapsed();
    flow.classList.toggle('le-quiz-collapsed', on);
    btn.classList.toggle('le-q-collapsed', on);
    const label = on ? '展开测验设置' : '收起测验设置';
    if (btn.title !== label) {
      btn.title = label;
      btn.setAttribute('aria-label', label);
      btn.setAttribute('aria-expanded', String(!on));
    }
  }

  function mount() {
    const panel = document.getElementById('le-quiz-settings');
    if (!panel) return false;
    let btn = document.getElementById('le-quiz-toggle');
    if (!btn) {
      btn = document.createElement('button');
      btn.id = 'le-quiz-toggle';
      btn.type = 'button';
      btn.innerHTML = ICONS;   // 只在这里写一次，paint 不碰
      btn.addEventListener('click', () => {
        try { localStorage.setItem(KEY, collapsed() ? '0' : '1'); } catch (e) {}
        paint();
      });
      panel.appendChild(btn);
    }
    paint();
    return true;
  }

  mount();
  if (!document.getElementById('le-quiz-toggle')) {
    let n = 0;
    const timer = setInterval(() => { if (mount() || ++n > 60) clearInterval(timer); }, 300);
  }
  // 组件被 Gradio 重渲染后按钮会丢，补回去（只补不重画，避免自触发）
  new MutationObserver(() => {
    if (!document.getElementById('le-quiz-settings')) return;
    if (document.getElementById('le-quiz-toggle')) paint(); else mount();
  }).observe(document.documentElement, { childList: true, subtree: true });
})();

/* 开发中页面：一键复制反馈模板，用户粘给客服就行 */
(function soonFeedback(){
  const TEMPLATE = [
    '【动手学 · 功能建议】',
    '我最想用它练的场景：',
    '（例如：用 Excel 做月度报表，每次都卡在数据透视表）',
    '',
    '最希望它做到：',
    '（例如：我在第 3 步走错时当场提醒，而不是做完才说）',
  ].join('\n');

  document.addEventListener('click', (e) => {
    const btn = e.target.closest && e.target.closest('[data-soon-copy]');
    if (!btn) return;
    const done = () => {
      btn.textContent = '已复制，去粘给客服';
      btn.classList.add('is-done');
      setTimeout(() => {
        btn.textContent = '复制反馈模板';
        btn.classList.remove('is-done');
      }, 2400);
    };
    const fallback = () => {
      const ta = document.createElement('textarea');
      ta.value = TEMPLATE;
      ta.style.position = 'fixed';
      ta.style.top = '-999px';
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); done(); } catch (err) { btn.textContent = '请手动联系客服'; }
      document.body.removeChild(ta);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(TEMPLATE).then(done).catch(fallback);
    } else {
      fallback();
    }
  });
})();
