document.addEventListener('DOMContentLoaded', async () => {
  const checks = [];
  const check = (condition, name) => { if (!condition) throw new Error(name); checks.push(name); };
  const wait = () => new Promise(resolve => setTimeout(resolve, 30));
  const press = (element, key) => element.dispatchEvent(new KeyboardEvent('keydown', {key, bubbles: true, cancelable: true}));
  const host = document.getElementById('route-host');
  let root = host.querySelector('.le-route-browser');
  let tabs = [...root.querySelectorAll('[role="tab"]')];
  const active = () => [...root.querySelectorAll('[role="tabpanel"]')].filter(panel => !panel.hidden);
  const selected = () => [...root.querySelectorAll('[role="tab"]')].filter(tab => tab.getAttribute('aria-selected') === 'true');
  try {
    check(root.classList.contains('is-enhanced') && !root.querySelector('[role="tablist"]').hidden, 'navigation is enhanced once');
    check(active().length === 1 && active()[0].dataset.stageIndex === '2', 'next learning stage is the only visible panel');
    check(selected().length === 1 && selected()[0] === tabs[1], 'one initial selected tab');
    check(tabs.every(tab => document.getElementById(tab.getAttribute('aria-controls')).getAttribute('aria-labelledby') === tab.id), 'tab and panel labels are linked');
    check(tabs.filter(tab => tab.tabIndex === 0).length === 1, 'only active tab is in the tab order');
    tabs[1].focus(); press(tabs[1], 'ArrowDown');
    check(selected()[0] === tabs[2] && document.activeElement === tabs[2] && active().length === 1, 'ArrowDown selects and focuses next stage');
    press(tabs[2], 'ArrowRight');
    check(selected()[0] === tabs[0] && active()[0].dataset.stageIndex === '1', 'ArrowRight wraps to the first stage');
    press(tabs[0], 'End');
    check(selected()[0] === tabs[2], 'End selects the final stage');
    press(tabs[2], 'Home');
    check(selected()[0] === tabs[0], 'Home selects the first stage');
    tabs[1].querySelector('.le-stage-title').click();
    check(selected()[0] === tabs[1] && active()[0].querySelector('.le-route-stage').open, 'clicking a tab child opens its course list');
    const courses = [...active()[0].querySelectorAll('.le-route-course')];
    courses[0].open = true; await wait();
    courses[1].open = true; await wait();
    check(!courses[0].open && courses[1].open, 'opening a course collapses only its sibling details');
    const oldId = tabs[0].id;
    host.innerHTML = window.initialRoute; await wait();
    root = host.querySelector('.le-route-browser');
    tabs = [...root.querySelectorAll('[role="tab"]')];
    check(active().length === 1 && selected()[0] === tabs[1] && tabs[0].id !== oldId, 'replacement route initializes without previous navigation state');
    tabs[0].click();
    check(selected()[0] === tabs[0] && active()[0].dataset.stageIndex === '1', 'replacement route remains interactive');
    check(!window.testErrors.length, 'no browser exceptions');
    const output = document.createElement('pre'); output.id = 'results'; output.textContent = JSON.stringify({checks}); document.body.append(output);
  } catch (error) {
    const output = document.createElement('pre'); output.id = 'results'; output.textContent = JSON.stringify({checks, error: error.message, errors: window.testErrors}); document.body.append(output);
  }
});
