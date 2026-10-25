from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version


ROOT = Path(__file__).resolve().parents[2]
TOOLS = {
    "python": ("Python", r"\bpython\b", ["--version"]),
    "git": ("Git", r"\bgit\b", ["--version"]),
    "node": ("Node.js", r"\bnode(?:\.js|js)?\b", ["--version"]),
    "go": ("Go", r"\bgolang\b|\bgo\s*(?:语言|[1-9]\.)", ["version"]),
    "java": ("Java", r"\bjava\b|\bjdk\b", ["-version"]),
    "docker": ("Docker", r"\bdocker\b", ["--version"]),
    "code": ("VS Code", r"\bvs\s*code\b|\bvisual studio code\b", []),
    "excel": ("Microsoft Excel", r"(?<![a-z])excel(?![a-z])|微软表格", []),
    "wps": ("WPS 表格", r"(?<![a-z])wps(?![a-z])|金山表格", []),
    "libreoffice": ("LibreOffice Calc", r"(?<![a-z])libreoffice(?![a-z])|(?<![a-z])calc(?![a-z])", []),
}
OFFICE_KEYS = {"excel", "wps", "libreoffice"}


def _app_paths(key):
    if os.name != "nt":
        return []
    import winreg
    executables = {"excel": "excel.exe", "wps": "et.exe", "libreoffice": "scalc.exe", "code": "Code.exe"}
    exe = executables.get(key)
    if not exe:
        return []
    paths = []
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\" + exe, 0, winreg.KEY_READ | view) as entry:
                    value = winreg.QueryValueEx(entry, "")[0]
                    if isinstance(value, str):
                        paths.append(Path(os.path.expandvars(value.strip('"'))))
            except OSError:
                pass
    return paths


def _file_version(path):
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes
    library = ctypes.windll.version
    library.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    library.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    library.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
    size = library.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return None
    data = ctypes.create_string_buffer(size)
    if not library.GetFileVersionInfoW(str(path), 0, size, data):
        return None
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    if not library.VerQueryValueW(data, "\\", ctypes.byref(pointer), ctypes.byref(length)) or length.value < 52:
        return None
    fields = ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD))
    if fields[0] != 0xFEEF04BD:
        return None
    return f"{fields[2] >> 16}.{fields[2] & 0xffff}.{fields[3] >> 16}.{fields[3] & 0xffff}"


def requirements(text):
    result = []
    for key, (name, pattern, _) in TOOLS.items():
        if not re.search(pattern, text, re.I):
            continue
        specs = []
        for match in re.finditer(r"(?:" + pattern + r")\s*(?:版本\s*)?(>=|<=|>|<|==|≥|≤)?\s*(\d+\.\d+(?:\.\d+)?)(\s*\+|\s*及以上|\s*以上|\s*或更高)?", text, re.I):
            op, version, suffix = match.groups()
            op = {"≥": ">=", "≤": "<="}.get(op, op)
            specs.append((op or (">=" if suffix else "==")) + version + (".*" if not op and not suffix else ""))
        result.append({"key": key, "name": name, "spec": ",".join(dict.fromkeys(specs))})
    if not any(item["key"] in OFFICE_KEYS for item in result) and re.search(r"电子表格|办公表格", text):
        result.append({"key": "excel", "name": "Microsoft Excel", "spec": ""})
    return result


