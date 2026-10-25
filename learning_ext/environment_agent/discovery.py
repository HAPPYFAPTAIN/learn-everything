from __future__ import annotations

from itertools import islice
import os
from pathlib import Path
import platform
import re
import shutil
import uuid

from learning_ext.agent.zcode_core import Capability
from learning_ext.practice.environment import ROOT, TOOLS, _file_version, _probe


READ_ONLY = Capability(read_only=True, scope="none", needs_approval=False)


def system_info():
    return {"os": platform.system(), "release": platform.release(), "architecture": platform.machine(),
            "shell": "PowerShell" if os.name == "nt" else Path(os.environ.get("SHELL", "/bin/sh")).name,
            "scope": "运行学习应用的本机；远程浏览器不代表远程电脑已检测", "read_only": True}


def _terms(values):
    if not isinstance(values, list) or not 1 <= len(values) <= 6:
        raise ValueError("需要 1–6 个搜索词")
    if any(not isinstance(v, str) or not 1 <= len(v.strip()) <= 60 or re.search(r"[\\/\r\n*?;|<>]", v) for v in values):
        raise ValueError("仅接受软件或命令名称")
    return list(dict.fromkeys(v.strip() for v in values))


def _path(value):
    if not isinstance(value, str) or not value.strip():
        return None
    value = os.path.expandvars(value.strip().strip('"'))
    if value.startswith(("\\\\", "//")):
        return None
    path = Path(value)
    return path if path.is_absolute() else None


def _registry_apps():
    if os.name != "nt":
        return
    import winreg
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            for branch, kind in (("Uninstall", "installed_app"), ("App Paths", "registered_command")):
                try:
                    root = winreg.OpenKey(hive, "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\" + branch, 0, winreg.KEY_READ | view)
                except OSError:
                    continue
                with root:
                    for index in range(min(winreg.QueryInfoKey(root)[0], 2000)):
                        try:
                            name = winreg.EnumKey(root, index)
                            with winreg.OpenKey(root, name) as entry:
                                def value(field):
                                    try:
                                        return winreg.QueryValueEx(entry, field)[0]
                                    except OSError:
                                        return ""
                                if kind == "registered_command":
                                    yield {"name": name, "path": _path(value("")), "version": "", "source": "app_paths"}
                                else:
                                    label = value("DisplayName")
                                    if isinstance(label, str) and label:
                                        icon = value("DisplayIcon")
                                        icon_path = _path(re.sub(r",\s*-?\d+$", "", icon).strip('"')) if isinstance(icon, str) else None
                                        yield {"name": label[:160], "path": icon_path,
                                               "directory": _path(value("InstallLocation")),
                                               "version": str(value("DisplayVersion"))[:60], "source": "installed_apps"}
                        except OSError:
                            continue


def _shortcuts():
    if os.name != "nt":
        return
    for variable in ("ProgramData", "APPDATA"):
        location = os.environ.get(variable)
        if not location:
            continue
        root = Path(location) / "Microsoft/Windows/Start Menu/Programs"
        try:
            for directory, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs[:80] if not (Path(directory)/d).is_symlink()]
                if len(Path(directory).relative_to(root).parts) >= 3:
                    dirs[:] = []
                for name in files[:200]:
                    if name.lower().endswith(".lnk"):
                        yield {"name": Path(name).stem, "path": None, "source": "start_menu", "version": ""}
        except OSError:
            continue


