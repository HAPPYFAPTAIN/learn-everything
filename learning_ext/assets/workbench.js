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
  let signature='', targets=[];
  function update(){
    const row=document.querySelector('#le-workbench-row'),guide=document.querySelector('#le-guide-md');
    if(!row||!guide)return;
    if(window.__leFoldAnswers) window.__leFoldAnswers(guide);
    if(window.__leMaybeOpenContentTools) window.__leMaybeOpenContentTools(guide);
    let nav=document.querySelector('#le-lesson-outline');
    if(!nav){nav=document.createElement('details');nav.id='le-lesson-outline';nav.open=innerWidth>1000;nav.innerHTML='<summary>本节目录</summary><nav aria-label="本节章节"></nav><p>选中文字，可随时查看解释。</p>';row.insertBefore(nav,document.querySelector('#le-center-col'));}
    const headings=[...guide.querySelectorAll('h2')];
    const next=headings.map(h=>h.textContent).join('|');
    targets=headings;
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
    if(h){h.setAttribute('tabindex','-1');h.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});h.focus({preventScroll:true});document.querySelectorAll('[data-lesson-section]').forEach(b=>b.setAttribute('aria-current',b===button?'location':'false'));}}
    requestAnimationFrame(jump);
  });
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

/* 选段改写：选中正文里的一段，浮出「讲浅一点 / 加个例子…」；
   鼠标贴到段落右边缘，还能直接改这一段，不用先选中。
   请求通过两个隐藏组件（输入框 + 按钮）交给后端，改完只动这一段，可撤销。 */
(() => {
  const BAR = 'le-sel-bar';
  const PENCIL = 'le-block-pencil';
  const PRESETS = [
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
    b.setAttribute('aria-label', '改写这一段');
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
    const input = document.createElement('input');
    input.type = 'text';
    input.placeholder = '想怎么改？回车确认';
    input.hidden = true;
    b.appendChild(input);

    b.addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-act]');
      if (!btn) return;
      if (btn.dataset.act === 'custom') {
        input.hidden = false;
        input.focus();
        return;
      }
      send(btn.dataset.act, '');
    });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.isComposing) {
        e.preventDefault();
        send('custom', input.value.trim());
      } else if (e.key === 'Escape') {
        input.value = '';
        input.hidden = true;
        hideBar();
      }
    });
    document.body.appendChild(b);
    return b;
  }

  function showAt(x, y, text) {
    const clean = (text || '').trim();
    if (clean.length < 3) return;
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
    const p = document.getElementById(PENCIL);
    if (p) p.hidden = true;
  }

  function fromSelection() {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed) return;
    const text = sel.toString().trim();
    if (!text) return;
    const g = guide();
    if (!g) return;
    const node = sel.anchorNode;
    if (!node || !g.contains(node.nodeType === 3 ? node.parentNode : node)) return;
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

  // 同步执行：名词解释浮窗在 mouseup 的 0ms 回调里要能看到我们是否已经接管
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
  document.addEventListener('wheel', hideBar, { passive: true });
  window.addEventListener('scroll', hideBar, { passive: true, capture: true });

  // 提示条上的「撤销 / 关闭」
  document.addEventListener('click', (e) => {
    const undo = e.target.closest('[data-rewrite-act]');
    if (undo) {
      send(undo.dataset.rewriteAct, '');
      return;
    }
    if (e.target.closest('.le-toast-x')) {
      const box = e.target.closest('#le-rewrite-note');
      if (box) box.innerHTML = '';
      busy = false;
    }
  });
})();
