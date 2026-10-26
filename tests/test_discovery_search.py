import json

import pytest

from learning_ext.environment_agent import discovery


def row(name, *, path=None, source="installed_apps", publisher=""):
    return {"name": name, "path": path, "source": source, "version": "1.0", "publisher": publisher}


def test_short_queries_do_not_match_unrelated_software(monkeypatch):
    monkeypatch.setattr(discovery, "_registry_apps", lambda: iter([row("Google Chrome"), row("Go 1.24.3"), row("Cargo")]))
    monkeypatch.setattr(discovery, "_shortcuts", lambda: iter([]))
    result = discovery.Discovery().find_applications(["go"])
    assert [item["name"] for item in result["matches"]] == ["Go 1.24.3"]
    assert result["matches"][0]["match_basis"] == "name_word"


def test_exact_matches_rank_above_related_names_and_publishers(monkeypatch):
    entries = [row("Blender Manual"), row("3D Helper", publisher="Blender Foundation"), row("Blender"), row("Blender")]
    monkeypatch.setattr(discovery, "_registry_apps", lambda: iter(entries))
    monkeypatch.setattr(discovery, "_shortcuts", lambda: iter([]))
    result = discovery.Discovery().find_applications(["Blender"])
    assert [item["name"] for item in result["matches"]] == ["Blender", "Blender Manual", "3D Helper"]
    assert result["matches"][-1]["match_basis"] == "publisher"
    assert all(item["evidence_level"] == "installation_hint" for item in result["matches"])


def test_search_collects_then_ranks_before_limiting(monkeypatch):
    entries = [row(f"Blender add-on {i}") for i in range(30)] + [row("Blender")]
    monkeypatch.setattr(discovery, "_registry_apps", lambda: iter(entries))
    monkeypatch.setattr(discovery, "_shortcuts", lambda: iter([]))
    result = discovery.Discovery().find_applications(["Blender"])
    assert result["matches"][0]["name"] == "Blender"
    assert len(result["matches"]) == 24 and result["truncated"]


def test_command_discovery_preserves_unknown_evidence_without_path_leak(tmp_path, monkeypatch):
    program = tmp_path / "tool.exe"
    program.write_bytes(b"fixture")
    monkeypatch.setattr(discovery.shutil, "which", lambda name: str(program))
    monkeypatch.setattr(discovery, "_file_version", lambda path: "2.0")
    tool = discovery.Discovery()
    result = tool.find_commands(["tool"])
    assert tool.evidence[0]["status"] == "unknown"
    candidate_id = result[0]["candidate_id"]
    checked = tool.inspect_candidate(candidate_id)
    assert checked["status"] == "present"
    assert checked["evidence_level"] == "executable_verified"
    assert checked["version_source"] == "file_metadata"
    assert str(tmp_path) not in json.dumps([result, checked, tool.evidence])


def test_portable_lookup_is_scoped_and_keeps_paths_out_of_planner(tmp_path, monkeypatch):
    from learning_ext.agent import search

    root = tmp_path / "Programs"
    root.mkdir()
    program = root / "blender.exe"
    program.write_bytes(b"fixture")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    requests = []
    def find(directory, pattern, **kwargs):
        requests.append((directory, pattern, kwargs))
        return {"matches": [{"path": str(program)}], "truncated": False, "engine": "everything"}
    monkeypatch.setattr(search, "search_files", find)
    tool = discovery.Discovery()
    result = tool.find_portable_applications(["blender.exe"])
    assert result["matches"][0]["source"] == "portable_index"
    assert tool.evidence[0]["status"] == "unknown"
    assert requests == [(str(root), "blender.exe", {"limit": 8, "max_depth": 5})]
    assert str(tmp_path) not in json.dumps([result, tool.evidence])
    for names, location in [(["*.exe"], "user_programs"), (["blender.exe"], "all_disks"), (["blender"], "user_programs")]:
        with pytest.raises(ValueError):
            tool.find_portable_applications(names, location)
