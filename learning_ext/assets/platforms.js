(() => {
  function start() {
    const root = document.getElementById('le-platform-filter');
    const picker = document.getElementById('le-platform-picker');
    if (!root || !picker) { setTimeout(start, 250); return; }
    const catalog = JSON.parse(root.dataset.catalog);
    const search = root.querySelector('input');
    let group = '全部';
    function filter() {
      const query = search.value.trim().toLowerCase();
      let count = 0;
      picker.querySelectorAll('label:has(input[type=radio])').forEach(label => {
        const id = label.querySelector('input').value;
        const item = catalog[id];
        const match = item && (group === '全部' || item.group === group) && `${id} ${item.name} ${item.tag}`.toLowerCase().includes(query);
        label.classList.toggle('le-platform-filtered', !match);
        if (match) count++;
      });
      root.querySelector('.le-platform-count').textContent = count ? `${count} 个平台` : '没有找到，试试其他名称或自定义连接';
    }
    search.addEventListener('input', filter);
    root.querySelectorAll('[data-group]').forEach(button => button.addEventListener('click', () => {
      group = button.dataset.group;
      root.querySelectorAll('[data-group]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
      filter();
    }));
    new MutationObserver(filter).observe(picker, {childList:true,subtree:true});
    filter();
  }
  start();
})();
