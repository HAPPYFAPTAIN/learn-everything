(function foldAnswers(){
  // 老内容把答案写成引用块（> **答案：B**），一进页面就露出来了。
  // 这里把这种引用块折成「点击查看答案」，跟新内容用的 <details> 保持一致。
  const MARK = /^(答案|参考答案|参考|解析|答案解析|思路|答题思路|提示)\s*[：:]/;

  function run(guide){
    if (!guide) return;
    guide.querySelectorAll('blockquote').forEach(function (bq) {
      const text = (bq.textContent || '').trim();
      if (!MARK.test(text)) return;
      const detail = document.createElement('details');
      detail.className = 'le-fold';
      const summary = document.createElement('summary');
      summary.textContent = '点击查看答案';
      detail.appendChild(summary);
      const body = document.createElement('div');
      body.className = 'le-fold-body';
      while (bq.firstChild) body.appendChild(bq.firstChild);
      detail.appendChild(body);
      bq.replaceWith(detail);
    });
  }
  window.__leFoldAnswers = run;
})();

(function openContentToolsWhenMissing(){
  let lastKey = '';
  // 正文没生成成功时，把「课程内容工具」面板自动展开，
  // 否则「重新生成本节」按钮藏在折叠里，根本找不到。
  function maybeOpen(guide){
    const text = (guide && guide.innerText) || '';
    if (!text.includes('还没有生成成功')) return;
    const key = text.slice(0, 48);
    if (key === lastKey) return;
    lastKey = key;
    const regen = [...document.querySelectorAll('button')]
      .find(b => (b.textContent || '').trim() === '重新生成本节');
    if (!regen || regen.getBoundingClientRect().width > 0) return;   // 已经展开了
    const header = [...document.querySelectorAll('button.label-wrap')]
      .find(b => (b.textContent || '').includes('课程内容工具'));
    if (header) header.click();
  }
  window.__leMaybeOpenContentTools = maybeOpen;
})();

(() => {
  const SMALL_KEY='le.toc.mobileOpen';
  let signature='', targets=[], observedOpen=null, desktop=innerWidth>1000, currentFrame=0;
  function storedSmallOpen(){
    try{const value=localStorage.getItem(SMALL_KEY);return value===null?null:value==='1';}catch(e){return null;}
  }
  function setOpen(nav,open){observedOpen=open;nav.open=open;}
  function syncViewport(nav,force=false){
    const next=innerWidth>1000;
    if(!force&&next===desktop)return;
    desktop=next;
    setOpen(nav,desktop||storedSmallOpen()===true);
  }
  function bindOutline(nav){
    observedOpen=nav.open;
    nav.addEventListener('toggle',()=>{
      const open=nav.open;
      if(open===observedOpen)return;
      observedOpen=open;
      if(innerWidth<=1000){try{localStorage.setItem(SMALL_KEY,open?'1':'0');}catch(e){}}
    });
  }
  function markCurrent(button){
    document.querySelectorAll('[data-lesson-section]').forEach(b=>b.setAttribute('aria-current',b===button?'location':'false'));
  }
  function updateCurrent(){
    currentFrame=0;
    const guide=document.querySelector('#le-guide-md');
    if(!guide||!guide.getClientRects().length)return;
    const buttons=[...document.querySelectorAll('#le-lesson-outline [data-lesson-section]')];
    if(!targets.length||buttons.length!==targets.length)return;
    const offset=innerWidth<=800?140:180;
    let index=0;
    targets.forEach((h,i)=>{if(h.getBoundingClientRect().top<=offset)index=i;});
    markCurrent(buttons[index]);
  }
  function scheduleCurrent(){
    if(!currentFrame)currentFrame=requestAnimationFrame(updateCurrent);
  }
  function update(){
    const row=document.querySelector('#le-workbench-row'),guide=document.querySelector('#le-guide-md');
    if(!row||!guide)return;
    if(window.__leFoldAnswers) window.__leFoldAnswers(guide);
    if(window.__leMaybeOpenContentTools) window.__leMaybeOpenContentTools(guide);
    let nav=document.querySelector('#le-lesson-outline');
    if(!nav){
      nav=document.createElement('details');nav.id='le-lesson-outline';nav.open=innerWidth>1000;
      nav.innerHTML='<summary>本节目录</summary><nav aria-label="本节章节"></nav>';
      row.insertBefore(nav,document.querySelector('#le-center-col'));
      bindOutline(nav);
      syncViewport(nav,true);
    }
    const headings=[...guide.querySelectorAll('h2')];
    const next=headings.map(h=>h.textContent).join('|');
    targets=headings;
    scheduleCurrent();
    if(next===signature&&nav.querySelector('nav').children.length)return;
    signature=next;const list=nav.querySelector('nav');list.replaceChildren();
    headings.forEach((h,i)=>{const b=document.createElement('button');b.type='button';b.textContent=h.textContent;b.dataset.lessonSection=i;list.append(b);});
    if(!headings.length){const p=document.createElement('p');p.textContent='选好课程后，章节会显示在这里。';list.append(p);}
  }
  document.addEventListener('click',e=>{
    const button=e.target.closest('[data-lesson-section]');if(!button)return;
    document.querySelector('#le-lookup-zone-button')?.click();
    const h=targets[Number(button.dataset.lessonSection)];
    let tries=0;
    function jump(){if(h&&!h.getClientRects().length&&tries++<30){requestAnimationFrame(jump);return;}
    if(h){h.setAttribute('tabindex','-1');h.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});h.focus({preventScroll:true});markCurrent(button);}}
    requestAnimationFrame(jump);
  });
  window.addEventListener('scroll',scheduleCurrent,{passive:true});
  window.addEventListener('resize',()=>{const nav=document.querySelector('#le-lesson-outline');if(nav)syncViewport(nav);scheduleCurrent();},{passive:true});
  const ready=setInterval(()=>{const guide=document.querySelector('#le-guide-md');if(!guide)return;clearInterval(ready);update();new MutationObserver(update).observe(guide,{childList:true,subtree:true,characterData:true});},300);
})();

