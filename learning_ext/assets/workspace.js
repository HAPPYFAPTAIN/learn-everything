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
    {tab:'quick-setup-tab',target:'#le-settings-form',title:'先让 AI 连上',body:'选择服务商，填好模型和密钥。点「测试连接」，成功后「保存并启用」。已经配好可以直接下一步。'},
    {tab:'learning-path-tab',target:'#le-plan-input',title:'写一句你想学什么',body:'填写一个学习方向，点「继续」逐步选择基础、目标和节奏；可选内容可以跳过。最后点「生成我的学习路线」。'},
    {tab:'learning-path-tab',target:'#le-plan-preview',title:'看一眼路线，再保存',body:'等路线生成后，确认内容合适后点「保存路线，开始学习」。保存完成后再进入下一步。'},
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
      {tab:'indices-tab',target:'#indices-tab',title:'先添加一份资料',body:'在「文件资料」上传 PDF、文档或笔记，再点「上传并建立索引」。等处理完成后，选中文件，点「使用此资料提问」。'},
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
  let index=0;
  const fields=['le-wizard-topic','le-wizard-background','le-wizard-goal','le-wizard-hours'];
  const titles=['想学点什么？','从你的起点出发','学完后，你想做到什么？','选择舒服的学习节奏'];
  const hints=['从一个想解决的问题开始，一句话就够。','完全零基础也没关系；不确定可以跳过。','例如：完成一个小项目，或读懂一篇论文。可以先留空。','不用一次投入很多，稳定的小步更容易坚持。'];
  function render(feedback=''){
    const planner=document.getElementById('le-planner');if(!planner)return;
    planner.classList.add('le-wizard');planner.classList.remove('le-show-preview');
    fields.forEach((id,i)=>document.getElementById(id)?.classList.toggle('le-wizard-current',i===index));
    document.querySelector('[data-wizard-title]').textContent=titles[index];
    document.querySelector('[data-wizard-hint]').textContent=hints[index];
    document.querySelector('[data-wizard-count]').textContent=`0${index+1} / 04`;
    document.querySelector('.le-wizard-track i').style.width=`${index*100/4}%`;
    document.querySelector('[data-wizard-feedback]').textContent=feedback;
    const back=document.querySelector('[data-wizard-back]');back.disabled=index===0;
    const next=document.querySelector('[data-wizard-next]');next.hidden=index===3;
    next.textContent=index===0?'继续 →':'继续 / 跳过 →';
    document.getElementById('le-wizard-generate').classList.toggle('le-wizard-ready',index===3);
  }
  function init(){if(!document.getElementById('le-wizard-topic')){setTimeout(init,300);return;}render();}
  document.addEventListener('click',e=>{
    if(e.target.closest('[data-wizard-next]')){
      const input=document.querySelector('#le-wizard-topic textarea');
      if(index===0&&!input?.value.trim()){document.querySelector('[data-wizard-feedback]').textContent='先写下一个想学的方向。';input?.focus();return;}
      const filled=document.querySelector('#'+fields[index]+' textarea')?.value.trim();
      index=Math.min(3,index+1);render(filled?'已填写，向前一步。':'已跳过，之后也可以补充。');
      document.getElementById('le-wizard-header')?.scrollIntoView({block:'start',behavior:'smooth'});
    }
    if(e.target.closest('[data-wizard-back]')){index=Math.max(0,index-1);render();}
    if(e.target.closest('[data-wizard-edit]')){render();}
    if(e.target.closest('#le-route-regenerate, #le-route-refine, #le-route-load'))document.getElementById('le-planner')?.classList.add('le-show-preview');
    if(e.target.closest('#le-wizard-generate')&&!e.target.closest('button')?.disabled){
      if(document.querySelector('#le-wizard-topic textarea')?.value.trim())document.getElementById('le-planner').classList.add('le-show-preview');
    }
  });
  init();
})();

