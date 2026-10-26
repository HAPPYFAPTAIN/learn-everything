(async () => {
  const checks = [];
  const check = (ok, name) => { if (!ok) throw Error(name); checks.push(name); };
  const wait = (milliseconds = 35) => new Promise(resolve => setTimeout(resolve, milliseconds));
  const bot = document.getElementById('main-chat-bot');
  const content = document.getElementById('html-info-panel');
  const messages = bot.querySelector('.message-wrap');
  const trigger = () => document.getElementById('le-answer-reference-trigger');
  const dialog = () => document.getElementById('le-chat-reference-dialog');
  const visible = element => !!element && !element.hidden && getComputedStyle(element).display !== 'none';
  const isOpen = () => !!dialog()?.open;
  const empty = '<h5><b>No evidence found.</b></h5>';
  const source = (name, id) => `<details class="evidence" open><summary><i>${name}</i><a class="pdf-link" href="#" data-page="1" data-src="/sample.pdf">[Preview]</a></summary><div class="evidence-content"><p><mark id="${id}">可核对的来源正文</mark></p></div></details>`;
  let renderedEvidence;
  let revision = 0;
  const setEvidence = html => {
    if (html === renderedEvidence) return;
    renderedEvidence = html;
    content.innerHTML = `<div class="prose">${html}</div>`;
  };
  const selection = (html, index) => `${html}<!--le-reference-selection:${index}:00000000-0000-4000-8000-${String(++revision).padStart(12, '0')}-->`;
  const addAnswer = (text, html, citationId, delay = 8) => {
    const row = document.createElement('div');
    row.className = 'message-row bubble bot-row';
    row.innerHTML = `<div class="flex-wrap bot"><div class="message bot"><button data-testid="bot"><div class="prose chatbot md"><p>${text}</p></div></button></div></div>`;
    const actions = document.createElement('div');
    actions.className = 'message-buttons';
    actions.innerHTML = '<button aria-label="复制">复制</button>';
    const button = row.querySelector('[data-testid="bot"]');
    if (citationId) {
      const citation = document.createElement('a');
      citation.className = 'citation';
      citation.id = citationId;
      citation.href = '#';
      citation.textContent = '[1]';
      button.querySelector('p').append(citation);
    }
    button.addEventListener('click', () => {
      const index = [...bot.querySelectorAll('.bot-row')].indexOf(row);
      setTimeout(() => setEvidence(selection(html, index)), delay);
    });
    messages.append(row, actions);
    return button;
  };
  const openExplicitly = async () => {
    check(visible(trigger()), 'sources action available before explicit open');
    trigger().focus();
    trigger().click();
    await wait();
    check(isOpen(), 'explicit sources action opens the viewer');
  };
  const escape = async () => {
    dialog().dispatchEvent(new Event('cancel', {cancelable: true}));
    await wait();
  };
  try {
    const plain = addAnswer('好，这是普通回答。', empty);
    await wait();
    check(!visible(trigger()), 'empty reference placeholder has no action');
    plain.click();
    await wait();
    check(!visible(trigger()) && !isOpen(), 'plain answer click never exposes an empty viewer');

    setEvidence(empty + '<h5>Answer confidence: 0.8</h5>');
    await wait();
    check(!visible(trigger()), 'status and confidence text are not sources');
    setEvidence('<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M4 12h16"/></svg>');
    await wait();
    check(!visible(trigger()), 'decorative icons alone are not reference content');

    const first = addAnswer('第一份资料的总结', source('第一份资料.pdf', 'mark-first'), 'mark-first');
    first.click();
    await wait();
    check(visible(trigger()), 'real evidence provides a compact action');
    check(!isOpen(), 'selecting an answer with evidence does not open the viewer');
    await openExplicitly();
    check(dialog().contains(document.getElementById('chat-info-panel')), 'viewer retains the original evidence component');
    check(dialog().querySelector('.pdf-link')?.dataset.src === '/sample.pdf', 'PDF preview link and metadata survive');
    await escape();
    check(!isOpen(), 'Escape closes the sources viewer');
    check(document.activeElement === trigger(), 'Escape restores focus to the entry');

    const second = addAnswer('第二份资料的总结', source('第二份资料.pdf', 'mark-second'), 'mark-second');
    second.click();
    await wait();
    check(!isOpen() && visible(trigger()), 'selecting another answer keeps sources closed');
    await openExplicitly();
    check(dialog().textContent.includes('第二份资料.pdf') && !dialog().textContent.includes('第一份资料.pdf'), 'history selection shows the matching evidence');
    await escape();
    const duplicate = addAnswer('同一来源的另一条回答', source('第二份资料.pdf', 'mark-second'));
    duplicate.click();
    await wait();
    check(visible(trigger()) && !isOpen(), 'answers sharing identical evidence retain their source action');
    const delayed = addAnswer('稍后才完成的资料', source('正确资料.pdf', 'mark-delayed'), null, 100);
    delayed.click();
    setEvidence(selection(source('过时资料.pdf', 'mark-stale'), 2));
    await wait();
    check(!visible(trigger()) && !isOpen(), 'stale selection response cannot expose another answer sources');
    await wait(110);
    check(visible(trigger()), 'matching completed selection enables the source action');
    await openExplicitly();
    check(dialog().textContent.includes('正确资料.pdf') && !dialog().textContent.includes('过时资料.pdf'), 'the viewer displays only the selected answer completion');
    await escape();
    first.querySelector('a.citation').click();
    await wait();
    await wait();
    check(isOpen(), 'explicit inline citation opens the sources viewer');
    check(dialog().querySelector('mark[id="mark-first"]'), 'inline citation resolves the selected historical source');
    await escape();

    plain.click();
    await wait();
    check(!visible(trigger()) && !isOpen(), 'returning to an answer without sources clears the action');

    const map = addAnswer('这是一张思维导图', '<details class="evidence" open><summary>Mindmap</summary><div class="markmap"><svg class="markmap"><text>学习目标</text></svg></div></details>');
    map.click();
    await wait();
    check(visible(trigger()) && !isOpen(), 'mindmap is available without automatically opening');
    await openExplicitly();
    check(dialog().querySelector('svg.markmap'), 'mindmap remains renderable inside the viewer');
    await escape();
    const plot = document.querySelector('#chat-info-panel .plot-container');
    const chartAnswer = addAnswer('根据数据得到的图表', '');
    plot.hidden = false;
    plot.innerHTML = '<div class="plotly js-plotly-plot"><svg class="main-svg"><path d="M0 20L20 0"/></svg></div>';
    chartAnswer.click();
    await wait();
    check(visible(trigger()) && !isOpen(), 'actual chart data has an explicit viewer action');
    await openExplicitly();
    check(dialog().querySelector('.js-plotly-plot .main-svg'), 'chart remains mounted in the viewer');
    plot.hidden = true;
    plot.replaceChildren();

    document.getElementById('new-conv-button').click();
    messages.replaceChildren();
    setEvidence('');
    await wait();
    check(!isOpen() && !visible(trigger()), 'new conversation clears the selected evidence');

    const next = addAnswer('可引用的回答', source('当前资料.pdf', 'mark-current'));
    next.click();
    await wait();
    await openExplicitly();
    document.querySelector('#chat-input textarea').dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true}));
    await wait();
    check(!isOpen() && !visible(trigger()), 'sending another question closes stale evidence');

    next.click();
    await wait();
    await openExplicitly();
    document.querySelector('#conversation-dropdown [role="option"]').click();
    setEvidence('');
    await wait();
    check(!isOpen() && !visible(trigger()), 'switching conversation closes and clears evidence');
    check(document.querySelectorAll('#le-chat-reference-dialog').length === 1, 'rerenders do not duplicate the dialog');
    const result = document.createElement('pre');
    result.id = 'results';
    result.textContent = JSON.stringify({checks});
    document.body.append(result);
  } catch (error) {
    const result = document.createElement('pre');
    result.id = 'results';
    result.textContent = JSON.stringify({checks, error:error.message, stack:error.stack});
    document.body.append(result);
  }
})();