/* 内容标签栏的收起 / 展开（右上角箭头）。
   收起状态记在 localStorage，与左侧目录的收起保持同一套习惯。 */
(() => {
  const KEY='le.tabsCollapsed';
  const CHEVRON='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 15l6-6 6 6"/></svg>';
  const col=()=>document.getElementById('le-center-col');
  const nav=()=>document.querySelector('#le-content-tabs > .tab-nav');
  function stored(){try{return localStorage.getItem(KEY)==='1';}catch(e){return false;}}
  function paint(){
    const c=col();if(!c)return;
    const collapsed=stored();
    c.classList.toggle('le-tabs-collapsed',collapsed);
    const b=document.getElementById('le-tabs-toggle');
    if(b){
      b.setAttribute('aria-expanded',String(!collapsed));
      b.title=collapsed?'展开内容标签栏':'收起内容标签栏';
      b.setAttribute('aria-label',b.title);
    }
  }
  function mount(){
    const n=nav();if(!n)return false;
    if(!document.getElementById('le-tabs-toggle')){
      const b=document.createElement('button');
      b.id='le-tabs-toggle';b.type='button';b.innerHTML=CHEVRON;
      b.addEventListener('click',()=>{
        try{localStorage.setItem(KEY,stored()?'0':'1');}catch(e){}
        paint();
      });
      n.appendChild(b);
    }
    paint();
    return true;
  }
  paint();
  if(!mount()){let t=0;const timer=setInterval(()=>{if(mount()||++t>60)clearInterval(timer);},200);}
  /* 脚本在 <head> 里执行，此刻还没有 body，所以挂在 documentElement 上 */
  new MutationObserver(()=>{
    if(document.getElementById('le-tabs-toggle'))paint();else mount();
  }).observe(document.documentElement,{childList:true,subtree:true});
})();

(() => {
  const ID='le-master-shortcut';
  let frame=0, observedCenter=null, centerObserver=null;
  function schedule(){if(!frame)frame=requestAnimationFrame(update);}
  function reading(){
    const tab=document.getElementById('le-lookup-zone-button');
    return !!tab&&(tab.classList.contains('selected')||tab.getAttribute('aria-selected')==='true');
  }
  function update(){
    frame=0;
    const b=document.getElementById(ID),master=document.getElementById('le-master-btn'),guide=document.getElementById('le-guide-md');
    if(!b||!master||!guide)return;
    const r=master.getBoundingClientRect();
    const masterVisible=r.width>0&&r.height>0&&r.bottom>0&&r.top<innerHeight;
    const active=reading()&&guide.getClientRects().length>0&&!!(guide.innerText||'').trim();
    b.hidden=!active||masterVisible;
    b.disabled=master.disabled;
  }
  function mount(){
    const n=document.querySelector('#le-content-tabs>.tab-nav'),master=document.getElementById('le-master-btn'),c=document.getElementById('le-center-col');
    if(!n||!master||!c)return false;
    let b=document.getElementById(ID);
    if(!b){
      b=document.createElement('button');
      b.id=ID;b.type='button';b.textContent='完成本节';
      b.title='已掌握本节（仍需通过过关检查）';b.setAttribute('aria-label',b.title);
      b.addEventListener('click',()=>{const current=document.getElementById('le-master-btn');if(current)current.click();});
      n.insertBefore(b,document.getElementById('le-tabs-toggle'));
    }
    if(observedCenter!==c){
      if(centerObserver)centerObserver.disconnect();
      observedCenter=c;
      centerObserver=new MutationObserver(schedule);
      centerObserver.observe(c,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['class','style']});
    }
    update();
    return true;
  }
  document.addEventListener('click',e=>{if(e.target.closest('#le-content-tabs>.tab-nav'))schedule();});
  window.addEventListener('scroll',schedule,{passive:true});
  window.addEventListener('resize',schedule,{passive:true});
  mount();
  new MutationObserver(()=>{if(!document.getElementById(ID))mount();else schedule();}).observe(document.documentElement,{childList:true,subtree:true});
})();

