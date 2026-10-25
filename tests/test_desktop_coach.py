from pathlib import Path

import pytest

from learning_ext.agent.desktop_coach import DesktopCoach


class FakeProcess:
    def __init__(self):
        self.terminated = False

    def poll(self):
        return 0 if self.terminated else None

    def wait(self, timeout=None):
        return self.poll()

    def terminate(self):
        self.terminated = True


@pytest.fixture
def desktop_runtime(monkeypatch):
    import learning_ext.agent.desktop_coach as module

    process = FakeProcess()
    calls = []
    state = {"typed": "", "checked": False, "undone": False}
    edit = {"t": "Edit", "n": "输入目标", "x": 100, "y": 100}

    def fake_popen(args):
        calls.append(("popen", args))
        return process

    def fake_find_window(title):
        calls.append(("find_window", title))
        return (0, "") if process.terminated else (123, "练习器")

    def fake_ui_items(_hwnd):
        items = [edit]
        if state["checked"]:
            items.append({"t": "Text", "n": f"已完成：{state['typed']}", "x": 400, "y": 160})
        if state["undone"]:
            items.append({"t": "Text", "n": "已撤销", "x": 400, "y": 160})
        return ("练习器", items), None

    def fake_execute(name, args):
        calls.append((name, args))
        if name == "click_ui":
            if args["text"] == "检查":
                state["checked"] = True
            if args["text"] == "撤销":
                state["undone"] = True
            return f"已点击「{args['text']}」。"
        raise AssertionError(name)

    def fake_goal_value(value=None):
        if value is not None:
            state["typed"] = value
        return state["typed"], ""

    def fake_request_close(hwnd):
        calls.append(("close_window", hwnd))
        process.terminate()
        return True

    def fail_ps(*args, **kwargs):
        raise AssertionError("不应访问剪贴板")

    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(module, "_find_window", fake_find_window)
    monkeypatch.setattr(module, "_ui_items", fake_ui_items)
    monkeypatch.setattr(module, "execute_tool", fake_execute)
    monkeypatch.setattr(module.DesktopCoach, "_request_close", staticmethod(fake_request_close))
    monkeypatch.setattr(module.DesktopCoach, "_goal_value", staticmethod(fake_goal_value))
    monkeypatch.setattr(module, "_ps", fail_ps)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    return module, process, calls, state


def test_desktop_observation_requires_owned_practice_window(desktop_runtime):
    module, process, calls, state = desktop_runtime
    coach = DesktopCoach()

    assert coach.observe()["ok"] is False
    assert calls == []


def test_desktop_close_targets_only_practice_window(desktop_runtime):
    module, process, calls, state = desktop_runtime
    coach = DesktopCoach()

    assert coach.launch(True)["ok"] is True
    assert coach.close()["ok"] is True
    assert ("close_window", 123) in calls
    assert not any(call[0] == "press_keys" for call in calls)


def test_desktop_launch_passes_fixed_polish_worker_paths(desktop_runtime):
    module, process, calls, state = desktop_runtime
    coach = DesktopCoach()

    assert coach.launch(True)["ok"] is True
    args = next(call[1] for call in calls if call[0] == "popen")
    assert args[args.index("-PolishPython") + 1] == module.sys.executable
    worker = Path(args[args.index("-PolishScript") + 1])
    assert worker == Path(module.__file__).resolve().parents[1] / "text_polish" / "native.py"
    assert worker.is_file()


def test_desktop_type_uses_uia_without_global_keyboard(desktop_runtime):
    module, process, calls, state = desktop_runtime
    coach = DesktopCoach()

    assert coach.launch(True)["ok"] is True
    assert coach.observe()["ok"] is True
    assert coach.type_goal("整理本周销售表", True)["ok"] is True
    assert state["typed"] == "整理本周销售表"
    assert not any(call[0] in {"type_text", "click_at", "press_keys"} for call in calls)


def test_desktop_type_rejects_mismatched_control_value(desktop_runtime, monkeypatch):
    module, process, calls, state = desktop_runtime
    coach = DesktopCoach()
    monkeypatch.setattr(module.DesktopCoach, "_goal_value", staticmethod(lambda value=None: ("", "")))

    assert coach.launch(True)["ok"] is True
    assert coach.observe()["ok"] is True
    result = coach.type_goal("整理本周销售表", True)
    assert result["ok"] is False
    assert "不一致" in result["message"]
    assert coach.step == 2


def test_desktop_actions_require_approval_and_preserve_order(desktop_runtime):
    module, process, calls, state = desktop_runtime
    coach = DesktopCoach()

    assert coach.launch(False)["ok"] is False
    assert not any(call[0] == "popen" for call in calls)
    assert coach.type_goal("任务", True)["ok"] is False
    assert coach.check(True)["ok"] is False
    assert coach.undo(True)["ok"] is False
    assert state["typed"] == ""


def test_full_desktop_flow_checks_real_window_state(desktop_runtime):
    module, process, calls, state = desktop_runtime
    coach = DesktopCoach()

    assert coach.launch(True)["ok"] is True
    assert coach.observe()["ok"] is True
    assert coach.type_goal("整理本周销售表", True)["ok"] is True
    assert coach.check(True)["ok"] is True
    assert coach.undo(True)["ok"] is True
    assert coach.close()["ok"] is True
    assert process.terminated is True
    assert state["typed"] == "整理本周销售表"
    assert not any(call[0] in {"type_text", "click_at", "press_keys"} for call in calls)
    assert ("click_ui", {"text": "检查", "window": coach.window_title}) in calls
    assert ("click_ui", {"text": "撤销", "window": coach.window_title}) in calls


def test_desktop_page_contains_real_mode_and_safe_back_action():
    from learning_ext.pages.coach_lesson import CoachLessonPage
    import inspect

    ui = inspect.getsource(CoachLessonPage.on_building_ui)
    events = inspect.getsource(CoachLessonPage.on_register_events)
    html = (Path("learning_ext/coach.py").read_text(encoding="utf-8"))

    assert 'elem_id="le-desktop-coach"' in ui
    assert "desktop_approve" in ui
    assert "desktop_back" in ui
    assert "desktop_mode.click" in events
    assert 'data-coach-course="desktop"' in html
    assert "desktop.close()" in inspect.getsource(CoachLessonPage._desktop_back)


def test_practice_window_script_has_windows_compatible_encoding():
    data = Path("learning_ext/agent/practice_window.ps1").read_bytes()
    script = data.decode("utf-8-sig")

    assert data.startswith(b"\xef\xbb\xbf")
    assert "检查" in script
    assert "撤销" in script
    assert 'AutomationProperties.AutomationId="GoalInput"' in script
