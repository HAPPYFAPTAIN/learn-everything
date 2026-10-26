"""Exercise real global observers without a live app or model connection."""

import html
import json
from pathlib import Path
import re
import subprocess

import pytest

from test_ui_navigation_frontend import BROWSER


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "learning_ext/assets"
MODULES = ("text_polish.js", "settings_panels.js", "selects.js", "assistant.js")


SCENARIO = r"""
(async () => {
  const checks = [], samples = {};
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  const assert = (value, message) => { if (!value) throw Error(message); checks.push(message); };
  const count = window.observerCounts;
  const reset = () => Object.keys(count).forEach(key => count[key] = 0);
  const copy = () => ({...count});
  const active = (sample, name) => Object.values(sample).every(value => value > 0) ||
    (() => { throw Error(name + ': ' + JSON.stringify(sample)); })();
  try {
    await wait(100);
    reset();
    await wait(50);
    samples.idle = copy();
    assert(Object.values(count).every(value => value === 0), 'Observers settle while idle');
    const transcript = document.getElementById('le-coach-transcript');
    const transport = document.getElementById('le-coach-stream');
    const field = document.querySelector('#le-coach-composer textarea');
    for (let tick = 0; tick < 40; tick++) {
      if (tick % 2 === 0) transcript.innerHTML = '<p>Assistant response ' + tick + '</p>';
      else transcript.firstChild.firstChild.data += ' more tokens';
      transcript.firstChild.style.opacity = tick % 2 ? '1' : '.95';
      transport.textContent = JSON.stringify({sequence: tick, delta: 'hello'});
      await wait(5);
    }
    await wait(30);
    samples.streaming = copy();
    assert(Object.values(count).every(value => value === 0),
      '40 transcript/transport frames perform zero unrelated scans: ' + JSON.stringify(count));

    reset();
    transcript.remove();
    transport.remove();
    await wait(30);
    samples.removed = copy();
    assert(active(count, 'Root removal'), 'Root removal still refreshes all four modules');
    reset();
    document.getElementById('le-coach-root').prepend(transcript, transport);
    await wait(30);
    samples.mounted = copy();
    assert(active(count, 'Root mounting'), 'Root mounting still refreshes all four modules');

    reset();
    const newcomer = document.createElement('div');
    newcomer.className = 'le-polishable';
    newcomer.innerHTML = '<textarea>New task</textarea>';
    document.getElementById('le-coach-composer').append(newcomer);
    await wait(40);
    samples.composer = copy();
    assert(active(count, 'Composer mutation'), 'Composer changes still refresh all four modules');
    assert(!!newcomer.querySelector('.le-polish-button'), 'New composer field receives polish control');

    reset();
    field.disabled = true;
    await wait(30);
    samples.disabled = copy();
    assert(count.polish > 0, 'Composer disabled changes still refresh polish state');
    assert(document.querySelector('#le-coach-input .le-polish-button').disabled,
      'Disabled composer cannot start polishing');

    reset();
    transcript.innerHTML = '<p>Mixed streaming batch</p>';
    field.disabled = false;
    const menu = document.querySelector('ul.options');
    const option = document.createElement('li');
    option.setAttribute('role', 'option');
    option.setAttribute('aria-label', 'New platform');
    option.textContent = 'New platform';
    menu.append(option);
    await wait(40);
    samples.mixed = copy();
    assert(active(count, 'Mixed batch'), 'Mixed stream and external mutations keep real work');
    assert(option.title === 'New platform', 'New platform option is decorated');
    assert(!document.querySelector('#le-coach-input .le-polish-button').disabled,
      'Re-enabled composer can polish again');
    const report = document.createElement('pre'); report.id = 'results';
    report.textContent = JSON.stringify({checks, samples}); document.body.append(report);
  } catch (error) {
    const report = document.createElement('pre'); report.id = 'results';
    report.textContent = JSON.stringify({checks, samples, error: String(error), stack: error.stack});
    document.body.append(report);
  }
})();
"""


def _page_source(sources):
    return (
        '<!doctype html><meta charset="utf-8"><body>'
        '<div class="le-topbar"></div><div id="le-app-tabs">'
        '<nav class="tab-nav"><button id="learning-coach-tab-button" class="selected">Coach</button></nav>'
        '<section id="le-coach-root"><div id="le-coach-transcript"><p>Initial response</p></div>'
        '<div id="le-coach-stream" hidden></div><div id="le-coach-composer">'
        '<div id="le-coach-input" class="le-polishable"><textarea>Check my environment</textarea></div>'
        '<button id="le-coach-send">Send</button></div></section>'
        '<div class="wrap"><input role="listbox"><ul class="options" role="listbox">'
        '<li role="option" aria-label="Existing platform">Existing platform</li></ul></div></div>'
        '<script>window.requestAnimationFrame=callback=>setTimeout(()=>callback(performance.now()),1);'
        'window.cancelAnimationFrame=clearTimeout;'
        'window.observerCounts={polish:0,settings:0,selects:0,assistant:0};'
        'const nativeAll=Document.prototype.querySelectorAll;'
        'Document.prototype.querySelectorAll=function(selector){'
        'if(selector.includes(".le-polishable"))observerCounts.polish++;'
        'if(selector==="#le-route-picker label > span")observerCounts.settings++;'
        'if(selector===\'ul.options[role="listbox"]\')observerCounts.selects++;'
        'return nativeAll.call(this,selector);};'
        'const nativeId=Document.prototype.getElementById;'
        'Document.prototype.getElementById=function(id){'
        'if(id==="le-assistant-fab")observerCounts.assistant++;return nativeId.call(this,id);};'
        '</script>'
        + ''.join('<script>' + source + '</script>' for source in sources)
        + '<script>' + SCENARIO + '</script>'
    )


def _run_probe(tmp_path, sources):
    page = tmp_path / "coach-observers.html"
    page.write_text(_page_source(sources), encoding="utf-8")
    completed = subprocess.run(
        [BROWSER, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
         "--disable-background-networking", "--disable-extensions", "--disable-background-timer-throttling",
         "--window-size=1200,900", "--virtual-time-budget=4000", "--dump-dom",
         f"--user-data-dir={tmp_path / 'profile'}", page.as_uri()],
        cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace", timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    match = re.search(r'<pre id="results">(.*?)</pre>', completed.stdout, re.S)
    assert match, completed.stdout[-5000:] + completed.stderr[-1000:]
    return json.loads(html.unescape(match.group(1)))


@pytest.mark.skipif(BROWSER is None, reason="Chromium is required for observer integration tests")
def test_coach_stream_does_not_rescan_unrelated_ui(tmp_path):
    result = _run_probe(tmp_path, [(ASSETS / name).read_text(encoding="utf-8") for name in MODULES])
    assert not result.get("error"), json.dumps(result, ensure_ascii=False, indent=2)
    assert len(result["checks"]) == 11, result
