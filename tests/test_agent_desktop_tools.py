import base64
import copy
import re
import subprocess
import sys

import pytest

from learning_ext.agent import tools
from learning_ext.agent.outcomes import ToolOutput, tool_succeeded


@pytest.fixture
def desktop(monkeypatch):
    title = "Editor — lesson.txt"
    item = {"n": "下一步", "t": "Button", "x": 100, "y": 90, "key": "1.2", "id": "next", "enabled": True, "offscreen": False}
    state = dict(title=title, hwnd=12, identity=(12, 34, 56.0), items=[item], foreground=99,
                 hit=12, clicks=[], clipboard=[], keys=[], focus_allowed=True)

    class API:
        def IsIconic(self, hwnd): return False
        def ShowWindow(self, hwnd, mode): pass
        def SetForegroundWindow(self, hwnd):
            if state["focus_allowed"]: state["foreground"] = hwnd
        def SetCursorPos(self, x, y): state["cursor"] = (x, y)
        def WindowFromPoint(self, point): return state["hit"]
        def GetAncestor(self, hwnd, mode): return hwnd
        def mouse_event(self, *args): state["clicks"].append(args[0])

    api = API()
    tools._UI_OBSERVATIONS.clear()
    monkeypatch.setattr(tools, "_win_api", lambda: api)
    monkeypatch.setattr(tools, "_find_window", lambda name: (12, title) if name in (title, "Editor") else (0, ""))
    monkeypatch.setattr(tools, "_foreground", lambda: (state["foreground"], title if state["foreground"] == 12 else "授权页面"))
    monkeypatch.setattr(tools, "_window_identity", lambda hwnd: state["identity"])
    monkeypatch.setattr(tools, "_window_rect", lambda hwnd: (0, 0, 800, 600))
    monkeypatch.setattr(tools, "_ui_items", lambda hwnd: ((title, copy.deepcopy(state["items"])), None))
    monkeypatch.setattr(tools.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(tools, "_clipboard_set", lambda text: state["clipboard"].append(text) or ToolOutput("已设置"))
    monkeypatch.setattr(tools, "_send_keys_to_target", lambda keys, target, expected_text=None: state["keys"].append((keys, target, expected_text)) or ToolOutput("已发送"))
    return state, api


def observe(state):
    output = tools._read_ui("Editor")
    assert tool_succeeded(output)
    return re.search(r"observation=([a-f0-9]+)", output).group(1)


def test_missing_target_never_uses_approval_window(desktop):
    state, _ = desktop
    for result in (tools._click_at(100, 90), tools._click_ui("下一步"), tools._press_keys("{ENTER}"), tools._type_text("示例")):
        assert not tool_succeeded(result)
    assert not state["clicks"] and not state["keys"] and not state["clipboard"]


def test_observation_provides_full_title_and_single_use_target(desktop):
    state, _ = desktop
    token = observe(state)
    assert tool_succeeded(tools._press_keys("^s", window=state["title"], observation=token))
    assert state["foreground"] == 12
    assert state["keys"][0][1]["hwnd"] == 12
    assert not tool_succeeded(tools._press_keys("^s", window=state["title"], observation=token))
    assert len(state["keys"]) == 1


@pytest.mark.parametrize("changed", ["expired", "process", "title", "focus", "ui"])
def test_changed_context_prevents_keyboard_and_clipboard(desktop, changed):
    state, _ = desktop
    token = observe(state)
    if changed == "expired": tools._UI_OBSERVATIONS[token]["observed"] -= 91
    if changed == "process": state["identity"] = (12, 78, 90.0)
    if changed == "title": state["title"] = "Editor"
    if changed == "focus": state["focus_allowed"] = False
    if changed == "ui": state["items"][0]["n"] = "确认删除"
    result = tools._type_text("准备输入", window=state["title"], observation=token)
    assert not tool_succeeded(result)
    assert not state["clipboard"] and not state["keys"]


@pytest.mark.parametrize("keys", ["hello{ENTER}", "^a^v", "%{TAB}", "+%{TAB}", "^{ESC}", "^+{ESC}"])
def test_key_sequences_cannot_escape_target(desktop, keys):
    state, _ = desktop
    token = observe(state)
    assert not tool_succeeded(tools._press_keys(keys, window=state["title"], observation=token))
    assert not state["keys"]


def test_clipboard_failure_never_sends_paste(desktop, monkeypatch):
    state, _ = desktop
    token = observe(state)
    monkeypatch.setattr(tools, "_clipboard_set", lambda text: ToolOutput("剪贴板不可用", ok=False))
    assert not tool_succeeded(tools._type_text("示例", window=state["title"], observation=token))
    assert not state["keys"]


def test_paste_binds_expected_text_to_native_guard(desktop):
    state, _ = desktop
    token = observe(state)
    assert tool_succeeded(tools._type_text("中文与符号 $(foo)", window=state["title"], observation=token))
    assert state["keys"][0][0] == "^v" and state["keys"][0][2] == "中文与符号 $(foo)"


@pytest.mark.parametrize("changed", ["guessed", "moved", "replaced", "occluded", "out_of_window"])
def test_coordinates_require_current_unique_visible_control(desktop, monkeypatch, changed):
    state, _ = desktop
    token = observe(state)
    x, y = 100, 90
    if changed == "guessed": x = 101
    if changed == "moved": state["items"][0]["x"] = 150
    if changed == "replaced": state["items"][0]["key"] = "another"
    if changed == "occluded": state["hit"] = 99
    if changed == "out_of_window": monkeypatch.setattr(tools, "_window_rect", lambda hwnd: (200, 200, 80, 60))
    assert not tool_succeeded(tools._click_at(x, y, window=state["title"], observation=token))
    assert not state["clicks"]


def test_coordinate_click_emits_one_pair_only(desktop):
    state, _ = desktop
    token = observe(state)
    assert tool_succeeded(tools._click_at(100, 90, window=state["title"], observation=token))
    assert state["clicks"] == [0x0002, 0x0004]


def test_pointer_checks_focus_again_after_cursor_move(desktop, monkeypatch):
    state, api = desktop
    token = observe(state)
    monkeypatch.setattr(api, "SetCursorPos", lambda *args: state.update(foreground=99))
    assert not tool_succeeded(tools._click_at(100, 90, window=state["title"], observation=token))
    assert not state["clicks"]


def test_named_click_requires_full_window_and_unambiguous_control(desktop):
    state, _ = desktop
    assert not tool_succeeded(tools._click_ui("下一步", window="Editor", observation=observe(state)))
    state["items"].append({**state["items"][0], "key": "another", "x": 200})
    assert not tool_succeeded(tools._click_ui("下一步", window=state["title"], observation=observe(state)))
    assert not state["clicks"]
    state["items"].pop()
    assert tool_succeeded(tools._click_ui("下一步", window=state["title"], observation=observe(state)))
    assert len(state["clicks"]) == 2


def test_same_button_in_changed_page_cannot_reuse_approval(desktop):
    state, _ = desktop
    token = observe(state)
    state["items"].append({"n": "新的页面", "t": "Text", "x": 30, "y": 30, "key": "2.1"})
    assert not tool_succeeded(tools._click_ui("下一步", window=state["title"], observation=token))
    assert not state["clicks"]
    assert not tool_succeeded(tools._click_ui("下一步", window=state["title"], observation=token))


def test_desktop_tool_schemas_require_observed_targets():
    for name in ("click_at", "click_ui", "press_keys", "type_text"):
        assert {"window", "observation"}.issubset(tools.TOOLS[name].parameters["required"])
    assert "window" in tools.TOOLS["click_ui"].parameters["required"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows input guard")
def test_native_keyboard_guard_rejects_invalid_window_before_send(monkeypatch):
    calls = []
    def execute(command, **kwargs):
        calls.append(command)
        encoded = base64.b64encode(("[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + command).encode("utf-16-le")).decode("ascii")
        completed = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                                   capture_output=True, encoding="utf-8", errors="replace", timeout=20)
        return completed.returncode, completed.stdout + completed.stderr
    monkeypatch.setattr(tools, "_ps", execute)
    target = dict(title="fixture", identity=(0, 424242, 0.0))
    assert not tool_succeeded(tools._send_keys_to_target("{ENTER}", target, expected_text="test"))
    assert "GetForegroundWindow() -ne $h" in calls[0]
    assert calls[0].index("GetForegroundWindow() -ne $h") < calls[0].index("SendWait")
