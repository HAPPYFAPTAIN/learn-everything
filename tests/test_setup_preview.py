import pytest
from learning_ext.db.models import LearningProject, Task


@pytest.fixture
def setup_case(session, monkeypatch):
    import learning_ext.pages.study_workbench as page
    import learning_ext.practice.auto_setup as service
    monkeypatch.setattr(page, "engine", session.get_bind())
    project = LearningProject(user_id="test", topic="setup")
    session.add(project)
    session.commit()
    task = Task(project_id=project.id, title="test setup", task_type="env", description="Check environment")
    session.add(task)
    session.commit()
    monkeypatch.setattr(service, "generate_install_commands", lambda *args: [{"cmd": "Write-Output 'preview-execution-ok'", "desc": "输出验收文字"}])
    return page.StudyWorkbenchPage.__new__(page.StudyWorkbenchPage), project.id, task, service


def test_preview_never_executes(session, monkeypatch, setup_case):
    page, pid, _, service = setup_case
    monkeypatch.setattr(service, "run_all_commands", lambda *a, **k: pytest.fail("Preview must not execute"))
    outputs = list(page._prepare_setup(pid))
    assert outputs[0][0]["visible"] is False
    assert 'aria-busy="true"' in outputs[0][1]
    assert "Write-Output" in outputs[-1][0]["value"]
    assert outputs[-1][2]["project_id"] == pid
    assert outputs[-1][3]["visible"] is True
    assert 'data-env-state="ready"' in outputs[-1][1]
    assert "输出验收文字" in outputs[-1][1]


def test_generated_step_descriptions_are_safe_html(setup_case, monkeypatch):
    page, pid, _, service = setup_case
    monkeypatch.setattr(service, "generate_install_commands", lambda *args: [{"cmd": "echo safe", "desc": '<img src=x onerror="alert(1)">'}])
    result = list(page._prepare_setup(pid))[-1]
    assert '<img' not in result[1]
    assert '&lt;img' in result[1]


def test_changed_project_cannot_execute_preview(session, monkeypatch, setup_case):
    page, pid, _, service = setup_case
    plan = list(page._prepare_setup(pid))[-1][2]
    monkeypatch.setattr(service, "run_all_commands", lambda *a, **k: pytest.fail("Stale plan executed"))
    result = list(page._execute_setup(pid + 100, plan))[-1]
    assert "当前项目" in result[1]
    assert result[2] is None


def test_changed_checklist_cannot_execute_preview(session, monkeypatch, setup_case):
    page, pid, task, service = setup_case
    plan = list(page._prepare_setup(pid))[-1][2]
    task.description = "Updated checklist"
    session.add(task)
    session.commit()
    monkeypatch.setattr(service, "run_all_commands", lambda *a, **k: pytest.fail("Stale plan executed"))
    assert "已更新" in list(page._execute_setup(pid, plan))[-1][1]


def test_explicit_execution_runs_preview_and_clears_plan(session, setup_case):
    page, pid, _, _ = setup_case
    plan = list(page._prepare_setup(pid))[-1][2]
    result = list(page._execute_setup(pid, plan))[-1]
    assert "preview-execution-ok" in result[0]["value"]
    assert "命令执行成功" in result[1]
    assert result[2] is None
    assert result[3]["visible"] is False
