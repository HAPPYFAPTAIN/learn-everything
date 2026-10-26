import json
from pathlib import Path
import subprocess
import sys

import pytest

from learning_ext.agent import guided_desktop as desktop


@pytest.fixture
def control(monkeypatch):
    monkeypatch.setattr(desktop.time, "time", lambda: 1000.0)
    window = dict(hwnd=1, pid=2, started=3, title="学习选项")
    monkeypatch.setattr(desktop, "windows", lambda: [dict(window)])
    item = dict(key="1.2", name="显示目录", type="CheckBox", action="toggle",
                state="Off", automation_id="toc", class_name="CheckBox", observed_at=990.0)
    return window, item


@pytest.mark.parametrize("age", [181, -1, float("nan"), float("inf"), True, None])
def test_stale_or_invalid_observation_never_calls_native_backend(control, monkeypatch, age):
    window, item = control
    item["observed_at"] = 1000 - age if type(age) in (int, float) else age
    called = []
    monkeypatch.setattr(desktop, "_ps", lambda *a, **k: called.append(a))
    with pytest.raises(ValueError, match="过期"):
        desktop.operate(window, item)
    assert not called


def test_observation_starts_expiry_before_native_collection(control, monkeypatch):
    window, item = control
    item.pop("observed_at")
    result = {"items": [item], "truncated": True}
    monkeypatch.setattr(desktop, "_ps", lambda *a, **k: (0, json.dumps(result)))
    observation = desktop.observe(window)
    assert observation["items"][0]["observed_at"] == 1000
    assert observation["observed"] == 1000 and observation["truncated"]
    assert "observed_at" not in item
    window["title"] = "另一个窗口"
    assert observation["window"]["title"] == "学习选项"


@pytest.mark.parametrize("items", ["invalid", [None], [{"key": "same"}, {"key": "same"}]])
def test_invalid_control_lists_cannot_become_targets(control, monkeypatch, items):
    monkeypatch.setattr(desktop, "_ps", lambda *a, **k: (0, json.dumps({"items": items})))
    with pytest.raises(ValueError):
        desktop.observe(control[0])


@pytest.mark.parametrize("field", ["state", "automation_id", "class_name"])
def test_incomplete_control_identity_never_operates(control, monkeypatch, field):
    window, item = control
    item.pop(field)
    called = []
    monkeypatch.setattr(desktop, "_ps", lambda *a, **k: called.append(a))
    with pytest.raises(ValueError):
        desktop.operate(window, item)
    assert not called


def test_action_must_match_known_control_capability(control):
    window, item = control
    for kind, action in (("CheckBox", "invoke"), ("Button", "toggle"), ("TabItem", "execute"), ("Edit", "invoke")):
        assert not desktop.can_operate(window, {**item, "type": kind, "action": action})


def test_native_stale_target_reason_is_preserved(control, monkeypatch):
    monkeypatch.setattr(desktop, "_ps", lambda *a, **k: (1, json.dumps({"error": "控件或状态已变化，请重新读取并圈出目标。"})))
    with pytest.raises(ValueError, match="状态已变化"):
        desktop.operate(*control)


def test_unverified_receipt_is_never_promoted_to_success(control, monkeypatch):
    receipt = {"ok": False, "executed": True, "verified": False, "status": "unverified", "message": "请检查当前窗口，不要重复点击。"}
    monkeypatch.setattr(desktop, "_ps", lambda *a, **k: (0, json.dumps(receipt)))
    assert desktop.operate(*control) == receipt
    monkeypatch.setattr(desktop, "_ps", lambda *a, **k: (0, '{"ok":true}'))
    with pytest.raises(ValueError, match="不要重复"):
        desktop.operate(*control)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows UI Automation helper")
def test_native_control_actions_verify_state_without_replaying(tmp_path):
    source = str(desktop.SCRIPT).replace("'", "''")
    script = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('__SOURCE__', [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$ast.FindAll({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -in @('Get-ControlState','Invoke-ControlAction')}, $true) | ForEach-Object { Invoke-Expression $_.Extent.Text }
function Fake($state, $change) {
    $current = [pscustomobject]@{ToggleState=$state;IsSelected=($state -eq 'True');ExpandCollapseState=$state}
    $pattern = [pscustomobject]@{Current=$current;Calls=0;Change=$change}
    $pattern | Add-Member ScriptMethod Toggle { $this.Calls++; if ($this.Change) { $this.Current.ToggleState='On' } }
    $pattern | Add-Member ScriptMethod Select { $this.Calls++; if ($this.Change) { $this.Current.IsSelected=$true } }
    $pattern | Add-Member ScriptMethod Expand { $this.Calls++; if ($this.Change) { $this.Current.ExpandCollapseState='Expanded' } }
    $pattern | Add-Member ScriptMethod Invoke { $this.Calls++ }
    $element = [pscustomobject]@{Pattern=$pattern}
    $element | Add-Member ScriptMethod GetCurrentPattern {param($ignored) return $this.Pattern}
    return $element
}
$results = @()
foreach ($case in @(@('toggle','Off',$true),@('toggle','Off',$false),@('select','True',$true),@('select','False',$true),@('expand','Expanded',$true),@('expand','Collapsed',$true),@('invoke','',$true))) {
    $element = Fake $case[1] $case[2]
    $receipt = Invoke-ControlAction $element $case[0] $case[1]
    $results += @{receipt=$receipt;calls=$element.Pattern.Calls}
}
$stale = Fake 'On' $true
$blocked = $false
try { Invoke-ControlAction $stale 'toggle' 'Off' } catch { $blocked=$true }
@{results=$results;stale_blocked=$blocked;stale_calls=$stale.Pattern.Calls} | ConvertTo-Json -Depth 8 -Compress
'''.replace("__SOURCE__", source)
    target = tmp_path / "native-control-check.ps1"
    target.write_text(script, encoding="utf-8-sig")
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(target)],
                            capture_output=True, timeout=20, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    receipts = data["results"]
    assert receipts[0]["receipt"]["verified"] and receipts[0]["calls"] == 1
    assert not receipts[1]["receipt"]["verified"] and receipts[1]["calls"] == 1
    assert receipts[1]["receipt"]["executed"] and not receipts[1]["receipt"]["ok"]
    for index in (2, 4):
        assert receipts[index]["receipt"]["status"] == "already_satisfied"
        assert receipts[index]["receipt"]["verified"] and receipts[index]["calls"] == 0
    for index in (3, 5):
        assert receipts[index]["receipt"]["verified"] and receipts[index]["calls"] == 1
    assert receipts[6]["receipt"]["status"] == "sent" and not receipts[6]["receipt"]["verified"]
    assert data["stale_blocked"] and data["stale_calls"] == 0


def test_native_script_keeps_windows_encoding():
    assert Path(desktop.SCRIPT).read_bytes().startswith(b"\xef\xbb\xbf")
