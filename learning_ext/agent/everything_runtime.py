from __future__ import annotations

import atexit
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
import stat
import struct
import subprocess
import threading
import time
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "vendor" / "everything"
DATA = ROOT / "kotaemon" / "ktem_app_data" / "everything"
IS_WINDOWS = os.name == "nt"
MAX_INSTANCES = 4
SNAPSHOT_TTL = 60
MAX_ENTRIES = 25000
MAX_SCAN_SECONDS = 2.0
MAX_DEPTH = 12
EXCLUDED_DIRECTORIES = frozenset({
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__",
    ".pytest_cache", "$recycle.bin", "system volume information",
})
PAYLOAD_HASHES = {
    "Everything.exe": "f191f756996a14a11e5445fa7103d302efd510cf2fbf920e6c0c8ed51d512e36",
    "Everything64.dll": "81b5be18126acd2c2b913f8f4a821e476b18393cdd3debd03387c50afd8db88f",
    "es.exe": "f7378761cf6e01f51c4123a485e628d70e3fea147d341f473ce2820844e5cee5",
}
_OWNER = uuid.uuid4().hex[:12]
_LOCK = threading.RLock()
_OWNED = {}
_JOB = None


def bundle_status():
    try:
        manifest = json.loads((BUNDLE / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("schema") != 1:
            raise ValueError("manifest")
        for name, digest in PAYLOAD_HASHES.items():
            if hashlib.sha256((BUNDLE / name).read_bytes()).hexdigest() != digest:
                raise ValueError("hash")
        for name in ("LICENSE-Everything.txt", "LICENSE-SDK.txt", "LICENSE-ES.txt"):
            content = (BUNDLE / name).read_bytes()
            if not content or hashlib.sha256(content).hexdigest() != manifest["files"][name]:
                raise ValueError("license")
    except (OSError, ValueError, KeyError, TypeError):
        return {"ok": False, "error": "bundle_missing_or_invalid"}
    return {
        "ok": True, "version": "1.4.1.1032", "cli_version": "1.1.0.38",
        "sdk_path": str(BUNDLE / "Everything64.dll"), "cli_path": str(BUNDLE / "es.exe"),
    }


def _scope(root):
    path = Path(root).resolve(strict=True)
    if not path.is_dir() or path == Path(path.anchor) or str(path).startswith("\\\\"):
        raise ValueError("Choose a local folder, not an entire drive")
    return path


def _scope_key(root):
    return hashlib.sha256(str(_scope(root)).casefold().encode()).hexdigest()[:24]


def instance_name(root):
    return f"LearnEverything-{_OWNER}-{_scope_key(root)}"


def _list_value(value):
    value = str(value)
    if any(char in value for char in '\r\n"'):
        raise ValueError("Invalid index folder")
    if "," in value:
        return '"' + value.replace("\\", "\\\\") + '"'
    return value


def _config(filelist):
    values = {
        "app_data": "0", "run_as_admin": "0", "run_in_background": "1",
        "show_tray_icon": "0", "check_for_updates_on_startup": "0",
        "auto_include_fixed_volumes": "0", "auto_include_removable_volumes": "0",
        "auto_include_fixed_refs_volumes": "0", "auto_include_removable_refs_volumes": "0",
        "ntfs_volume_guids": "", "ntfs_volume_paths": "", "ntfs_volume_includes": "",
        "refs_volume_guids": "", "refs_volume_paths": "", "refs_volume_includes": "",
        "http_server_enabled": "0", "etp_server_enabled": "0",
        "folders": "", "filelists": _list_value(filelist),
        "search_history_enabled": "0", "run_history_enabled": "0",
    }
    return "[Everything]\n" + "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"


class SnapshotIncomplete(ValueError):
    pass


def _snapshot(root, target):
    started = time.monotonic()
    pending = [(root, 0)]
    rows = []
    checked = 0
    while pending:
        directory, depth = pending.pop()
        if directory.is_symlink() or getattr(directory.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            continue
        if not directory.resolve(strict=True).is_relative_to(root):
            raise SnapshotIncomplete("scope_changed")
        with os.scandir(directory) as entries:
            for entry in entries:
                if checked >= MAX_ENTRIES or time.monotonic() - started >= MAX_SCAN_SECONDS:
                    raise SnapshotIncomplete("snapshot_budget")
                checked += 1
                metadata = entry.stat(follow_symlinks=False)
                if entry.is_symlink() or getattr(metadata, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    continue
                path = Path(entry.path)
                if not path.resolve(strict=True).is_relative_to(root):
                    raise SnapshotIncomplete("scope_changed")
                if entry.is_dir(follow_symlinks=False):
                    if entry.name.casefold() in EXCLUDED_DIRECTORIES or path == DATA or path.is_relative_to(DATA):
                        continue
                    if depth >= MAX_DEPTH:
                        raise SnapshotIncomplete("snapshot_depth")
                    pending.append((path, depth + 1))
                elif entry.is_file(follow_symlinks=False):
                    rows.append((str(path), metadata.st_size, int((metadata.st_mtime + 11644473600) * 10000000), 32))
    with target.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(("Filename", "Size", "Date Modified", "Attributes"))
        writer.writerows(rows)
    return {"snapshot_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "snapshot_complete": True, "snapshot_files": len(rows), "index_mode": "scoped_snapshot"}


def _lock_cache(directory):
    import msvcrt
    directory.mkdir(parents=True, exist_ok=True)
    handle = (directory / "owner.lock").open("a+b")
    try:
        if handle.seek(0, 2) == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        raise
    return handle


def _terminate(process):
    for operation in (process.terminate, process.kill):
        try:
            if process.poll() is not None:
                return True
            operation()
            process.wait(timeout=2)
            return True
        except (OSError, subprocess.TimeoutExpired):
            pass
    return process.poll() is not None


def _stop_entry(instance, entry):
    process = entry["process"]
    if process.poll() is None:
        try:
            subprocess.run([str(BUNDLE / "Everything.exe"), "-instance", instance, "-exit"],
                           timeout=2, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, **_hidden_process())
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            if not _terminate(process):
                return False
    entry["lock"].close()
    _OWNED.pop(instance, None)
    return True


def _hidden_process():
    if not IS_WINDOWS:
        return {}
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    return {"startupinfo": startup, "creationflags": subprocess.CREATE_NO_WINDOW}


def _attach_job(process):
    global _JOB
    if not IS_WINDOWS:
        return False
    import ctypes
    from ctypes import wintypes

    class BasicLimit(ctypes.Structure):
        _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                    ("flags", wintypes.DWORD), ("minimum", ctypes.c_size_t),
                    ("maximum", ctypes.c_size_t), ("active", wintypes.DWORD),
                    ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                    ("scheduling", wintypes.DWORD)]

    class ExtendedLimit(ctypes.Structure):
        _fields_ = [("basic", BasicLimit), ("io", ctypes.c_uint64 * 6),
                    ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                    ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    if _JOB is None:
        handle = kernel.CreateJobObjectW(None, None)
        limits = ExtendedLimit()
        limits.basic.flags = 0x2000
        if not handle or not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            if handle:
                kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                kernel.CloseHandle(handle)
            return False
        _JOB = handle
    return bool(kernel.AssignProcessToJobObject(_JOB, int(process._handle)))


def ensure_started(root):
    if not IS_WINDOWS or struct.calcsize("P") != 8:
        return {"ok": False, "error": "unsupported_platform"}
    bundled = bundle_status()
    if not bundled["ok"]:
        return bundled
    try:
        scope = _scope(root)
        instance = instance_name(scope)
        with _LOCK:
            for key, entry in list(_OWNED.items()):
                if entry["process"].poll() is not None:
                    _stop_entry(key, entry)
            if instance in _OWNED and time.monotonic() - _OWNED[instance]["created"] >= SNAPSHOT_TTL:
                if not _stop_entry(instance, _OWNED[instance]):
                    return {"ok": False, "error": "index_shutdown_failed"}
            if instance not in _OWNED:
                if len(_OWNED) >= MAX_INSTANCES:
                    if not _OWNED or MAX_INSTANCES < 1:
                        return {"ok": False, "error": "index_capacity_reached"}
                    oldest = min(_OWNED, key=lambda key: _OWNED[key]["last_used"])
                    if not _stop_entry(oldest, _OWNED[oldest]):
                        return {"ok": False, "error": "index_capacity_reached"}
                directory = DATA / _scope_key(scope)
                try:
                    cache_lock = _lock_cache(directory)
                except OSError:
                    return {"ok": False, "error": "index_cache_in_use"}
                try:
                    snapshot = _snapshot(scope, directory / "files.efu")
                    config = directory / "Everything.ini"
                    config.write_text(_config(directory / "files.efu"), encoding="utf-8")
                    command = [str(BUNDLE / "Everything.exe"), "-instance", instance, "-startup",
                               "-config", str(config), "-db", str(directory / "Everything.db")]
                    process = subprocess.Popen(command, cwd=str(directory), stdin=subprocess.DEVNULL,
                                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **_hidden_process())
                except Exception:
                    cache_lock.close()
                    raise
                _OWNED[instance] = {"process": process, "root": str(scope), "directory": str(directory),
                                    "lock": cache_lock, "created": time.monotonic(),
                                    "last_used": time.monotonic(), "protected": False, **snapshot}
                try:
                    protected = _attach_job(process)
                except (OSError, AttributeError):
                    protected = False
                if not protected:
                    if _terminate(process):
                        cache_lock.close()
                        _OWNED.pop(instance, None)
                    return {"ok": False, "error": "lifecycle_protection_failed"}
                _OWNED[instance]["protected"] = True
            entry = _OWNED[instance]
            if not entry["protected"]:
                return {"ok": False, "error": "lifecycle_protection_failed"}
            entry["last_used"] = time.monotonic()
            return {**bundled, "instance": instance, "pid": entry["process"].pid,
                    "root": str(scope), "status": "indexing_or_ready", "owned": True,
                    **{key: entry[key] for key in ("snapshot_at", "snapshot_complete", "snapshot_files", "index_mode")}}
    except SnapshotIncomplete as exc:
        return {"ok": False, "error": str(exc), "snapshot_complete": False, "index_mode": "scoped_snapshot"}
    except (OSError, ValueError, TypeError):
        return {"ok": False, "error": "index_start_failed"}


def status():
    with _LOCK:
        entries = [{"instance": name, "pid": entry["process"].pid,
                    "running": entry["process"].poll() is None, "root": entry["root"]}
                   for name, entry in _OWNED.items()]
    return {**bundle_status(), "instances": entries}


def stop_owned():
    with _LOCK:
        for instance, entry in list(_OWNED.items()):
            _stop_entry(instance, entry)


atexit.register(stop_owned)
