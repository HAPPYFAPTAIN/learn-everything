import json
from pathlib import Path

import pytest

from learning_ext.agent.zcode_core import Capability, TurnMachine, permission
from learning_ext.environment_agent import service
from learning_ext.environment_agent.discovery import Discovery
from learning_ext.practice import environment


@pytest.fixture
def empty_base(monkeypatch):
    monkeypatch.setattr(service, "inspect_environment", lambda text: {"checked_at": "2026-10-25", "items": [], "application": ""})


def test_zcode_phase_and_capability_boundaries():
    events = []
    machine = TurnMachine("s", lambda event, **data: events.append((event, data)))
    with pytest.raises(ValueError):
        machine.transition("executing_tools")
    machine.transition("processing_input")
    machine.transition("awaiting_model_response")
    machine.transition("streaming")
    machine.schedule([{"tool": "install_anything", "args": {}}])
    calls = []
    results = machine.execute({"install_anything": (Capability(), lambda: calls.append(True))})
    assert not results[0]["ok"] and not calls
    assert machine.phase == "aggregating_results"
    assert permission(Capability(read_only=True, destructive=True, scope="none", needs_approval=False))[0] == "deny"
    assert permission(None)[0] == "deny"
    assert permission(Capability(), plan=False)[0] == "ask"
    machine.transition("completing")
    assert len({data["trace_id"] for _, data in events}) == 1


def test_general_application_search_verifies_without_running(tmp_path, monkeypatch, empty_base):
    import learning_ext.environment_agent.discovery as discovery
    executable = tmp_path / "blender.exe"
    executable.write_bytes(b"fixture")
    monkeypatch.setattr(discovery, "_registry_apps", lambda: iter([{"name": "Blender", "path": executable, "version": "4.2", "source": "installed_apps"}]))
    monkeypatch.setattr(discovery, "_shortcuts", lambda: iter([]))
    monkeypatch.setattr(discovery, "_file_version", lambda path: "4.2.0")
    round_number = []
    def plan(prompt, **kwargs):
        data = json.loads(prompt)
        round_number.append(data)
        if len(round_number) == 1:
            return {"calls": [{"tool": "find_applications", "args": {"queries": ["Blender"]}}]}
        if len(round_number) == 2:
            candidate = data["history"][0]["results"][0]["data"]["matches"][0]["candidate_id"]
            return {"calls": [{"tool": "inspect_candidate", "args": {"candidate_id": candidate}}]}
        return {"calls": [], "summary": "发现 Blender，首次运行仍需验证"}
    log = []
    report = service.explore_environment({"lesson": "用 Blender 建模"}, planner=plan, emit=lambda event, **data: log.append(event))
    assert report["complete"] and report["engine"] == "zcode-core-python"
    assert report["items"][0]["status"] == "present"
    assert str(tmp_path) not in json.dumps(round_number)
    assert "agent_permission" in log and "agent_tool_completed" in log


def test_registry_and_shortcuts_are_not_ready(tmp_path, monkeypatch):
    import learning_ext.environment_agent.discovery as discovery
    monkeypatch.setattr(discovery, "_registry_apps", lambda: iter([{"name": "Design Tool", "path": tmp_path/"gone.exe", "version": "9", "source": "installed_apps"}]))
    monkeypatch.setattr(discovery, "_shortcuts", lambda: iter([]))
    tools = Discovery()
    found = tools.find_applications(["Design"])["matches"][0]
    assert tools.inspect_candidate(found["candidate_id"])["status"] == "unknown"
    with pytest.raises(ValueError):
        tools.inspect_candidate("invented")
    with pytest.raises(ValueError):
        tools.find_commands(["python; Remove-Item *"])


def test_agent_cannot_execute_unlisted_tools(empty_base):
    report = service.explore_environment("任务", planner=lambda *a, **k: {"calls": [{"tool": "run_command", "args": {"command": "install something"}}]})
    assert report["stop_reason"] == "tool_failed_or_denied" and not report["complete"]


def test_agent_stops_repeated_queries_and_model_failure(empty_base, monkeypatch):
    tools = Discovery()
    monkeypatch.setattr(tools, "find_applications", lambda queries: {"matches": []})
    report = service.explore_environment("任务", discovery=tools, planner=lambda *a, **k: {"calls": [{"tool": "find_applications", "args": {"queries": ["Tool"]}}]})
    assert report["stop_reason"] == "repeated_queries"
    def unavailable(*a, **k):
        raise RuntimeError("network failed with private detail")
    report = service.explore_environment("任务", planner=unavailable)
    assert report["stop_reason"] == "RuntimeError"
    assert "private detail" not in json.dumps(report)


def ready_python():
    return {"key": "python", "name": "Python", "status": "ready", "version": "3.12.8", "spec": ">=3.10", "detail": "版本检查通过"}


