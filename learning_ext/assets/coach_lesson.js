(() => {
  const STORAGE_KEY = 'le.coach.lessons.v1';
  const LESSONS = {
    settings: {
      name: '电脑设置',
      steps: [
        { title: '先打开夜间模式', body: '找到“夜间模式”开关并打开它。看到状态变为开启后，再检查这一步。', hint: '开关在练习区顶部。只需要打开，不需要调整亮度。' },
        { title: '把亮度调到舒适区间', body: '保持夜间模式开启，把亮度调到 40%–60%。', hint: '拖动亮度滑块，右侧数值在 40% 到 60% 之间即可。' },
        { title: '撤销刚才的更改', body: '学习也包括撤销。关闭夜间模式，恢复原来的状态。', hint: '再次点击“夜间模式”开关，让它回到关闭状态。' },
        { title: '独立复做：完整走一遍', body: '不看提示，独立打开夜间模式、调到 40%–60%，最后撤销关闭。', hint: '先打开，再调亮度，最后关闭。使用提示后，本次会记为跟随完成。', independent: true },
      ],
    },
    excel: {
      name: 'Excel 入门',
      steps: [
        { title: '写出第一条求和公式', body: '在公式框输入 =SUM(B1:B3)，让 B1、B2、B3 三个单元格相加，结果为 90。', hint: '公式以英文等号开头，单元格范围用英文冒号：=SUM(B1:B3)。' },
        { title: '修改数据，检查结果', body: '把 B2 从 30 改为 40，公式保持不变，检查结果应自动变为 100。', hint: '只修改 B2 的数值，不要改公式。20 + 40 + 40 = 100。' },
        { title: '撤销数据修改', body: '把 B2 恢复为 30，确认结果重新回到 90。', hint: '撤销的不只是公式，也包括数据。恢复 B2 后，结果就是 90。' },
        { title: '独立复做：重新写出公式', body: '清空公式后，重新输入 =SUM(B1:B3)，确认结果为 90。', hint: '只需要 =SUM(B1:B3)。使用提示后，本次会记为跟随完成。', independent: true },
      ],
    },
    agent: {
      name: 'AI Agent',
      steps: [
        { title: '写清一个可执行任务', body: '用至少 12 个字写清你想让 Agent 完成什么，包括目标和结果。', hint: '例如：整理本周销售表并生成一份汇总报告。这里只检查任务是否写清楚，不评价语义质量。' },
        { title: '设置执行边界', body: '打开“执行前先让我确认”，避免 Agent 未经确认就执行操作。', hint: '勾选练习区中的“执行前先让我确认”。' },
        { title: '写出验收标准', body: '用至少 12 个字说明什么结果才算完成，并保留执行前确认。', hint: '例如：汇总字段完整、金额计算正确，我检查后才允许执行。' },
        { title: '独立复做：任务与边界一起写', body: '独立写出任务、执行确认和验收标准，三项都要满足。', hint: '目标与验收标准都至少 12 个字，并打开执行前确认。使用提示后，本次会记为跟随完成。', independent: true },
      ],
    },
  };
  const DEFAULT_VALUES = {
    night: false,
    brightness: 50,
    formula: '',
    cells: { B1: 20, B2: 30, B3: 40 },
    goal: '',
    criteria: '',
    confirm: false,
  };
  let store = loadStore();
  let lessonId = store.lessonId || 'settings';
  let state = store.sessions[lessonId] || freshState();
  let feedback = { type: '', text: '' };
  let staticBound = false;

  const $ = (id) => document.getElementById(id);

  function freshState() {
    return {
      step: 0,
      passed: false,
      completed: false,
      attempts: 0,
      hints: 0,
      hintSteps: [],
      mistakes: [],
      journal: [],
      values: JSON.parse(JSON.stringify(DEFAULT_VALUES)),
      startedAt: Date.now(),
      errorRecorded: false,
    };
  }

  function loadStore() {
    try {
      const value = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
      return value && value.sessions ? value : { lessonId: 'settings', sessions: {} };
    } catch (_) {
      return { lessonId: 'settings', sessions: {} };
    }
  }

  function persist() {
    store.lessonId = lessonId;
    store.sessions[lessonId] = state;
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(store)); } catch (_) {}
  }

  function record(type, message) {
    state.journal.push({ type, step: state.step, message, time: new Date().toISOString() });
    if (state.journal.length > 100) state.journal.splice(0, state.journal.length - 100);
    persist();
  }

  function normalizeFormula(value) {
    return String(value || '').replace(/\s+/g, '').replace(/＝/g, '=').replace(/：/g, ':').replace(/（/g, '(').replace(/）/g, ')').toUpperCase();
  }

  function computeResult(values) {
    const cells = values.cells || {};
    const numbers = ['B1', 'B2', 'B3'].map((key) => Number(cells[key]));
    return numbers.every(Number.isFinite) ? numbers.reduce((sum, value) => sum + value, 0) : NaN;
  }

  function validate(lesson, step, values) {
    if (lesson === 'settings') {
      if (step === 0) {
        return values.night ? { ok: true } : { ok: false, message: '先打开夜间模式，再检查。' };
      }
      if (step === 1) {
        if (!values.night) return { ok: false, message: '调亮度时请先保持夜间模式开启。' };
        const value = Number(values.brightness);
        return value >= 40 && value <= 60
          ? { ok: true }
          : { ok: false, message: '亮度需要在 40%–60% 之间。' };
      }
      if (step === 2) {
        return values.night
          ? { ok: false, message: '这一步要撤销：请关闭夜间模式。' }
          : { ok: true };
      }
      if (values.night) return { ok: false, message: '最后一步还需要撤销：请关闭夜间模式。' };
      const finalBrightness = Number(values.brightness);
      return finalBrightness >= 40 && finalBrightness <= 60
        ? { ok: true }
        : { ok: false, message: '独立复做时，亮度也要保持在 40%–60%。' };
    }
    if (lesson === 'excel') {
      const formula = normalizeFormula(values.formula);
      if (formula !== '=SUM(B1:B3)') {
        return { ok: false, message: '公式需要使用 =SUM(B1:B3)。' };
      }
      const result = computeResult(values);
      if (!Number.isFinite(result)) return { ok: false, message: '三个单元格都需要填入数字。' };
      if (step === 1 && Number(values.cells.B2) !== 40) {
        return { ok: false, message: '这一步请把 B2 改为 40。' };
      }
      if (step >= 2 && Number(values.cells.B2) !== 30) {
        return { ok: false, message: '这一步请把 B2 恢复为 30。' };
      }
      const expected = step === 1 ? 100 : 90;
      return result === expected
        ? { ok: true }
        : { ok: false, message: `当前结果应为 ${expected}，请检查数据和公式。` };
    }
    if (String(values.goal || '').trim().length < 12) {
      return { ok: false, message: '任务目标至少写 12 个字，并包含要完成的结果。' };
    }
    if (step >= 1 && !values.confirm) {
      return { ok: false, message: '请打开“执行前先让我确认”。' };
    }
    if (step >= 2 && String(values.criteria || '').trim().length < 12) {
      return { ok: false, message: '验收标准至少写 12 个字，说明什么结果才算完成。' };
    }
    return { ok: true };
  }

  function setFeedback(type, text) {
    feedback = { type, text };
    const node = $('coach-feedback');
    if (!node) return;
    node.textContent = text;
    node.classList.toggle('is-error', type === 'error');
    node.classList.toggle('is-success', type === 'success');
  }

  function markMistake(message) {
    if (state.errorRecorded) return;
    state.errorRecorded = true;
    state.mistakes.push({ step: state.step, message, time: new Date().toISOString() });
    record('mistake', message);
  }

  function check() {
    if (state.passed || state.completed) return;
    state.attempts += 1;
    const result = validate(lessonId, state.step, state.values);
    if (!result.ok) {
      markMistake(result.message);
      record('check', `第 ${state.step + 1} 步未通过`);
      setFeedback('error', result.message);
      render();
      return;
    }
    state.passed = true;
    state.errorRecorded = false;
    record('pass', `第 ${state.step + 1} 步通过`);
    if (state.step === 3) {
      state.completed = true;
      record('complete', state.hintSteps.includes(3) ? '跟随完成' : '独立完成');
    }
    setFeedback('success', state.step === 3 ? '复做通过，复盘已生成。' : '通过，可以继续。');
    render();
  }

  function next() {
    if (!state.passed || state.completed || state.step >= 3) return;
    state.step += 1;
    state.passed = false;
    state.errorRecorded = false;
    setFeedback('', '');
    persist();
    render();
    $('coach-title')?.focus({ preventScroll: true });
  }

  function reset() {
    state = freshState();
    setFeedback('', '');
    persist();
    render();
  }

  function renderSurface() {
    const surface = $('coach-surface');
    if (!surface) return;
    if (lessonId === 'settings') {
      surface.innerHTML = `
        <div class="coach-switch-row">
          <input id="coach-night" type="checkbox" aria-label="夜间模式">
          <label for="coach-night">夜间模式</label>
        </div>
        <div class="coach-field">
          <label for="coach-brightness">亮度 <output id="coach-brightness-value">${state.values.brightness}%</output></label>
          <input id="coach-brightness" type="range" min="0" max="100" step="1" value="${state.values.brightness}" aria-label="亮度">
        </div>
        ${state.step === 3 ? '<div class="coach-independent-note">独立完成后再查看复盘。提示仍可使用，但会记为跟随完成。</div>' : ''}`;
      $('coach-night').checked = Boolean(state.values.night);
      $('coach-night').addEventListener('change', (event) => {
        state.values.night = event.target.checked;
        onInput();
      });
      $('coach-brightness').addEventListener('input', (event) => {
        state.values.brightness = Number(event.target.value);
        $('coach-brightness-value').textContent = `${event.target.value}%`;
        onInput();
      });
      return;
    }
    if (lessonId === 'excel') {
      const cells = ['B1', 'B2', 'B3'].map((key) => `<td><input id="coach-${key}" type="number" value="${state.values.cells[key]}" aria-label="${key} 数值"></td>`).join('');
      surface.innerHTML = `
        <table class="coach-table"><thead><tr><th>单元格</th><th>B1</th><th>B2</th><th>B3</th></tr></thead><tbody><tr><th>数值</th>${cells}</tr></tbody></table>
        <div class="coach-field"><label for="coach-formula">公式</label><input id="coach-formula" class="coach-formula" type="text" value="${escapeHtml(state.values.formula)}" placeholder="=SUM(B1:B3)" aria-label="求和公式"></div>
        <div class="coach-result"><small>当前计算结果</small><span id="coach-result"></span></div>
        ${state.step === 3 ? '<div class="coach-independent-note">公式已准备好重新填写。独立完成后再查看复盘。</div>' : ''}`;
      ['B1', 'B2', 'B3'].forEach((key) => {
        $(`coach-${key}`).addEventListener('input', (event) => {
          state.values.cells[key] = event.target.value === '' ? '' : Number(event.target.value);
          updateResult();
          onInput();
        });
      });
      $('coach-formula').addEventListener('input', (event) => {
        state.values.formula = event.target.value;
        updateResult();
        onInput();
      });
      updateResult();
      return;
    }
    surface.innerHTML = `
      <div class="coach-field"><label for="coach-goal">任务目标</label><textarea id="coach-goal" data-le-polish-kind="goal" placeholder="例如：整理本周销售表并生成汇总报告">${escapeHtml(state.values.goal)}</textarea></div>
      <div class="coach-switch-row"><input id="coach-confirm" type="checkbox" aria-label="执行前先让我确认"><label for="coach-confirm">执行前先让我确认</label></div>
      <div class="coach-field"><label for="coach-criteria">验收标准</label><textarea id="coach-criteria" data-le-polish-kind="instruction" placeholder="例如：字段完整、金额计算正确，我检查后才允许执行">${escapeHtml(state.values.criteria)}</textarea></div>
      ${state.step === 3 ? '<div class="coach-independent-note">目标、边界和验收缺一不可。独立完成后再查看复盘。</div>' : ''}`;
    $('coach-goal').addEventListener('input', (event) => {
      state.values.goal = event.target.value;
      onInput();
    });
    $('coach-confirm').checked = Boolean(state.values.confirm);
    $('coach-confirm').addEventListener('change', (event) => {
      state.values.confirm = event.target.checked;
      onInput();
    });
    $('coach-criteria').addEventListener('input', (event) => {
      state.values.criteria = event.target.value;
      onInput();
    });
  }

  function updateResult() {
    const node = $('coach-result');
    if (!node) return;
    const formula = normalizeFormula(state.values.formula);
    const result = computeResult(state.values);
    node.textContent = formula === '=SUM(B1:B3)' && Number.isFinite(result) ? result : '—';
  }

  function onInput() {
    const result = validate(lessonId, state.step, state.values);
    if (state.passed || state.completed) {
      state.passed = false;
      state.completed = false;
      $('coach-check').disabled = false;
      $('coach-next').hidden = true;
      $('coach-summary').hidden = true;
      setFeedback('', '内容已修改，请重新检查。');
    }
    if (!result.ok && lessonId === 'settings') {
      markMistake(result.message);
      setFeedback('error', result.message);
    } else if (result.ok && feedback.type === 'error') {
      setFeedback('', '');
    }
    const label = $('coach-stage-label');
    label.textContent = feedback.type === 'error' ? '需要修正' : '等待操作';
    label.classList.toggle('is-error', feedback.type === 'error');
    label.classList.remove('is-success');
    persist();
  }

  function renderSummary() {
    const independent = !state.hintSteps.includes(3);
    $('coach-summary-result').textContent = independent ? '独立完成' : '跟随完成';
    const minutes = Math.max(1, Math.round((Date.now() - state.startedAt) / 60000));
    $('coach-summary-stats').innerHTML = `<span>检查 ${state.attempts} 次</span><span>提示 ${state.hints} 次</span><span>错误 ${state.mistakes.length} 次</span><span>用时 ${minutes} 分钟</span>`;
    $('coach-summary-mistakes').innerHTML = state.mistakes.length
      ? `<strong>需要再看一眼</strong><ul>${state.mistakes.slice(-5).map((item) => `<li>第 ${item.step + 1} 步：${escapeHtml(item.message)}</li>`).join('')}</ul>`
      : '<strong>本次没有错误记录</strong>';
  }

  function render() {
    const step = LESSONS[lessonId].steps[state.step];
    $('coach-count').textContent = `第 ${state.step + 1} / 4 步 · ${LESSONS[lessonId].name}`;
    $('coach-progress').value = state.completed ? 4 : state.step + (state.passed ? 1 : 0);
    $('coach-title').textContent = step.title;
    $('coach-body').textContent = step.body;
    $('coach-hint').textContent = step.hint;
    $('coach-hint-wrap').open = false;
    $('coach-check').disabled = state.passed || state.completed;
    $('coach-next').hidden = !state.passed || state.completed;
    $('coach-next').textContent = state.step === 2 ? '进入独立复做 →' : '下一步 →';
    $('coach-stage-label').textContent = state.completed ? '已完成' : state.passed ? '检查通过' : feedback.type === 'error' ? '需要修正' : '等待操作';
    $('coach-stage-label').classList.toggle('is-error', feedback.type === 'error');
    $('coach-stage-label').classList.toggle('is-success', state.passed || state.completed);
    $('coach-stage-state').textContent = state.completed ? '已完成' : state.passed ? '通过' : '由你操作';
    $('coach-summary').hidden = !state.completed;
    if (state.completed) renderSummary();
    renderSurface();
  }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  }

  function downloadReview() {
    const independent = !state.hintSteps.includes(3);
    const lines = [
      `# ${LESSONS[lessonId].name} · 动手学复盘`,
      '',
      `- 结果：${independent ? '独立完成' : '跟随完成'}`,
      `- 检查次数：${state.attempts}`,
      `- 提示次数：${state.hints}`,
      `- 错误次数：${state.mistakes.length}`,
      `- 开始时间：${new Date(state.startedAt).toLocaleString('zh-CN')}`,
      '',
      '## 操作记录',
      ...state.journal.map((entry) => `- 第 ${entry.step + 1} 步 · ${entry.type} · ${entry.message}`,
      ),
      '',
      '本复盘由本地练习生成，不代表真实 Windows、Excel 或 Agent 已接入。',
    ];
    const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${lessonId}-复盘.md`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function bind() {
    document.querySelectorAll('[data-coach-course]').forEach((button) => {
      button.setAttribute('aria-pressed', String(button.dataset.coachCourse === lessonId));
      if (button.dataset.coachBound === '1') return;
      button.dataset.coachBound = '1';
      button.addEventListener('click', () => {
        if (button.dataset.coachCourse === 'desktop') {
          document.getElementById('le-desktop-mode')?.click();
          return;
        }
        lessonId = button.dataset.coachCourse;
        state = store.sessions[lessonId] || freshState();
        setFeedback('', '');
        persist();
        bind();
        render();
        $('coach-title')?.focus({ preventScroll: true });
      });
    });
    if (staticBound) return;
    staticBound = true;
    $('coach-check')?.addEventListener('click', check);
    $('coach-next')?.addEventListener('click', next);
    $('coach-restart')?.addEventListener('click', reset);
    $('coach-redo')?.addEventListener('click', reset);
    $('coach-download')?.addEventListener('click', downloadReview);
    $('coach-hint-wrap')?.addEventListener('toggle', (event) => {
      if (!event.target.open || state.hintSteps.includes(state.step)) return;
      state.hintSteps.push(state.step);
      state.hints += 1;
      record('hint', `查看第 ${state.step + 1} 步提示`);
    });
  }

  function boot() {
    if (!$('le-coach') || !$('coach-surface') || !$('coach-check') || !$('coach-next')) return;
    bind();
    render();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }

  const mountTimer = setInterval(() => {
    if ($('le-coach') && !$('coach-surface')?.hasChildNodes()) {
      clearInterval(mountTimer);
      boot();
    }
  }, 250);
  setTimeout(() => clearInterval(mountTimer), 20000);
})();
