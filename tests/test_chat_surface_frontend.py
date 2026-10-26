import html
import json
from pathlib import Path
import re
import subprocess

import pytest

from test_ui_navigation_frontend import BROWSER


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(BROWSER is None, reason="Chromium is required for layout tests")
@pytest.mark.parametrize("width", [1200, 390])
@pytest.mark.parametrize("dark", [False, True], ids=["light", "dark"])
def test_chat_message_geometry_contrast_and_interactions(tmp_path, width, dark):
    from learning_ext.presentation import presentation_css

    assets = ROOT / "learning_ext/assets"
    css = "\n".join((assets / name).read_text(encoding="utf-8") for name in (
        "theme_tokens.css", "shell.css", "assistant.css", "text_polish.css", "theme_toggle.css",
    )) + "\n" + presentation_css()
    if dark:
        css += "\n" + (assets / "dark_theme.css").read_text(encoding="utf-8")
    css = css.replace("__ASSETS__", assets.as_uri()).replace("/file=" + assets.as_posix(), assets.as_uri())
    stylesheet = tmp_path / "application.css"
    stylesheet.write_text(css, encoding="utf-8")
    scenarios = (ROOT / "tests/chat_surface_frontend.js").read_text(encoding="utf-8")
    page = tmp_path / "chat-surface.html"
    config = {"width": width, "dark": dark, "stylesheet": stylesheet.as_uri()}
    page.write_text(
        '<!doctype html><meta charset="utf-8"><body><script>window.testScene='
        + json.dumps(config) + ';</script><script>' + scenarios + '</script>',
        encoding="utf-8",
    )
    completed = subprocess.run(
        [BROWSER, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
         "--disable-background-networking", "--disable-extensions", "--disable-background-timer-throttling",
         "--window-size=1320,1000", "--virtual-time-budget=6000", "--dump-dom",
         f"--user-data-dir={tmp_path / 'profile'}", page.as_uri()],
        cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace", timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    match = re.search(r'<pre id="results">(.*?)</pre>', completed.stdout, re.S)
    assert match, completed.stdout[-4000:] + completed.stderr[-1000:]
    result = json.loads(html.unescape(match.group(1)))
    assert not result.get("error"), result
    assert len(result["checks"]) >= 15, result
