import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
BROWSER = next((path for path in (
    os.environ.get("CHROME_BIN"),
    shutil.which("chromium"),
    shutil.which("google-chrome"),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
) if path and Path(path).is_file()), None)


@pytest.mark.skipif(BROWSER is None, reason="Chromium is required for UI interaction tests")
def test_navigation_and_preview_interactions_in_chromium(tmp_path):
    assets = ROOT / "learning_ext/assets"
    scripts = "".join(
        "<script>" + (assets / name).read_text(encoding="utf-8") + "</script>"
        for name in ("workspace.js", "settings_panels.js", "selects.js", "document_preview.js")
    )
    scenarios = (ROOT / "tests/ui_navigation_frontend.js").read_text(encoding="utf-8")
    page = tmp_path / "ui-navigation.html"
    page.write_text(
        '<!doctype html><meta charset="utf-8"><style>'
        '[hidden]{display:none!important}.wrap{padding:4px}ul.options{height:30px}'
        '.le-panel-source:not(.le-panel-current){display:none}.le-settings-deck{position:fixed}'
        '#le-chat-tool-menu button{display:block}button{min-height:24px}'
        '</style><body><div class="gradio-container" id="le-app-tabs">'
        '<section id="chat-tab"><div id="chat-area"><div id="main-chat-bot"></div>'
        '<div id="chat-input"><textarea></textarea></div></div>'
        '<div id="chat-settings-expand"><button class="label-wrap open">Settings</button></div>'
        '<div id="conv-settings-panel"><div id="index-0"><div class="wrap">'
        '<input id="files-input" aria-label="Files"><ul id="files-options" class="options" role="listbox" hidden><li role="option">One file</li></ul>'
        '</div></div><div id="le-chat-add-source"><button class="label-wrap open">Add</button>'
        '<div class="wrap"><input id="nested-input" aria-label="Nested"><ul id="nested-options" class="options" role="listbox" hidden><li role="option">Nested option</li></ul></div>'
        '</div></div><div id="conversation-dropdown"><div class="wrap">'
        '<input id="history-input" role="listbox" aria-expanded="false"><ul id="history-options" class="options" role="listbox" hidden><li role="option">Earlier chat</li></ul>'
        '</div></div><div id="use-mindmap-checkbox"><input type="checkbox"></div></section>'
        '<div id="le-quiz-settings"></div><section class="le-source-original" id="preview-panel">'
        '<button data-preview-zoom="out">Out</button><button data-preview-zoom="fit">Fit</button>'
        '<button data-preview-zoom="in">In</button><button data-preview-fullscreen aria-label="全屏阅读">Fullscreen</button>'
        '<div class="le-original-canvas"><img alt="Local preview" width="100" height="100"></div></section>'
        '<section class="le-source-original" id="other-preview"><button data-preview-fullscreen>Other fullscreen</button></section>'
        '</div><script>window.requestAnimationFrame=callback=>setTimeout(()=>callback(performance.now()),1);window.cancelAnimationFrame=clearTimeout;</script>'
        + scripts + '<script>' + scenarios + '</script>',
        encoding="utf-8",
    )
    completed = subprocess.run(
        [BROWSER, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
         "--disable-background-networking", "--disable-extensions", "--disable-background-timer-throttling",
         "--window-size=1100,1000", "--virtual-time-budget=5000", "--dump-dom",
         f"--user-data-dir={tmp_path / 'profile'}", page.as_uri()],
        cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace", timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    match = re.search(r'<pre id="results">(.*?)</pre>', completed.stdout, re.S)
    assert match, completed.stdout[-4000:] + completed.stderr[-1000:]
    result = json.loads(html.unescape(match.group(1)))
    assert not result.get("error"), result
    assert len(result["checks"]) == 30, result

