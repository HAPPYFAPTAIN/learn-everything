import io
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from learning_ext.text_polish import native


def call_native(monkeypatch, handler, payload):
    monkeypatch.setitem(sys.modules, "learning_ext.text_polish.service", SimpleNamespace(polish_request=handler))
    output = io.StringIO()
    native.run(io.StringIO(payload), output)
    lines = output.getvalue().splitlines()
    assert len(lines) == 1
    assert lines[0].startswith(native.RESULT_PREFIX)
    return json.loads(lines[0][len(native.RESULT_PREFIX):])


def test_native_polish_uses_only_clicked_goal_and_hides_logs(monkeypatch):
    captured = []

    def polish(payload):
        captured.append(json.loads(payload))
        print("raw provider detail must not appear")
        print("raw error detail must not appear", file=sys.stderr)
        return json.dumps({"id": "request-1", "ok": True, "text": "整理本周销售表。"}, ensure_ascii=False)

    result = call_native(monkeypatch, polish, json.dumps({
        "id": "request-1", "text": "整理 本周销售表", "kind": "other",
        "context": "Other form text must not be forwarded", "extra": "ignored",
    }))
    assert captured == [{"id": "request-1", "text": "整理 本周销售表", "kind": "goal"}]
    assert result == {"id": "request-1", "ok": True, "text": "整理本周销售表。", "error": "", "changed": True}


def test_native_polish_errors_do_not_expose_provider_details(monkeypatch):
    def fail(_payload):
        raise RuntimeError("private credential or response")

    result = call_native(monkeypatch, fail, json.dumps({"id": "request-2", "text": "目标"}))
    assert result == {"id": "request-2", "ok": False, "text": "", "error": native.ERROR, "changed": False}


def test_native_polish_rejects_stale_response(monkeypatch):
    result = call_native(monkeypatch, lambda _: json.dumps({
        "id": "another-request", "ok": True, "text": "other text"
    }), json.dumps({"id": "current-request", "text": "目标"}))
    assert result["ok"] is False
    assert result["text"] == ""


def test_native_polish_rejects_invalid_requests_before_model(monkeypatch):
    calls = []

    def unexpected(_payload):
        calls.append(_payload)
        return "{}"

    for raw in ("not json", "[]", json.dumps({"id": "a", "text": " "}),
                json.dumps({"id": "a", "text": "x" * (native.MAX_TEXT + 1)})):
        result = call_native(monkeypatch, unexpected, raw)
        assert result["ok"] is False
        assert result["text"] == ""
    assert calls == []


def test_native_polish_unchanged_text_is_not_marked_changed(monkeypatch):
    result = call_native(monkeypatch, lambda _: json.dumps({
        "id": "same", "ok": True, "text": "整理销售表", "changed": True
    }), json.dumps({"id": "same", "text": "整理销售表"}))
    assert result["ok"] is True
    assert result["changed"] is False