class Discovery:
    def __init__(self):
        self.candidates = {}
        self.evidence = []

    def _evidence(self, result):
        self.evidence = [item for item in self.evidence if item["key"] != result["key"]]
        self.evidence.append(result)

    def _candidate(self, row):
        for key, existing in self.candidates.items():
            if existing == row:
                return key
        key = uuid.uuid4().hex[:16]
        self.candidates[key] = row
        return key

    def find_applications(self, queries):
        terms = _terms(queries)
        matches, seen = [], set()
        for row in islice(_registry_apps(), 8000):
            if not any(term.casefold() in row["name"].casefold() for term in terms):
                continue
            fingerprint = row["name"], str(row.get("path")), row["source"]
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            matches.append({"candidate_id": self._candidate(row), "name": row["name"],
                            "source": row["source"], "status": "detected", "reported_version": row["version"]})
            if len(matches) >= 24:
                break
        if len(matches) < 24:
            for row in islice(_shortcuts(), 1500):
                if any(term.casefold() in row["name"].casefold() for term in terms):
                    matches.append({"candidate_id": self._candidate(row), "name": row["name"], "source": "start_menu", "status": "detected"})
                    if len(matches) >= 24:
                        break
        for item in matches:
            self._evidence({"key": "candidate:" + item["candidate_id"], "name": item["name"], "status": "unknown",
                            "version": "", "spec": "", "source": item["source"], "detail": "已发现安装线索，等待验证程序文件"})
        if not matches:
            for term in terms:
                self._evidence({"key": "search:" + term.casefold(), "name": term, "status": "missing", "version": "", "spec": "",
                                "source": "application_search", "detail": "本次搜索未找到；便携版或其他安装位置仍需确认"})
        return {"matches": matches, "scope": "Windows 安装登记、App Paths 与开始菜单",
                "status": "searched" if os.name == "nt" else "unsupported", "absence_is_not_proof": True}

    def find_commands(self, names):
        names = _terms(names)
        results = []
        for name in names:
            if not re.fullmatch(r"[A-Za-z0-9_.+-]{1,60}", name) or name in {".", ".."}:
                raise ValueError("命令名称无效")
            location = shutil.which(name)
            path = _path(location)
            if path and (ROOT in path.resolve().parents or "windowsapps" in str(path).lower()):
                path = None
            if path:
                row = {"name": name, "path": path, "version": "", "source": "PATH"}
                results.append({"name": name, "candidate_id": self._candidate(row), "status": "detected", "source": "PATH"})
            else:
                results.append({"name": name, "status": "not_found", "scope": "当前应用进程 PATH，不代表所有终端"})
                self._evidence({"key": "command:" + name.casefold(), "name": name, "status": "missing", "version": "", "spec": "",
                                "source": "PATH", "detail": "当前进程 PATH 未找到；可能安装在其他位置或需要重启终端"})
        return results

    def inspect_candidate(self, candidate_id):
        row = self.candidates.get(candidate_id)
        if row is None:
            raise ValueError("只能验证本轮搜索返回的候选")
        path = row.get("path")
        executable = path and path.is_file() and (path.suffix.lower() == ".exe" if os.name == "nt" else os.access(path, os.X_OK))
        if executable and ROOT in path.resolve().parents:
            executable = False
        version = _file_version(path) if executable else None
        result = {"key": "candidate:" + candidate_id, "name": row["name"], "source": row["source"],
                  "status": "present" if executable else "unknown", "version": version or "", "spec": "",
                  "detail": "已确认程序文件；运行、授权和功能需在实践时验证" if executable else "只有安装登记或快捷方式线索，尚未验证程序可用"}
        self._evidence(result)
        return result

    def check_tool(self, key, spec=""):
        if key not in TOOLS or not isinstance(spec, str) or len(spec) > 60:
            raise ValueError("没有对应的固定验证器；使用定向搜索")
        from packaging.specifiers import SpecifierSet
        SpecifierSet(spec)
        result = _probe({"key": key, "name": TOOLS[key][0], "spec": spec})
        result["source"] = "fixed_probe"
        self._evidence(result)
        return result

    def registry(self):
        return {name: (READ_ONLY, getattr(self, name)) for name in
                ("find_applications", "find_commands", "inspect_candidate", "check_tool")}

    @staticmethod
    def descriptions():
        return {
            "find_applications": {"args": {"queries": ["软件名/厂商名/别名，1–6项"]}, "purpose": "定向发现任意已安装软件，不读取文档"},
            "find_commands": {"args": {"names": ["可执行命令名，1–6项"]}, "purpose": "在当前 PATH 中定位任意命令，不执行"},
            "inspect_candidate": {"args": {"candidate_id": "本轮搜索返回的ID"}, "purpose": "只读验证程序文件与版本，不运行未知程序"},
            "check_tool": {"args": {"key": " | ".join(TOOLS), "spec": "课程明确的版本约束，如 >=3.10；否则空字符串"}, "purpose": "固定版本探针；其他软件用搜索工具"},
        }
