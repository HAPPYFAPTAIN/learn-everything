from __future__ import annotations

import base64
import logging
import subprocess
import sys
import time
import uuid
from pathlib import Path

from learning_ext.agent.tools import (
    _find_window,
    _ps,
    _ui_items,
    execute_tool,
)


class DesktopCoach:
    def __init__(self):
        self.process = None
        self.window_title = ""
        self.step = 0

    def _result(self, ok, message, details=""):
        logging.getLogger(__name__).info("[动手学桌面练习] step=%s ok=%s %s", self.step, ok, message)
        return {"ok": ok, "step": self.step, "message": message, "details": details}

    def _hwnd(self):
        if not self.window_title or self.process is None or self.process.poll() is not None:
            return 0
        return _find_window(self.window_title)[0]

    def _items(self):
        hwnd = self._hwnd()
        if not hwnd:
            return None, "练习器未启动或已经关闭"
        data, error = _ui_items(hwnd)
        if error:
            return None, error
        _, items = data
        if not items:
            return None, "还没有读到窗口控件"
        return items, ""

    def _goal_value(self, value=None):
        hwnd = self._hwnd()
        if not hwnd:
            return None, "练习器未启动或已经关闭"
        set_value = ""
        if value is not None:
            blob = base64.b64encode(value.encode("utf-8")).decode("ascii")
            set_value = (
                f"$value=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{blob}')); "
                "$pattern.SetValue($value); "
            )
        command = (
            "$ErrorActionPreference='Stop'; "
            "Add-Type -AssemblyName UIAutomationClient; "
            "Add-Type -AssemblyName UIAutomationTypes; "
            f"$root=[System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]{int(hwnd)}); "
            "$condition=[System.Windows.Automation.PropertyCondition]::new("
            "[System.Windows.Automation.AutomationElement]::AutomationIdProperty,'GoalInput'); "
            "$edit=$root.FindFirst([System.Windows.Automation.TreeScope]::Descendants,$condition); "
            "if ($null -eq $edit) { throw '找不到任务输入框' }; "
            "$pattern=$edit.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern); "
            + set_value
            + "[Console]::Out.Write($pattern.Current.Value)"
        )
        code, actual = _ps(command, timeout=20)
        if code != 0:
            return None, f"无法读写任务输入框：{actual[:160]}"
        return actual, ""

    @staticmethod
    def _request_close(hwnd):
        import ctypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.PostMessageW.argtypes = (
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
        )
        user32.PostMessageW.restype = ctypes.c_bool
        return bool(user32.PostMessageW(hwnd, 0x0010, 0, 0))

    @staticmethod
    def _approved(approved):
        return bool(approved)

    def launch(self, approved):
        if not self._approved(approved):
            return self._result(False, "先勾选允许，再启动桌面练习器")
        if self.process is not None and self.process.poll() is None:
            return self._result(False, "练习器已经在运行，请先关闭再重新启动")
        script = Path(__file__).with_name("practice_window.ps1")
        self.window_title = f"动手学桌面练习器-{uuid.uuid4().hex[:8]}"
        try:
            self.process = subprocess.Popen(
                [
                    "powershell",
                    "-NoProfile",
                    "-WindowStyle",
                    "Hidden",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-Title",
                    self.window_title,
                    "-PolishPython",
                    sys.executable,
                    "-PolishScript",
                    str(Path(__file__).resolve().parents[1] / "text_polish" / "native.py"),
                ]
            )
        except Exception as exc:
            return self._result(False, f"练习器启动失败：{exc}")
        time.sleep(1.5)
        items, error = self._items()
        if error:
            self.close()
            return self._result(False, error)
        self.step = 1
        names = "、".join(f"「{item.get('n')}」" for item in items[:8])
        return self._result(True, "独立桌面练习器已启动，可以读取控件。", names)

    def observe(self):
        items, error = self._items()
        if error:
            return self._result(False, error)
        self.step = max(self.step, 2)
        lines = [
            f"{item.get('t')}「{item.get('n')}」坐标 {item.get('x')},{item.get('y')}"
            for item in items[:12]
        ]
        return self._result(True, "已读取窗口控件，可以输入任务文字。", "\n".join(lines))

    def type_goal(self, goal, approved):
        if not self._approved(approved):
            return self._result(False, "先勾选允许，再输入任务文字")
        if self.step < 2:
            return self._result(False, "先启动练习器并读取窗口控件")
        goal = (goal or "").strip()
        if not goal:
            return self._result(False, "先写下要输入的任务文字")
        value, error = self._goal_value(goal)
        if error:
            return self._result(False, error)
        if value != goal:
            return self._result(False, "输入框内容与任务文字不一致，请重试")
        self.step = 3
        return self._result(True, "任务文字已输入，可以执行检查。", "已读取并核对输入框内容")

    def check(self, approved):
        if not self._approved(approved):
            return self._result(False, "先勾选允许，再点击检查按钮")
        if self.step < 3:
            return self._result(False, "先输入任务文字")
        result = execute_tool("click_ui", {"text": "检查", "window": self.window_title})
        if "已点击" not in result:
            return self._result(False, result)
        items, error = self._items()
        if error:
            return self._result(False, error)
        status = next((str(item.get("n") or "") for item in items if str(item.get("n") or "").startswith("已完成：")), "")
        if not status:
            return self._result(False, "没有看到完成状态，检查尚未通过")
        self.step = 4
        return self._result(True, "检查已通过，可以撤销。", status)

    def undo(self, approved):
        if not self._approved(approved):
            return self._result(False, "先勾选允许，再点击撤销")
        if self.step < 4:
            return self._result(False, "先完成一次检查，再撤销")
        result = execute_tool("click_ui", {"text": "撤销", "window": self.window_title})
        if "已点击" not in result:
            return self._result(False, result)
        items, error = self._items()
        if error:
            return self._result(False, error)
        if not any(str(item.get("n") or "") == "已撤销" for item in items):
            return self._result(False, "没有看到撤销后的状态")
        self.step = 5
        return self._result(True, "已撤销本次输入，可以关闭练习器。", "已撤销")

    def close(self):
        process = self.process
        if process is None:
            self.step = 6
            return self._result(True, "桌面练习器已关闭。", "")
        title = self.window_title
        try:
            hwnd, _ = _find_window(title)
            if hwnd and not self._request_close(hwnd):
                return self._result(False, "无法向练习器发送关闭请求，请重试")
        except Exception as exc:
            return self._result(False, f"练习器关闭失败：{exc}")
        for _ in range(20):
            if process.poll() is not None:
                break
            time.sleep(0.1)
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            return self._result(False, "练习器未响应关闭，请重试")
        if _find_window(title)[0]:
            return self._result(False, "练习器窗口仍然存在，尚未确认关闭")
        self.process = None
        self.step = 6
        return self._result(True, "桌面练习器已关闭。", "")
