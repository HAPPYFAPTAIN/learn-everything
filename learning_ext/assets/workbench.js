(() => {
  let signature='', targets=[];
  function update(){
    const row=document.querySelector('#le-workbench-row'),guide=document.querySelector('#le-guide-md');
    if(!row||!guide)return;
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
