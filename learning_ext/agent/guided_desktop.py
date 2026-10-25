from __future__ import annotations

import base64
import ctypes
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import queue
import threading

from learning_ext.agent.tools import _ps

SCRIPT = Path(__file__).with_name("guided_controls.ps1")
RISKY = re.compile(r"删除|移除|清空|格式化|支付|购买|转账|发送|发布|提交|授权|权限|登录|退出|关闭|安装|卸载|运行|执行|终端|控制台|delete|remove|erase|format|pay|buy|send|publish|submit|allow|permission|sign.?in|log.?in|close|install|uninstall|run|execute|terminal|console", re.I)
_OVERLAYS = {}


def windows():
    if sys.platform != "win32":
        raise ValueError("电脑引导目前支持 Windows。")
    import psutil

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    result = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def collect(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        name = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, name, 512)
        if not name.value:
            return True
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            proc = psutil.Process(pid.value)
            result.append(dict(hwnd=int(hwnd), pid=pid.value, started=proc.create_time(),
                               title=name.value, process=proc.name()))
        except (psutil.Error, OSError):
            pass
        return True

    user32.EnumWindows(collect, 0)
    return result


def validate_window(window):
    current = next((item for item in windows() if item["hwnd"] == window["hwnd"]), None)
    if not current or any(current[key] != window[key] for key in ("pid", "started", "title")):
        raise ValueError("窗口已关闭或改变，请重新选择并定位。")
    return current


def _payload(window, mode, item=None):
    data = dict(window=window, mode=mode, item=item)
    return base64.b64encode(json.dumps(data, ensure_ascii=False).encode()).decode()


def _call(window, mode, item=None):
    validate_window(window)
    payload = _payload(window, mode, item)
    path = str(SCRIPT).replace("'", "''")
    code, output = _ps(f"& '{path}' -Payload '{payload}'", timeout=25)
    if code:
        raise ValueError("无法读取或操作这个窗口，请重新定位；某些软件不提供标准控件。")
    try:
        result = json.loads(output)
    except (TypeError, json.JSONDecodeError):
        raise ValueError("窗口没有返回可识别的控件。") from None
    if result.get("error"):
        raise ValueError(result["error"])
    return result


def observe(window):
    result = _call(window, "observe")
    items = result.get("items") or []
    if not items:
        raise ValueError("没有识别到标准控件。可以继续查看文字提示，或换一个窗口。")
    return dict(window=window, items=items, observed=time.time())


def stop_highlight(session_id):
    proc = _OVERLAYS.pop(session_id, None)
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()


def highlight(session_id, window, item):
    _call(window, "resolve", item)
    stop_highlight(session_id)
    proc = subprocess.Popen(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
         "-Payload", _payload(window, "highlight", item)],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8", errors="replace",
    )
    _OVERLAYS[session_id] = proc
    ready = queue.Queue()
    threading.Thread(target=lambda: ready.put(proc.stdout.readline()), daemon=True).start()
    try:
        marker = ready.get(timeout=8).strip()
    except queue.Empty:
        marker = ""
    if marker != "READY":
        stop_highlight(session_id)
        raise ValueError("圈选层未能显示，请重新定位或改用文字提示。")
    return proc


def can_operate(window, item):
    return (bool(item.get("action")) and item.get("type") in {"Button", "CheckBox", "RadioButton", "TabItem", "TreeItem", "ComboBox"}
            and not RISKY.search(item.get("name", "") + " " + window.get("title", "")))


def operate(window, item):
    if not can_operate(window, item):
        raise ValueError("这个控件只提供定位，请你亲自操作。")
    return _call(window, "operate", item)
