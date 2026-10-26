import base64
import html
import json
from pathlib import Path
import re
import subprocess

import pytest

from test_ui_navigation_frontend import BROWSER


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "learning_ext" / "assets"


def _token(selection):
    return "saved-connection:" + base64.urlsafe_b64encode(json.dumps(selection).encode()).decode()


def test_thinking_script_loads_right_after_settings_panels():
    custom = (ROOT / "custom_app.py").read_text(encoding="utf-8")
    assert custom.index("learning_ext/assets/settings_panels.js") < custom.index("learning_ext/assets/chat_thinking.js")
    assert (ASSETS / "chat_thinking.js").is_file()
    assert (ASSETS / "chat_thinking.css").is_file()


def test_thinking_styles_join_the_stylesheet_after_every_page_layer():
    source = (ROOT / "learning_ext" / "presentation.py").read_text(encoding="utf-8")
    function = source.split("def presentation_css():", 1)[1].split("BRAND =", 1)[0]
    layers = re.findall(r'"([a-z_]+)"', re.findall(r"for workspace_layer in \(([^)]+)\)", function)[0])

    assert "chat_thinking" in layers
    assert layers.index("chat_thinking") > layers.index("chat_references")
    assert function.index("for page_layer in") < function.index("for workspace_layer in")
    assert "chat_thinking" not in re.findall(r'ASSETS / "([a-z_-]+\.css)"', function)


def test_thinking_styles_use_theme_tokens_only():
    css = (ASSETS / "chat_thinking.css").read_text(encoding="utf-8")

    assert "#le-chat-connection-controls" in css
    assert ".le-thinking" in css
    assert "[aria-checked=true]" in css
    assert ":focus-visible" in css
    assert "border-top: 1px solid var(--le-line)" in css
    assert "@media (max-width: 420px)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "var(--le-" in css
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css)
    assert not re.search(r"\b(?:rgba?|hsla?)\(", css)
    colors_only = re.sub(r"white-space\s*:[^;]+;", "", css)
    assert not re.search(r"\b(?:white|black|red|green|blue|orange|purple|gray|grey)\b", colors_only)
    for token in re.findall(r"var\((--[a-z0-9-]+)", css):
        assert token.startswith("--le-"), token


def test_thinking_script_encodes_preferences_inside_the_saved_model_token():
    js = (ASSETS / "chat_thinking.js").read_text(encoding="utf-8")

    assert "le.chat.thinking.v1" in js
    assert "saved-connection:" in js
    assert "le-chat-model-token" in js
    assert "le-chat-default-model" in js
    assert "TextEncoder" in js and "TextDecoder" in js
    assert "getOwnPropertyDescriptor" in js
    assert "new Event('input'" in js and "new Event('change'" in js
    assert "new Event('blur')" in js
    assert "kimi-k3.1" in js and "glm-5.3" in js
    assert "(default)" in js
    assert "aria-checked" in js
    assert 'role="switch"' in js
    assert "show_thinking" in js and "effort" in js
    assert "reasoning_effort" not in js
    assert "api_key" not in js and "http" not in js


def test_served_stylesheet_carries_thinking_rules_after_the_page_layers():
    import ast

    source = ast.parse((ROOT / "custom_app.py").read_text(encoding="utf-8"))
    function = next(node for node in source.body
                    if isinstance(node, ast.FunctionDef) and node.name == "_presentation_stylesheet")
    namespace = {"Path": Path, "_HERE": str(ROOT)}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "custom_app.py", "exec"), namespace)
    css = namespace["_presentation_stylesheet"]()

    assistant_marker = "#le-assistant-fab[aria-controls][aria-expanded]:not(.le-fab-docked)"
    assert ".le-thinking-switch" in css
    assert ".le-thinking-seg" in css
    assert css.index(assistant_marker) < css.index(".le-thinking-switch")


def test_reasoning_details_stay_flat_and_token_based():
    css = (ASSETS / "chat_thinking.css").read_text(encoding="utf-8")

    assert "#main-chat-bot .prose details.le-reasoning" in css
    assert "> summary" in css and "> blockquote" in css
    assert "border-left: 2px solid var(--le-line-strong)" in css
    assert "white-space: pre-wrap" in css
    assert "summary::before" in css
    assert "summary::-webkit-details-marker" in css
    details = css.split("details.le-reasoning {", 1)[1].split("}", 1)[0]
    assert "background: transparent !important" in details
    assert "border: 0 !important" in details
    assert "box-shadow: none !important" in details


