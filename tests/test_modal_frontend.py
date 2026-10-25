import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def test_modal_script_is_loaded_once_after_workbench():
    source = (ROOT / "custom_app.py").read_text(encoding="utf-8")

    assert source.count("assets/modal.js") == 1
    assert source.index("assets/workbench.js") < source.index("assets/modal.js")
    assert source.index("assets/modal.js") < source.index("assets/assistant.js")


@pytest.mark.skipif(NODE is None, reason="Node.js is required for frontend behavior tests")
def test_modal_focus_trap_escape_and_background_lifecycle():
    source = (ROOT / "learning_ext" / "assets" / "modal.js").read_text(encoding="utf-8")
    source = source.replace("\n})();", "\n  globalThis.__modalTest = { sync };\n})();", 1)
    prelude = r"""
const results = {};
const keydown = [];
function makeElement(id, focusItems = []) {
  return {
    id,
    focusItems,
    attrs: {},
    inert: false,
    isConnected: true,
    _visible: false,
    getClientRects() { return this._visible ? [1] : []; },
    setAttribute(name, value) { this.attrs[name] = value; },
    querySelectorAll() { return this.focusItems; },
    closest() { return null; },
    focus() { document.activeElement = this; },
    contains(element) {
      if (element === this) return true;
      return this.focusItems.includes(element);
    },
  };
}
const overlay = makeElement('le-adapt-overlay');
const modal = makeElement('le-adapt-modal');
const background = makeElement('background');
const brand = makeElement('brand');
const nav = makeElement('nav');
const openButton = makeElement('le-adapt-open');
const closeButton = makeElement('le-adapt-close');
const secondButton = makeElement('second');
closeButton._visible = true;
secondButton._visible = true;
let closeClicks = 0;
closeButton.click = () => { closeClicks += 1; overlay._visible = false; };
modal.focusItems = [closeButton, secondButton];
overlay.focusItems = [closeButton, secondButton];
overlay.parentElement = { children: [overlay, background] };
const ids = {
  'le-adapt-overlay': overlay,
  'le-adapt-modal': modal,
  'le-adapt-close': closeButton,
  'le-adapt-intro': makeElement('le-adapt-intro'),
  'le-adapt-open': openButton,
};
const document = {
  readyState: 'complete',
  documentElement: {},
  activeElement: openButton,
  getElementById(id) { return ids[id] || null; },
  querySelector(selector) {
    if (selector === '#le-brand-bar') return brand;
    if (selector === '#le-app-tabs > .tab-nav') return nav;
    return null;
  },
  addEventListener(type, callback) { if (type === 'keydown') keydown.push(callback); },
};
function getComputedStyle() { return { visibility: 'visible' }; }
function requestAnimationFrame(callback) { callback(); }
class MutationObserver {
  constructor(callback) { this.callback = callback; }
  observe() {}
}
let api;
"""
    scenario = r"""
api = globalThis.__modalTest;
overlay._visible = true;
api.sync();
results.open = {
  role: modal.attrs.role,
  modal: modal.attrs['aria-modal'],
  labelledby: modal.attrs['aria-labelledby'],
  focus: document.activeElement.id,
  backgroundInert: background.inert,
  brandInert: brand.inert,
};
document.activeElement = secondButton;
keydown[0]({ key: 'Tab', preventDefault() {}, stopPropagation() {} });
results.tabForward = document.activeElement.id;
document.activeElement = closeButton;
keydown[0]({ key: 'Tab', shiftKey: true, preventDefault() {}, stopPropagation() {} });
results.tabBackward = document.activeElement.id;
keydown[0]({ key: 'Escape', preventDefault() {}, stopPropagation() {} });
api.sync();
results.closed = {
  closeClicks,
  backgroundInert: background.inert,
  brandInert: brand.inert,
  focus: document.activeElement.id,
};
console.log(JSON.stringify(results));
"""
    completed = subprocess.run(
        [NODE, "-"],
        input=prelude + source + scenario,
        text=True,
        encoding="utf-8",
        capture_output=True,
        cwd=ROOT,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["open"] == {
        "role": "dialog",
        "modal": "true",
        "labelledby": "le-adapt-intro",
        "focus": "le-adapt-close",
        "backgroundInert": True,
        "brandInert": True,
    }
    assert result["tabForward"] == "le-adapt-close"
    assert result["tabBackward"] == "second"
    assert result["closed"] == {
        "closeClicks": 1,
        "backgroundInert": False,
        "brandInert": False,
        "focus": "le-adapt-open",
    }
