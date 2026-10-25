(() => {
  const seen = new Set();
  let preparationShown = false;
  let confirmationShown = false;
  let exploreRequested = false;
  let lastFeedback = '';
  const scrollBehavior = () => matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth';
  const primary = ['learning-guide-tab-button','learning-workbench-tab-button','learning-review-tab-button','learning-quiz-tab-button'];
  const secondary = ['learning-path-tab-button','learning-dashboard-tab-button','learning-coach-tab-button','chat-tab-button','indices-tab-button'];
  let more = false;
  try { more = localStorage.getItem('le.nav.more') === 'true'; } catch (_) {}
  function syncNav() {
    const nav = document.querySelector('#le-app-tabs > .tab-nav');
    if (!nav) return;
    let toggle = document.getElementById('le-more-nav');
    if (!toggle) {
      toggle = document.createElement('button');
      toggle.id = 'le-more-nav'; toggle.type = 'button';
      toggle.addEventListener('click', () => {
        more = !more;
        try { localStorage.setItem('le.nav.more', String(more)); } catch (_) {}
        syncNav();
      });
      nav.append(toggle);
    }
    const label = more ? '收起更多功能 −' : '更多功能 +';
    if (toggle.textContent !== label) toggle.textContent = label;
    toggle.setAttribute('aria-expanded', String(more));
    primary.forEach(id => {
      const button = document.getElementById(id);
      if (!button) return;
      delete button.dataset.leSecondary;
      button.hidden = false;
    });
    secondary.forEach(id => {
      const button = document.getElementById(id);
      if (!button) return;
      button.dataset.leSecondary = 'true';
      button.hidden = !more && !button.classList.contains('selected');
    });
  }
  function syncHomeAccessibility() {
    const feedback = document.getElementById('le-onboarding-feedback');
    if (feedback) {
      feedback.setAttribute('role', 'alert');
      feedback.setAttribute('aria-live', 'assertive');
      feedback.setAttribute('aria-atomic', 'true');
      const message = feedback.textContent.trim();
      const input = document.querySelector('#le-onboarding-topic textarea');
      if (message && message !== lastFeedback && input && !input.value.trim() && input.getClientRects().length) {
        input.setAttribute('aria-invalid', 'true');
        input.setAttribute('aria-errormessage', 'le-onboarding-feedback');
        input.focus({preventScroll:true});
      }
      lastFeedback = message;
    }
    document.querySelectorAll('.le-direction-button').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.leSelected === 'true'));
    });
  }
  function processMarkers() {
    syncHomeAccessibility();
    const confirmation = document.querySelector('#le-home-confirm');
    const confirmationVisible = Boolean(confirmation?.getClientRects().length);
    if (confirmationVisible && !confirmationShown) confirmation.scrollIntoView({block:'center',behavior:scrollBehavior()});
    confirmationShown = confirmationVisible;
    if (exploreRequested && document.querySelector('#le-home-goal-panel')?.getClientRects().length) {
      exploreRequested = false;
      document.querySelector('#le-discovery-heading')?.scrollIntoView({block:'center',behavior:scrollBehavior()});
    }
    const preparation = document.querySelector('#le-route-save-progress .le-prep-panel');
    if (preparation && !preparationShown && preparation.dataset.prepPhase === 'saving') preparation.scrollIntoView({block:'center',behavior:scrollBehavior()});
    preparationShown = Boolean(preparation);
    document.querySelectorAll('[data-le-flow-target]').forEach(marker => {
      const id = marker.dataset.leFlowId;
      if (!id || seen.has(id)) return;
      const tab = document.getElementById(marker.dataset.leFlowTarget + '-button');
      if (!tab) return;
      seen.add(id);
      tab.hidden = false;
      tab.click();
      document.dispatchEvent(new CustomEvent('le:onboarding-stage', {detail: marker.dataset.leFlowStage}));
      requestAnimationFrame(() => { tab.focus({preventScroll:true}); window.scrollTo({top:0,behavior:'instant'}); });
    });
  }
  function boot() {
    document.addEventListener('input', event => {
      if(event.target.matches('#le-onboarding-topic textarea')) {
        event.target.removeAttribute('aria-invalid');
        event.target.removeAttribute('aria-errormessage');
        lastFeedback = '';
      }
    });
    document.addEventListener('click', event => {
      const action = event.target.closest('[data-le-home-action]');
      const direction = event.target.closest('.le-direction-button');
      if (action || direction) {
        const key = action?.dataset.leHomeAction;
        if (key === 'explore' && !document.querySelector('#le-home-goal-panel')?.getClientRects().length) {
          exploreRequested = true;
          document.querySelector('#le-home-back')?.click();
        }
        const destination = direction ? document.querySelector('#le-onboarding-card')
          : key === 'sample' ? document.querySelector('#le-guided-home .le-sample')
          : document.querySelector('#le-discovery-heading');
        if (key === 'sample' && destination) destination.open = true;
        if (direction) {
          document.querySelectorAll('.le-direction-button').forEach(button => {
            const selected = button === direction;
            button.dataset.leSelected = String(selected);
            button.setAttribute('aria-pressed', String(selected));
          });
        }
        destination?.scrollIntoView({block:'center',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
        if (direction) document.querySelector('#le-onboarding-topic textarea')?.focus({preventScroll:true});
      }
      const sample = event.target.closest('[data-le-sample]');
      if (sample) {
        const section = sample.closest('.le-sample');
        section.querySelectorAll('[data-le-sample]').forEach(button => button.setAttribute('aria-pressed', String(button === sample)));
        section.querySelector('[data-le-sample-result]').textContent = sample.dataset.leSample === 'date'
          ? '答对了。先在日期列找到 10 月 1 日，再看这一行的商品与金额。你已经完成第一次小练习。'
          : '再想一下：我们要找的是某一天的订单。试试“日期”列，先确定时间。';
      }
      const link = event.target.closest('[data-le-nav]');
      if (link) {
        const target = document.getElementById(link.dataset.leNav + '-button');
        if (target) target.hidden = false;
      }
      if (event.target.closest('#le-app-tabs > .tab-nav > button')) setTimeout(syncNav, 0);
    });
    let frame = 0;
    const observer = new MutationObserver(() => {
      if (frame) return;
      frame = requestAnimationFrame(() => {frame = 0; syncNav(); processMarkers();});
    });
    observer.observe(document.body, {childList:true,subtree:true});
    syncNav(); processMarkers();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, {once:true});
  else boot();
})();
