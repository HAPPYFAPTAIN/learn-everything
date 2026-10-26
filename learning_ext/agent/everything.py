from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


QUERY_TIMEOUT = 4.0
MAX_RESULTS = 256
MAX_OUTPUT_BYTES = 1024 * 1024
_ROOT = Path(__file__).resolve().parents[2]


def _query_pattern(root, pattern):
    if any(char in pattern for char in '[]"'):
        raise ValueError("unsupported_pattern")
    filename = "".join(r"[^\\]*" if char == "*" else r"[^\\]" if char == "?" else re.escape(char) for char in pattern)
    expression = "^" + re.escape(str(root).rstrip("\\/") + "\\") + r"(?:[^\\]+\\)*" + filename + "$"
    return expression.replace(r"\ ", r"\x20")


def _configured_runtime(root):
    explicit = os.environ.get("LE_EVERYTHING_DLL", "").strip()
    if explicit:
        path = Path(explicit)
        if not path.is_absolute() or explicit.startswith(("\\\\", "//")) or path.suffix.casefold() != ".dll" or not path.is_file():
            return {"ok": False, "error": "invalid_sdk_path"}
        if os.environ.get("LE_EVERYTHING_INSTANCE", ""):
            return {"ok": False, "error": "sdk_named_instance_unsupported"}
        return {"ok": True, "sdk_path": str(path.resolve()), "instance": ""}
    try:
        from learning_ext.agent.everything_runtime import ensure_started
        return ensure_started(root=str(root))
    except ImportError:
        return {"ok": False, "error": "runtime_not_bundled"}
    except (OSError, ValueError):
        return {"ok": False, "error": "runtime_unavailable"}


def query_index(root, pattern, limit=40):
    if sys.platform != "win32" or os.environ.get("LE_EVERYTHING_DISABLED") == "1":
        return {"ok": False, "error": "disabled_or_unsupported"}
    base = Path(root)
    if not base.is_absolute() or not base.is_dir() or str(base).startswith(("\\\\", "//")) or base == Path(base.anchor):
        return {"ok": False, "error": "invalid_scope"}
    if not isinstance(pattern, str) or not 1 <= len(pattern) <= 160 or any(char in pattern for char in "/\\\0\r\n"):
        return {"ok": False, "error": "invalid_pattern"}
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 80:
        return {"ok": False, "error": "invalid_limit"}
    try:
        query = _query_pattern(base, pattern)
    except ValueError:
        return {"ok": False, "error": "unsupported_pattern"}
    runtime = _configured_runtime(base)
    metadata = {name: runtime[name] for name in ("index_mode", "snapshot_at", "snapshot_complete") if name in runtime}
    if not runtime.get("ok"):
        return {"ok": False, "error": runtime.get("error", "runtime_unavailable"), **metadata}
    maximum = min(MAX_RESULTS, max(64, limit * 4))
    if runtime.get("instance"):
        return {**_cli_query(runtime, query, maximum), **metadata}
    payload = {"dll": runtime["sdk_path"], "query": query, "limit": maximum}
    try:
        result = subprocess.run([sys.executable, "-I", str(Path(__file__).resolve()), "--worker"],
                                input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=QUERY_TIMEOUT,
                                cwd=str(_ROOT), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode or len(result.stdout) > MAX_OUTPUT_BYTES:
            return {"ok": False, "error": "worker_failed"}
        data = json.loads(result.stdout)
        if not isinstance(data, dict) or not isinstance(data.get("ok"), bool):
            return {"ok": False, "error": "invalid_response"}
        if data["ok"] and (not isinstance(data.get("paths"), list) or len(data["paths"]) > MAX_RESULTS or
                           any(not isinstance(path, str) or len(path) > 2048 for path in data["paths"])):
            return {"ok": False, "error": "invalid_response"}
        return data
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "query_timeout"}
    except (OSError, ValueError):
        return {"ok": False, "error": "worker_unavailable"}


