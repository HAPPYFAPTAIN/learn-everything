import html
import json
from pathlib import Path
import re
import subprocess

import pytest

from learning_ext.rich_text import render_rich_text
from test_ui_navigation_frontend import BROWSER


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(BROWSER is None, reason="Chromium is required")
def test_copy_dynamic_steps_and_clipboard_fallback(tmp_path):
    assets = ROOT / "learning_ext/assets"
    page = tmp_path / "rich-text.html"
    rendered = render_rich_text('```python\nif a < 3:\n    print("你好 & <world>")\n```')
    page.write_text(
        '<!doctype html><meta charset="utf-8"><style>'
        + (assets / "rich_text.css").read_text(encoding="utf-8")
        + '</style><main id="content">' + rendered + '</main>'
        '<script>' + (assets / "rich_text.js").read_text(encoding="utf-8") + '</script>'
        '''<script>
        (async()=>{
          const checks=[];
          const check=(ok,name)=>{if(!ok)throw Error(name);checks.push(name)};
          const wait=()=>new Promise(r=>setTimeout(r,30));
          let clipboard='', fallback=false;
          try {
            Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>{clipboard=text}}});
            let button=document.querySelector('.le-code-copy');
            const code=document.querySelector('pre code');
            const expected='if a < 3:\\n    print("你好 & <world>")\\n';
            check(code.textContent===expected,'code is lossless');
            button.click();await wait();
            check(clipboard===expected && !clipboard.includes('Python'),'copy excludes toolbar and preserves indentation');
            check(button.textContent==='已复制' && button.getAttribute('aria-disabled')==='true','successful copy announced');
            document.querySelector('#content').innerHTML=RENDERED;
            button=document.querySelector('.le-code-copy');
            button.focus();button.click();await wait();
            check(button.textContent==='已复制','delegated copy works after step replacement');
            Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async()=>{throw Error('denied')}}});
            document.execCommand=()=>{fallback=true;clipboard=document.querySelector('textarea').value;return true};
            document.querySelector('#content').innerHTML=RENDERED;
            button=document.querySelector('.le-code-copy');button.focus();button.click();await wait();
            check(fallback && clipboard===expected && button.textContent==='已复制','desktop clipboard fallback copies exact code');
            check(document.activeElement===button && !document.querySelector('textarea'),'fallback restores focus and cleans up');
            document.execCommand=()=>false;
            document.querySelector('#content').innerHTML=RENDERED;
            button=document.querySelector('.le-code-copy');button.click();await wait();
            check(button.textContent==='请选中后复制','failed copy never claims success');
            check(window.getSelection().toString().trimEnd()===expected.trimEnd(),'failed copy selects code for manual copy');
            check(getComputedStyle(document.querySelector('pre')).whiteSpace==='pre','code formatting preserved');
          }catch(error){checks.push({error:error.message})}
          const result=document.createElement('pre');result.id='results';result.textContent=JSON.stringify(checks);document.body.append(result);
        })();
        </script>'''.replace('RENDERED', json.dumps(rendered, ensure_ascii=True)), encoding="utf-8",
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
    assert not [item for item in report if isinstance(item, dict)], report[-1]
    assert len(report) == 9
