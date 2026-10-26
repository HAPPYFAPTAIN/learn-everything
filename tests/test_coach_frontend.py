import ast
import html
import json
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace

import pytest

from test_ui_navigation_frontend import BROWSER


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "learning_ext/assets"


def _served_css():
    source = ast.parse((ROOT / "custom_app.py").read_text(encoding="utf-8"))
    function = next(node for node in source.body
                    if isinstance(node, ast.FunctionDef) and node.name == "_presentation_stylesheet")
    namespace = {"Path": Path, "_HERE": str(ROOT)}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "custom_app.py", "exec"), namespace)
    return namespace["_presentation_stylesheet"]().replace("/file=" + ASSETS.as_posix(), ASSETS.as_uri())


def _frames():
    from learning_ext.pages.coach import CoachPage

    page = CoachPage(SimpleNamespace())
    code = 'result = process_document("' + "example-document-name-" * 24 + '")'
    page.items = [
        {"type": "user", "text": "只回复：好"},
        {"type": "ai", "text": "好"},
        {"type": "user", "text": "请检查我当前的学习环境，并说明哪些工具可以直接使用，哪些还需要准备。" * 10},
        {"type": "ai", "text": f"可以先阅读下面的代码：\n```python\n{code}\n```"},
        {"type": "tool", "call_id": "environment-1", "name": "system_info", "status": "ok", "ms": 15,
         "output": "操作系统：Windows\n环境检查已完成。"},
    ] + [{"type": "ai", "text": f"第 {index + 1} 条观察：" + "继续核实当前环境，确认后再进入下一步。" * 4}
         for index in range(16)]
    initial = page._frame(snapshot=True)
    page.items.append({"type": "ai", "text": "新的观察结果。"})
    page._busy = True
    deltas = []
    for index in range(40):
        page.items[-1]["text"] += "继续核实环境，确认后再进入下一步。"
        if index % 10 == 0:
            page.items[4]["output"] += f"\n已核实第 {index + 1} 项。"
        deltas.append(page._frame())
    page._busy = False
    final = page._frame(snapshot=True)
    page.items[4]["output"] += " 后续检查。"
    updated = page._frame()

    # Keep the sequence monotonic when starting a new session. Simulate Gradio
    # dropping the initial user update and all but the last of 40 stream frames.
    page.session = type(page.session)()
    page.items = []
    recovery_empty = page._frame()
    page.items = [{"type": "user", "text": "检查新会话的学习环境"},
                  {"type": "ai", "text": "先核实已有工具。"},
                  {"type": "tool", "call_id": "recovery-check", "name": "system_info", "status": "ok",
                   "output": "环境已检查。"}]
    page._frame()  # This initial populated frame is deliberately never delivered.
    page.items.append({"type": "ai", "text": "已确认："})
    page._busy = True
    for index in range(40):
        page.items[-1]["text"] += f"第 {index + 1} 项已就绪。"
        recovery_last = page._frame()
    return {"initial": initial, "deltas": deltas, "final": final, "updated": updated, "code": code,
            "recoveryEmpty": recovery_empty, "recoveryLast": recovery_last,
            "recoveryCount": len(page.items), "recoveryText": page.items[-1]["text"]}


@pytest.mark.skipif(BROWSER is None, reason="Chromium is required for coach layout tests")
@pytest.mark.parametrize("width", [1200, 390])
@pytest.mark.parametrize("dark", [False, True], ids=["light", "dark"])
def test_coach_layout_theme_and_streaming_interactions(tmp_path, width, dark):
    stylesheet = tmp_path / "application.css"
    stylesheet.write_text(_served_css(), encoding="utf-8")
    scenarios = (ROOT / "tests/coach_frontend.js").read_text(encoding="utf-8")
    config = {
        "width": width,
        "dark": dark,
        "stylesheet": stylesheet.as_uri(),
        "frames": _frames(),
        "coachScript": (ASSETS / "coach.js").read_text(encoding="utf-8"),
        "richTextScript": (ASSETS / "rich_text.js").read_text(encoding="utf-8"),
        "themeScript": (ASSETS / "theme_mode.js").read_text(encoding="utf-8").replace("__LE_ASSETS__", ASSETS.as_uri()),
        "darkCss": (ASSETS / "dark_theme.css").read_text(encoding="utf-8"),
    }
    page = tmp_path / "coach.html"
    page.write_text(
        '<!doctype html><meta charset="utf-8"><body><script>window.testScene='
        + json.dumps(config).replace("</", "<\\/") + ';</script><script>' + scenarios + '</script>',
        encoding="utf-8",
    )
    completed = subprocess.run(
        [BROWSER, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
         "--disable-background-networking", "--disable-extensions", "--disable-background-timer-throttling",
         "--window-size=1320,1000", "--virtual-time-budget=9000", "--dump-dom",
         f"--user-data-dir={tmp_path / 'profile'}", page.as_uri()],
        cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace", timeout=40,
    )
    assert completed.returncode == 0, completed.stderr
    match = re.search(r'<pre id="results">(.*?)</pre>', completed.stdout, re.S)
    assert match, completed.stdout[-5000:] + completed.stderr[-1000:]
    result = json.loads(html.unescape(match.group(1)))
    assert not result.get("error"), json.dumps(result, ensure_ascii=False, indent=2)
    assert len(result["checks"]) >= 65, result
