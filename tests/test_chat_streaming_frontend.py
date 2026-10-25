import html
import json
from pathlib import Path
import re
import subprocess

import pytest

from test_ui_navigation_frontend import BROWSER


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(BROWSER is None, reason="Chromium is required")
def test_live_answer_is_not_covered_by_progress_overlay(tmp_path):
    assets = ROOT / "learning_ext/assets"
    page = tmp_path / "stream.html"
    page.write_text(
        '<!doctype html><meta charset="utf-8"><style>'
        '.wrap{position:absolute;inset:0;background:white;z-index:20}'
        + (assets / "compact.css").read_text(encoding="utf-8")
        + '</style><div id="le-app-tabs"><section id="chat-tab"><div id="chat-area">'
        '<div id="main-chat-bot"><div class="wrap translucent hide"></div>'
        '<div class="wrapper"><div class="bubble-wrap"><div class="message-row bot-row">'
        '<div class="prose">Thinking ...</div></div></div></div></div>'
        '<div id="le-composer"></div></div></section></div>'
        '<script>requestAnimationFrame=fn=>setTimeout(fn,1);cancelAnimationFrame=clearTimeout;</script>'
        '<script>' + (assets / "chat_streaming.js").read_text(encoding="utf-8") + '</script>'
        '''<script>
        (async()=>{
          const checks=[];
          const check=(ok,name)=>{if(!ok)throw Error(name);checks.push(name)};
          const wait=()=>new Promise(r=>setTimeout(r,20));
          try {
            await wait();
            const bot=document.getElementById('main-chat-bot');
            const overlay=bot.querySelector('.wrap'), row=bot.querySelector('.bot-row');
            const answer=bot.querySelector('.prose'), status=document.getElementById('le-chat-stream-status');
            check(status.hidden,'idle has no loader');
            overlay.classList.remove('hide');await wait();
            check(!status.hidden && status.textContent.includes('正在思考'),'waiting status visible');
            check(getComputedStyle(overlay).display==='none','progress overlay cannot cover text');
            check(getComputedStyle(row).display==='none','English placeholder hidden while waiting');
            answer.textContent='第一条建议';await wait();
            check(getComputedStyle(row).display!=='none' && status.textContent.includes('正在回答'),'first chunk visible while busy');
            answer.firstChild.appendData('，第二条建议');await wait();
            check(answer.textContent.includes('第二条') && bot.getAttribute('aria-busy')==='true','subsequent text node chunks stay visible');
            overlay.classList.add('hide');await wait();
            check(status.hidden && getComputedStyle(row).display!=='none','completion retains answer and clears status');
            overlay.className='wrap error';await wait();
            check(getComputedStyle(overlay).display!=='none' && status.hidden,'error remains visible');
            const result=document.createElement('pre');result.id='results';result.textContent=JSON.stringify({checks});document.body.append(result);
          }catch(error){const result=document.createElement('pre');result.id='results';result.textContent=JSON.stringify({checks,error:error.message});document.body.append(result)}
        })();
        </script>''', encoding="utf-8",
    )
    result = subprocess.run(
        [BROWSER, "--headless=new", "--disable-gpu", "--no-first-run",
         "--disable-background-networking", "--disable-extensions", "--dump-dom",
         "--virtual-time-budget=3000", f"--user-data-dir={tmp_path / 'profile'}", page.as_uri()],
        capture_output=True, encoding="utf-8", errors="replace", timeout=30,
    )
    assert result.returncode == 0, result.stderr
    match = re.search(r'<pre id="results">(.*?)</pre>', result.stdout, re.S)
    assert match, result.stdout[-3000:]
    report = json.loads(html.unescape(match.group(1)))
    assert not report.get("error"), report
    assert len(report["checks"]) == 8
