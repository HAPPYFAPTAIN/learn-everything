import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from learning_ext.route_view import render_route


ROOT = Path(__file__).resolve().parents[1]
BROWSER = next((path for path in (
    os.environ.get("CHROME_BIN"),
    shutil.which("chromium"),
    shutil.which("google-chrome"),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
) if path and Path(path).is_file()), None)


@pytest.mark.skipif(BROWSER is None, reason="Chromium is required for route interaction tests")
def test_stage_navigation_and_rerender_in_chromium(tmp_path):
    route = render_route({"nodes": [
        {"code": f"{index}.{course}", "title": f"Course {index}.{course}", "stage": stage,
         "status": "learning" if index == 2 and course == 1 else "pending", "est_hours": 1}
        for index, stage in enumerate(("base", "strengthen", "sprint"), 1)
        for course in (1, 2)
    ]})
    script = (ROOT / "learning_ext/assets/route_browser.js").read_text(encoding="utf-8")
    scenario = (ROOT / "tests/route_browser_frontend.js").read_text(encoding="utf-8")
    page = tmp_path / "route.html"
    page.write_text(
        '<!doctype html><meta charset="utf-8"><style>[hidden]{display:none!important}</style>'
        '<body><div id="route-host">' + route + '</div>'
        '<script>window.testErrors=[];window.addEventListener("error",e=>testErrors.push(e.message));'
        'window.addEventListener("unhandledrejection",e=>testErrors.push(String(e.reason)));'
        'window.initialRoute=' + json.dumps(route) + ';</script>'
        '<script>' + script + '</script><script>' + scenario + '</script>',
        encoding="utf-8",
    )
    completed = subprocess.run(
        [BROWSER, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
         "--disable-background-networking", "--disable-extensions", "--disable-background-timer-throttling",
         "--window-size=1100,900", "--virtual-time-budget=5000", "--dump-dom",
         f"--user-data-dir={tmp_path / 'profile'}", page.as_uri()],
        cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace", timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    match = re.search(r'<pre id="results">(.*?)</pre>', completed.stdout, re.S)
    assert match, completed.stdout[-4000:] + completed.stderr[-1000:]
    result = json.loads(html.unescape(match.group(1)))
    assert not result.get("error"), result
    assert len(result["checks"]) == 14, result