@pytest.mark.skipif(sys.platform != "win32", reason="WPF is Windows-only")
def test_native_window_preview_cancel_and_stale_input_without_showing_window(tmp_path):
    worker = tmp_path / "fake worker.py"
    worker.write_text(
        "import json, subprocess, sys, time\n"
        "from pathlib import Path\n"
        "request = json.load(sys.stdin)\n"
        "if request['text'] == 'wait-tree':\n"
        "    child = subprocess.Popen([sys._base_executable, '-c', 'import time; time.sleep(60)'], creationflags=subprocess.CREATE_NO_WINDOW)\n"
        "    Path(__file__).with_suffix('.child.pid').write_text(str(child.pid))\n"
        "    time.sleep(60)\n"
        "time.sleep(3 if request['text'] == 'wait' else 0.1)\n"
        "print('provider log that must not enter preview')\n"
        "print('__LE_POLISH_RESULT__:' + json.dumps({'id':request['id'], 'ok':True, 'text':'polished ' + request['text']}))\n",
        encoding="utf-8",
    )
    script = Path("learning_ext/agent/practice_window.ps1").read_text(encoding="utf-8-sig")
    assert script.count("$window.ShowDialog() | Out-Null") == 1
    script = script.replace("$window.ShowDialog() | Out-Null", "")
    script += r'''
function Click-TestButton($button) {
    $button.RaiseEvent([Windows.RoutedEventArgs]::new([Windows.Controls.Button]::ClickEvent))
}
function Assert-Test($condition, [string]$message) {
    if (-not $condition) { throw $message }
}
function Invoke-TestDispatcherTick {
    $frame = [Windows.Threading.DispatcherFrame]::new()
    $pumpTimer = [Windows.Threading.DispatcherTimer]::new()
    $pumpTimer.Interval = [TimeSpan]::FromMilliseconds(25)
    $pumpTimer.Add_Tick({ $frame.Continue = $false })
    $pumpTimer.Start()
    [Windows.Threading.Dispatcher]::PushFrame($frame)
    $pumpTimer.Stop()
}
function Wait-TestPolish {
    $deadline = [DateTime]::UtcNow.AddSeconds(8)
    while ($null -ne $polishState.Process -and [DateTime]::UtcNow -lt $deadline) {
        Invoke-TestDispatcherTick
    }
    Assert-Test ($null -eq $polishState.Process) 'worker did not finish'
}
function Wait-TestTreeChild {
    $pidFile = [IO.Path]::ChangeExtension($PolishScript, 'child.pid')
    $deadline = [DateTime]::UtcNow.AddSeconds(8)
    while (-not (Test-Path -LiteralPath $pidFile) -and [DateTime]::UtcNow -lt $deadline) {
        Invoke-TestDispatcherTick
    }
    Assert-Test (Test-Path -LiteralPath $pidFile) 'helper did not create a child'
    $ownedChildId = [int][IO.File]::ReadAllText($pidFile)
    [IO.File]::Delete($pidFile)
    return $ownedChildId
}
function Assert-TestChildStopped([int]$childId) {
    $deadline = [DateTime]::UtcNow.AddSeconds(3)
    while ((Get-Process -Id $childId -ErrorAction SilentlyContinue) -and [DateTime]::UtcNow -lt $deadline) {
        Start-Sleep -Milliseconds 25
    }
    Assert-Test (-not (Get-Process -Id $childId -ErrorAction SilentlyContinue)) 'child remained alive'
}
try {
    $goalInput.Text = 'original'
    Click-TestButton $polishButton
    Wait-TestPolish
    Assert-Test ($goalInput.Text -ceq 'original') 'preview changed input'
    Assert-Test ($polishPreview.Text -ceq 'polished original') ('preview missing: ' + $polishStatus.Text)
    Assert-Test $polishAccept.IsEnabled 'adoption should be available'
    Click-TestButton $polishCancel
    Assert-Test ($goalInput.Text -ceq 'original') 'cancel changed input'

    Click-TestButton $polishButton
    Wait-TestPolish
    $goalInput.Text = 'changed'
    Click-TestButton $polishAccept
    Assert-Test ($goalInput.Text -ceq 'changed') 'stale preview overwrote edit'
    Assert-Test (-not $polishAccept.IsEnabled) 'stale adoption remained enabled'

    Click-TestButton $polishButton
    Wait-TestPolish
    Click-TestButton $polishAccept
    Assert-Test ($goalInput.Text -ceq 'polished changed') 'explicit adoption did not replace text'
    Assert-Test (-not $statusText.Text.StartsWith('已完成：')) 'adoption performed a check'

    $goalInput.Text = 'wait'
    Click-TestButton $polishButton
    $childId = $polishState.Process.Id
    $goalInput.Text = 'new edit'
    Assert-Test ($null -eq $polishState.Process) 'typing did not cancel request'
    Assert-TestChildStopped $childId
    Assert-Test ($goalInput.Text -ceq 'new edit') 'typing cancellation lost text'

    $goalInput.Text = 'wait'
    Click-TestButton $polishButton
    $childId = $polishState.Process.Id
    Click-TestButton $polishCancel
    Assert-TestChildStopped $childId
    Assert-Test ($goalInput.Text -ceq 'wait') 'pending cancellation changed text'

    foreach ($reason in @('cancel', 'edit', 'timeout', 'close')) {
        $goalInput.Text = 'wait-tree'
        Click-TestButton $polishButton
        $childId = $polishState.Process.Id
        $descendantId = Wait-TestTreeChild
        switch ($reason) {
            'cancel' { Click-TestButton $polishCancel }
            'edit' { $goalInput.Text = 'edited during tree request' }
            'timeout' { $polishState.Started = [DateTime]::UtcNow.AddSeconds(-121); Wait-TestPolish }
            'close' { $window.Close() }
        }
        Assert-TestChildStopped $childId
        Assert-TestChildStopped $descendantId
    }
    Write-Output 'native lifecycle passed without showing a window'
} finally {
    Stop-PolishWorker
    $window.Close()
}
'''
    harness = tmp_path / "headless practice.ps1"
    harness.write_text(script, encoding="utf-8-sig")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-STA", "-ExecutionPolicy", "Bypass", "-File", str(harness),
         "-PolishPython", sys.executable, "-PolishScript", str(worker)],
        capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert result.returncode == 0, (result.stdout + result.stderr).decode("utf-8", errors="replace")
    assert b"native lifecycle passed" in result.stdout
