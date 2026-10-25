"""动手学的本地工具：真的能操作这台电脑。

设计要点：
* 每个工具 = JSON schema（给模型看）+ 一个 Python 执行器（返回纯文本）。
* 只读工具直接执行；`run_command` / `write_file` / `open_path` / `clipboard_set`
  由 safety 标记为需要确认，runtime 在非自动模式下会先暂停。
* 输出一律截断，避免一次 `dir /s` 把上下文撑爆。
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from learning_ext.agent.safety import blocked_reason, needs_approval
from learning_ext.agent.zcode_core import Capability, permission

MAX_OUTPUT = 6000
_REPO = Path(__file__).resolve().parents[2]
_SHOT_DIR = _REPO / "kotaemon" / "ktem_app_data" / "coach" / "shots"

# 关键：进程必须“感知 DPI”。否则界面元素报的是物理像素、而鼠标 API 走的是
# 缩放后的逻辑坐标，125%/150% 缩放的机器上点按钮会整体偏移（点 7 点到 4）。
if sys.platform == "win32":
    try:  # noqa: SIM105
        import ctypes as _ct

        try:
            _ct.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor aware
        except Exception:  # noqa: BLE001
            _ct.windll.user32.SetProcessDPIAware()
    except Exception:  # noqa: BLE001
        pass


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict
    handler: object

    def to_openai(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _cut(text: str, limit: int = MAX_OUTPUT) -> str:
    text = "" if text is None else str(text)
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…（已截断，共 {len(text)} 字符）"


def _ps(command: str, timeout: float = 30.0, cwd: str | None = None) -> tuple[int, str]:
    """在本机执行一条命令，返回 (退出码, 输出)。

    Windows 上走 powershell（能力比 cmd 完整），并把输出编码统一到 UTF-8；
    非 Windows 走 /bin/sh，方便以后跨平台。
    """
    if sys.platform == "win32":
        argv = [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; " + command,
        ]
    else:
        argv = ["/bin/sh", "-c", command]
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            timeout=timeout,
            cwd=cwd or str(Path.home()),
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return 124, f"命令超时（>{timeout:.0f}s）：{command}"
    except FileNotFoundError as exc:
        return 127, f"找不到可执行文件：{exc}"
    except Exception as exc:  # noqa: BLE001
        return 1, f"{type(exc).__name__}: {exc}"
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if err:
        out = (out + "\n[stderr]\n" + err).strip()
    return proc.returncode, out


# ---------------------------------------------------------------- 工具实现


def _run_command(command: str, cwd: str | None = None, timeout: float = 30) -> str:
    reason = blocked_reason(command)
    if reason:
        return f"已拒绝执行：这条命令被判定为「{reason}」，不在可执行范围内。"
    timeout = max(5.0, min(float(timeout or 30), 120.0))
    started = time.time()
    code, out = _ps(command, timeout=timeout, cwd=cwd)
    spent = time.time() - started
    if not out:
        out = "（无输出）"
    return f"退出码 {code} · 用时 {spent:.1f}s\n{_cut(out)}"


def _list_dir(path: str = ".") -> str:
    target = Path(path).expanduser()
    if not target.exists():
        return f"路径不存在：{target}"
    if target.is_file():
        return f"这是一个文件：{target}（{target.stat().st_size} 字节）"
    rows = []
    try:
        entries = sorted(
            target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())
        )
    except PermissionError:
        return f"没有权限读取：{target}"
    for item in entries[:200]:
        try:
            st = item.stat()
            kind = "目录" if item.is_dir() else "文件"
            size = "" if item.is_dir() else f" · {st.st_size:,} 字节"
            mtime = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
            rows.append(f"{kind:2s} {item.name}{size} · {mtime}")
        except OSError:
            rows.append(f"?? {item.name}")
    if not rows:
        return f"{target} 是空目录"
    more = "" if len(entries) <= 200 else f"\n…共 {len(entries)} 项，只列前 200 项"
    return f"{target}（{len(entries)} 项）\n" + "\n".join(rows) + more


def _read_file(path: str, max_chars: int = 16000) -> str:
    target = Path(path).expanduser()
    if not target.exists():
        return f"文件不存在：{target}"
    if target.is_dir():
        return f"这是目录，不是文件：{target}"
    try:
        raw = target.read_bytes()
    except PermissionError:
        return f"没有权限读取：{target}"
    if b"\x00" in raw[:4096]:
        return f"这是二进制文件（{len(raw):,} 字节），不按文本读取：{target}"
    for enc in ("utf-8", "gbk", "utf-8-sig"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    limit = max(1000, min(int(max_chars or 16000), 40000))
    return f"{target}（{len(text):,} 字符）\n" + _cut(text, limit)


def _write_file(path: str, content: str, mode: str = "overwrite") -> str:
    target = Path(path).expanduser()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if mode == "append" and target.exists():
            with target.open("a", encoding="utf-8") as fh:
                fh.write(content or "")
        else:
            target.write_text(content or "", encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return f"写入失败：{type(exc).__name__}: {exc}"
    size = target.stat().st_size
    verb = "追加到" if mode == "append" else "写入"
    return f"已{verb} {target}（现 {size:,} 字节）"


def _search_files(root: str, pattern: str, limit: int = 80) -> str:
    base = Path(root or ".").expanduser()
    if not base.exists():
        return f"路径不存在：{base}"
    limit = max(1, min(int(limit or 80), 500))
    hits: list[str] = []
    skipped = 0
    for item in base.rglob(pattern or "*"):
        try:
            if item.is_file():
                hits.append(f"{item}  ({item.stat().st_size:,} 字节)")
        except OSError:
            skipped += 1
        if len(hits) >= limit:
            break
    if not hits:
        return f"在 {base} 下没有匹配 {pattern} 的文件"
    tail = f"\n…只列前 {limit} 个" if len(hits) >= limit else ""
    if skipped:
        tail += f"（{skipped} 个无权限项已跳过）"
    return f"在 {base} 下匹配 {pattern}：{len(hits)} 个\n" + "\n".join(hits) + tail


def _open_path(path: str) -> str:
    target = Path(path).expanduser()
    if not target.exists():
        return f"路径不存在：{target}"
    try:
        if sys.platform == "win32":
            os.startfile(str(target))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(target)])  # noqa: S603
    except Exception as exc:  # noqa: BLE001
        return f"打开失败：{type(exc).__name__}: {exc}"
    return f"已用系统默认程序打开：{target}"


def _open_url(url: str) -> str:
    import webbrowser

    if not (url or "").startswith(("http://", "https://")):
        return "只接受 http/https 网址。"
    try:
        webbrowser.open(url)
    except Exception as exc:  # noqa: BLE001
        return f"打开失败：{type(exc).__name__}: {exc}"
    return f"已在默认浏览器打开：{url}"


def _screenshot() -> str:
    try:
        from PIL import ImageGrab
    except Exception as exc:  # noqa: BLE001
        return f"截图不可用（缺少 Pillow 图像抓取能力）：{exc}"
    try:
        _SHOT_DIR.mkdir(parents=True, exist_ok=True)
        img = ImageGrab.grab(all_screens=True)
        name = datetime.now().strftime("shot_%Y%m%d_%H%M%S.png")
        out = _SHOT_DIR / name
        img.save(out)
    except Exception as exc:  # noqa: BLE001
        return f"截图失败：{type(exc).__name__}: {exc}"
    return (
        f"已保存截图：{out}\n分辨率 {img.width}x{img.height}。"
        "（我看不到图像内容，只能保存文件给你看。）"
    )


def _system_info() -> str:
    try:
        import psutil
    except Exception:  # noqa: BLE001
        return "psutil 不可用，无法读取系统信息。"
    try:
        vm = psutil.virtual_memory()
        disk = psutil.disk_usage(str(Path.home().anchor or "/"))
        cpu = psutil.cpu_percent(interval=0.4)
        boot = datetime.fromtimestamp(psutil.boot_time()).strftime("%Y-%m-%d %H:%M")
        procs = []
        for proc in sorted(
            psutil.process_iter(["name", "memory_info"]),
            key=lambda p: getattr(p.info.get("memory_info"), "rss", 0) or 0,
            reverse=True,
        )[:6]:
            rss = getattr(proc.info.get("memory_info"), "rss", 0) or 0
            procs.append(f"{proc.info.get('name') or '?'} · {rss / 1048576:.0f} MB")
        return (
            f"系统：{sys.platform} · 主机名 {os.environ.get('COMPUTERNAME', '?')}\n"
            f"CPU：{psutil.cpu_count(logical=True)} 逻辑核，当前占用 {cpu:.0f}%\n"
            f"内存：{vm.used / 1073741824:.1f} / {vm.total / 1073741824:.1f} GB（{vm.percent:.0f}%）\n"
            f"磁盘：{disk.used / 1073741824:.0f} / {disk.total / 1073741824:.0f} GB（{disk.percent:.0f}%）\n"
            f"开机时间：{boot}\n"
            f"内存占用前 6 的进程：\n  " + "\n  ".join(procs)
        )
    except Exception as exc:  # noqa: BLE001
        return f"读取系统信息失败：{type(exc).__name__}: {exc}"


def _list_windows() -> str:
    code, out = _ps(
        "Get-Process | Where-Object { $_.MainWindowTitle } | "
        "Select-Object ProcessName,MainWindowTitle,Id | ConvertTo-Json -Compress",
        timeout=20,
    )
    if code != 0 or not out:
        return f"读取窗口列表失败（退出码 {code}）"
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return _cut(out)
    if isinstance(data, dict):
        data = [data]
    lines = [f"{d.get('ProcessName')} · {d.get('MainWindowTitle')} (pid {d.get('Id')})" for d in data]
    return f"当前有 {len(lines)} 个可见窗口：\n" + "\n".join(lines[:30])


def _clipboard_get() -> str:
    code, out = _ps("Get-Clipboard -Raw", timeout=15)
    if code != 0:
        return f"读取剪贴板失败（退出码 {code}）{out}"
    return f"剪贴板内容（{len(out)} 字符）：\n{_cut(out, 4000)}"


def _clipboard_set(text: str) -> str:
    blob = base64.b64encode((text or "").encode("utf-8")).decode("ascii")
    code, out = _ps(
        "$t=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"
        + blob
        + "')); Set-Clipboard -Value $t",
        timeout=15,
    )
    if code != 0:
        return f"写入剪贴板失败（退出码 {code}）{out}"
    return f"已写入剪贴板（{len(text or '')} 字符）"


# ---------------------------------------------------------------- 屏幕与操作

_UI_SCRIPT = r'''
$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$h = [IntPtr]__HWND__
if ($h -eq [IntPtr]::Zero) { '{"error":"没有窗口句柄"}'; exit }
try { $root = [System.Windows.Automation.AutomationElement]::FromHandle($h) }
catch { '{"error":"这个窗口不提供界面元素（多半是自绘界面）"}'; exit }
if ($root -eq $null) { '{"error":"这个窗口不提供界面元素"}'; exit }
$walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
$out = New-Object System.Collections.ArrayList
$script:left = 70
function Walk($el, $depth) {
  if ($depth -gt 4) { return }
  $child = $walker.GetFirstChild($el)
  while ($child -ne $null) {
    if ($script:left -le 0) { return }
    try {
      $name = $child.Current.Name
      $type = $child.Current.ControlType.ProgrammaticName -replace 'ControlType\.',''
      $r = $child.Current.BoundingRectangle
      if ($name -and $r.Width -gt 0) {
        $script:left--
        [void]$out.Add([pscustomobject]@{ t=$type; n=$name; x=[int]($r.X+$r.Width/2); y=[int]($r.Y+$r.Height/2) })
      }
    } catch {}
    Walk $child ($depth+1)
    $child = $walker.GetNextSibling($child)
  }
}
Walk $root 0
@{ window=$root.Current.Name; items=@($out) } | ConvertTo-Json -Depth 4 -Compress
'''


def _win_api():
    import ctypes

    return ctypes.windll.user32


def _foreground():
    """返回 (hwnd, 标题)。"""
    h = _win_api().GetForegroundWindow()
    buf = None
    try:
        import ctypes

        buf = ctypes.create_unicode_buffer(512)
        _win_api().GetWindowTextW(h, buf, 512)
    except Exception:  # noqa: BLE001
        pass
    return int(h), (buf.value if buf else "")


def _window_rect(hwnd: int):
    import ctypes

    class RECT(ctypes.Structure):
        _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]

    r = RECT()
    if _win_api().GetWindowRect(hwnd, ctypes.byref(r)):
        return r.l, r.t, r.r - r.l, r.b - r.t
    return None


def _observe_screen() -> str:
    try:
        import ctypes

        hwnd, title = _foreground()
        w = _win_api().GetSystemMetrics(0)
        h = _win_api().GetSystemMetrics(1)

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        pt = POINT()
        _win_api().GetCursorPos(ctypes.byref(pt))

        pid = ctypes.c_ulong()
        _win_api().GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc = "?"
        try:
            import psutil

            proc = psutil.Process(pid.value).name()
        except Exception:  # noqa: BLE001
            pass

        rect = _window_rect(hwnd)
        lines = [
            f"前台窗口：{title or '（无标题）'}",
            f"进程：{proc}（pid {pid.value}）",
        ]
        if rect:
            lines.append(f"窗口位置：{rect[0]},{rect[1]} 大小 {rect[2]}x{rect[3]}")
        lines.append(f"屏幕：{w}x{h}")
        lines.append(f"鼠标：{pt.x},{pt.y}")
        lines.append("（我看不到画面像素；要知道窗口里有哪些按钮/输入框，调 read_ui）")
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        return f"读取屏幕状态失败：{type(exc).__name__}: {exc}"


def _find_window(title_part: str):
    """按标题片段找窗口句柄（找不到返回 0）。"""
    import ctypes

    target = (title_part or "").lower()
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def _cb(hwnd, _):
        if not _win_api().IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(512)
        _win_api().GetWindowTextW(hwnd, buf, 512)
        if buf.value and target in buf.value.lower():
            found.append((int(hwnd), buf.value))
            return False
        return True

    _win_api().EnumWindows(_cb, 0)
    return found[0] if found else (0, "")


def _ui_items(hwnd: int):
    """取窗口的控件清单，返回 ((窗口名, items) | None, 错误说明 | None)。"""
    if not hwnd:
        return None, "没有可读的窗口"
    code, out = _ps(_UI_SCRIPT.replace("__HWND__", str(int(hwnd))), timeout=45)
    if code != 0 or not out:
        return None, f"读取界面元素失败（退出码 {code}）：{_cut(out, 300)}"
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None, _cut(out)
    if isinstance(data, dict) and data.get("error"):
        return None, str(data["error"])
    return (data.get("window") or "", data.get("items") or []), None


def _read_ui(window: str = "") -> str:
    """把某个窗口里的控件（按钮/输入框/菜单）连同坐标列出来。"""
    try:
        if window:
            hwnd, title = _find_window(window)
            if not hwnd:
                return f"没找到标题包含「{window}」的窗口。先用 observe_screen 或 list_windows 看看有哪些窗口。"
        else:
            hwnd, title = _foreground()
        if not hwnd:
            return "当前没有前台窗口。"

        data, err = _ui_items(hwnd)
        if err:
            return f"「{title}」：{err}（很多自绘界面应用会这样，比如微信）"
        win_name, items = data
        if not items:
            return f"「{win_name or title}」里没有可识别的标准控件（可能是自绘界面）。想要精确操作就截图看看，或者改用键盘快捷键。"
        lines = [f"{it.get('t')}「{it.get('n')}」坐标 {it.get('x')},{it.get('y')}" for it in items]
        return (
            f"窗口「{win_name or title}」共 {len(lines)} 个元素（坐标是中心点，可给 click_at；"
            f"但更稳的是直接用 click_ui 按名字点）：\n" + "\n".join(lines)
        )
    except Exception as exc:  # noqa: BLE001
        return f"读取界面元素出错：{type(exc).__name__}: {exc}"


def _click_ui(text: str, window: str = "") -> str:
    """按控件名字找到它并立刻点下去（读坐标与点击在同一口气里完成，避免窗口移位导致点错）。"""
    target = (text or "").strip()
    if not target:
        return "要点击哪个控件？把按钮上的文字告诉我。"
    try:
        if window:
            hwnd, title = _find_window(window)
        else:
            hwnd, title = _foreground()
        if not hwnd:
            return "当前没有前台窗口。"

        # 先把目标窗口提到最前，否则点击会落到别的窗口上
        try:
            _win_api().SetForegroundWindow(hwnd)
            time.sleep(0.35)
        except Exception:  # noqa: BLE001
            pass

        data, err = _ui_items(hwnd)
        if err:
            return f"读不到「{title}」的控件：{err}"
        win_name, items = data
        if not items:
            return f"「{win_name or title}」里没有可识别的标准控件，没法按名字点。改用键盘或截图。"
        low = target.lower()
        exact = [it for it in items if (it.get("n") or "").strip() == target]
        partial = [it for it in items if low in (it.get("n") or "").lower()]
        pick = (exact or partial or [None])[0]
        if not pick:
            names = "、".join(f"「{it.get('n')}」" for it in items[:20])
            return f"「{win_name or title}」里没有叫「{target}」的控件。可选的有：{names}"
        x, y = int(pick.get("x") or 0), int(pick.get("y") or 0)
        _click_at(x, y)
        time.sleep(0.3)
        return f"已点击「{pick.get('n')}」（{x},{y}）。"
    except Exception as exc:  # noqa: BLE001
        return f"点击控件出错：{type(exc).__name__}: {exc}"


def _click_at(x: float, y: float, button: str = "left") -> str:
    try:
        import ctypes

        u = _win_api()
        u.SetCursorPos(int(x), int(y))
        time.sleep(0.15)
        down, up = (0x0008, 0x0010) if str(button).lower() == "right" else (0x0002, 0x0004)
        u.mouse_event(down, 0, 0, 0, 0)
        time.sleep(0.05)
        u.mouse_event(up, 0, 0, 0, 0)
        return f"已在 ({int(x)}, {int(y)}) 点击{('右键' if down == 0x0008 else '左键')}。"
    except Exception as exc:  # noqa: BLE001
        return f"点击失败：{type(exc).__name__}: {exc}"


def _press_keys(keys: str) -> str:
    """发送按键组合，语法同 SendKeys：^ 是 Ctrl，% 是 Alt，{ENTER} / {TAB} / {ESC}。"""
    safe = (keys or "").replace("'", "''")
    code, out = _ps(
        "Add-Type -AssemblyName System.Windows.Forms; "
        f"[System.Windows.Forms.SendKeys]::SendWait('{safe}'); 'sent'",
        timeout=20,
    )
    if code != 0:
        return f"按键发送失败（退出码 {code}）：{out[:200]}"
    return f"已发送按键：{keys}"


def _type_text(text: str) -> str:
    """用剪贴板粘贴输入，中文和符号都可靠。注意会覆盖剪贴板。"""
    if not text:
        return "没有要输入的内容。"
    _clipboard_set(text)
    time.sleep(0.12)
    return _press_keys("^v")


def _launch_app(target: str) -> str:
    if not (target or "").strip():
        return "要启动什么？给个程序名或路径。"
    safe = target.replace("'", "''")
    # 裸名字（notepad、calc）要先走 PATH 解析；直接 Start-Process 会被交给浏览器搜索
    cmd = (
        "Add-Type -AssemblyName Microsoft.VisualBasic; "
        f"$t = '{safe}'; $src = $null; "
        "if ($t -match '^[A-Za-z][A-Za-z0-9+.-]*:') { $src = $t } "
        "elseif (Test-Path -LiteralPath $t) { $src = (Resolve-Path -LiteralPath $t).Path } "
        "else { $c = Get-Command $t -ErrorAction SilentlyContinue; if ($c) { $src = $c.Source } else { $src = $t } }; "
        "$p = Start-Process -FilePath $src -PassThru -ErrorAction Stop; "
        "Start-Sleep -Milliseconds 1200; "
        "try { [Microsoft.VisualBasic.Interaction]::AppActivate($p.Id) } catch { }; "
        "$src + '|' + $p.ProcessName"
    )
    code, out = _ps(cmd, timeout=30)
    if code != 0 or "|" not in (out or ""):
        return f"启动失败：{_cut(out or '没有返回信息', 300)}"
    time.sleep(0.8)
    src, _, name = (out or "").partition("|")
    _, title = _foreground()
    head = f"已启动 {name or target}"
    if src and src.lower() != str(target).lower():
        head += f"（解析为 {src}）"
    return f"{head}。当前前台窗口：{title or '（还没切过来，可能被别的窗口挡着）'}"


# ---------------------------------------------------------------- 注册表

_NO_ARGS = {"type": "object", "properties": {}}


def _inspect_learning_environment(task):
    from learning_ext.environment_agent.service import audited_exploration
    if not isinstance(task, str) or not 1 <= len(task) <= 18000:
        raise ValueError("请提供当前学习任务")
    return json.dumps(audited_exploration(task), ensure_ascii=False)

TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in [
        ToolSpec("inspect_learning_environment", "根据当前学习任务探索本机的软件、终端命令和版本，只读检查并保留证据，不安装或修改配置。",
                 {"type": "object", "properties": {"task": {"type": "string", "description": "学习目标、当前课节和已明确的工具要求"}}, "required": ["task"], "additionalProperties": False},
                 _inspect_learning_environment),
        ToolSpec(
            "run_command",
            "在这台电脑上执行一条命令行（Windows 默认走 powershell）。可以装包、运行脚本、"
            "查询系统、调用任意 CLI 工具。返回退出码与实际输出。",
            {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的命令"},
                    "cwd": {"type": "string", "description": "工作目录，默认用户主目录"},
                    "timeout": {"type": "number", "description": "超时秒数，默认 30，最大 120"},
                },
                "required": ["command"],
            },
            _run_command,
        ),
        ToolSpec(
            "list_dir",
            "列出目录内容（名称、类型、大小、修改时间）。",
            {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "目录路径，默认当前目录"}},
            },
            _list_dir,
        ),
        ToolSpec(
            "read_file",
            "读取文本文件内容。二进制文件会被拒绝。",
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "max_chars": {"type": "integer", "description": "最多读取字符数，默认 16000"},
                },
                "required": ["path"],
            },
            _read_file,
        ),
        ToolSpec(
            "write_file",
            "写入文本文件（会创建父目录）。",
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "content": {"type": "string", "description": "写入内容"},
                    "mode": {
                        "type": "string",
                        "enum": ["overwrite", "append"],
                        "description": "覆盖或追加，默认 overwrite",
                    },
                },
                "required": ["path", "content"],
            },
            _write_file,
        ),
        ToolSpec(
            "search_files",
            "在目录下按文件名通配符递归搜索，例如 *.py、报告*.docx。",
            {
                "type": "object",
                "properties": {
                    "root": {"type": "string", "description": "搜索起点目录"},
                    "pattern": {"type": "string", "description": "通配符，例如 *.md"},
                    "limit": {"type": "integer", "description": "最多返回条数，默认 80"},
                },
                "required": ["root", "pattern"],
            },
            _search_files,
        ),
        ToolSpec(
            "open_path",
            "用系统默认程序打开文件或文件夹（相当于双击）。",
            {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "文件或文件夹路径"}},
                "required": ["path"],
            },
            _open_path,
        ),
        ToolSpec(
            "open_url",
            "在默认浏览器打开网址。",
            {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "http/https 网址"}},
                "required": ["url"],
            },
            _open_url,
        ),
        ToolSpec(
            "screenshot",
            "截取整个屏幕并保存为 PNG，返回文件路径与分辨率。注意：你看不到图像内容本身。",
            _NO_ARGS,
            _screenshot,
        ),
        ToolSpec("system_info", "读取 CPU、内存、磁盘、开机时间与占用最高的进程。", _NO_ARGS, _system_info),
        ToolSpec("list_windows", "列出当前打开的可见窗口（进程名 + 窗口标题）。", _NO_ARGS, _list_windows),
        ToolSpec("clipboard_get", "读取剪贴板文本。", _NO_ARGS, _clipboard_get),
        ToolSpec(
            "clipboard_set",
            "把文本写入剪贴板。",
            {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "要复制的文本"}},
                "required": ["text"],
            },
            _clipboard_set,
        ),
        ToolSpec(
            "observe_screen",
            "看一眼当前电脑状态：前台是哪个窗口、什么程序、窗口位置、屏幕分辨率和鼠标坐标。"
            "动手前先调它，别凭空猜用户屏幕上是什么。",
            _NO_ARGS,
            _observe_screen,
        ),
        ToolSpec(
            "read_ui",
            "列出某个窗口里的可操作控件（按钮、输入框、菜单项）及其中心坐标。"
            "用来知道「该点哪里」。很多自绘界面（微信、部分游戏）读不出内容，属正常。",
            {
                "type": "object",
                "properties": {
                    "window": {
                        "type": "string",
                        "description": "窗口标题片段，留空则读当前前台窗口",
                    }
                },
            },
            _read_ui,
        ),
        ToolSpec(
            "click_at",
            "在屏幕坐标处点击鼠标。坐标一般来自 read_ui 给出的元素中心。",
            {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "横坐标"},
                    "y": {"type": "integer", "description": "纵坐标"},
                    "button": {
                        "type": "string",
                        "enum": ["left", "right"],
                        "description": "左键或右键，默认 left",
                    },
                },
                "required": ["x", "y"],
            },
            _click_at,
        ),
        ToolSpec(
            "click_ui",
            "按控件上的文字找到按钮/菜单项并直接点下去。优先用这个：比 read_ui 拿坐标再 click_at 稳，"
            "不会因为窗口移位点错。例：「保存」「下一步」「七」。",
            {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "控件上的文字（按钮名、菜单项名）"},
                    "window": {
                        "type": "string",
                        "description": "窗口标题片段，留空则用当前前台窗口",
                    },
                },
                "required": ["text"],
            },
            _click_ui,
        ),
        ToolSpec(
            "press_keys",
            "按下按键或快捷键。语法：^ 是 Ctrl、% 是 Alt、+ 是 Shift，"
            "特殊键用花括号，如 {ENTER} {TAB} {ESC} {F2} {DEL}。"
            "例：^s 保存、%{TAB} 切窗口、^%{T} 打开任务管理器。",
            {
                "type": "object",
                "properties": {"keys": {"type": "string", "description": "按键序列"}},
                "required": ["keys"],
            },
            _press_keys,
        ),
        ToolSpec(
            "type_text",
            "往当前焦点里输入一段文字（通过剪贴板粘贴，中文和符号都可靠）。会覆盖剪贴板。",
            {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "要输入的文字"}},
                "required": ["text"],
            },
            _type_text,
        ),
        ToolSpec(
            "launch_app",
            "启动一个程序或打开系统设置页。可以写程序名（notepad、calc、explorer）、"
            "协议（ms-settings:、ms-settings:display）或完整路径。",
            {
                "type": "object",
                "properties": {"target": {"type": "string", "description": "程序名、协议或路径"}},
                "required": ["target"],
            },
            _launch_app,
        ),
        ToolSpec(
            "update_plan",
            "把「接下来要一步步怎么做」写成清单推到用户界面上，并标记当前进行到第几步（从 0 开始）。"
            "开工前先列一次，之后每完成一步更新一次 index。",
            {
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "步骤文字，每步一句话",
                    },
                    "index": {
                        "type": "integer",
                        "description": "当前进行到第几步（0 起），全部完成时传步骤数",
                    },
                },
                "required": ["steps"],
            },
            lambda steps=None, index=0: "计划已推送到界面。",
        ),
    ]
}


def build_tool_specs() -> list[dict]:
    """给模型的工具清单（含 MCP 工具，若配置了服务器）。"""
    specs = [t.to_openai() for t in TOOLS.values()]
    try:
        from learning_ext.agent.mcp_bridge import mcp_tool_specs

        specs.extend(mcp_tool_specs())
    except Exception:  # noqa: BLE001
        pass
    return specs


def tool_needs_approval(name: str) -> bool:
    if name in TOOLS:
        ask = needs_approval(name)
        decision, _ = permission(Capability(read_only=not ask, scope="system" if ask else "none", needs_approval=ask), plan=False)
        return decision != "allow"
    return True  # MCP 工具来源不可控，一律确认


def execute_tool(name: str, args: dict) -> str:
    """执行工具，任何异常都转成文本返回给模型，绝不让整轮对话崩掉。"""
    args = args or {}
    if name.startswith("mcp__"):
        try:
            from learning_ext.agent.mcp_bridge import mcp_call

            return mcp_call(name, args)
        except Exception as exc:  # noqa: BLE001
            return f"MCP 工具执行失败：{type(exc).__name__}: {exc}"
    spec = TOOLS.get(name)
    if not spec:
        return f"未知工具：{name}"
    try:
        return spec.handler(**args)
    except TypeError as exc:
        return f"参数不匹配：{exc}"
    except Exception as exc:  # noqa: BLE001
        return f"执行出错：{type(exc).__name__}: {exc}"


def tool_titles() -> dict[str, str]:
    """给前端的中文名。"""
    return {
        "inspect_learning_environment": "检查学习环境",
        "run_command": "执行命令",
        "list_dir": "列出目录",
        "read_file": "读取文件",
        "write_file": "写入文件",
        "search_files": "搜索文件",
        "open_path": "打开文件",
        "open_url": "打开网址",
        "screenshot": "截屏",
        "system_info": "系统信息",
        "list_windows": "窗口列表",
        "clipboard_get": "读剪贴板",
        "clipboard_set": "写剪贴板",
        "observe_screen": "看当前屏幕",
        "read_ui": "读取界面控件",
        "click_ui": "点击控件",
        "click_at": "鼠标点击",
        "press_keys": "按键",
        "type_text": "输入文字",
        "launch_app": "启动程序",
        "update_plan": "更新步骤",
    }