def _candidate_paths(key):
    names = [key + ".exe"] if os.name == "nt" else [key]
    if key == "python" and os.name != "nt":
        names.insert(0, "python3")
    paths = [Path(path) for name in names if (path := shutil.which(name))]
    paths.extend(_app_paths(key))
    if os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        program = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        if key == "python":
            paths.extend((local / "Programs/Python").glob("Python*/python.exe"))
            paths.extend(program.glob("Python*/python.exe"))
        elif key == "code":
            paths.extend([local / "Programs/Microsoft VS Code/Code.exe", program / "Microsoft VS Code/Code.exe"])
        elif key in OFFICE_KEYS:
            roots = [program, Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")), local]
            patterns = {"excel": ["Microsoft Office/root/Office*/EXCEL.EXE", "Microsoft Office/Office*/EXCEL.EXE"],
                        "wps": ["Kingsoft/WPS Office/*/office6/et.exe", "Kingsoft/WPS Office/office6/et.exe", "Kingsoft/office6/et.exe"],
                        "libreoffice": ["LibreOffice*/program/scalc.exe"]}
            for root in roots:
                for pattern in patterns[key]:
                    paths.extend(root.glob(pattern))
        else:
            known = {"git": "Git/cmd/git.exe", "node": "nodejs/node.exe", "go": "Go/bin/go.exe", "docker": "Docker/Docker/resources/bin/docker.exe"}
            if key in known:
                paths.append(program / known[key])
    candidates = []
    for path in paths:
        if str(path).startswith(("\\\\", "//")):
            continue
        path = path.resolve()
        if not path.is_file() or ROOT in path.parents or "windowsapps" in str(path).lower():
            continue
        if (path.parent.parent / "pyvenv.cfg").exists():
            continue
        if path not in candidates:
            candidates.append(path)
    return candidates[:6]


def _run(args):
    env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}}
    try:
        result = subprocess.run(args, shell=False, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=4, cwd=tempfile.gettempdir(), env=env,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return (result.stdout + "\n" + result.stderr).strip()[:2000] if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _probe(requirement):
    key = requirement["key"]
    result = {**requirement, "status": "missing", "version": "", "detail": "未在常用安装位置找到，需确认或安装"}
    for path in _candidate_paths(key):
        if key in OFFICE_KEYS:
            output = _file_version(path)
        elif key == "code":
            package = path.parent / "resources/app/package.json"
            try:
                output = str(json.loads(package.read_text(encoding="utf-8"))["version"])
            except (OSError, ValueError, KeyError):
                output = _file_version(path)
        else:
            output = _run([str(path), *TOOLS[key][2]])
        if output is None:
            result.update(status="unknown", detail="已找到程序，但版本检查未成功")
            continue
        match = re.search(r"\b(\d+\.\d+(?:\.\d+)?)\b", output)
        if not match:
            result.update(status="unknown", detail="程序有响应，但未能确认版本")
            continue
        version = match[1]
        try:
            compatible = not requirement["spec"] or Version(version) in SpecifierSet(requirement["spec"])
        except (InvalidVersion, InvalidSpecifier):
            compatible = False
        result.update(version=version, status="ready" if compatible else "mismatch",
                      detail="版本检查通过" if compatible else "与课程版本要求不符，保留准备步骤")
        if compatible:
            if key == "code":
                result.update(status="present", detail="已确认程序文件与版本；首次运行和扩展需实际验证")
            if key in OFFICE_KEYS:
                result["detail"] = "已找到软件与版本；首次启动、授权和专属功能需实际确认"
            if key == "docker":
                result["detail"] = "Docker 命令可用；服务是否运行仍需在对应步骤检查"
            if key == "python":
                pip = _run([str(path), "-I", "-m", "pip", "--version"])
                venv = _run([str(path), "-I", "-S", "-c", "import importlib.util; print('available' if importlib.util.find_spec('venv') else 'missing')"])
                result["pip"] = bool(pip and re.match(r"pip \d+\.", pip))
                result["venv"] = venv == "available"
            return result
    return result


def inspect_environment(text):
    wanted = requirements(text)
    required_keys = {item["key"] for item in wanted}
    if required_keys & OFFICE_KEYS:
        wanted += [{"key": key, "name": TOOLS[key][0], "spec": "", "alternative": True} for key in ("excel", "wps", "libreoffice") if key not in required_keys]
    with ThreadPoolExecutor(max_workers=4) as pool:
        items = list(pool.map(_probe, wanted))
    items = [item for item in items if not item.get("alternative") or item["status"] == "ready"]
    applications = [item for item in items if item["key"] in OFFICE_KEYS and item["status"] == "ready"]
    application = applications[0]["name"] if applications else ""
    return {"checked_at": datetime.now().astimezone().isoformat(timespec="seconds"), "items": items, "application": application}


def skip_reason(step, report):
    title = step["title"].strip().rstrip("。")
    text = step["action"]
    if re.search(r"venv|虚拟环境|激活|mkdir|\bcd\s|pip\s+install|项目|写入|运行.*(?:脚本|服务)|启动", title + "\n" + text, re.I):
        return None
    for item in report["items"]:
        if item["status"] not in {"ready", "present"} or item["key"] == "docker" or item.get("alternative"):
            continue
        pattern = TOOLS[item["key"]][1] if item["key"] in TOOLS else re.escape(item["name"].removesuffix(".exe"))
        if item["status"] == "present" and not re.match(r"^(?:安装|下载并安装)", title):
            continue
        if not re.fullmatch(r"(?:安装|下载并安装|验证|检查|确认)\s*(?:本机|电脑上的)?\s*(?:" + pattern + r")\s*(?:\d+\.\d+(?:\.\d+)?\+?\s*)?(?:已安装|是否安装|已安装成功|版本|是否可用|安装情况|安装成功)?", title, re.I):
            continue
        own = next((r for r in requirements(title + "\n" + text) if r["key"] == item["key"]), None)
        if item["status"] == "present" and re.search(r"\d+\.\d+|版本|至少|以上", title + "\n" + text):
            continue
        if own and own["spec"] and Version(item["version"]) not in SpecifierSet(own["spec"]):
            continue
        if re.search(r"[;&|]|\b(?:import|print|def)\b|创建|编写|练习|配置|安装.*(?:依赖包|软件包|第三方包|依赖|扩展)", text, re.I):
            continue
        return f'{item["name"]} {item["version"]} 已确认，跳过重复安装' + ("或版本检查" if item["status"] == "ready" else "；首次运行仍需验证")
    return None


def adapt_steps(steps, report):
    return {str(index): reason for index, step in enumerate(steps) if (reason := skip_reason(step, report))}


def report_text(report):
    return json.dumps(report, ensure_ascii=False)