def test_reasoning_toggle_state_is_keyed_by_row_and_question():
    js = (ASSETS / "chat_thinking.js").read_text(encoding="utf-8")

    assert "main-chat-bot" in js
    assert "details.le-reasoning" in js
    assert "addEventListener('toggle'" in js
    assert "MutationObserver" in js
    assert "previousElementSibling" in js
    assert "user-row" in js
    assert "details.open = true" in js
    assert "requestAnimationFrame" in js


@pytest.mark.skipif(BROWSER is None, reason="Chromium is required for the thinking menu test")
def test_thinking_menu_follows_the_model_and_keeps_preferences_per_model(tmp_path):
    js = (ASSETS / "chat_thinking.js").read_text(encoding="utf-8")
    css = "\n".join((ASSETS / name).read_text(encoding="utf-8")
                    for name in ("theme_tokens.css", "chat_thinking.css"))
    panels = (ASSETS / "settings_panels.js").read_text(encoding="utf-8")
    legacy = _token(["rec-1", "moonshotai/Kimi-K3.1"])
    glm = _token(["rec-2", "ZhipuAI/GLM-5.3-Air"])
    spaced = _token(["rec-1", "moonshotai/Kimi-K3.1", {"effort": "max", "show_thinking": True}])
    scenarios = """
(async () => {
  const checks = [];
  const check = (ok, name) => { if (!ok) throw Error(name); checks.push(name); };
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  const until = async (fn, name) => {
    for (let i = 0; i < 140; i += 1) { if (fn()) return; await wait(30); }
    throw Error(name || 'condition not met');
  };
  const root = () => document.getElementById('le-chat-connection-controls');
  const section = () => document.getElementById('le-chat-thinking');
  const field = () => document.querySelector('#le-chat-model-token input');
  const model = () => root().querySelector('input[aria-label="回答模型"]');
  const radios = () => Array.from(section().querySelectorAll('[role=radio]'));
  const display = () => section().querySelector('[role=switch]');
  const decode = () => {
    const raw = field().value.replace(/^saved-connection:/, '').replace(/-/g, '+').replace(/_/g, '/');
    const binary = atob(raw + '='.repeat((4 - raw.length % 4) % 4));
    return JSON.parse(new TextDecoder().decode(Uint8Array.from(binary, character => character.charCodeAt(0))));
  };
  const store = () => JSON.parse(localStorage.getItem('le.chat.thinking.v1') || '{}');
  const prefs = () => decode()[2] || {};
  const setInput = (node, value) => {
    node.value = value;
    node.dispatchEvent(new Event('input', {bubbles: true}));
    node.dispatchEvent(new Event('change', {bubbles: true}));
  };
  let writes = 0, documentClicks = 0, documentKeys = 0;
  try {
    await until(() => section(), 'thinking controls installed');
    check(decode().length === 3, 'legacy two-item token gains preferences');
    check(decode()[0] === 'rec-1' && decode()[1] === 'moonshotai/Kimi-K3.1', 'saved record and model are preserved');
    check(prefs().effort === 'low' && prefs().show_thinking === false, 'defaults are low and hidden');
    check(Object.keys(prefs()).sort().join(',') === 'effort,show_thinking', 'token carries only effort and display flag');
    check(section().parentElement === root() && root().lastElementChild === section(), 'compact settings sit at the end of the model menu');
    check(!section().hidden, 'thinking models expose the controls');
    check(radios().map(item => item.textContent).join('|') === 'Low|High|Max', 'three effort segments in order');
    check(radios()[0].getAttribute('aria-checked') === 'true' && radios()[1].getAttribute('aria-checked') === 'false', 'low is checked by default');
    check(radios()[0].tabIndex === 0 && radios()[1].tabIndex === -1 && radios()[2].tabIndex === -1, 'radio group has one tab stop');
    check(section().querySelector('[role=radiogroup]').getAttribute('aria-labelledby') === 'le-chat-thinking-effort-label', 'radio group is labelled');
    check(display().getAttribute('aria-checked') === 'false', 'thinking display starts switched off');
    check(display().getAttribute('aria-labelledby') === 'le-chat-thinking-display-label', 'switch is labelled');

    await until(() => document.getElementById('le-chat-model-trigger'), 'model trigger');
    document.getElementById('le-chat-model-trigger').click();
    await until(() => document.querySelector('.le-settings-deck[open]'), 'menu opens');
    check(root().closest('.le-settings-deck') !== null && section().parentElement === root(), 'settings travel with the menu dialog');
    check(!section().hidden && root().contains(section()), 'controls stay inside the open menu');

    field().value = LEGACY_TOKEN;
    await until(() => decode().length === 3);
    check(prefs().effort === 'low' && decode()[0] === 'rec-1', 'menu re-merges preferences when the model token is rewritten');

    field().addEventListener('input', () => { writes += 1; });
    let committed = '', blurs = 0;
    field().addEventListener('blur', () => { blurs += 1; committed = field().value; });
    document.addEventListener('click', () => { documentClicks += 1; });
    document.addEventListener('keydown', () => { documentKeys += 1; });

    radios()[1].click();
    await until(() => prefs().effort === 'high');
    check(writes === 1, 'one write per effort change');
    check(blurs === 1 && committed === field().value, 'gradio commits the merged token on blur');
    check(store()['kimi-k3.1'].effort === 'high', 'effort persists per model');
    check(document.querySelector('.le-settings-deck[open]') !== null, 'choosing an effort keeps the menu open');
    check(documentClicks === 0, 'controls do not bubble clicks out of the menu');

    display().click();
    await until(() => prefs().show_thinking === true);
    check(writes === 2, 'one write per display toggle');
    check(store()['kimi-k3.1'].show_thinking === true, 'display choice persists per model');
    check(display().getAttribute('aria-checked') === 'true', 'switch reflects the stored state');

    radios()[0].focus();
    radios()[0].dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowLeft', bubbles: true, cancelable: true}));
    await until(() => prefs().effort === 'max');
    check(writes === 3, 'keyboard navigation writes once');
    check(radios()[2].getAttribute('aria-checked') === 'true' && document.activeElement === radios()[2], 'arrow keys wrap and move focus');
    check(documentKeys === 0, 'radio keys do not escape the menu');

    const beforeStable = writes;
    field().value = SPACED_TOKEN;
    await wait(1000);
    check(writes === beforeStable, 'server formatting of the same preferences is not rewritten');

    const stable = field().value;
    setInput(model(), 'qwen3-max');
    await until(() => section().hidden);
    await wait(400);
    check(field().value === stable, 'other models get no effort token');
    check(!('qwen3-max' in store()), 'other models store no capability');

    setInput(model(), 'moonshotai/Kimi-K3.1');
    await until(() => !section().hidden);
    await wait(400);
    check(radios()[2].getAttribute('aria-checked') === 'true' && display().getAttribute('aria-checked') === 'true', 'switching back restores this model preferences');
    check(writes === 3, 'switching models does not rewrite unchanged preferences');

    field().value = GLM_TOKEN;
    setInput(model(), 'ZhipuAI/GLM-5.3-Air');
    await until(() => decode()[1] === 'ZhipuAI/GLM-5.3-Air' && decode().length === 3);
    check(prefs().effort === 'low' && prefs().show_thinking === false, 'each thinking model starts from its own defaults');
    check(writes === 4, 'namespaced model merges its own preferences once');

    radios()[1].click();
    await until(() => prefs().effort === 'high');
    check(writes === 5, 'namespaced model saves its own preference once');
    check(store()['glm-5.3-air'].effort === 'high', 'namespace is stripped for the preference key');
    check(store()['kimi-k3.1'].effort === 'max', 'another model keeps its own preference');

    field().value = '';
    setInput(model(), '(default)');
    document.getElementById('le-chat-default-model').textContent = 'Kimi K3.1';
    await until(() => {
      try { const token = decode(); return token.length === 3 && token[0] === '' && token[1] === ''; }
      catch (error) { return false; }
    });
    check(prefs().effort === 'max' && prefs().show_thinking === true, 'default connection reuses the remembered Kimi preferences');
    check(writes === 6, 'default connection writes one preference token');
    check(document.querySelector('.le-settings-deck[open]') !== null, 'menu stays open through connection changes');
    check(blurs === writes && committed === field().value, 'every preference write is committed for the next answer');

    const raw = localStorage.getItem('le.chat.thinking.v1');
    check(!/https?:|api[_-]?key|secret|bearer|sk-/i.test(raw), 'stored preferences contain no credentials or urls');

    document.getElementById('results').textContent = JSON.stringify({checks, token: field().value});
  } catch (error) {
    document.getElementById('results').textContent = JSON.stringify({error: String(error && error.stack || error), checks});
  }
})();
""".replace("GLM_TOKEN", json.dumps(glm)).replace("LEGACY_TOKEN", json.dumps(legacy)).replace("SPACED_TOKEN", json.dumps(spaced))
    page = tmp_path / "chat-thinking.html"
    page.write_text(
        '<!doctype html><meta charset="utf-8"><style>'
        '[hidden]{display:none!important}dialog:not([open]){display:none}'
        '.le-panel-source:not(.le-panel-current){display:none}.le-settings-deck{position:fixed}'
        '.le-settings-entry{display:block}'
        + css + '</style><body><div class="gradio-container" id="le-app-tabs">'
        '<section id="chat-tab"><div id="le-chat-model-header">'
        '<div id="le-chat-connection-controls">'
        '<div class="stretch"><div class="row"><div class="wrap">'
        '<input aria-label="回答平台" value="Kimi">'
        '<input aria-label="回答模型" value="moonshotai/Kimi-K3.1">'
        '</div><button id="le-chat-model-refresh">刷新模型</button></div></div>'
        '<div id="le-chat-connection-status"></div>'
        '<div id="le-chat-default-model" hidden>Kimi K3.1</div></div></div>'
        f'<div id="le-chat-model-token" hidden><input aria-label="回答模型" value="{legacy}"></div>'
        '</section></div><pre id="results"></pre>'
        '<script>window.requestAnimationFrame=callback=>setTimeout(()=>callback(performance.now()),1);'
        'window.cancelAnimationFrame=clearTimeout;</script>'
        '<script>' + panels + '</script><script>' + js + '</script>'
        '<script>' + scenarios + '</script>',
        encoding="utf-8",
    )
    completed = subprocess.run(
        [BROWSER, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
         "--disable-background-networking", "--disable-extensions", "--disable-background-timer-throttling",
         "--window-size=1100,900", "--virtual-time-budget=9000", "--dump-dom",
         f"--user-data-dir={tmp_path / 'profile'}", page.as_uri()],
        cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace", timeout=40,
    )
    assert completed.returncode == 0, completed.stderr
    match = re.search(r'<pre id="results">(.*?)</pre>', completed.stdout, re.S)
    assert match, completed.stdout[-4000:] + completed.stderr[-1000:]
    result = json.loads(html.unescape(match.group(1)))
    assert not result.get("error"), result
    assert len(result["checks"]) >= 25, result
    selection = json.loads(base64.b64decode(
        result["token"].split("saved-connection:", 1)[1], altchars=b"-_", validate=True))
    assert selection == ["", "", {"effort": "max", "show_thinking": True}]