@pytest.mark.parametrize("title,action,skip", [
    ("安装 Python", "下载 Python 安装包后完成安装。", True),
    ("检查 Python 版本", "python --version", True),
    ("安装 Python 3.9", "需要使用 Python 3.9", False),
    ("创建虚拟环境", "python -m venv .venv", False),
    ("安装 Python", "安装后运行 print('hello')", False),
    ("安装依赖包", "pip install pandas", False),
    ("创建项目文件夹", "mkdir project", False),
])
def test_only_proven_redundant_preparation_skipped(title, action, skip):
    result = environment.skip_reason({"title": title, "action": action}, {"items": [ready_python()]})
    assert bool(result) == skip


def test_unknown_and_alternative_cannot_skip():
    step = {"title": "安装 Python", "action": "下载并安装 Python"}
    for override in ({"status": "unknown"}, {"alternative": True}, {"status": "mismatch"}):
        assert not environment.skip_reason(step, {"items": [{**ready_python(), **override}]})


def test_arbitrary_application_install_can_skip_but_run_check_cannot():
    item = {"key": "candidate:123", "name": "Blender", "status": "present", "version": "4.2.0"}
    report = {"items": [item]}
    assert environment.skip_reason({"title": "安装 Blender", "action": "下载安装包并安装 Blender"}, report)
    assert not environment.skip_reason({"title": "检查 Blender 是否可用", "action": "打开软件"}, report)


def test_first_card_navigation_and_resume_do_not_complete_learning(tmp_path, monkeypatch):
    from learning_ext.action_learning.service import ActionLearning, Journal
    from learning_ext.pages.action_learning import action_card, ActionLearningPanel
    state = dict(id="test", owner="test", node=1, fingerprint="f", context={"course": "课程"}, index=0, done=[],
                 steps=[{"title": "安装 Python", "action": "下载 Python 安装包", "check": "安装完成", "hint": "", "source": ""},
                        {"title": "创建项目", "action": "mkdir project", "check": "看到目录", "hint": "", "source": ""}], active=True)
    runner = ActionLearning(Journal(tmp_path/"journal.sqlite"))
    report = {"items": [ready_python()], "complete": True}
    runner.apply_environment(state, report)
    assert state["index"] == -1 and state["skipped"] and state["done"] == []
    assert "从你已有的工具开始" in action_card(state)
    rendered = ActionLearningPanel.render(state, "")
    assert rendered[17]["visible"] is False and rendered[18]["visible"] is True
    runner.move(state, 1)
    assert state["index"] == 1 and state["done"] == []
    runner.move(state, -1)
    assert state["index"] == -1
    runner.complete(state)
    assert not state["done"]
    stored = runner.journal.resume("test", 1, "f")
    assert stored["environment"] == report
    with pytest.raises(ValueError):
        runner.prepare_operation(state, {})


def test_known_version_probe_checks_exit_status(monkeypatch):
    monkeypatch.setattr(environment, "_candidate_paths", lambda key: [Path("python.exe")])
    monkeypatch.setattr(environment, "_run", lambda args: None)
    assert environment._probe({"key": "python", "name": "Python", "spec": ">=3.10"})["status"] == "unknown"


def test_editor_metadata_fallback_is_stable_without_model(tmp_path, monkeypatch):
    executable = tmp_path / "Code.exe"
    executable.write_bytes(b"fixture")
    monkeypatch.setattr(environment, "_candidate_paths", lambda key: [executable])
    monkeypatch.setattr(environment, "_file_version", lambda path: "1.137.0.0")
    monkeypatch.setattr(environment, "_run", lambda args: pytest.fail("Editor must not be launched"))
    result = environment._probe({"key": "code", "name": "VS Code", "spec": ""})
    assert result["status"] == "present" and result["version"] == "1.137.0"
    result = environment._probe({"key": "code", "name": "VS Code", "spec": ">=2.0"})
    assert result["status"] == "mismatch"


def test_setup_plan_uses_evidence_and_never_executes(monkeypatch):
    from learning_ext.practice import auto_setup
    monkeypatch.setattr(auto_setup, "audited_exploration", lambda *a, **k: {"items": [ready_python()]})
    captured = []
    def planner(prompt, **kwargs):
        captured.append(json.loads(prompt))
        return [{"desc": "安装 Python", "cmd": "winget install Python.Python.3.12"}, {"desc": "检查 Git", "cmd": "git --version"}]
    monkeypatch.setattr(auto_setup, "chat_json", planner)
    result = auto_setup.generate_install_commands("Python 3.10+ 和 Git")
    assert len(result) == 1 and result[0]["cmd"] == "git --version"
    assert captured[0]["environment"]["items"][0]["status"] == "ready"
