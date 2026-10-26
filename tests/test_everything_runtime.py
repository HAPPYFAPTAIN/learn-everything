import csv
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from learning_ext.agent import everything_runtime as runtime


class Process:
    pid = 731

    def __init__(self):
        self.returncode = None
        self.terminated = 0

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated += 1
        self.returncode = 0

    kill = terminate

    def wait(self, timeout=None):
        return self.returncode


@pytest.fixture
def mocked_runtime(monkeypatch, tmp_path):
    calls = []
    processes = []

    def popen(command, **options):
        calls.append((command, options))
        process = Process()
        processes.append(process)
        return process

    def graceful(command, **options):
        for process in processes:
            process.returncode = 0
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runtime, "IS_WINDOWS", True)
    monkeypatch.setattr(runtime, "DATA", tmp_path / "cache")
    monkeypatch.setattr(runtime, "_OWNED", {})
    monkeypatch.setattr(runtime, "bundle_status", lambda: {"ok": True, "sdk_path": "sdk.dll", "cli_path": "es.exe"})
    monkeypatch.setattr(runtime, "_attach_job", lambda process: True)
    monkeypatch.setattr(runtime, "_hidden_process", lambda: {})
    monkeypatch.setattr(runtime, "_lock_cache", lambda directory: (directory.mkdir(parents=True, exist_ok=True), io.BytesIO())[1])
    monkeypatch.setattr(runtime.subprocess, "Popen", popen)
    monkeypatch.setattr(runtime.subprocess, "run", graceful)
    yield calls, processes
    for process in processes:
        process.returncode = 0
    runtime.stop_owned()


def test_bundle_rejects_payload_tampering(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, "BUNDLE", tmp_path)
    monkeypatch.setattr(runtime, "PAYLOAD_HASHES", {"Everything.exe": hashlib.sha256(b"official").hexdigest()})
    (tmp_path / "manifest.json").write_text('{"schema": 1}')
    (tmp_path / "Everything.exe").write_bytes(b"modified")
    assert runtime.bundle_status() == {"ok": False, "error": "bundle_missing_or_invalid"}


def test_snapshot_excludes_nested_dependencies_and_preserves_unicode(tmp_path):
    root = tmp_path / "中文, scope"
    root.mkdir()
    (root / "中文 文件.txt").write_text("safe")
    for name in (".git", ".venv", "venv", "node_modules", "__pycache__"):
        directory = root / "nested" / name
        directory.mkdir(parents=True)
        (directory / "not-indexed.txt").write_text("ignored")
    target = tmp_path / "files.efu"
    result = runtime._snapshot(root, target)
    rows = list(csv.DictReader(target.open(encoding="utf-8")))
    assert [Path(row["Filename"]).name for row in rows] == ["中文 文件.txt"]
    assert result["snapshot_complete"] and result["snapshot_files"] == 1
    config = runtime._config(target)
    assert "folders=\n" in config and "filelists=" in config
    assert "auto_include_fixed_volumes=0" in config
    assert '"' in runtime._list_value(root)


def test_budget_does_not_publish_partial_snapshot(monkeypatch, tmp_path):
    (tmp_path / "one.txt").write_text("one")
    monkeypatch.setattr(runtime, "MAX_ENTRIES", 0)
    target = tmp_path / "files.efu"
    with pytest.raises(runtime.SnapshotIncomplete, match="snapshot_budget"):
        runtime._snapshot(tmp_path, target)
    assert not target.exists()


def test_starts_own_hidden_instance_and_reuses_cache(mocked_runtime, tmp_path):
    calls, _ = mocked_runtime
    root = tmp_path / "scope"
    root.mkdir()
    first = runtime.ensure_started(root)
    second = runtime.ensure_started(root)
    assert first["ok"] and first == second and len(calls) == 1
    command, options = calls[0]
    assert command[1:4] == ["-instance", first["instance"], "-startup"]
    assert "-install-service" not in command and "-admin" not in command
    assert options["stdout"] == subprocess.DEVNULL
    assert first["index_mode"] == "scoped_snapshot"
    cache = Path(options["cwd"])
    runtime.stop_owned()
    assert runtime.ensure_started(root)["ok"]
    assert Path(calls[-1][1]["cwd"]) == cache


def test_expired_snapshot_restarts_only_owned_instance(mocked_runtime, monkeypatch, tmp_path):
    calls, processes = mocked_runtime
    root = tmp_path / "scope"
    root.mkdir()
    assert runtime.ensure_started(root)["ok"]
    monkeypatch.setattr(runtime, "SNAPSHOT_TTL", 0)
    assert runtime.ensure_started(root)["ok"]
    assert len(calls) == 2 and processes[0].poll() is not None