/* 选段改写：选中正文里的一段，浮出「讲浅一点 / 加个例子…」；
   鼠标贴到段落右边缘，还能直接改这一段，不用先选中。
   请求通过两个隐藏组件（输入框 + 按钮）交给后端，改完只动这一段，可撤销。 */
(() => {
  const BAR = 'le-sel-bar';
  const PENCIL = 'le-block-pencil';
  const PRESETS = [
    ['explain', '解释名词'],
    ['annotate', '记一笔'],
    ['simplify', '讲浅一点'],
    ['example', '加个例子'],
    ['rewrite', '改顺一点'],
    ['tighten', '精简']
  ];
  const PEN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>';

  let target = '';       // 这次要改的那段文字
  let busy = false;      // 上一次还在跑，避免连点
  let lastEvt = null;
  let raf = 0;
  let mode = 'custom';   // 输入框当前是「改写指令」还是「批注内容」
  let draftTarget = '';  // 草稿属于哪一段（浮条被收起来再点回来时用来还原）
  let draftMode = '';
  let keepScroll = null; // 改写会把正文整块重渲染，先记下位置，回来再放回去

  const guide = () => document.getElementById('le-guide-md');
  const blockOf = (el) =>
    (el.closest && (el.closest('#le-guide-md .prose > *') || el.closest('#le-guide-md > *'))) || null;

  function bar() {
    let b = document.getElementById(BAR);
    if (b) return b;
    b = document.createElement('div');
    b.id = BAR;
    b.setAttribute('role', 'toolbar');
    b.setAttribute('aria-label', '选中文本工具');
    b.hidden = true;
    PRESETS.forEach(([act, label]) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.dataset.act = act;
      btn.textContent = label;
      b.appendChild(btn);
    });
    const self = document.createElement('button');
    self.type = 'button';
    self.dataset.act = 'custom';
    self.className = 'le-self';
    self.textContent = '✎';
    self.title = '自己说怎么改';
    b.appendChild(self);
    /* 用 textarea 而不是单行 input：写批注常常要好几句，单行输入框文字一长
       就会内部横向滚动，那个 scroll 事件会被下面 window 上的「滚动收起」监听
       捕获，浮条连同没写完的内容一起消失。多行 + 自动撑高也没这个问题。 */
    const input = document.createElement('textarea');
    input.rows = 2;
    input.className = 'le-bar-input';
    input.dataset.lePolishKind = 'instruction';
    input.placeholder = '想怎么改？回车确认（Shift+回车换行）';
    input.hidden = true;
    b.appendChild(input);

    function fitInput() {
      input.style.height = 'auto';
      input.style.height = Math.min(132, Math.max(38, input.scrollHeight)) + 'px';
      // 多行框展开后浮条可能顶出屏幕下沿，顺手拉回来
      const b2 = document.getElementById(BAR);
      if (b2 && !b2.hidden) {
        const r = b2.getBoundingClientRect();
        if (r.bottom > innerHeight - 8) {
          b2.style.top = Math.max(8, innerHeight - r.height - 12) + 'px';
        }
      }
    }
    input.addEventListener('input', fitInput);

    b.addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-act]');
      if (!btn) return;
      const act = btn.dataset.act;
      if (act === 'explain') {
        input.hidden = true;
        if (window.__leExplainSelection) window.__leExplainSelection(target, b);
        return;
      }
      if (window.__leCloseExplanation) window.__leCloseExplanation();
      if (act === 'annotate' || act === 'custom') {
        // 这两个都是「先打开输入框」，区别只在提示语和提交去哪
        // 同一段上重复打开时保留上次没写完的草稿，别因为手滑点没了就白写
        const keepDraft = draftTarget === target && draftMode === act && input.value.trim();
        mode = act;
        input.dataset.lePolishKind = act === 'annotate' ? 'note' : 'instruction';
        if (!keepDraft) input.value = '';
        input.placeholder = act === 'annotate'
          ? '写一句批注，回车保存（Shift+回车换行）'
          : '想怎么改？回车确认（Shift+回车换行）';
        input.hidden = false;
        fitInput();
        draftTarget = target; draftMode = act;
        // 点按钮时焦点会先落到按钮上，等一拍再抢回来，不然直接打字没反应
        input.focus();
        requestAnimationFrame(() => input.focus());
        setTimeout(() => { if (document.activeElement !== input) input.focus(); }, 60);
        return;
      }
      send(act, '');
    });
    input.addEventListener('keydown', (e) => {
      // 回车保存，Shift+回车换行；输入法组字中的回车不算
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        const text = input.value.trim();
        if (!text) return;
        draftTarget = ''; draftMode = '';
        if (mode === 'annotate') sendAnnotation(text);
        else send('custom', text);
      } else if (e.key === 'Escape') {
        input.value = '';
        input.hidden = true;
        draftTarget = ''; draftMode = '';
        hideBar();
      }
    });
    document.body.appendChild(b);
    return b;
  }

  function showAt(x, y, text) {
    const clean = (text || '').trim();
    if (!clean) return;
    if (target !== clean.slice(0, 800) && window.__leCloseExplanation) window.__leCloseExplanation();
    target = clean.slice(0, 800);
    const b = bar();
    b.hidden = false;
    const r = b.getBoundingClientRect();
    let left = x - r.width / 2;
    let top = y - r.height - 10;
    left = Math.max(12, Math.min(left, innerWidth - r.width - 12));
    if (top < 8) top = y + 18;
    b.style.left = left + 'px';
    b.style.top = top + 'px';
  }

  function hideBar() {
    const b = document.getElementById(BAR);
    if (b) b.hidden = true;
    if (window.__leCloseExplanation) window.__leCloseExplanation();
    const p = document.getElementById(PENCIL);
    if (p) p.hidden = true;
  }

  /* 正在写东西的时候不许被“顺手”收掉。
     滚动、滚轮、点别处本来都会收起浮条，但人在输入框里打字时这些动作
     可能来自浏览器的自动滚动（页面重渲染把光标滚进视野之类），一收就把
     没写完的字丢了。这里只挡住输入中的那一种，其他照旧。 */
  function typingInBar() {
    const b = document.getElementById(BAR);
    if (!b || b.hidden) return false;
    if (b.querySelector('#le-lookup-popup')) return true;
    if (document.querySelector('.le-polish-popover[open]')) return true;
    const t = b.querySelector('.le-bar-input');
    // 只要光标在框里就算在用，不要求已经写了字——空框被收起来后
    // 焦点仍留在隐藏的输入框上，接着打字会打进一个看不见的地方
    return !!(t && !t.hidden && document.activeElement === t);
  }

  function hideBarUnlessTyping() {
    if (typingInBar()) return;
    hideBar();
  }

  function fromSelection(event) {
    if (event && event.target && event.target.closest('#le-sel-bar')) return;
    // 正在浮条里写字（尤其 Shift+回车换行）时别去接管选区，
    // 否则会把这次要批注的那段 target 换成别的段落
    if (typingInBar()) return;
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed) return;
    const text = sel.toString().trim();
    if (!text) return;
    const node = sel.anchorNode;
    const anchor = node && (node.nodeType === 3 ? node.parentElement : node);
    const g = anchor && anchor.closest('#le-guide-md, #le-center-content, .le-lookup-zone');
    if (!g || !g.contains(sel.focusNode)) return;
    const range = sel.getRangeAt(0);
    const r = range.getBoundingClientRect();
    if (!r || (!r.width && !r.height)) return;
    showAt(r.left + r.width / 2, r.top, text);
  }

  function pencil() {
    let p = document.getElementById(PENCIL);
    if (p) return p;
    p = document.createElement('button');
    p.id = PENCIL;
    p.type = 'button';
    p.innerHTML = PEN;
    p.title = '改这一段';
    p.setAttribute('aria-label', '改这一段');
    p.hidden = true;
    p.addEventListener('click', () => {
      const el = p._block;
      if (!el) return;
      const r = el.getBoundingClientRect();
      showAt(r.left + r.width / 2, r.top, el.innerText || '');
    });
    document.body.appendChild(p);
    return p;
  }

  function onMove() {
    raf = 0;
    const e = lastEvt;
    const g = guide();
    if (!e || !g || !e.target || !g.contains(e.target)) {
      const cur = document.getElementById(PENCIL);
      if (cur) cur.hidden = true;
      return;
    }
    const p = pencil();
    const el = blockOf(e.target);
    if (!el) { p.hidden = true; return; }
    const r = el.getBoundingClientRect();
    if (r.height < 26 || (el.innerText || '').trim().length < 12) { p.hidden = true; return; }
    // 只在贴近右边缘时才冒出来，免得干扰阅读和划词
    if (e.clientX < r.right - 38) { p.hidden = true; return; }
    const barEl = document.getElementById(BAR);
    if (barEl && !barEl.hidden) { p.hidden = true; return; }
    p._block = el;
    p.hidden = false;
    p.style.left = Math.round(r.right - 32) + 'px';
    p.style.top = Math.round(Math.max(8, r.top + 4)) + 'px';
  }

  function setValue(el, value) {
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement : HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(proto.prototype, 'value').set;
    setter.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  }

  function send(action, instruction) {
    if (busy) {
      // 上一段还在改，别静默吞掉点击
      const b = document.getElementById(BAR);
      if (b) {
        let hint = b.querySelector('.le-sel-hint');
        if (!hint) {
          hint = document.createElement('span');
          hint.className = 'le-sel-hint';
          b.appendChild(hint);
        }
        hint.textContent = '正在改上一段，稍等十几秒';
        clearTimeout(hint._t);
        hint._t = setTimeout(() => hint.remove(), 2600);
      }
      return;
    }
    const ta = document.querySelector('#le-rewrite-payload textarea');
    const go = document.getElementById('le-rewrite-trigger');
    if (!ta || !go) {
      console.warn('[le] 改写通道还没就绪');
      return;
    }
    setValue(ta, JSON.stringify({ snippet: action === 'undo' ? '' : target, action, instruction: instruction || '' }));
    busy = true;
    keepScroll = window.scrollY;
    hideBar();
    if (window.getSelection) window.getSelection().removeAllRanges();
    // 留一帧给 Svelte 把值同步到状态，再触发按钮
    setTimeout(() => go.click(), 60);
  }

  // 记一条批注：走另一条隐藏通道，不动正文
  function sendAnnotation(body) {
    if (!body) return;   // 空内容不提交，浮条留着让人继续写
    const ta = document.querySelector('#le-anno-payload textarea');
    const go = document.getElementById('le-anno-trigger');
    if (!ta || !go) {
      console.warn('[le] 批注通道还没就绪');
      return;
    }
    setValue(ta, JSON.stringify({ action: 'add', quote: target, body }));
    // 记笔记时把「是否解释名词」那个浮窗收掉，两个浮层叠在一起太乱
    const lookup = document.getElementById('le-lookup-popup');
    if (lookup) lookup.style.display = 'none';
    hideBar();
    if (window.getSelection) window.getSelection().removeAllRanges();
    setTimeout(() => go.click(), 60);
  }

  function deleteAnnotation(id) {
    const ta = document.querySelector('#le-anno-payload textarea');
    const go = document.getElementById('le-anno-trigger');
    if (!ta || !go || !id) return;
    setValue(ta, JSON.stringify({ action: 'del', id }));
    setTimeout(() => go.click(), 60);
  }

  // 后端把结果写成提示条；非「正在改」就解锁
  function watchNote() {
    const n = document.getElementById('le-rewrite-note');
    if (!n) return false;
    if (n.dataset.leWatched) return true;
    n.dataset.leWatched = '1';
    new MutationObserver(() => {
      const toast = n.querySelector('.le-toast');
      if (toast && !toast.classList.contains('le-toast-busy')) {
        busy = false;
        // 用属性隐藏，不删 DOM：清空 Gradio 组件的内容会让它的引用失效
        delete n.dataset.leHidden;
        clearTimeout(n._leHide);
        n._leHide = setTimeout(() => { n.dataset.leHidden = '1'; }, 5000);
        if (keepScroll !== null) {
          const y = keepScroll;
          keepScroll = null;
          // 正文刚被替换，等一帧再回位，别让读者被甩回顶部
          requestAnimationFrame(() => requestAnimationFrame(() => window.scrollTo(0, y)));
        }
      }
    }).observe(n, { childList: true, subtree: true });
    return true;
  }
  const poll = setInterval(() => { if (watchNote()) clearInterval(poll); }, 500);

  document.addEventListener('mouseup', fromSelection);
  document.addEventListener('keyup', (e) => {
    if (e.shiftKey || /^Arrow/.test(e.key)) setTimeout(fromSelection, 10);
  });
  document.addEventListener('mousedown', (e) => {
    const b = document.getElementById(BAR);
    if (b && !b.hidden && !b.contains(e.target)) hideBar();
  }, true);
  document.addEventListener('mousemove', (e) => {
    lastEvt = e;
    if (!raf) raf = requestAnimationFrame(onMove);
  }, { passive: true });
  document.addEventListener('wheel', (e) => {
    if (!e.target.closest('#le-sel-bar')) hideBarUnlessTyping();
  }, { passive: true });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') hideBar(); });
  // 输入框自己滚动（文字多到撑出高度）也会冒到 window 的捕获阶段，得挡掉
  window.addEventListener('scroll', (e) => {
    const b = document.getElementById(BAR);
    if (b && e.target && b.contains(e.target)) return;
    hideBarUnlessTyping();
  }, { passive: true, capture: true });

  // 提示条上的「撤销 / 关闭」，以及笔记页里的「删除批注」
  document.addEventListener('click', (e) => {
    const del = e.target.closest('[data-anno-del]');
    if (del) {
      e.preventDefault();
      deleteAnnotation(del.dataset.annoDel);
      return;
    }
    const undo = e.target.closest('[data-rewrite-act]');
    if (undo) {
      send(undo.dataset.rewriteAct, '');
      return;
    }
    if (e.target.closest('.le-toast-x')) {
      const box = e.target.closest('#le-rewrite-note');
      if (box) box.dataset.leHidden = '1';
      busy = false;
    }
  });
})();

