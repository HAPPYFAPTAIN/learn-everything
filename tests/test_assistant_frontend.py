import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "learning_ext" / "assets"
NODE = shutil.which("node")


def _css_rule(source, selector):
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", source)
    assert match, selector
    return match.group(1)


def test_mascot_is_not_reset_by_onboarding_background():
    assistant_css = (ASSETS / "assistant.css").read_text(encoding="utf-8")
    onboarding_css = (ASSETS / "onboarding.css").read_text(encoding="utf-8")
    fab_rule = _css_rule(assistant_css, "#le-assistant-fab")
    override_rule = _css_rule(onboarding_css, "#le-assistant-fab")

    assert 'url("__ASSETS__/coach-mascot.png")' in fab_rule
    assert "background-image" in fab_rule
    assert not re.search(r"(?:^|[;\n])\s*background\s*:", override_rule)
    assert re.search(r"background-color\s*:\s*#f7fbfe\s*!important", override_rule)
    assert (ASSETS / "coach-mascot.png").is_file()


def test_empty_state_has_three_non_submitting_prompts():
    source = (ROOT / "learning_ext" / "assistant.py").read_text(encoding="utf-8")
    empty_html = source.split("EMPTY_HTML = (", 1)[1].split("\n)\n\nSYSTEM_PROMPT", 1)[0]

    assert empty_html.count('type="button" data-le-assistant-suggestion>') == 3
    assert "data-le-assistant-context-label" in empty_html
    assert "data-le-assistant-context-title" in empty_html
    assert "data-le-assistant-context-detail" in empty_html
    assert source.index("self.empty_state =") < source.index("self.chatbot =")


