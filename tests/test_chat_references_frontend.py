import html
import json
from pathlib import Path
import re
import subprocess

import pytest

from test_ui_navigation_frontend import BROWSER


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(BROWSER is None, reason="Chromium is required for UI interaction tests")
def test_chat_sources_are_explicit_and_follow_the_selected_answer(tmp_path):
    script = (ROOT / "learning_ext/assets/chat_references.js").read_text(encoding="utf-8")
    scenarios = (ROOT / "tests/chat_references_frontend.js").read_text(encoding="utf-8")
    page = tmp_path / "chat-references.html"
    page.write_text(
        '<!doctype html><meta charset="utf-8"><style>'
        '[hidden]{display:none!important}dialog:not([open]){display:none}'
        '.message-buttons{display:flex}.message-row{padding:8px}'
        '</style><body><div class="gradio-container" id="le-app-tabs">'
        '<section id="chat-tab"><div id="chat-area">'
        '<div id="main-chat-bot"><div class="wrap hide"></div>'
        '<div class="wrapper"><div class="bubble-wrap"><div class="message-wrap"></div></div></div>'
        '</div><div id="le-composer"><div id="chat-input"><textarea></textarea>'
        '<button class="submit-button" aria-label="发送">发送</button></div></div>'
        '</div><div id="chat-info-panel"><div id="info-expand">'
        '<button class="label-wrap">引用与来源</button><div id="pdf-modal"></div>'
        '<div class="plot-container" hidden></div>'
        '<div id="html-info-panel"><div class="prose"><h5><b>No evidence found.</b></h5></div></div>'
        '</div></div><button id="new-conv-button">新对话</button>'
        '<div id="conversation-dropdown"><input aria-label="历史对话">'
        '<ul role="listbox"><li role="option">另一段对话</li></ul></div>'
        '</section></div><script>'
        'window.requestAnimationFrame=callback=>setTimeout(()=>callback(performance.now()),1);'
        'window.cancelAnimationFrame=clearTimeout;'
        '</script><script>' + script + '</script><script>' + scenarios + '</script>',
        encoding="utf-8",
    )
    completed = subprocess.run(
        [BROWSER, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
         "--disable-background-networking", "--disable-extensions", "--disable-background-timer-throttling",
         "--window-size=1100,900", "--virtual-time-budget=7000", "--dump-dom",
         f"--user-data-dir={tmp_path / 'profile'}", page.as_uri()],
        cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace", timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    match = re.search(r'<pre id="results">(.*?)</pre>', completed.stdout, re.S)
    assert match, completed.stdout[-4000:] + completed.stderr[-1000:]
    result = json.loads(html.unescape(match.group(1)))
    assert not result.get("error"), result
    assert len(result["checks"]) >= 20, result
