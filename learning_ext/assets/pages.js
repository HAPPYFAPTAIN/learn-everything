(() => {
  const headers = {id:'内部编号',name:'资料名称',size:'大小',tokens:'文本量',loader:'解析方式',date_created:'添加时间'};
  function notebookLayout(layout) {
    const collection = layout?.querySelector('.le-library-collection');
    if (!collection) return;
    if (!layout.querySelector('.le-notebook-reader')) {
      layout.classList.add('le-notebook');
      collection.querySelector('.le-library-section-title').textContent = '来源';
      const reader = document.createElement('section');
      reader.className = 'le-notebook-reader';
      reader.setAttribute('aria-label', '资料阅读');
      reader.innerHTML = '<header class="le-notebook-panel-head"><h2>阅读</h2><span>原文与出处</span></header><div class="le-notebook-empty"><div class="le-notebook-book" aria-hidden="true"><span></span><span></span></div><h3>让资料，成为你的知识。</h3><p>从左侧选择一份来源，开始阅读。</p></div>';
      const studio = document.createElement('aside');
      studio.className = 'le-notebook-studio';
      studio.setAttribute('aria-label', '资料问答');
      studio.innerHTML = '<header class="le-notebook-panel-head"><h2>探索</h2><span>带着资料提问</span></header><div class="le-notebook-studio-intro"><span aria-hidden="true">✦</span><h3>读懂，然后用起来。</h3></div><div class="le-notebook-prompts"></div><p class="le-notebook-selection-note" role="status">先选择一份来源</p>';
      const chat = collection.querySelector('.le-source-chat');
      const actions = collection.querySelector('.le-source-download')?.parentElement;
      if (actions) actions.classList.add('le-source-actions');
      for (const selector of ['.le-source-selection', '.le-source-original', '.le-source-summary', '.le-source-filter', '.le-source-chunks']) {
        const component = collection.querySelector(selector) || reader.querySelector(selector);
        if (component) reader.append(component);
      }
      const extracted = document.createElement('details');
      extracted.className = 'le-extracted-content';
      extracted.innerHTML = '<summary>解析内容与引用片段</summary>';
      reader.querySelectorAll('.le-source-summary,.le-source-filter,.le-source-chunks').forEach(node => extracted.append(node));
      reader.append(extracted);
      if (actions) reader.append(actions);
      if (chat) studio.append(chat);
      const prompts = [
        ['≡', '提炼重点', '请根据选中的资料，提炼核心观点，并标明依据。'],
        ['◇', '解释概念', '请解释选中资料中最重要的概念，用一个容易理解的例子说明，并标明依据。'],
        ['↗', '检验理解', '请根据选中的资料出三道自测题，先不要揭晓答案。'],
      ];
      prompts.forEach(([icon, title, prompt]) => {
        const button = document.createElement('button');
        button.type = 'button'; button.disabled = true;
        button.innerHTML = `<span aria-hidden="true">${icon}</span><strong>${title}</strong><b aria-hidden="true">↗</b>`;
        button.addEventListener('click', () => {
          if (!chat || chat.disabled) return;
          chat.click();
          const deadline = Date.now() + 10000;
          const fillDraft = () => {
            const input = document.querySelector('#chat-input textarea');
            if (input?.getClientRects().length) {
              if (!input.value.trim()) {
                const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
                setter.call(input, prompt);
                input.dispatchEvent(new Event('input', {bubbles:true}));
              }
              input.focus();
            } else if (Date.now() < deadline) setTimeout(fillDraft, 100);
          };
          fillDraft();
        });
        studio.querySelector('.le-notebook-prompts').append(button);
      });
      layout.append(reader, studio);
    }
    const selected = Boolean(layout.querySelector('.le-source-title h3'));
    const actions = collection.querySelector('.le-source-download')?.parentElement;
    if (actions) {
      actions.classList.add('le-source-actions');
      const reader = layout.querySelector('.le-notebook-reader');
      reader.append(actions);
    }
    const title = layout.querySelector('.le-source-title h3')?.textContent || '';
    const original = layout.querySelector('.le-source-original');
    const extracted = layout.querySelector('.le-extracted-content');
    const hasPreview = original && !original.classList.contains('hide') && getComputedStyle(original).display !== 'none';
    if (extracted && extracted.dataset.hasPreview !== String(Boolean(hasPreview))) {
      extracted.open = !hasPreview;
      extracted.dataset.hasPreview = String(Boolean(hasPreview));
    }
    const firstChunk = layout.querySelector('.le-source-chunks details');
    if (title && layout.dataset.previewTitle !== title) {
      if (firstChunk) firstChunk.open = true;
      layout.querySelector('.le-notebook-reader').scrollTop = 0;
      const canvas = layout.querySelector('.le-original-canvas');
      if (canvas) canvas.scrollTop = 0;
      layout.dataset.previewTitle = title;
    }
    if (!selected) delete layout.dataset.previewTitle;
    collection.querySelectorAll('.le-source-groups thead th [role="button"]').forEach(button => {
      const label = {id:'编号', name:'资料集', files:'来源', date_created:'创建时间'}[button.textContent.trim()];
      if (label) button.textContent = label;
    });
    layout.classList.toggle('le-source-selected', selected);
    layout.querySelectorAll('.le-notebook-prompts button').forEach(button => { button.disabled = !selected; });
    const note = layout.querySelector('.le-notebook-selection-note');
    const noteText = selected ? '在知识问答中继续，可编辑后发送。' : '先选择一份来源';
    if (note.textContent !== noteText) note.textContent = noteText;
  }
  function polishLibrary() {
    const library = document.getElementById('indices-tab');
    if (!library) return;
    library.querySelectorAll('.tab-nav').forEach(nav => {
      const extensions = [...nav.querySelectorAll(':scope > button')].filter(button => button.textContent.includes('可选扩展'));
      if (!extensions.length || nav.querySelector('.le-library-switch')) return;
      nav.classList.add('le-library-nav');
      extensions.forEach(button => button.classList.add('le-library-extension'));
      const toggle = document.createElement('button');
      toggle.type = 'button';
      toggle.className = 'le-library-switch';
      toggle.textContent = '更多资料库';
      toggle.setAttribute('aria-expanded', 'false');
      toggle.addEventListener('click', () => {
        const expanded = nav.classList.toggle('le-library-extensions-open');
        toggle.setAttribute('aria-expanded', String(expanded));
        toggle.textContent = expanded ? '收起扩展' : '更多资料库';
      });
      nav.append(toggle);
    });
    library.querySelectorAll('[id="file_list_view"]').forEach(table => {
      let layout = table.closest('.le-library-layout') || table.parentElement;
      while (layout && layout !== library) {
        if (layout.classList.contains('le-library-layout')) break;
        if (layout.children.length === 2 && layout.querySelector('input[type="file"]') &&
            [...layout.children].some(child => child.contains(table)) &&
            [...layout.children].some(child => !child.contains(table) && child.querySelector('input[type="file"]'))) {
          layout.classList.add('le-library-layout');
          [...layout.children].forEach(child => child.classList.add(child.contains(table) ? 'le-library-collection' : 'le-library-add'));
          for (const [selector, title] of [['.le-library-add', '添加新资料'], ['.le-library-collection', '我的资料']]) {
            const column = layout.querySelector(selector);
            if (column && !column.querySelector('.le-library-section-title')) {
              const heading = document.createElement('h2');
              heading.className = 'le-library-section-title';
              heading.textContent = title;
              column.prepend(heading);
            }
          }
          const collection = layout.querySelector('.le-library-collection');
          const upload = layout.querySelector('.le-library-add');
          const toolbar = document.createElement('div');
          toolbar.className = 'le-library-toolbar';
          toolbar.append(collection.querySelector('.le-library-section-title'));
          const add = document.createElement('button');
          add.type = 'button'; add.className = 'le-library-new';
          add.innerHTML = '<span aria-hidden="true">＋</span> 添加资料';
          toolbar.append(add); collection.prepend(toolbar);
          const dialog = document.createElement('dialog');
          dialog.className = 'le-library-dialog'; dialog.setAttribute('aria-label','添加资料');
          const close = document.createElement('button');
          close.type = 'button'; close.className = 'le-library-close';
          close.textContent = '×'; close.setAttribute('aria-label','关闭添加资料');
          dialog.append(close, upload);
          const progress = collection.querySelector('.le-library-progress');
          if (progress) upload.append(progress);
          layout.append(dialog);
          const positionUpload=()=>{if(dialog.open)window.LEPanels?.place(dialog,add,'bottom',440);};
          add.addEventListener('click', () => {dialog.showModal();positionUpload();});
          new ResizeObserver(positionUpload).observe(upload);
          window.addEventListener('resize',positionUpload);
          close.addEventListener('click', () => dialog.close());
          dialog.addEventListener('click', event => {
            const rect = dialog.getBoundingClientRect();
            if (event.target === dialog && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) dialog.close();
          });
          dialog.addEventListener('close', () => add.focus());
          break;
        }
        layout = layout.parentElement;
      }
      const search = layout?.querySelector('.le-library-search input');
      if (search && !search.hasAttribute('aria-label')) search.setAttribute('aria-label','查找资料');
      if (!table.parentElement.querySelector(':scope > .le-library-list-tools, :scope > .le-library-searchbar')) {
        const tools = document.createElement('div');
        tools.className = 'le-library-list-tools';
        tools.innerHTML = '<button type="button" aria-pressed="false">显示技术信息</button>';
        tools.querySelector('button').addEventListener('click', event => {
          const expanded = table.classList.toggle('le-library-technical');
          event.currentTarget.setAttribute('aria-pressed', String(expanded));
          event.currentTarget.textContent = expanded ? '收起技术信息' : '显示技术信息';
        });
        const searchForm = table.parentElement.querySelector('.form:has(.le-library-search)');
        if (searchForm) {
          const bar = document.createElement('div'); bar.className = 'le-library-searchbar';
          table.before(bar); bar.append(searchForm,tools);
        } else table.before(tools);
      }
      table.querySelectorAll('thead th [role="button"]').forEach(button => {
        const title = headers[button.textContent.trim()];
        if (title) button.textContent = title;
      });
      table.querySelectorAll('tbody td:nth-child(2)').forEach(cell => {
        const title = cell.textContent.trim();
        if (cell.getAttribute('title') !== title) cell.setAttribute('title', title);
        const extension = title.includes('.') ? title.split('.').pop().toUpperCase() : '文档';
        cell.dataset.leType = /^[A-Z0-9]{1,5}$/.test(extension) ? extension : '文档';
      });
      if (layout?.classList.contains('le-library-layout')) {
        notebookLayout(layout);
        const nav = library.querySelector('.le-library-nav');
        const toolbar = layout.querySelector('.le-library-toolbar');
        if (nav && toolbar && layout.getBoundingClientRect().width && window.LEPanels && !nav.closest('dialog[open]')) {
          const item = window.LEPanels.register(nav, '切换资料库', 'book');
          if (item && item.entry.parentElement !== toolbar) {
            item.entry.classList.add('le-library-kind');
            toolbar.append(item.entry);
          }
        }
      }
    });
  }
  let pending = false;
  const queue = () => {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => { pending = false; polishLibrary(); });
  };
  function start() {
    const library = document.getElementById('indices-tab');
    if (!library) { setTimeout(start, 250); return; }
    new MutationObserver(queue).observe(library, {childList:true,subtree:true,characterData:true});
    document.addEventListener('click', event => { if (event.target.closest('[role=tab]')) queue(); });
    polishLibrary();
  }
  start();
})();