def test_job_failure_is_explicit_and_terminates_child(mocked_runtime, monkeypatch, tmp_path):
    _, processes = mocked_runtime
    monkeypatch.setattr(runtime, "_attach_job", lambda process: False)
    root = tmp_path / "scope"
    root.mkdir()
    assert runtime.ensure_started(root)["error"] == "lifecycle_protection_failed"
    assert processes[0].terminated == 1
    assert not runtime._OWNED


def test_unprotected_owned_process_is_never_reused(mocked_runtime, tmp_path):
    root = tmp_path / "scope"
    root.mkdir()
    first = runtime.ensure_started(root)
    runtime._OWNED[first["instance"]]["protected"] = False
    assert runtime.ensure_started(root)["error"] == "lifecycle_protection_failed"


@pytest.mark.skipif(os.name != "nt", reason="Windows file lock")
def test_cache_lock_rejects_second_owner_and_releases(tmp_path):
    handle = runtime._lock_cache(tmp_path)
    try:
        with pytest.raises(OSError):
            runtime._lock_cache(tmp_path)
    finally:
        handle.close()
    runtime._lock_cache(tmp_path).close()


def test_termination_timeout_is_contained(monkeypatch):
    process = Process()
    monkeypatch.setattr(process, "terminate", lambda: None)
    monkeypatch.setattr(process, "kill", lambda: None)

    def timeout(**options):
        raise subprocess.TimeoutExpired("Everything", options["timeout"])

    monkeypatch.setattr(process, "wait", timeout)
    assert runtime._terminate(process) is False


def test_capacity_and_snapshot_failure_fall_back(mocked_runtime, monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, "MAX_INSTANCES", 0)
    root = tmp_path / "scope"
    root.mkdir()
    assert runtime.ensure_started(root)["error"] == "index_capacity_reached"
    monkeypatch.setattr(runtime, "MAX_INSTANCES", 4)
    monkeypatch.setattr(runtime, "MAX_ENTRIES", 0)
    (root / "file.txt").write_text("test")
    result = runtime.ensure_started(root)
    assert result["error"] == "snapshot_budget" and not result["snapshot_complete"]


def test_new_scope_replaces_least_recently_used(mocked_runtime, monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, "MAX_INSTANCES", 1)
    for name in ("first", "second"):
        (tmp_path / name).mkdir()
    first = runtime.ensure_started(tmp_path / "first")
    second = runtime.ensure_started(tmp_path / "second")
    assert first["ok"] and second["ok"]
    assert first["instance"] not in runtime._OWNED
    assert second["instance"] in runtime._OWNED


def test_scope_does_not_accept_drive_or_network_root():
    with pytest.raises((ValueError, OSError)):
        runtime._scope(Path.cwd().anchor)


@pytest.mark.skipif(os.name != "nt" or os.environ.get("LE_EVERYTHING_INTEGRATION") != "1", reason="Opt-in real official Windows payload")
def test_official_payload_named_scope_and_parent_death(tmp_path):
    import ctypes
    from ctypes import wintypes
    from learning_ext.agent.everything import query_index

    assert runtime.bundle_status()["ok"]
    scope = tmp_path / "search acceptance 中文"
    scope.mkdir()
    expected = scope / "中文 验证.txt"
    expected.write_text("acceptance")
    dependency = scope / "nested" / "node_modules"
    dependency.mkdir(parents=True)
    (dependency / "ignored.txt").write_text("not indexed")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "outside.txt").write_text("outside scope")
    junction = scope / "link-outside"
    environment = dict(os.environ, LE_TEST_JUNCTION=str(junction), LE_TEST_TARGET=str(outside))
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                    "New-Item -ItemType Junction -Path $env:LE_TEST_JUNCTION -Target $env:LE_TEST_TARGET | Out-Null"],
                   env=environment, timeout=10, check=True, capture_output=True,
                   creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        result = query_index(scope, "*.txt")
        assert result["ok"] and result["source"] == "everything_cli"
        assert result["paths"] == [str(expected)]
        owned = [entry["process"] for entry in runtime._OWNED.values()]
        assert owned and all(process.poll() is None for process in owned)
    finally:
        runtime.stop_owned()
    assert all(process.poll() is not None for process in owned)

    source = (
        "import importlib.util,json,time; "
        f"s=importlib.util.spec_from_file_location('owned_runtime', {str(Path(runtime.__file__))!r}); "
        "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
        f"r=m.ensure_started({str(scope)!r}); print(json.dumps(r),flush=True); time.sleep(60)"
    )
    process = subprocess.Popen([sys._base_executable, "-I", "-c", source], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = None
    try:
        child = json.loads(process.stdout.readline())
        assert child["ok"], child
        handle = kernel.OpenProcess(0x00100000, False, child["pid"])
        assert handle
        process.terminate()
        process.wait(timeout=5)
        assert kernel.WaitForSingleObject(handle, 5000) == 0
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        if handle:
            kernel.CloseHandle(handle)
        junction.rmdir()
