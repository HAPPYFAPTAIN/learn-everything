(() => {
  const initialized = new WeakSet();
  let serial = 0;

  function select(root, tab, focus = false) {
    const index = tab.dataset.stageIndex;
    root.querySelectorAll('.le-route-stage-tab').forEach(item => {
      const active = item === tab;
      item.setAttribute('aria-selected', String(active));
      item.tabIndex = active ? 0 : -1;
    });
    root.querySelectorAll('.le-route-stage-panel').forEach(panel => {
      const active = panel.dataset.stageIndex === index;
      panel.hidden = !active;
      if (active) {
        panel.querySelector('.le-route-stage').open = true;
        panel.scrollTop = 0;
        const courses = panel.querySelector('.le-stage-courses');
        if (courses) courses.scrollTop = 0;
      }
    });
    if (focus) tab.focus({preventScroll: true});
  }

  function enhance(root) {
    if (initialized.has(root)) return;
    const tabs = [...root.querySelectorAll('.le-route-stage-tab')];
    const panels = [...root.querySelectorAll('.le-route-stage-panel')];
    const nav = root.querySelector('.le-route-stage-nav');
    if (!nav || !tabs.length || tabs.length !== panels.length) return;
    initialized.add(root);
    const prefix = `le-route-stage-${++serial}`;
    tabs.forEach((tab, index) => {
      tab.id = `${prefix}-tab-${index}`;
      panels[index].id = `${prefix}-panel-${index}`;
      tab.setAttribute('aria-controls', panels[index].id);
      panels[index].setAttribute('aria-labelledby', tab.id);
    });
    root.classList.add('is-enhanced');
    nav.hidden = false;
    select(root, tabs.find(tab => tab.getAttribute('aria-selected') === 'true') || tabs[0]);
    nav.addEventListener('click', event => {
      const tab = event.target.closest('.le-route-stage-tab');
      if (tab && nav.contains(tab)) select(root, tab);
    });
    nav.addEventListener('keydown', event => {
      const tab = event.target.closest('.le-route-stage-tab');
      if (!tab) return;
      const position = tabs.indexOf(tab);
      let next;
      if (event.key === 'ArrowDown' || event.key === 'ArrowRight') next = (position + 1) % tabs.length;
      else if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') next = (position - 1 + tabs.length) % tabs.length;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = tabs.length - 1;
      else return;
      event.preventDefault();
      event.stopPropagation();
      select(root, tabs[next], true);
    });
    root.addEventListener('toggle', event => {
      const course = event.target;
      if (!course.matches('.le-route-course') || !course.open) return;
      course.parentElement.querySelectorAll('.le-route-course[open]').forEach(other => {
        if (other !== course) other.open = false;
      });
    }, true);
  }

  function install(container = document) {
    if (container.matches?.('.le-route-browser')) enhance(container);
    container.querySelectorAll?.('.le-route-browser').forEach(enhance);
  }
  function start() {
    install();
    new MutationObserver(records => {
      records.forEach(record => record.addedNodes.forEach(node => {
        if (node.nodeType === Node.ELEMENT_NODE) install(node);
      }));
    }).observe(document.body, {childList: true, subtree: true});
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once: true});
  else start();
})();