/* 正文里给被批注过的句子加标记。
   批注数据由笔记页那块 HTML 通过 data-json 带过来，这里只负责在正文里
   找到同样的文字并画上下划线 + 序号，不依赖后端做锚点。 */
(function markAnnotations(){
  const HOLDER = '#le-annotation-list .le-anno-data';

  function items(){
    const el = document.querySelector(HOLDER);
    if (!el) return [];
    try { return JSON.parse(el.dataset.json || '[]'); } catch (e) { return []; }
  }

  /* 只给段落加属性，不去包文本节点。
     之前用 Range + surroundContents 把句子包进 <mark>，会让 Gradio 缓存的
     文本节点引用失效，之后任何一次组件更新都会抛
     「insertBefore ... is not a child of this node」，整个事件更新都中断。 */
  function paint(guide){
    // 清掉上一次的标记（可能是结构不同的元素，所以按属性全量清）
    guide.querySelectorAll('[data-anno-pin]').forEach((el) => {
      delete el.dataset.annoPin;
      delete el.dataset.annoIds;
    });
    // 只认可读的块级元素。以前用 '.prose > *' 会命中包住整篇的容器，
    // 结果角标挂在一个上万像素高的 div 上，位置整个跑掉。
    const hosts = [...guide.querySelectorAll('p, li, h2, h3, h4, blockquote, td')]
      .filter((el) => el.closest('.prose'));
    const list = items();
    if (!list.length) return;
    list.forEach((it) => {
      if (it.stale) return;                     // 原文已被改写，正文里不再标记
      const q = (it.quote || '').replace(/\s/g, '');
      if (q.length < 4) return;
      for (const el of hosts) {
        if ((el.innerText || '').replace(/\s/g, '').indexOf(q) < 0) continue;
        const ids = (el.dataset.annoIds || '').split(',').filter(Boolean);
        if (!ids.includes(String(it.id))) ids.push(String(it.id));
        el.dataset.annoIds = ids.join(',');
        el.dataset.annoPin = '1';
        break;
      }
    });
  }

  /* 数字标：不塞进正文（动 DOM 结构会让 Gradio 的节点引用失效），
     而是单独一层浮在正文右侧，位置按段落的位置算。
     数字 = 这一段有几条笔记；只有点它才展开，点段落任意处不再弹窗。 */
  function pinsLayer(){
    let l = document.getElementById('le-anno-pins');
    if (l) return l;
    l = document.createElement('div');
    l.id = 'le-anno-pins';
    document.body.appendChild(l);
    return l;
  }

  function syncPins(){
    const guide = document.getElementById('le-guide-md');
    const layer = pinsLayer();
    if (!guide) return;
    const hosts = [...guide.querySelectorAll('[data-anno-pin]')];
    // 多出来的按钮回收，少了的补上（复用，避免每次重建导致闪）
    while (layer.children.length > hosts.length) layer.lastChild.remove();
    hosts.forEach((host, i) => {
      let btn = layer.children[i];
      if (!btn) {
        btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'le-anno-pin';
        layer.appendChild(btn);
      }
      const ids = (host.dataset.annoIds || '').split(',').filter(Boolean);
      btn.textContent = String(ids.length);
      btn.dataset.ids = ids.join(',');
      btn.title = ids.length > 1 ? `这一段有 ${ids.length} 条笔记，点开看` : '这一段有 1 条笔记，点开看';
      btn._host = host;
      const r = host.getBoundingClientRect();
      // 段落所在的标签页没打开时 rect 全是 0，别把按钮怼到屏幕左上角
      if (!r.width || !r.height) {
        btn.hidden = true;
        return;
      }
      btn.hidden = false;
      let left = r.right + 6;
      if (left + 24 > document.documentElement.clientWidth) left = r.right - 26;
      btn.style.left = Math.round(left) + 'px';
      btn.style.top = Math.round(r.top + 2) + 'px';
    });
  }

  function refresh(){
    const guide = document.getElementById('le-guide-md');
    const holder = document.querySelector('#le-annotation-list');
    if (!guide || !holder) return;
    const list = items();
    // 改属性也会触发 observer，用签名挡住，否则会自己刷自己
    const key = list.map((x) => x.id).join(',') + '|' + (guide.innerText || '').slice(0, 60);
    if (key === lastKey) return;
    lastKey = key;
    paint(guide);
    syncPins();
  }

  function esc(t){
    return String(t || '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }

  function setNativeValue(el, value){
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement : HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(proto.prototype, 'value').set;
    setter.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  }

  function sendAnno(payload){
    const ta = document.querySelector('#le-anno-payload textarea');
    const go = document.getElementById('le-anno-trigger');
    if (!ta || !go) return false;
    setNativeValue(ta, JSON.stringify(payload));
    setTimeout(() => go.click(), 60);
    return true;
  }

  function card(){
    let c = document.getElementById('le-anno-card');
    if (c) return c;
    c = document.createElement('div');
    c.id = 'le-anno-card';
    c.hidden = true;
    document.body.appendChild(c);
    c.addEventListener('click', (e) => {
      if (e.target.closest('[data-card-close]')) { c.hidden = true; return; }
      const del = e.target.closest('[data-card-del]');
      if (del) {
        sendAnno({ action: 'del', id: del.dataset.cardDel });
        c.hidden = true;
        return;
      }
      const edit = e.target.closest('[data-card-edit]');
      if (edit) { renderEdit(c, edit.dataset.cardEdit); return; }
      const save = e.target.closest('[data-card-save]');
      if (save) {
        const ta = c.querySelector('textarea');
        const body = (ta && ta.value || '').trim();
        if (!body) return;
        sendAnno({ action: 'update', id: save.dataset.cardSave, body });
        c.hidden = true;
        return;
      }
      if (e.target.closest('[data-card-cancel]')) { c.hidden = true; }
    });
    return c;
  }

  function renderEdit(c, id){
    const item = c.querySelector('[data-item="' + id + '"]');
    if (!item) return;
    const body = item.querySelector('.le-card-body');
    const ta = document.createElement('textarea');
    ta.rows = 3;
    ta.dataset.lePolishKind = 'note';
    ta.value = body ? body.textContent : '';
    if (body) body.replaceWith(ta);
    const actions = item.querySelector('.le-card-actions');
    if (actions) {
      actions.innerHTML = '<button type="button" data-card-save="' + id + '">保存</button>'
        + '<button type="button" data-card-cancel="1">取消</button>';
    }
    ta.focus();
    ta.setSelectionRange(ta.value.length, ta.value.length);
    ta.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        const v = ta.value.trim();
        if (v) sendAnno({ action: 'update', id, body: v });
        c.hidden = true;
      } else if (e.key === 'Escape') {
        openCard(c._host);
      }
    });
  }

  function openCard(host, cx, cy){
    if (!host) return;
    const ids = (host.dataset.annoIds || '').split(',').filter(Boolean);
    const list = items().filter((x) => ids.includes(String(x.id)));
    if (!list.length) return;
    const c = card();
    c._host = host;
    c.innerHTML = list.map((x) => (
      '<div class="le-card-item" data-item="' + x.id + '">'
      + '<div class="le-card-quote">' + esc(x.quote) + '</div>'
      + '<div class="le-card-body">' + esc(x.body) + '</div>'
      + '<div class="le-card-actions">'
      + '<button type="button" data-card-edit="' + x.id + '">改</button>'
      + '<button type="button" data-card-del="' + x.id + '">删</button>'
      + '</div></div>'
    )).join('') + '<button type="button" class="le-card-x" data-card-close="1" aria-label="关闭">×</button>';
    c.hidden = false;
    const r = host.getBoundingClientRect();
    const w = Math.min(340, innerWidth - 32);
    c.style.width = w + 'px';
    // 跟着点的地方走，不跟着整段底部走（长段落会把卡片顶到屏幕外）
    const ax = typeof cx === 'number' ? cx : r.left + 40;
    const ay = typeof cy === 'number' ? cy : r.top + 20;
    const h = Math.min(c.offsetHeight || 200, 260);
    c.style.left = Math.max(12, Math.min(ax - 20, innerWidth - w - 12)) + 'px';
    c.style.top = Math.max(12, Math.min(ay + 14, innerHeight - h - 20)) + 'px';
  }

  document.addEventListener('click', (e) => {
    const c = document.getElementById('le-anno-card');
    if (!c || c.hidden) return;
    if (c.contains(e.target)) return;
    // 点数字标交给下面那个监听处理（要能开/关切换），别在这里先关掉
    if (e.target.closest && e.target.closest('#le-anno-pins .le-anno-pin')) return;
    c.hidden = true;
  }, true);

  // 只有点右侧的数字标才展开这一段的所有笔记；点段落本身不弹窗
  document.addEventListener('click', (e) => {
    const btn = e.target.closest && e.target.closest('#le-anno-pins .le-anno-pin');
    if (!btn || !btn._host) return;
    const c = document.getElementById('le-anno-card');
    if (c && !c.hidden && c._host === btn._host) {   // 再点一次收起
      c.hidden = true;
      return;
    }
    const r = btn.getBoundingClientRect();
    openCard(btn._host, r.left + 8, r.bottom);
  });

  let lastKey = '';
  window.__leMarkAnnotations = refresh;

  // 数字标是 fixed 定位的，正文滚动/窗口变化后要重新对齐
  let pinRaf = 0;
  const schedulePins = () => {
    if (pinRaf) return;
    pinRaf = requestAnimationFrame(() => { pinRaf = 0; syncPins(); });
  };
  window.addEventListener('scroll', schedulePins, { passive: true, capture: true });
  window.addEventListener('resize', schedulePins, { passive: true });

  let tries = 0;
  const timer = setInterval(() => {
    if (!document.querySelector('#le-annotation-list') || !document.getElementById('le-guide-md')) {
      if (++tries > 100) clearInterval(timer);
      return;
    }
    clearInterval(timer);
    refresh();
    const holder = document.querySelector('#le-annotation-list');
    if (holder) new MutationObserver(refresh).observe(holder, { childList: true, subtree: true });
    const guide = document.getElementById('le-guide-md');
    if (guide) {
      new MutationObserver(refresh).observe(guide, { childList: true, subtree: true });
      // 图片/字体加载完高度会变，段落位置跟着变
      if (window.ResizeObserver) new ResizeObserver(schedulePins).observe(guide);
    }
  }, 600);
})();