(() => {
  function install(){
    const area=document.getElementById('chat-area'),settings=document.getElementById('chat-settings-expand'),input=document.getElementById('chat-input'),bot=document.getElementById('main-chat-bot');
    if(!area||!settings||!input||!bot){setTimeout(install,300);return;}
    if(document.getElementById('le-composer'))return;
    // Move the original bound model control; preserve its Gradio callbacks.
    const modelInput=settings.querySelector('input[aria-label="回答模型"]');
    const modelBlock=modelInput?.closest('.block');
    if(modelBlock){
      const header=document.createElement('header');header.id='le-chat-model-header';header.setAttribute('aria-label','回答模型');
      document.getElementById('chat-tab').prepend(header);header.append(modelBlock);
      modelInput.setAttribute('title','选择回答模型');
    }
    const title=document.createElement('div');title.id='le-chat-welcome';title.innerHTML='<h1>今天想学点什么？</h1>';
    const composer=document.createElement('div');composer.id='le-composer';input.before(composer);composer.append(input);composer.before(title);
    const suggestions=document.getElementById('le-chat-suggestions');
    area.append(title,composer);
    if(suggestions)area.append(suggestions);
    document.querySelector('#suggest-chat-checkbox input')?.setAttribute('role','switch');
    const plus=document.createElement('button');plus.id='le-chat-plus';plus.type='button';plus.textContent='+';plus.setAttribute('aria-label','打开问答工具');plus.setAttribute('aria-expanded','false');composer.append(plus);
    const menu=document.createElement('div');menu.id='le-chat-tool-menu';menu.hidden=true;
    const options=[['sources','参考资料','选择文件与检索范围'],['answer','检索方式','选择适合问题的检索方式'],['citation','来源展示','选择引用原文的呈现方式'],['mindmap','思维导图','把回答中的要点整理成图']];
    menu.innerHTML='<div class="le-menu-caption">问答工具</div>'+options.map(([key,label,desc])=>`<button type="button" data-chat-menu="${key}"><span>${label}<small>${desc}</small></span><span aria-hidden="true">›</span></button>`).join('');composer.append(menu);composer.append(settings);
    const flyout=document.createElement('section');flyout.id='le-chat-flyout';flyout.hidden=true;flyout.setAttribute('aria-label','问答工具设置');
    flyout.innerHTML='<div class="le-flyout-head"><button type="button" data-flyout-back>‹ 返回</button><strong></strong><button type="button" data-flyout-close aria-label="关闭工具菜单">×</button></div>';
    composer.append(flyout);
    const sources=document.getElementById('conv-settings-panel'),evidence=document.getElementById('chat-info-panel');
    [settings,sources].filter(Boolean).forEach(el=>flyout.append(el));
    if(evidence){
      const references=document.createElement('details');references.id='le-answer-references';references.hidden=true;references.setAttribute('aria-label','回答的引用资料');const summary=document.createElement('summary');summary.textContent='查看引用资料与思维导图';references.append(summary);bot.after(references);references.append(evidence);
      let frame;
      function updateReferences(){
        cancelAnimationFrame(frame);frame=requestAnimationFrame(()=>{
          const content=document.getElementById('html-info-panel');
          const hasAnswer=!!bot.querySelector('[data-testid="bot"], [data-testid="assistant"]');
          const busy=!!bot.querySelector('.wrap:not(.hide).translucent, .wrap.generating, .message.pending');
          const referenceText=content?.textContent.trim()||'';
          const hasReferences=!!content&&!/^No evidence found[.!]?$/i.test(referenceText)&&(referenceText.length>0||!!content.querySelector('a[href],img,svg,canvas'));
          references.hidden=!(hasAnswer&&hasReferences&&!busy);
        });
      }
      const refsObserver=new MutationObserver(updateReferences);
      refsObserver.observe(bot,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['class']});
      refsObserver.observe(evidence,{subtree:true,childList:true,characterData:true});
      updateReferences();
    }
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
      function updateHistoryEmpty(){emptyHistory.hidden=!!conversation?.querySelector('[role="option"]');}
      if(conversation)new MutationObserver(updateHistoryEmpty).observe(conversation,{subtree:true,childList:true});
      history.addEventListener('toggle',()=>{
        if(!history.open)return;
        const selector=conversation?.querySelector('input[role="listbox"]');
        if(selector&&selector.getAttribute('aria-expanded')!=='true')selector.focus({preventScroll:true});
        updateHistoryEmpty();
      });
      conversation?.addEventListener('click',event=>{
        if(event.target.closest('[role="option"]')){history.open=false;history.querySelector('summary').focus();}
      });

      document.addEventListener('click',e=>{if(!e.composedPath().includes(history))history.open=false;});
      document.addEventListener('keydown',e=>{if(e.key==='Escape'&&history.open){history.open=false;history.querySelector('summary').focus();}});
      const advanced=document.createElement('details');advanced.className='le-source-advanced';advanced.innerHTML='<summary>高级检索</summary><p>仅在需要图谱或关联检索时使用。</p>';
      sources.append(advanced);['index-1','index-2','report-accordion'].forEach(id=>{const el=document.getElementById(id);if(el)advanced.append(el);});
      const note=document.createElement('p');note.className='le-source-note';note.textContent='选择参考资料，回答会基于你的检索范围。';sources.prepend(note);
      function localize(){sources.querySelectorAll('input[placeholder="Browse conversation"]').forEach(el=>el.setAttribute('placeholder','选择历史对话'));const walk=document.createTreeWalker(sources,NodeFilter.SHOW_TEXT);const words={'Browse conversation':'选择历史对话','Search All':'全部资料','Search In File(s)':'指定文件','Drop File Here':'将文件拖到这里','Click to Upload':'点击上传'};while(walk.nextNode()){const key=walk.currentNode.textContent.trim();if(words[key])walk.currentNode.textContent=words[key];}}
      localize();new MutationObserver(localize).observe(sources,{subtree:true,childList:true,characterData:true});
    }
    function position(){if(flyout.hidden)return;const rect=menu.getBoundingClientRect();const width=Math.min(420,innerWidth-32);const fits=rect.right+width+20<=innerWidth;flyout.style.width=width+'px';flyout.style.left=(fits?rect.right+10:Math.max(16,Math.min(rect.left,innerWidth-width-16)))+'px';flyout.style.top=Math.max(16,Math.min(rect.top,innerHeight-280))+'px';flyout.style.maxHeight=(innerHeight-parseFloat(flyout.style.top)-16)+'px';}
    let hoverTimer;
    function close(){clearTimeout(hoverTimer);menu.hidden=true;flyout.hidden=true;settings.dataset.menu='';plus.setAttribute('aria-expanded','false');document.getElementById('chat-tab')?.classList.remove('le-chat-sources-open','le-chat-evidence-open');menu.querySelectorAll('button').forEach(el=>el.setAttribute('aria-expanded','false'));}
    close();
    plus.addEventListener('click',()=>{const open=menu.hidden;close();menu.hidden=!open;plus.setAttribute('aria-expanded',String(open));});
    function openSubmenu(button){clearTimeout(hoverTimer);if(!button||menu.hidden)return;const kind=button.dataset.chatMenu;
      const changed=flyout.hidden||flyout.dataset.panel!==kind;
      flyout.hidden=false;flyout.dataset.panel=kind;settings.dataset.menu=['sources','evidence'].includes(kind)?'':kind;
      flyout.querySelector('strong').textContent=options.find(item=>item[0]===kind)[1];
      menu.querySelectorAll('button').forEach(el=>el.setAttribute('aria-expanded',String(el===button)));
      const toggle=settings.querySelector(':scope>.label-wrap');if(toggle&&!toggle.classList.contains('open'))toggle.click();position();
      if(changed&&!matchMedia('(prefers-reduced-motion: reduce)').matches){flyout.getAnimations().forEach(animation=>animation.cancel());flyout.animate([{opacity:0,transform:'translateX(-5px)'},{opacity:1,transform:'translateX(0)'}],{duration:160,easing:'ease-out'});}
    }
    menu.addEventListener('click',e=>openSubmenu(e.target.closest('[data-chat-menu]')));
    menu.addEventListener('pointerover',e=>{if(e.pointerType!=='mouse')return;const button=e.target.closest('[data-chat-menu]');if(!button||button.contains(e.relatedTarget))return;clearTimeout(hoverTimer);hoverTimer=setTimeout(()=>openSubmenu(button),140);});
    menu.addEventListener('pointerout',e=>{const button=e.target.closest('[data-chat-menu]');if(button&&!button.contains(e.relatedTarget))clearTimeout(hoverTimer);});
    menu.addEventListener('focusin',e=>openSubmenu(e.target.closest('[data-chat-menu]')));
    menu.addEventListener('keydown',e=>{if(e.key==='ArrowRight'){openSubmenu(e.target.closest('[data-chat-menu]'));flyout.querySelector('[data-flyout-back]').focus();e.preventDefault();}});
    flyout.querySelector('[data-flyout-close]').addEventListener('click',()=>{close();plus.focus();});
    flyout.querySelector('[data-flyout-back]').addEventListener('click',()=>{flyout.hidden=true;settings.dataset.menu='';menu.querySelectorAll('button').forEach(el=>el.setAttribute('aria-expanded','false'));});
    window.addEventListener('resize',position);window.addEventListener('scroll',position,true);
    function sync(){area.classList.toggle('le-chat-empty',!!bot.querySelector('.placeholder-container'));}
    new MutationObserver(sync).observe(bot,{subtree:true,childList:true});sync();
    document.addEventListener('click',e=>{if(!e.composedPath().includes(composer))close();});
    document.addEventListener('keydown',e=>{if(e.key==='Escape'){close();}});
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
