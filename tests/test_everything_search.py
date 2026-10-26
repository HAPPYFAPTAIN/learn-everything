import json
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace

import pytest

from learning_ext.agent import everything, search

_configured_runtime = everything._configured_runtime


@pytest.fixture(autouse=True)
def no_real_index(monkeypatch):
    monkeypatch.delenv("LE_EVERYTHING_DISABLED", raising=False)
    monkeypatch.setattr(everything, "_configured_runtime", lambda root: {"ok": False, "error": "not_configured"})


def test_generated_query_has_no_unescaped_search_operators():
    root = r"C:\Programs (Learning)[1]"
    pattern = "guide|draft*.txt"
    expression = everything._query_pattern(root, pattern)
    assert re.fullmatch(expression, root + r"\sub\guide|draft1.txt")
    assert not re.fullmatch(expression, r"C:\Private\guide|draft1.txt")
    assert not re.fullmatch(expression, root + r"\draft1.txt")
    assert " " not in expression and r"\x20" in expression
    with pytest.raises(ValueError):
        everything._query_pattern(root, '"|file:*')


def test_sdk_runs_in_disposable_process_and_timeout_is_handled(tmp_path, monkeypatch):
    monkeypatch.setattr(everything, "_configured_runtime", lambda root: {"ok": True, "sdk_path": str(tmp_path / "Everything64.dll"), "instance": ""})
    seen = []
    def run(arguments, **kwargs):
        seen.append((arguments, kwargs))
        raise subprocess.TimeoutExpired(arguments, kwargs["timeout"])
    monkeypatch.setattr(everything.subprocess, "run", run)
    result = everything.query_index(tmp_path, "*.txt")
    assert result["error"] == "query_timeout"
    arguments, options = seen[0]
    assert arguments[1] == "-I" and arguments[-1] == "--worker"
    assert options["timeout"] == 4 and "shell" not in options
    payload = json.loads(options["input"])
    assert payload["limit"] <= 256 and payload["query"].startswith("^")


def test_sdk_response_is_validated(tmp_path, monkeypatch):
    monkeypatch.setattr(everything, "_configured_runtime", lambda root: {"ok": True, "sdk_path": "test.dll", "instance": ""})
    monkeypatch.setattr(everything.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=b'{"ok":true,"paths":"wrong"}'))
    assert everything.query_index(tmp_path, "*.txt")["error"] == "invalid_response"


def test_named_instance_uses_official_cli_with_literal_arguments(tmp_path, monkeypatch):
    executable = tmp_path / "es.exe"
    executable.write_bytes(b"fixture")
    runtime = {"ok": True, "cli_path": str(executable), "sdk_path": "unused", "instance": "le-scope123",
               "index_mode": "scoped_snapshot", "snapshot_at": "2026-10-26T10:00:00Z", "snapshot_complete": True}
    monkeypatch.setattr(everything, "_configured_runtime", lambda root: runtime)
    captured = []
    def run(arguments, **kwargs):
        captured.append((arguments, kwargs))
        output = Path(arguments[arguments.index("-export-json") + 1])
        output.write_text(json.dumps([{"filename": str(tmp_path / "中文.txt")}], ensure_ascii=False), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout=b"")
    monkeypatch.setattr(everything.subprocess, "run", run)
    result = everything.query_index(tmp_path, "*.txt")
    assert result["source"] == "everything_cli" and result["paths"] == [str(tmp_path / "中文.txt")]
    assert result["index_mode"] == "scoped_snapshot" and result["snapshot_complete"]
    assert result["snapshot_at"] == runtime["snapshot_at"]
    arguments, options = captured[0]
    assert arguments[:4] == [str(executable), "-argv", "-instance", "le-scope123"]
    assert "-count" in arguments and "-regex" in arguments
    assert options["timeout"] == 4 and "shell" not in options