/* 学习时长心跳：在工作台读正文时，每 30 秒把「这 30 秒」记一次。
   之前 record_study_time() 从来没被调用过，看板的「近 7 天学习（分钟）」永远是 0。
   只在页面可见 + 正文有内容时发，切到别的标签页不算学习。 */
(function studyHeartbeat(){
  const TICK = 30;              // 秒
  let last = Date.now();

  function flush() {
    const now = Date.now();
    const elapsed = Math.round((now - last) / 1000);
    last = now;
    if (elapsed <= 5) return;                        // 刚切回来，忽略
    if (document.visibilityState !== 'visible') return;
    const guide = document.getElementById('le-guide-md');
    if (!guide || !guide.offsetParent || !(guide.innerText || '').trim()) return;
    const ta = document.querySelector('#le-time-payload textarea');
    const go = document.getElementById('le-time-trigger');
    if (!ta || !go) return;
    const proto = HTMLTextAreaElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(ta, String(Math.min(elapsed, 120)));
    ta.dispatchEvent(new Event('input', { bubbles: true }));
    setTimeout(() => go.click(), 40);
  }

  setInterval(flush, TICK * 1000);
  document.addEventListener('visibilitychange', () => { last = Date.now(); });
})();

/* 学习节奏条：去复习 / 去查漏 直接切标签页；「我先学，回头补」走隐藏桥 */
(function rhythmBar(){
  document.addEventListener('click', (e) => {
    const go = e.target.closest && e.target.closest('#le-rhythm-bar [data-goto]');
    if (go) {
      const btn = document.getElementById(go.dataset.goto + '-button');
      if (btn) btn.click();
      return;
    }
    const sn = e.target.closest && e.target.closest('#le-rhythm-bar [data-snooze]');
    if (!sn) return;
    const ta = document.querySelector('#le-snooze-payload textarea');
    const trg = document.getElementById('le-snooze-trigger');
    if (!ta || !trg) return;
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
    setter.call(ta, String(sn.dataset.snooze || ''));
    ta.dispatchEvent(new Event('input', { bubbles: true }));
    setTimeout(() => trg.click(), 30);
  });
})();