def _cli_query(runtime, query, maximum):
    executable = Path(runtime.get("cli_path", ""))
    instance = runtime.get("instance", "")
    if not executable.is_absolute() or not executable.is_file() or not isinstance(instance, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", instance):
        return {"ok": False, "error": "invalid_cli_configuration"}
    try:
        with tempfile.TemporaryDirectory(prefix="le-everything-query-") as directory:
            output = Path(directory) / "results.json"
            arguments = [str(executable), "-argv", "-instance", instance, "-timeout", "2500", "-count", str(maximum),
                         "-columns", "full-path", "-export-json", str(output), "-no-footer", "-no-pause", "-no-highlight",
                         "-match-path", "-no-case", "-regex", query]
            result = subprocess.run(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=QUERY_TIMEOUT,
                                    cwd=str(executable.parent), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode:
                return {"ok": False, "error": "ipc_unavailable" if result.returncode in {7, 8} else "query_failed"}
            with output.open("rb") as handle:
                raw = handle.read(MAX_OUTPUT_BYTES + 1)
            if len(raw) > MAX_OUTPUT_BYTES:
                return {"ok": False, "error": "response_too_large"}
            rows = json.loads(raw.decode("utf-8-sig")) if raw.strip() else []
        if not isinstance(rows, list) or len(rows) > maximum or any(not isinstance(row, dict) or not isinstance(row.get("filename"), str) or len(row["filename"]) > 2048 for row in rows):
            return {"ok": False, "error": "invalid_response"}
        return {"ok": True, "paths": [row["filename"] for row in rows], "truncated": len(rows) >= maximum, "source": "everything_cli"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "query_timeout"}
    except (OSError, ValueError):
        return {"ok": False, "error": "cli_unavailable"}


def _bind(dll, name, arguments, result):
    function = getattr(dll, name)
    function.argtypes = arguments
    function.restype = result
    return function


def _worker(payload):
    from ctypes import wintypes

    path = Path(payload["dll"])
    if not path.is_absolute() or str(path).startswith(("\\\\", "//")) or path.suffix.casefold() != ".dll" or not path.is_file():
        return {"ok": False, "error": "invalid_sdk_path"}
    library = ctypes.WinDLL(str(path), winmode=0x00000100 | 0x00000800)
    is_loaded = _bind(library, "Everything_IsDBLoaded", [], wintypes.BOOL)
    if not is_loaded():
        return {"ok": False, "error": "index_not_ready"}
    _bind(library, "Everything_SetMatchPath", [wintypes.BOOL], None)(True)
    _bind(library, "Everything_SetMatchCase", [wintypes.BOOL], None)(False)
    _bind(library, "Everything_SetRegex", [wintypes.BOOL], None)(True)
    _bind(library, "Everything_SetMax", [wintypes.DWORD], None)(min(MAX_RESULTS, int(payload["limit"])))
    _bind(library, "Everything_SetRequestFlags", [wintypes.DWORD], None)(0x1 | 0x2)
    _bind(library, "Everything_SetSearchW", [wintypes.LPCWSTR], None)(payload["query"])
    if not _bind(library, "Everything_QueryW", [wintypes.BOOL], wintypes.BOOL)(True):
        code = _bind(library, "Everything_GetLastError", [], wintypes.DWORD)()
        return {"ok": False, "error": "ipc_unavailable" if code == 2 else "query_failed", "code": code}
    count = _bind(library, "Everything_GetNumResults", [], wintypes.DWORD)()
    total = _bind(library, "Everything_GetTotResults", [], wintypes.DWORD)()
    is_file = _bind(library, "Everything_IsFileResult", [wintypes.DWORD], wintypes.BOOL)
    get_path = _bind(library, "Everything_GetResultFullPathNameW", [wintypes.DWORD, wintypes.LPWSTR, wintypes.DWORD], wintypes.DWORD)
    paths = []
    for index in range(min(count, MAX_RESULTS)):
        if not is_file(index):
            continue
        length = get_path(index, None, 0)
        if not 0 < length <= 2048:
            continue
        buffer = ctypes.create_unicode_buffer(length + 1)
        copied = get_path(index, buffer, length + 1)
        if copied == length:
            paths.append(buffer.value)
    _bind(library, "Everything_CleanUp", [], None)()
    return {"ok": True, "paths": paths, "truncated": total > count, "source": "everything_sdk"}


if __name__ == "__main__" and "--worker" in sys.argv:
    try:
        request = json.loads(sys.stdin.buffer.read(16384))
        response = _worker(request)
    except (OSError, ValueError, KeyError, AttributeError, TypeError):
        response = {"ok": False, "error": "sdk_unavailable"}
    sys.stdout.buffer.write(json.dumps(response, ensure_ascii=False).encode("utf-8"))