@pytest.mark.skipif(NODE is None, reason="Node.js is required for frontend behavior tests")
def test_assistant_frontend_behavior():
    source = (ASSETS / "assistant.js").read_text(encoding="utf-8")
    export = (
        "\n  globalThis.__assistantTest = {"
        "ensureRect, syncEmptyState, fillAssistantInput, placeFab, "
        "syncFabVisibility, setOpen };\n"
    )
    instrumented = source.replace("\n})();", export + "})();", 1)
    assert instrumented != source

    prelude = r"""
const store = {};
const styleProps = {};
const results = {};
function makeClassList(initial = []) {
  const values = new Set(initial);
  return {
    add: (...names) => names.forEach((name) => values.add(name)),
    remove: (...names) => names.forEach((name) => values.delete(name)),
    contains: (name) => values.has(name),
    toggle(name, force) {
      const enabled = force === undefined ? !values.has(name) : Boolean(force);
      if (enabled) values.add(name); else values.delete(name);
      return enabled;
    },
  };
}
const body = {
  classList: makeClassList(),
  appendChild(node) { node.parentElement = body; },
};
const topbar = {
  appendChild(node) { node.parentElement = topbar; },
};
const fabAttributes = {};
const fabStyle = { removeProperty(name) { delete this[name]; } };
let fabFocusCount = 0;
const fab = {
  classList: makeClassList(),
  style: fabStyle,
  parentElement: body,
  offsetWidth: 58,
  offsetHeight: 58,
  setAttribute(name, value) { fabAttributes[name] = value; },
  focus() { fabFocusCount += 1; },
};
const fields = Object.fromEntries(
  ['label', 'title', 'detail'].map((name) => [name, { textContent: '' }])
);
const buttons = Array.from({ length: 3 }, () => ({
  hidden: false,
  textContent: '',
  dataset: {},
}));
const empty = {
  hidden: false,
  querySelector(selector) {
    const match = selector.match(/^\[data-le-assistant-context-(label|title|detail)\]$/);
    return match ? fields[match[1]] : null;
  },
  querySelectorAll() { return buttons; },
};
const chatAttributes = {};
const chat = {
  message: false,
  classList: makeClassList(),
  querySelector() { return this.message ? {} : null; },
  setAttribute(name, value) { chatAttributes[name] = value; },
};
const inputEvents = [];
let inputFocused = false;
let inputSelection = null;
const input = {
  value: '',
  dispatchEvent(event) { inputEvents.push(event.type); },
  focus() { inputFocused = true; },
  setSelectionRange(start, end) { inputSelection = [start, end]; },
};
let sendClickCount = 0;
const send = { click() { sendClickCount += 1; } };
const selectedTab = { id: 'learning-workbench-tab-button' };
const nodes = {
  '#le-center-content h3': { textContent: '[1.1] 向量' },
  '#le-course-picker input': { value: '1.1 向量' },
  '#le-project-picker input': { value: '机器学习' },
  '#le-review-card': { textContent: '什么是向量？' },
  '#le-review-stats': { textContent: '待复习 2 · 共 8 张卡' },
  '#le-quiz-question': { textContent: '01 / 05 向量点积的几何意义是什么？' },
};
const ids = {
  'le-assistant-fab': fab,
  'le-assistant-empty': empty,
  'le-assistant-chat': chat,
  'le-chat-send': send,
};
const document = {
  readyState: 'loading',
  documentElement: {
    style: { setProperty(name, value) { styleProps[name] = value; } },
  },
  body,
  addEventListener() {},
  getElementById(id) { return ids[id] || null; },
  querySelector(selector) {
    if (selector === '#le-app-tabs > .tab-nav > button.selected') return selectedTab;
    if (selector === '.le-topbar') return topbar;
    if (selector === '#le-global-assistant #le-chat-compose textarea') return input;
    return nodes[selector] || null;
  },
};
const window = {
  innerWidth: 320,
  innerHeight: 300,
  setTimeout(callback) { callback(); return 0; },
  addEventListener() {},
};
const localStorage = {
  getItem(key) { return Object.hasOwn(store, key) ? store[key] : null; },
  setItem(key, value) { store[key] = value; },
};
class Event {
  constructor(type, options = {}) {
    this.type = type;
    this.bubbles = Boolean(options.bubbles);
  }
}
"""

    scenario = r"""
const api = globalThis.__assistantTest;
const tinyRect = api.ensureRect();
results.tiny = { rect: tinyRect, props: { ...styleProps } };
api.syncEmptyState();
results.empty = {
  hidden: empty.hidden,
  chatHidden: chat.classList.contains('le-assistant-chat-empty'),
  title: fields.title.textContent,
  detail: fields.detail.textContent,
  prompts: buttons.map((button) => button.textContent),
};
chat.message = true;
api.syncEmptyState();
results.withMessages = {
  emptyHidden: empty.hidden,
  chatHidden: chat.classList.contains('le-assistant-chat-empty'),
};
chat.message = false;
selectedTab.id = 'learning-review-tab-button';
api.syncEmptyState();
results.review = {
  title: fields.title.textContent,
  detail: fields.detail.textContent,
  firstPrompt: buttons[0].textContent,
};
selectedTab.id = 'learning-quiz-tab-button';
api.syncEmptyState();
results.quiz = {
  title: fields.title.textContent,
  firstPrompt: buttons[0].textContent,
};
api.fillAssistantInput('  给我一点回忆提示  ');
results.filled = {
  value: input.value,
  events: inputEvents,
  focused: inputFocused,
  selection: inputSelection,
  sendClickCount,
};
window.innerWidth = 390;
window.innerHeight = 844;
fab.style.left = '15px';
api.placeFab();
results.mobile = {
  docked: fab.classList.contains('le-fab-docked'),
  parentTopbar: fab.parentElement === topbar,
  left: fab.style.left || null,
};
window.innerWidth = 1200;
window.innerHeight = 800;
store['le.assistant.fab'] = JSON.stringify({ x: 180, y: 220 });
api.placeFab();
results.desktop = {
  docked: fab.classList.contains('le-fab-docked'),
  parentBody: fab.parentElement === body,
  left: fab.style.left,
  top: fab.style.top,
};
body.classList.add('le-assistant-open');
api.setOpen(false, true);
results.closed = {
  open: body.classList.contains('le-assistant-open'),
  expanded: fabAttributes['aria-expanded'],
  focusCount: fabFocusCount,
};
selectedTab.id = 'learning-dashboard-tab-button';
body.classList.add('le-assistant-open');
api.syncFabVisibility();
results.generic = {
  off: fab.classList.contains('le-fab-off'),
  open: body.classList.contains('le-assistant-open'),
  docked: fab.classList.contains('le-fab-docked'),
  parentTopbar: fab.parentElement === topbar,
  title: fields.title.textContent,
  firstPrompt: buttons[0].textContent,
  focusCount: fabFocusCount,
};
console.log(JSON.stringify(results));
"""

    completed = subprocess.run(
        [NODE, "-"],
        input=prelude + instrumented + scenario,
        text=True,
        encoding="utf-8",
        capture_output=True,
        cwd=ROOT,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)

    assert result["tiny"]["rect"] == {"x": 12, "y": 12, "w": 296, "h": 276}
    assert result["tiny"]["props"]["--le-dlg-w"] == "296px"
    assert result["tiny"]["props"]["--le-dlg-h"] == "276px"
    assert result["empty"] == {
        "hidden": False,
        "chatHidden": True,
        "title": "[1.1] 向量",
        "detail": "学习项目：机器学习",
        "prompts": ["用简单的例子解释这一节", "这一节最需要记住什么？", "出一个问题检查我的理解"],
    }
    assert result["withMessages"] == {"emptyHidden": True, "chatHidden": False}
    assert result["review"] == {
        "title": "什么是向量？",
        "detail": "待复习 2 · 共 8 张卡",
        "firstPrompt": "给我一点回忆提示",
    }
    assert result["quiz"]["title"] == "01 / 05 向量点积的几何意义是什么？"
    assert result["quiz"]["firstPrompt"] == "给我一点解题提示"
    assert result["filled"] == {
        "value": "给我一点回忆提示",
        "events": ["input"],
        "focused": True,
        "selection": [8, 8],
        "sendClickCount": 0,
    }
    assert result["mobile"] == {"docked": True, "parentTopbar": True, "left": None}
    assert result["desktop"] == {
        "docked": False,
        "parentBody": True,
        "left": "180px",
        "top": "220px",
    }
    assert result["closed"] == {"open": False, "expanded": "false", "focusCount": 1}
    assert result["generic"] == {
        "off": False,
        "open": True,
        "docked": True,
        "parentTopbar": True,
        "title": "学习规划、理解与复习",
        "firstPrompt": "帮我拆解一个学习目标",
        "focusCount": 1,
    }