def test_empty_cli_export_is_treated_as_unconfirmed_no_hits(tmp_path, monkeypatch):
    executable = tmp_path / "es.exe"
    executable.write_bytes(b"fixture")
    runtime = {"ok": True, "cli_path": str(executable), "instance": "le-empty"}
    monkeypatch.setattr(everything, "_configured_runtime", lambda root: runtime)
    def run(arguments, **kwargs):
        Path(arguments[arguments.index("-export-json") + 1]).write_bytes(b"")
        return SimpleNamespace(returncode=0, stdout=b"")
    monkeypatch.setattr(everything.subprocess, "run", run)
    result = everything.query_index(tmp_path, "*.txt")
    assert result["ok"] and result["paths"] == []
    monkeypatch.setattr(search, "query_index", lambda *args: result)
    (tmp_path / "new.txt").write_text("fresh")
    report = search.search_files(str(tmp_path), "*.txt")
    assert report["engine"] == "filesystem" and report["index_status"] == "no_verified_hits"


def test_sdk_never_pretends_to_support_named_instance(tmp_path, monkeypatch):
    dll = tmp_path / "Everything64.dll"
    dll.write_bytes(b"fixture")
    monkeypatch.setenv("LE_EVERYTHING_DLL", str(dll))
    monkeypatch.setenv("LE_EVERYTHING_INSTANCE", "custom")
    assert _configured_runtime(tmp_path)["error"] == "sdk_named_instance_unsupported"


def test_index_results_revalidated_for_scope_depth_and_exclusions(tmp_path, monkeypatch):
    root = tmp_path / "scope"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside")
    inside = root / "found.txt"
    inside.write_text("inside")
    (root / ".git").mkdir()
    excluded = root / ".git" / "private.txt"
    excluded.write_text("ignored")
    (root / "sub").mkdir()
    deep = root / "sub" / "deep.txt"
    deep.write_text("deep")
    monkeypatch.setattr(search, "query_index", lambda *a: {"ok": True, "paths": list(map(str, [outside, inside, excluded, deep, root / "stale.txt"])), "truncated": False, "source": "everything_cli"})
    result = search.search_files(str(root), "*.txt", max_depth=0)
    assert result["engine"] == "everything" and result["index_source"] == "everything_cli"
    assert [item["path"] for item in result["matches"]] == [str(inside)]
    assert result["skipped"]["excluded_directories"] == 1
    assert result["skipped"]["depth_limit"] == 1
    assert str(outside) not in json.dumps(result)


@pytest.mark.parametrize("index", [{"ok": False, "error": "ipc_unavailable"}, {"ok": True, "paths": [], "truncated": False}])
def test_index_failure_or_unready_empty_index_falls_back(tmp_path, monkeypatch, index):
    (tmp_path / "recent.txt").write_text("recent")
    monkeypatch.setattr(search, "query_index", lambda *a: index)
    result = search.search_files(str(tmp_path), "*.txt")
    assert result["engine"] == "filesystem" and len(result["matches"]) == 1
    assert result["index_status"] in {"ipc_unavailable", "no_verified_hits"}


def test_snapshot_freshness_reaches_search_report(tmp_path, monkeypatch):
    item = tmp_path / "current.txt"
    item.write_text("present")
    monkeypatch.setattr(search, "query_index", lambda *a: {
        "ok": True, "paths": [str(item)], "source": "everything_cli",
        "index_mode": "scoped_snapshot", "snapshot_at": "2026-10-26T10:00:00Z", "snapshot_complete": True,
    })
    result = search.search_files(str(tmp_path), "*.txt")
    assert result["engine"] == "everything" and result["snapshot_complete"]
    assert result["index_mode"] == "scoped_snapshot" and "快照" in result["freshness"]


def test_incomplete_snapshot_falls_back_without_losing_evidence(tmp_path, monkeypatch):
    (tmp_path / "found.txt").write_text("present")
    monkeypatch.setattr(everything, "_configured_runtime", lambda root: {
        "ok": False, "error": "snapshot_incomplete", "index_mode": "scoped_snapshot", "snapshot_complete": False,
    })
    monkeypatch.setattr(search, "query_index", everything.query_index)
    result = search.search_files(str(tmp_path), "*.txt")
    assert result["engine"] == "filesystem" and not result["snapshot_complete"]
    assert result["index_status"] == "snapshot_incomplete" and len(result["matches"]) == 1
