(async () => {
  const checks = [], metrics = {};
  const check = (ok, name) => { if (!ok) throw Error(name); checks.push(name); };
  const wait = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
  const {width, dark, stylesheet} = window.testScene;
  const frame = document.createElement('iframe');
  frame.style.cssText = `width:${width}px;height:900px;border:0;display:block`;
  document.body.append(frame);
  const doc = frame.contentDocument;
  const text = '请说明这项技术的主要用途，并提供三个可以在日常工作中尝试的具体例子，让没有基础的人也能按步骤操作。'.repeat(3);
  const code = 'const result = processDocument("' + 'example-document-name-'.repeat(24) + '");';
  const answer = (id, role, content) => `<div id="${id}" class="message-row bubble ${role}-row"><div class="flex-wrap ${role}"><div class="message ${role} message-fit"><button data-testid="${role}" aria-label="${role} message"><div class="prose chatbot md">${content}</div></button></div></div></div><div class="message-buttons message-buttons-${role === 'bot' ? 'left' : 'right'}"><button class="action" aria-label="复制"><svg width="16" height="16" viewBox="0 0 20 20"><rect x="5" y="5" width="10" height="10" fill="none" stroke="currentColor"/></svg></button></div>`;
  doc.open();
  doc.write(`<!doctype html><html class="${dark ? 'le-dark' : ''}"><head><meta charset="utf-8"><style>
    *{box-sizing:border-box}body{margin:0}button{font:inherit}p{margin:0 0 1em}
    .flex-wrap{width:100%;height:100%}.message-fit{width:fit-content!important}
    .message-wrap{display:flex;flex-direction:column;justify-content:space-between;margin-bottom:24px}
    .message-row{display:flex;position:relative}.user-row{align-self:flex-end}
    .bubble-wrap{width:100%;overflow-y:auto;height:100%}.prose.chatbot.md{opacity:.8}
    .message-buttons{display:flex;border:1px solid #ddd;background:#eee}
    .message>button{width:100%;user-select:text}.message>button:focus{outline:2px solid cyan}
    pre{white-space:pre}code{font-family:monospace}
  </style><link rel="stylesheet" href="${stylesheet}"></head><body><div class="gradio-container gradio-container-4-39-0"><div id="le-app-tabs"><section id="chat-tab" class="tabitem"><div id="chat-area"><div id="main-chat-bot"><div class="wrap hide"></div><div class="wrapper"><div class="bubble-wrap"><div class="message-wrap">
    ${answer('short-user', 'user', '<p>只回复：好</p>')}
    ${answer('short-answer', 'bot', '<p>好</p>')}
    ${answer('long-user', 'user', `<p>${text}</p>`)}
    ${answer('code-answer', 'bot', `<p>在终端运行以下代码。</p><pre><code>${code}</code></pre><p>运行完成后即可继续。</p>`)}
  </div></div></div></div><div id="le-composer"><div id="chat-input"><textarea aria-label="问题" placeholder="输入问题，按回车发送…"></textarea></div><div class="le-composer-tools"><button id="le-chat-plus">+</button><button class="le-source-shortcut">选择资料</button><button class="submit-button" aria-label="发送">↑</button></div></div></div></section></div></div></body></html>`);
  doc.close();
  try {
    if (doc.readyState !== 'complete') await new Promise(resolve => frame.addEventListener('load', resolve, {once:true}));
    await doc.fonts.ready;
    await wait(400);
    const win = frame.contentWindow;
    const byId = id => doc.getElementById(id);
    const style = element => win.getComputedStyle(element);
    const rect = element => element.getBoundingClientRect();
    const shortUser = byId('short-user'), shortText = shortUser.querySelector('p');
    const shortAnswer = byId('short-answer'), longUser = byId('long-user');
    const longBubble = longUser.querySelector('.flex-wrap');
    const codeAnswer = byId('code-answer'), pre = codeAnswer.querySelector('pre');
    metrics.viewport = win.innerWidth;
    metrics.shortLineHeight = parseFloat(style(shortText).lineHeight);
    metrics.shortTextHeight = rect(shortText).height;
    metrics.shortAnswerHeight = rect(shortAnswer).height;
    metrics.answerGap = rect(shortAnswer).top - rect(shortUser).bottom;
    metrics.longBubbleRatio = rect(longBubble).width / rect(longUser).width;
    metrics.pre = {width:rect(pre).width, scrollWidth:pre.scrollWidth, clientWidth:pre.clientWidth};
    check(win.innerWidth === width, 'fixture uses the requested viewport width');
    check(rect(shortText).height <= metrics.shortLineHeight + 1, 'short Chinese user message stays on one line');
    check(rect(shortUser.querySelector('.message')).width > rect(shortText).width + 20, 'user bubble keeps comfortable horizontal padding');
    check(metrics.shortAnswerHeight <= 48, 'one line assistant answer does not stretch vertically');
    check(metrics.answerGap >= 12 && metrics.answerGap <= 64, 'consecutive messages have a compact reading rhythm');
    check(metrics.longBubbleRatio <= (width > 800 ? .79 : .87), 'long user message respects the outer bubble width limit');
    check(metrics.longBubbleRatio >= .55, 'long user message does not collapse into a narrow column');
    check(rect(pre).width <= rect(codeAnswer.querySelector('.message')).width + 1, 'code block remains inside its answer column');
    check(pre.scrollWidth > pre.clientWidth + 100 && ['auto','scroll'].includes(style(pre).overflowX), 'long code has horizontal scrolling instead of page overflow');
    pre.scrollLeft = 80;
    check(pre.scrollLeft > 0, 'code can actually be scrolled horizontally');
    const monitored = [byId('chat-area'), shortUser, longUser, codeAnswer, byId('le-composer'), pre];
    metrics.horizontal = monitored.map(element => ({id:element.id || element.tagName, left:rect(element).left, right:rect(element).right}));
    check(monitored.every(element => rect(element).left >= -1 && rect(element).right <= win.innerWidth + 1), 'chat content remains within the viewport');
    check(doc.documentElement.scrollWidth <= win.innerWidth + 1, 'the page has no horizontal overflow');

    const bodyText = shortAnswer.querySelector('p');
    const prose = shortAnswer.querySelector('.prose');
    const probe = doc.createElement('span');
    probe.style.setProperty('color', 'var(--le-ink)', 'important');
    shortAnswer.append(probe);
    metrics.colors = {text:style(bodyText).color, ink:style(probe).color, background:style(doc.body).backgroundColor};
    check(style(bodyText).color === style(probe).color, 'answer text follows the active theme ink');
    check(Number(style(prose).opacity) === 1 && Number(style(bodyText).opacity) === 1, 'answer text is fully opaque');
    const rgb = color => color.match(/[\d.]+/g).slice(0,3).map(Number).map(channel => {
      const value = channel / 255;
      return value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4;
    });
    const luminance = color => rgb(color).reduce((total, value, index) => total + value * [.2126,.7152,.0722][index], 0);
    const foreground = luminance(style(bodyText).color), background = luminance(style(doc.body).backgroundColor);
    metrics.contrast = (Math.max(foreground,background) + .05) / (Math.min(foreground,background) + .05);
    check(metrics.contrast >= 4.5, 'body text has readable contrast in the selected theme');
    probe.remove();

    const messageButton = shortAnswer.querySelector('[data-testid="bot"]');
    messageButton.dispatchEvent(new win.PointerEvent('pointerdown', {bubbles:true, pointerType:'mouse'}));
    messageButton.focus();
    messageButton.click();
    check(style(messageButton).outlineStyle === 'none' || parseFloat(style(messageButton).outlineWidth) === 0, 'clicking answer text does not outline the entire message');
    const copy = shortAnswer.nextElementSibling.querySelector('button');
    copy.focus();
    check(copy.matches(':focus-visible'), 'action receives a keyboard visible focus state');
    check(style(copy).outlineStyle !== 'none' && parseFloat(style(copy).outlineWidth) >= 1, 'message actions retain a visible keyboard focus indicator');
    const result = document.createElement('pre');
    result.id = 'results';
    result.textContent = JSON.stringify({checks, metrics});
    document.body.append(result);
  } catch (error) {
    const result = document.createElement('pre');
    result.id = 'results';
    result.textContent = JSON.stringify({checks, metrics, error:error.message});
    document.body.append(result);
  }
})();
