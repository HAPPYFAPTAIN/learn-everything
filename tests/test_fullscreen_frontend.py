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


@pytest.mark.skipif(BROWSER is None, reason="Chromium is required for workspace display tests")
@pytest.mark.parametrize("initial_collapsed", [False, True])
def test_workspace_display_interactions_in_chromium(tmp_path, initial_collapsed):
    assets = ROOT / "learning_ext/assets"
    scripts = "".join(
        "<script>" + (assets / name).read_text(encoding="utf-8") + "</script>"
        for name in ("nav.js", "fullscreen_shell.js")
    )
    styles = "\n".join(
        (assets / name).read_text(encoding="utf-8")
        for name in ("theme_tokens.css", "fullscreen_shell.css")
    )
    scenarios = (ROOT / "tests/fullscreen_frontend.js").read_text(encoding="utf-8")
    page = tmp_path / "fullscreen.html"
    page.write_text(
        '<!doctype html><meta charset="utf-8"><style>'
        '[hidden]{display:none!important}body{margin:0}'
        '.le-topbar{display:flex;align-items:center;height:58px;padding:0 18px;gap:12px}'
        '.le-brand{display:flex;align-items:center}.le-app-title{flex:1}'
        '#le-app-tabs>.tab-nav{position:fixed;top:60px;left:0;bottom:0}'
        '#le-app-tabs>.tab-nav button{display:block;margin:4px}'
        '.tabitem{padding:30px;min-height:200px}button{min-height:28px}'
        + styles + '</style><body><div class="gradio-container">'
        '<header id="le-brand-bar"></header>'
        '<main id="le-app-tabs"><nav class="tab-nav">'
        '<button id="learning-workbench-tab-button" role="tab" aria-selected="true">学习工作台</button>'
        '<button id="learning-review-tab-button" role="tab" aria-selected="false">复习</button>'
        '<button id="indices-tab-button" role="tab" aria-selected="false" data-le-secondary="true" hidden>资料库</button>'
        '<button id="chat-tab-button" role="tab" aria-selected="false" data-le-secondary="true" hidden>知识问答</button>'
        '<button id="quick-setup-tab-button" role="tab" aria-selected="false">模型配置</button>'
        '<button id="unavailable-tab-button" role="tab" disabled>不可用</button></nav>'
        '<section class="tabitem"><article id="le-guide-md">阅读内容</article>'
        '<button id="outside-focus">页面内容</button></section></main>'
        '<section id="custom-modal" role="dialog" aria-modal="true" hidden>'
        '<button id="modal-focus">课程确认</button></section></div>'
        '<script>window.testErrors=[];window.addEventListener("error",e=>testErrors.push(e.message));'
        'window.addEventListener("unhandledrejection",e=>testErrors.push(String(e.reason)));'
        f'window.initialCollapsed={json.dumps(initial_collapsed)};'
        'localStorage.setItem("le.nav.collapsed",initialCollapsed?"1":"0");'
        'localStorage.setItem("le.reading.size","18");'
        '</script>' + scripts + '<script>' + scenarios + '</script>',
        encoding="utf-8",
    )
    completed = subprocess.run(
        [BROWSER, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
         "--disable-background-networking", "--disable-extensions", "--disable-background-timer-throttling",
         "--window-size=1100,1000", "--virtual-time-budget=6000", "--dump-dom",
         f"--user-data-dir={tmp_path / 'profile'}", page.as_uri()],
        cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace", timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    match = re.search(r'<pre id="results">(.*?)</pre>', completed.stdout, re.S)
    assert match, completed.stdout[-4000:] + completed.stderr[-1000:]
    result = json.loads(html.unescape(match.group(1)))
    assert not result.get("error"), result
    assert len(result["checks"]) == 34, result
