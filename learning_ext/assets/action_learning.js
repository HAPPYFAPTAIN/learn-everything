(() => {
  let last = '', frame;
  function update() {
    const card = document.querySelector('#learning-workbench-tab [data-le-focus]');
    const key = card ? card.dataset.leFocus + ':' + (card.dataset.step || '') + ':' + card.querySelector('h2')?.textContent : '';
    if (key && key !== last) {
      const panel = document.getElementById('le-action-learning');
      panel?.scrollIntoView({block:'start', behavior:'instant'});
      const title = card.querySelector('h2');
      title?.setAttribute('tabindex','-1');
      title?.focus({preventScroll:true});
    }
    if (last && !key) {
      const entry = document.getElementById('le-step-entry');
      if (entry?.getClientRects().length) {
        entry.scrollIntoView({block:'center', behavior:'instant'});
        entry.focus({preventScroll:true});
      }
    }
    last = key;
  }
  new MutationObserver(() => {cancelAnimationFrame(frame);frame=requestAnimationFrame(update);})
    .observe(document.documentElement,{childList:true,subtree:true});
})();
