(() => {
  let frame = 0;
  function decorate() {
    document.querySelectorAll('.le-library-progress').forEach(panel => {
      const summary = panel.querySelector('.le-import-summary');
      if (!summary || panel.querySelector('.le-import-details')) return;
      panel.prepend(summary);
      const details = document.createElement('details');
      details.className = 'le-import-details';
      const label = document.createElement('summary');
      label.textContent = '处理详情';
      details.append(label);
      panel.querySelectorAll('.le-import-log').forEach(log => details.append(log));
      panel.append(details);
    });
    const sources = document.querySelector('#le-chat-flyout #index-0');
    if (sources && !sources.querySelector('.le-source-intro')) {
      const intro = document.createElement('div');
      intro.className = 'le-source-intro';
      intro.innerHTML = '<span aria-hidden="true">▤</span><div><strong>让回答有据可依</strong><p>选择这次提问要参考的资料</p></div>';
      sources.prepend(intro);
    }
    const guide = document.getElementById('le-guide-md');
    guide?.querySelectorAll('h2,h3').forEach(heading => {
      const title = heading.textContent.trim();
      if (/^(本节导览|课程导览|本节概览|概述)$/.test(title)) {
        heading.classList.add('le-editorial-heading');
        if (heading.nextElementSibling?.tagName === 'P') heading.nextElementSibling.classList.add('le-lesson-intro');
      }
      if (/^(学习目标|本节目标|你将学会)$/.test(title)) {
        let next = heading.nextElementSibling;
        while (next && !/^H[1-3]$/.test(next.tagName)) {
          if (/^(UL|OL)$/.test(next.tagName)) next.classList.add('le-learning-outcomes');
          next = next.nextElementSibling;
        }
      }
    });
    document.querySelectorAll('.le-library-dialog .block:has(input[type=file]) > button, #quick-file > button:has(input[type=file])').forEach(button => {
      if (button.querySelector('.le-upload-prompt')) return;
      const prompt = document.createElement('div');
      prompt.className = 'le-upload-prompt';
      prompt.innerHTML = '<span class="le-upload-stack" aria-hidden="true"><i>DOC</i><i>PDF</i><i>IMG</i></span><strong>把好资料，放在一起</strong><span>拖入文件，或点击选择</span><small>文档 · PDF · 图片</small>';
      button.append(prompt);
    });
  }
  function schedule() { cancelAnimationFrame(frame); frame = requestAnimationFrame(decorate); }
  new MutationObserver(schedule).observe(document.documentElement, {childList:true,subtree:true});
  schedule();
})();
