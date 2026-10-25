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


@pytest.mark.skipif(BROWSER is None, reason="Chromium is required for motion behavior tests")
@pytest.mark.parametrize("initial_reduced", [False, True])
def test_motion_lifecycle_in_chromium(tmp_path, initial_reduced):
    source = (ROOT / "learning_ext/assets/motion.js").read_text(encoding="utf-8")
    styles = (ROOT / "learning_ext/assets/motion.css").read_text(encoding="utf-8")
    scenarios = (ROOT / "tests/motion_frontend.js").read_text(encoding="utf-8")
    page = tmp_path / "motion.html"
    page.write_text(
        '<!doctype html><meta charset="utf-8"><style>'
        '[hidden]{display:none!important}body{margin:0}.le-metric{height:30px}'
        '.target{width:120px;height:30px}.offscreen{position:fixed;top:3000px}'
        + styles + '</style><body><div class="gradio-container">'
        '<aside><div class="tab-nav"><button id="generated-label" role="tab" '
        'aria-selected="true">Home</button><button id="second-label" role="tab" '
        'aria-controls="second-panel" aria-selected="false">Next</button></div></aside>'
        '<main id="le-app-tabs"><button class="primary" id="motion-primary">Action</button>'
        '<section id="home-panel" role="tabpanel" '
        'aria-labelledby="generated-label">'
        + ''.join(f'<div class="le-metric" id="metric-{i}">Card {i}'
                  + ('<span class="le-section-heading" id="nested">Nested</span>' if i == 0 else '')
                  + '</div>' for i in range(8))
        + '<div class="le-metric offscreen" id="outside">Outside</div>'
        '<article id="le-center-content">Reading text</article></section>'
        '<section id="second-panel" role="tabpanel" hidden>'
        '<div id="second-card" class="le-metric">Second</div></section></main>'
        '<div id="target" class="target">Target</div><div id="chatbot"></div></div>'
        f'<script>window.initialReduced={json.dumps(initial_reduced)};</script>'
        '<script>' + scenarios.split('/* CONTROLLER */')[0] + '</script>'
        '<script>' + source + '</script>'
        '<script>' + scenarios.split('/* CONTROLLER */')[1] + '</script>',
        encoding="utf-8",
    )
    completed = subprocess.run(
        [BROWSER, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
         "--disable-background-networking", "--disable-extensions", "--disable-background-timer-throttling",
         "--window-size=1100,1000", "--virtual-time-budget=7000", "--dump-dom",
         f"--user-data-dir={tmp_path / 'profile'}"]
        + (["--force-prefers-reduced-motion=reduce"] if initial_reduced else []) + [page.as_uri()],
        cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace", timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    match = re.search(r'<pre id="results">(.*?)</pre>', completed.stdout, re.S)
    assert match, completed.stdout[-3000:] + completed.stderr[-1000:]
    result = json.loads(html.unescape(match.group(1)))
    assert not result.get("error"), result
    assert result["passed"] == 29, result