/* 跳到下一节之后把页面拉回顶部。
   Gradio 事件的 js 在请求前跑，滚了会被新内容顶回原位，
   所以由后端在内容替换时更新这个隐藏元素，前端一看到变化就滚。 */
(function scrollKick(){
  const bind = () => {
    const el = document.getElementById('le-scroll-kick');
    if (!el) return false;
    const toTop = () => {
      window.scrollTo({ top: 0, behavior: 'smooth' });
      document.querySelectorAll('.gradio-container, main, [data-testid="block-container"]').forEach((n) => {
        if (n && n.scrollTop) n.scrollTop = 0;
      });
    };
    new MutationObserver(toTop).observe(el, { childList: true, subtree: true, characterData: true });
    return true;
  };
  if (!bind()) {
    const timer = setInterval(() => { if (bind()) clearInterval(timer); }, 700);
    setTimeout(() => clearInterval(timer), 20000);
  }
})();

(() => {
  function updateEnvironment() {
    const root=document.getElementById('le-env-setup');
    if(!root)return;
    const busy=root.querySelector('.le-env-state')?.getAttribute('aria-busy')==='true';
    const log=root.querySelector('#le-env-log');
    if(log)log.classList.toggle('le-env-no-log',!log.querySelector('.cm-content')?.textContent.trim());
    root.querySelectorAll('#le-env-generate,#le-env-confirm,#le-env-execute').forEach(button=>{
      if(busy && !button.dataset.envLocked){button.dataset.envLocked=String(button.disabled);button.disabled=true;}
      else if(!busy && button.dataset.envLocked){button.disabled=button.dataset.envLocked==='true';delete button.dataset.envLocked;}
    });
  }
  new MutationObserver(updateEnvironment).observe(document.documentElement,{childList:true,subtree:true});
  updateEnvironment();
})();
