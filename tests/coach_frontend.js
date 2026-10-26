(async () => {
  const checks = [], metrics = {};
  const check = (ok, name) => { if (!ok) throw Error(name); checks.push(name); };
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  const scene = window.testScene;
  const frame = document.createElement('iframe');
  frame.style.cssText = `width:${scene.width}px;height:900px;border:0;display:block`;
  document.body.append(frame);
  const doc = frame.contentDocument;
  doc.open();
  doc.write(`<!doctype html><html><head><meta charset="utf-8"><style>
    *{box-sizing:border-box}body{margin:0}button,textarea{font:inherit}
    .column{display:flex;flex-direction:column;min-width:0}.row{display:flex;flex-wrap:wrap;min-width:0}
    .block{min-width:0;position:relative}.hidden,[hidden]{display:none!important}
    .html-container{width:100%}p{margin:0 0 1em}button{cursor:pointer;width:100%}
    pre{white-space:pre}code{font-family:monospace}
  </style><link rel="stylesheet" href="${scene.stylesheet}"></head><body>
    <div class="gradio-container gradio-container-4-39-0"><div id="le-app-tabs">
    <section id="learning-coach-tab" class="tabitem fill-main-area-height scrollable">
      <div id="le-coach-root" class="column">
        <div id="le-coach-welcome" class="block"><div class="html-container"><div class="le-coach-welcome-copy">
          <h1>想做什么，一起动手。</h1><p>先看看你的电脑，再把目标拆成一步步行动。</p>
        </div></div></div>
        <div id="le-coach-suggestions" class="row">
          <button class="secondary" id="le-coach-suggest-env">检查学习环境</button>
          <button class="secondary" id="le-coach-suggest-files">寻找软件或文件</button>
          <button class="secondary" id="le-coach-suggest-window">指导当前窗口</button>
        </div>
        <div id="le-coach-toolbar" class="row"><button id="le-coach-clear" class="secondary">开启新任务</button></div>
        <div id="le-coach-plan" class="block"><div class="html-container"></div></div>
        <div id="le-coach-scroll" class="column"><div id="le-coach-transcript" class="block">
          <div class="html-container"><div class="le-coach-feed" aria-live="polite" aria-busy="false"></div></div>
        </div></div>
        <div id="le-coach-stream" class="block"><div class="html-container"></div></div>
        <div id="le-coach-approve" class="column" hidden></div>
        <div id="le-coach-question" class="column" hidden>
          <div id="le-coach-question-copy" class="block"><div class="html-container"><div class="le-question-heading">
            <span>先确认一下</span><h3>你希望从哪个方向开始？</h3></div></div></div>
          <div id="le-coach-question-options" class="row">${Array.from({length:4}, (_, index) => `<button id="le-coach-option-${index}" hidden></button>`).join('')}</div>
          <div class="block"><span class="le-question-free-text">也可以直接输入你的想法</span></div>
        </div>
        <div id="le-coach-composer" class="row">
          <div id="le-coach-input" class="block"><div class="wrap"><label><textarea rows="1" placeholder="你想学会什么，或卡在哪一步？"></textarea></label></div><div class="le-polish-tools"><button class="le-polish-button">润色</button></div></div>
          <button id="le-coach-send" class="primary">发送</button>
        </div>
      </div>
    </section></div></div></body></html>`);
  doc.close();
  try {
    if (doc.readyState !== 'complete') await new Promise(resolve => frame.addEventListener('load', resolve, {once:true}));
    await doc.fonts.ready;
    const win = frame.contentWindow;
    win.requestAnimationFrame = callback => win.setTimeout(() => callback(win.performance.now()), 1);
    win.cancelAnimationFrame = win.clearTimeout;
    win.localStorage.setItem('le.theme.mode', scene.dark ? 'dark' : 'light');
    win.fetch = async url => {
      if (String(url).includes('dark_theme.css')) return {ok:true, text:async () => scene.darkCss};
      throw Error('Fixture cannot access external services');
    };
    let copiedText = '';
    Object.defineProperty(win.navigator, 'clipboard', {configurable:true, value:{writeText:async text => {copiedText = text;}}});
    win.eval(scene.themeScript);
    win.eval(scene.coachScript);
    win.eval(scene.richTextScript);
    await wait(180);
    const byId = id => doc.getElementById(id);
    const style = element => win.getComputedStyle(element);
    const rect = element => element.getBoundingClientRect();
    const visible = element => !!element?.getClientRects().length && style(element).display !== 'none' && rect(element).height > 0;
    const root = byId('le-coach-root'), area = byId('le-coach-scroll'), composer = byId('le-coach-composer');
    const transcript = byId('le-coach-transcript');
    const feed = transcript.querySelector('.le-coach-feed');
    const transport = byId('le-coach-stream').querySelector('.html-container');
    const sendFrame = html => { transport.innerHTML = html; };
    const latest = root.querySelector('.le-coach-latest');
    metrics.viewport = {width:win.innerWidth,height:win.innerHeight};
    metrics.emptyChildren = [...root.children].filter(visible).map(element => element.id || element.className);
    check(win.innerWidth === scene.width, 'uses the requested viewport width');
    check(root.classList.contains('le-empty'), 'empty transcript enters welcome state');
    check(metrics.emptyChildren.length === 3 && ['le-coach-welcome','le-coach-suggestions','le-coach-composer'].every(id => metrics.emptyChildren.includes(id)), 'empty state shows only welcome, suggestions and composer');
    check(!visible(latest) && !visible(byId('le-coach-clear')), 'empty state hides latest and new-conversation actions');
    check(root.querySelectorAll('#le-coach-suggestions button').length === 3 && !byId('le-desktop-coach'), 'suggested tasks replace fixed desktop exercises');
    metrics.emptyComposer = {top:rect(composer).top,bottom:rect(composer).bottom};
    check(rect(composer).bottom <= win.innerHeight && rect(composer).left >= 0 && rect(composer).right <= win.innerWidth + 1, 'empty composer fits the viewport');
    if (scene.dark) check(doc.documentElement.dataset.leThemeStatus === 'ready', 'dark theme uses the production scoped stylesheet loader');

    sendFrame(scene.frames.initial);
    byId('le-coach-welcome').hidden = true;
    byId('le-coach-suggestions').hidden = true;
    await wait(220);
    check(!root.classList.contains('le-empty'), 'first content switches to conversation state');
    check(!composer.contains(byId('le-coach-clear')), 'starting another task stays outside the writing surface');
    const writing = byId('le-coach-input').querySelector('textarea'), polish = composer.querySelector('.le-polish-button');
    check(rect(writing).left - rect(composer).left < 22 && rect(writing).width > rect(composer).width - 40, 'writing surface has full width without a new-task indent');
    check(Math.abs(rect(polish).bottom - rect(byId('le-coach-send')).bottom) < 2, 'polish and send share one action baseline');
    check(rect(writing).bottom <= rect(byId('le-coach-send')).top, 'input text never overlaps the action row');
    check(!visible(byId('le-coach-stream')), 'stream transport never appears as a second conversation');
    const initialFrame = transport.querySelector('[data-coach-frame]');
    check(initialFrame.children.length === 0 && !initialFrame.hasAttribute('data-order'), 'transport carries JSON text without reparsing historical message HTML');
    check(Object.values(JSON.parse(initialFrame.textContent)).every(value => typeof value === 'string'), 'frame payload maps message ids to rendered HTML strings');
    const messages = feed.querySelectorAll('.le-me');
    const shortBubble = messages[0].querySelector('.le-bubble'), shortText = shortBubble.querySelector('p');
    const longBubble = messages[1].querySelector('.le-bubble');
    metrics.short = {height:rect(shortText).height,lineHeight:parseFloat(style(shortText).lineHeight),width:rect(shortBubble).width};
    metrics.longRatio = rect(longBubble).width / rect(messages[1]).width;
    check(metrics.short.height <= metrics.short.lineHeight + 1, 'short Chinese messages stay on one line');
    check(metrics.longRatio >= .58 && metrics.longRatio <= (scene.width < 680 ? .92 : .80), 'long user messages use a readable bubble width');
    check(rect(shortBubble).width >= 100, 'short user bubble retains padding instead of a narrow column');
    metrics.composer = {top:rect(composer).top,bottom:rect(composer).bottom,rootBottom:rect(root).bottom};
    check(Math.abs(rect(composer).bottom - rect(root).bottom) <= 2 && rect(composer).bottom <= win.innerHeight + 1, 'conversation composer stays at the bottom of the available screen');
    check(area.scrollHeight > area.clientHeight + 500, 'long conversation scrolls within its content area');
    check(area.scrollHeight - area.scrollTop - area.clientHeight <= 2, 'new conversation initially follows latest content');

    const codeBlock = feed.querySelector('.le-code-block'), pre = codeBlock.querySelector('pre');
    metrics.code = {width:rect(pre).width,clientWidth:pre.clientWidth,scrollWidth:pre.scrollWidth,overflow:style(pre).overflowX};
    check(pre.scrollWidth > pre.clientWidth + 100 && ['auto','scroll'].includes(style(pre).overflowX), 'long code scrolls horizontally inside its code block');
    pre.scrollLeft = 80;
    check(pre.scrollLeft > 0, 'long code can actually scroll');
    check(rect(codeBlock).width <= rect(codeBlock.closest('.le-body')).width + 1 && doc.documentElement.scrollWidth <= win.innerWidth + 1, 'code does not widen the answer or page');

    const luminance = color => color.match(/[\d.]+/g).slice(0,3).map(Number).map(channel => {
      const value = channel / 255;
      return value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4;
    }).reduce((sum,value,index) => sum + value * [.2126,.7152,.0722][index],0);
    const paragraph = feed.querySelector('.le-ai .le-body p');
    const ink = luminance(style(paragraph).color), background = luminance(style(doc.body).backgroundColor);
    metrics.colors = {text:style(paragraph).color,background:style(doc.body).backgroundColor,
      contrast:(Math.max(ink,background)+.05)/(Math.min(ink,background)+.05)};
    check(metrics.colors.contrast >= 4.5, 'assistant text remains readable in the active theme');
    check(Number(style(paragraph).opacity) === 1, 'assistant text is not faded');

    area.scrollTop = 0;
    area.dispatchEvent(new win.Event('scroll'));
    await wait(100);
    const composerBeforeStream = rect(composer).top;
    const details = feed.querySelector('details[data-call-id="environment-1"]');
    details.open = true;
    await wait(100);
    const copyButton = codeBlock.querySelector('.le-code-copy');
    copyButton.click();
    await wait(20);
    metrics.copy = {length:copiedText.length, sourceLength:scene.frames.code.length};
    check(copiedText === codeBlock.querySelector('code').textContent && copiedText.replace(/\n+$/, '') === scene.frames.code, 'copy sends the exact code without toolbar text');
    check(copyButton.dataset.copied === 'true' && copyButton.textContent.includes('已复制'), 'code copy gives visible confirmation');
    copyButton.focus({preventScroll:true});
    const selection = win.getSelection(), range = doc.createRange(), selectedNode = paragraph.firstChild;
    range.setStart(selectedNode, 0); range.setEnd(selectedNode, selectedNode.length);
    selection.removeAllRanges(); selection.addRange(range);
    const selectedText = selection.toString(), history = [...feed.children], historySet = new Set(history);
    let removedHistory = 0, replacedFeed = 0;
    const stability = new win.MutationObserver(records => {
      for (const record of records) for (const removed of record.removedNodes) {
        if (historySet.has(removed)) removedHistory++;
        if (removed === feed || removed.contains?.(feed)) replacedFeed++;
      }
    });
    stability.observe(transcript, {childList:true,subtree:true});
    const topBeforeStream = area.scrollTop, codeScrollBeforeStream = pre.scrollLeft;
    const nativeCreate = doc.createElement;
    let parsedMessages = 0;
    doc.createElement = function(tag, ...args) {
      if (tag === 'template') parsedMessages++;
      return nativeCreate.call(this, tag, ...args);
    };
    let liveNode, liveTextNode;
    for (let index = 0; index < scene.frames.deltas.length; index++) {
      sendFrame(scene.frames.deltas[index]);
      await wait(6);
      if (!index) { liveNode = feed.lastElementChild; liveTextNode = liveNode.querySelector('p').firstChild; }
      if (feed.lastElementChild !== liveNode) throw Error('streaming message root was replaced at frame ' + index);
      if (liveNode.querySelector('p').firstChild !== liveTextNode) throw Error('streaming text node was replaced at frame ' + index);
    }
    await wait(40);
    metrics.stability = {frames:scene.frames.deltas.length,removedHistory,replacedFeed,parsedMessages,selectedText:selection.toString()};
    check(parsedMessages === 44, '40 frames parse only 40 active answers and four changed tool results');
    check(scene.frames.deltas.length === 40 && feed.lastElementChild === liveNode, '40 delta frames retain the active message root and text node');
    check(byId('le-coach-transcript') === transcript && transcript.querySelector('.le-coach-feed') === feed, 'visible transcript and feed roots are never replaced');
    check(history.every((node,index) => node === feed.children[index]) && removedHistory === 0 && replacedFeed === 0, 'stream deltas do not rebuild any historical message');
    check(selection.toString() === selectedText && selection.anchorNode === selectedNode, 'selection in a settled answer survives all 40 frames');
    check(doc.activeElement === copyButton && feed.querySelector('.le-code-block') === codeBlock, 'streaming preserves focused controls and settled code blocks');
    check(pre.scrollLeft === codeScrollBeforeStream, 'streaming preserves horizontal code scroll position');
    check(feed.getAttribute('aria-busy') === 'true', 'active delta marks the visible feed busy');
    metrics.afterStream = {before:topBeforeStream,after:area.scrollTop,composerBefore:composerBeforeStream,composerAfter:rect(composer).top};
    check(Math.abs(area.scrollTop - topBeforeStream) <= 2, 'streaming respects a reader who scrolled upward');
    check(visible(latest), 'latest-progress action appears while reading earlier content');
    check(rect(latest).width < 220, 'latest-progress action stays compact despite Gradio full-width button defaults');
    check(feed.querySelector('details[data-call-id="environment-1"]') === details && details.open, 'tool details keep their identity and open state while their result changes');
    check(Math.abs(rect(composer).top - composerBeforeStream) <= 2, 'streaming does not move the bottom composer');
    latest.click();
    await wait(100);
    check(area.scrollHeight - area.scrollTop - area.clientHeight <= 2, 'latest-progress action returns to the conversation bottom');
    check(!visible(latest), 'latest-progress action hides after catching up');
    sendFrame(scene.frames.final);
    await wait(30);
    check(parsedMessages === 44, 'unchanged final snapshot parses no historical HTML');
    check(feed.getAttribute('aria-busy') === 'false', 'final snapshot clears the busy state');
    check(history.every((node,index) => node === feed.children[index]) && details.open, 'full recovery snapshot preserves settled nodes and expanded details');
    const finalText = feed.textContent, finalCount = feed.children.length;
    sendFrame(scene.frames.initial);
    await wait(30);
    check(feed.textContent === finalText && feed.children.length === finalCount && feed.getAttribute('aria-busy') === 'false', 'older sequence is ignored without reverting content or busy state');
    root.dispatchEvent(new win.KeyboardEvent('keydown', {key:'Escape',bubbles:true}));
    await wait(60);
    check(!details.open, 'Escape closes expanded tool details');
    sendFrame(scene.frames.updated);
    await wait(30);
    check(!details.open && feed.querySelector('details[data-call-id="environment-1"]') === details, 'closed tool details remain closed after another result update');
    stability.disconnect();
    doc.createElement = nativeCreate;
    check(removedHistory === 0 && replacedFeed === 0, 'delta and snapshot sequences never detach historical message roots');

    const question = byId('le-coach-question'), options = [...byId('le-coach-question-options').children];
    let chosen = null;
    options.forEach((button,index) => button.addEventListener('click', () => {chosen = index;}));
    question.hidden = false;
    metrics.questions = [];
    for (const count of [4]) {
      options.forEach((button,index) => {
        button.hidden = index >= count;
        button.textContent = ['检查已有工具\n先验证环境再开始', '寻找合适的软件\n优先使用电脑已有的应用', '指导当前窗口\n指出下一步的控件位置', '补充我的目标\n先说明想完成什么'][index];
      });
      await wait(40);
      const shown = options.filter(visible), grid = style(byId('le-coach-question-options')).gridTemplateColumns.split(' ').length;
      metrics.questions.push({count,shown:shown.length,columns:grid,height:rect(question).height,scrollHeight:question.scrollHeight});
      check(shown.length === count, `${count} clarifying choices are visible without phantom buttons`);
      check(grid === 1, `${count} choices use the vertical four-choice list`);
      check(rect(question).height <= Math.min(win.innerHeight * .62, 540) + 2 && rect(question).left >= 0 && rect(question).right <= win.innerWidth + 1, `${count} choices stay in a bounded panel without horizontal overflow`);
      check(Math.abs(rect(composer).bottom - rect(root).bottom) <= 2 && rect(composer).bottom <= win.innerHeight + 1, `${count} choices keep the input anchored at the screen bottom`);
      options[count - 1].click();
      check(chosen === count - 1, `${count} choices remain clickable`);
    }
    question.hidden = true;
    await wait(40);
    check(rect(composer).left >= -1 && rect(composer).right <= win.innerWidth + 1 && doc.documentElement.scrollWidth <= win.innerWidth + 1, 'conversation still fits the page after interactions');

    sendFrame(scene.frames.recoveryEmpty);
    await wait(30);
    const emptySequence = Number(transport.firstElementChild.dataset.seq);
    check(feed.children.length === 0 && root.classList.contains('le-empty'), 'new session clears previous conversation before receiving a new answer');
    sendFrame(scene.frames.recoveryLast);
    await wait(40);
    const recoveredSequence = Number(transport.firstElementChild.dataset.seq);
    metrics.recovery = {emptySequence,recoveredSequence,messageCount:feed.children.length};
    check(recoveredSequence - emptySequence > 40, 'recovery delivers only frame 40 after skipping the populated initial frame and intermediate frames');
    check(feed.children.length === scene.frames.recoveryCount && feed.querySelector('.le-me')?.textContent === '检查新会话的学习环境', 'coalesced frame recovers the user question and all preceding messages');
    check(feed.lastElementChild.textContent.includes(scene.frames.recoveryText), 'coalesced frame displays the complete current streamed answer');
    check(!root.classList.contains('le-empty') && feed.getAttribute('aria-busy') === 'true', 'recovered conversation leaves the empty state while still streaming');
    const recoveredNodes = [...feed.children], recoveredText = feed.textContent;
    sendFrame(scene.frames.updated);
    await wait(30);
    check(feed.textContent === recoveredText && recoveredNodes.every((node,index) => feed.children[index] === node), 'late frame from the old session cannot resurrect its conversation');
    check(feed.getAttribute('aria-busy') === 'true' && !root.classList.contains('le-empty'), 'late old-session frame cannot reset the current busy state');
    check(doc.documentElement.scrollWidth <= win.innerWidth + 1, 'recovered conversation still has no page-level horizontal overflow');

    // A short window makes one expanded tool taller than the scroll area. With
    // scrollTop already zero, closing it does not generate a native scroll event.
    frame.style.height = '460px';
    win.dispatchEvent(new win.Event('resize'));
    const shortFrame = doc.createElement('div');
    shortFrame.innerHTML = scene.frames.recoveryLast;
    const shortEnvelope = shortFrame.firstElementChild;
    const toolEntry = Object.entries(JSON.parse(shortEnvelope.textContent)).find(([,html]) => html.includes('data-call-id="recovery-check"'));
    const toolTemplate = doc.createElement('template');
    toolTemplate.innerHTML = toolEntry[1];
    toolTemplate.content.querySelector('.le-tool-args').textContent = Array.from({length:20}, (_,index) => `Input ${index + 1}`).join('\n');
    toolTemplate.content.querySelector('.le-tool-out').textContent = Array.from({length:40}, (_,index) => `Observation ${index + 1}`).join('\n');
    shortEnvelope.dataset.session = 'compact-tool-fixture';
    shortEnvelope.dataset.seq = String(recoveredSequence + 1);
    shortEnvelope.dataset.busy = 'false';
    shortEnvelope.textContent = JSON.stringify({[toolEntry[0]]:toolTemplate.innerHTML});
    sendFrame(shortFrame.innerHTML);
    await wait(60);
    const shortTool = feed.querySelector('details[data-call-id="recovery-check"]');
    check(feed.children.length === 1 && area.scrollHeight <= area.clientHeight + 1, 'one collapsed tool fits a short conversation viewport');
    shortTool.open = true;
    await wait(40);
    area.scrollTop = 0;
    area.dispatchEvent(new win.Event('scroll'));
    await wait(30);
    metrics.collapse = {expandedHeight:area.scrollHeight,viewportHeight:area.clientHeight,latestWidth:rect(latest).width};
    check(area.scrollHeight - area.clientHeight > 72 && visible(latest), 'expanding long tool details exposes latest-progress while reading the top');
    check(rect(latest).width < 220, 'latest-progress also stays compact in the short viewport');
    let collapseScrollEvents = 0;
    area.addEventListener('scroll', () => {collapseScrollEvents++;}, {once:true});
    shortTool.open = false;
    await wait(50);
    metrics.collapse.closedHeight = area.scrollHeight;
    metrics.collapse.scrollEvents = collapseScrollEvents;
    check(area.scrollHeight <= area.clientHeight + 1, 'closing tool details removes conversation overflow');
    check(collapseScrollEvents === 0, 'tool collapse scenario requires no native scroll event');
    check(!visible(latest), 'collapsing fitting details hides latest-progress without a scroll event');
    const result = document.createElement('pre');
    result.id = 'results'; result.textContent = JSON.stringify({checks,metrics}); document.body.append(result);
  } catch (error) {
    const result = document.createElement('pre');
    result.id = 'results'; result.textContent = JSON.stringify({checks,metrics,error:error.message}); document.body.append(result);
  }
})();