@pytest.mark.skipif(BROWSER is None, reason="Chromium is required for the reasoning block test")
def test_reasoning_open_state_survives_chatbot_rerenders(tmp_path):
    js = (ASSETS / "chat_thinking.js").read_text(encoding="utf-8")
    css = "\n".join((ASSETS / name).read_text(encoding="utf-8")
                    for name in ("theme_tokens.css", "chat_thinking.css"))
    scenarios = """
(async () => {
  const checks = [];
  const check = (ok, name) => { if (!ok) throw Error(name); checks.push(name); };
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  const until = async (fn, name) => {
    for (let i = 0; i < 180; i += 1) { if (fn()) return; await wait(25); }
    throw Error(name || 'condition not met');
  };
  const wrap = () => document.querySelector('#main-chat-bot .message-wrap');
  const REASON = '<details class="le-reasoning"><summary>思考过程</summary><blockquote>推理内容</blockquote></details>';
  const evidence = open => '<details class="evidence"' + (open ? ' open' : '') + '><summary>来源</summary><blockquote>证据</blockquote></details>';
  const userRow = text => {
    const row = document.createElement('div');
    row.className = 'message-row user-row';
    row.innerHTML = '<div class="flex-wrap user"><div class="message user"><p></p></div></div>';
    row.querySelector('p').textContent = text;
    return row;
  };
  const botRow = (answer, extra = '') => {
    const row = document.createElement('div');
    row.className = 'message-row bot-row';
    row.innerHTML = '<div class="flex-wrap bot"><div class="message bot"><div class="prose chatbot">'
      + REASON + extra + '<p>' + answer + '</p></div></div></div>';
    return row;
  };
  const rebuild = (row, answer = '更新后的回答') => {
    row.querySelector('.prose').innerHTML = REASON + '<p>' + answer + '</p>';
  };
  const reason = row => row.querySelector('details.le-reasoning');
  try {
    wrap().replaceChildren(userRow('第一个问题'), botRow('回答一'),
                           userRow('第二个问题'), botRow('回答二', evidence(true) + evidence(false)));
    await wait(120);
    let bots = Array.from(document.querySelectorAll('.bot-row'));
    check(bots.length === 2, 'two answers rendered');
    check(!reason(bots[0]).open && !reason(bots[1]).open, 'reasoning blocks start collapsed');

    reason(bots[0]).querySelector('summary').click();
    await until(() => reason(bots[0]).open, 'reasoning expands');
    await wait(60);

    const quote = reason(bots[0]).querySelector('blockquote');
    const quoteStyle = getComputedStyle(quote);
    check(quoteStyle.backgroundColor === 'rgba(0, 0, 0, 0)', 'reasoning has no card fill');
    check(quoteStyle.borderLeftWidth === '2px' && quoteStyle.borderLeftStyle === 'solid', 'reasoning keeps a hairline rule');
    check(quoteStyle.marginTop === '2px' && quoteStyle.marginBottom === '12px', 'generic prose margins do not win');
    check(getComputedStyle(reason(bots[0])).backgroundColor === 'rgba(0, 0, 0, 0)', 'details itself stays flat');
    check(parseFloat(getComputedStyle(reason(bots[0]).querySelector('summary')).fontSize) <= 13, 'summary stays a compact line');

    for (let round = 0; round < 3; round += 1) {
      rebuild(bots[0], '流式回答' + round);
      await wait(100);
      check(reason(bots[0]).open, 'manual expansion survives streaming rebuild ' + round);
    }
    check(bots[0].querySelector('.prose').textContent.includes('流式回答2'), 'streaming content still updates');
    check(!reason(bots[1]).open, 'untouched reasoning stays collapsed');
    const others = bots[1].querySelectorAll('details.evidence');
    check(others[0].open && !others[1].open, 'other details are not touched');

    reason(bots[0]).querySelector('summary').click();
    await until(() => !reason(bots[0]).open, 'reasoning collapses');
    await wait(60);
    rebuild(bots[0], '关闭后回答');
    await wait(100);
    check(!reason(bots[0]).open, 'manual collapse survives streaming rebuild');

    reason(bots[0]).querySelector('summary').click();
    await until(() => reason(bots[0]).open, 'reasoning reopens');
    await wait(60);
    wrap().append(userRow('第三个问题'), botRow('回答三'));
    await wait(120);
    bots = Array.from(document.querySelectorAll('.bot-row'));
    check(bots.length === 3, 'a new answer is appended');
    check(!reason(bots[2]).open, 'a new reasoning block defaults to collapsed');
    reason(bots[2]).querySelector('summary').click();
    await until(() => reason(bots[2]).open, 'new reasoning expands');
    await wait(60);
    rebuild(bots[2], '回答三更新');
    await wait(100);
    check(reason(bots[2]).open, 'the new row keeps its own expanded state');

    const questions = ['第一个问题', '第二个问题', '第三个问题'];
    const answers = ['回答一', '回答二', '回答三'];
    wrap().replaceChildren(...questions.flatMap((question, index) => [userRow(question), botRow(answers[index])]));
    await wait(160);
    bots = Array.from(document.querySelectorAll('.bot-row'));
    check(bots.length === 3, 'a full rerender keeps every answer');
    check(reason(bots[0]).open, 'an expanded row is restored after a full rerender');
    check(reason(bots[2]).open, 'each expanded row is restored independently');
    check(!reason(bots[1]).open, 'a collapsed row stays collapsed after a full rerender');

    const oldBot = document.getElementById('main-chat-bot');
    const fresh = oldBot.cloneNode(true);
    fresh.querySelectorAll('details').forEach(node => { node.open = false; });
    oldBot.replaceWith(fresh);
    await until(() => {
      const rows = Array.from(fresh.querySelectorAll('.bot-row'));
      return rows.length === 3 && rows[0].querySelector('details.le-reasoning').open;
    }, 'state is restored after the chat container is replaced');
    const freshBots = Array.from(fresh.querySelectorAll('.bot-row'));
    check(freshBots[2].querySelector('details.le-reasoning').open, 'rebinding restores every stored row');
    check(!freshBots[1].querySelector('details.le-reasoning').open, 'rebinding never opens a collapsed row');

    fresh.querySelectorAll('.user-row')[0].querySelector('.message.user').textContent = '完全换掉的问题';
    rebuild(freshBots[0], '重新回答');
    await wait(140);
    check(!freshBots[0].querySelector('details.le-reasoning').open, 'the key includes the paired user question');

    for (let round = 0; round < 3; round += 1) {
      rebuild(freshBots[2], '再次更新' + round);
      await wait(90);
      check(freshBots[2].querySelector('details.le-reasoning').open, 'expanded state stays stable across repeated rebuilds ' + round);
    }
    check(fresh.querySelectorAll('details.le-reasoning').length === 3, 'restore never duplicates reasoning nodes');
    check(Array.from(fresh.querySelectorAll('details.le-reasoning > summary'))
      .every(summary => summary.textContent.trim() === '思考过程'), 'summaries keep only the backend copy');

    document.getElementById('results').textContent = JSON.stringify({checks});
  } catch (error) {
    document.getElementById('results').textContent = JSON.stringify({error: String(error && error.stack || error), checks});
  }
})();
"""
    page = tmp_path / "chat-reasoning.html"
    page.write_text(
        '<!doctype html><meta charset="utf-8"><style>'
        '[hidden]{display:none!important}'
        + css
        + '.prose blockquote { margin: 24px 0 !important; border-left: 5px solid rgb(0,128,0) !important; background: rgb(230,230,230) !important; }'
        '.prose details { margin: 18px 0 !important; border: 1px solid rgb(0,128,0) !important; background: rgb(230,230,230) !important; }'
        '.message .prose :is(p, li, blockquote) { color: rgb(0,100,0) !important; font-size: 20px !important; }'
        '</style><body><div class="gradio-container" id="le-app-tabs"><section id="chat-tab">'
        '<div id="main-chat-bot"><div class="bubble-wrap"><div class="message-wrap"></div></div></div>'
        '</section></div><pre id="results"></pre>'
        '<script>window.requestAnimationFrame=callback=>setTimeout(()=>callback(performance.now()),1);'
        'window.cancelAnimationFrame=clearTimeout;</script>'
        '<script>' + js + '</script><script>' + scenarios + '</script>',
        encoding="utf-8",
    )
    completed = subprocess.run(
        [BROWSER, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
         "--disable-background-networking", "--disable-extensions", "--disable-background-timer-throttling",
         "--window-size=1100,900", "--virtual-time-budget=9000", "--dump-dom",
         f"--user-data-dir={tmp_path / 'profile'}", page.as_uri()],
        cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace", timeout=40,
    )
    assert completed.returncode == 0, completed.stderr
    match = re.search(r'<pre id="results">(.*?)</pre>', completed.stdout, re.S)
    assert match, completed.stdout[-4000:] + completed.stderr[-1000:]
    result = json.loads(html.unescape(match.group(1)))
    assert not result.get("error"), result
    assert len(result["checks"]) >= 20, result
