import inspect

import pytest
from sqlmodel import select

from learning_ext.db.models import LearningProject, NodeAnnotation, KnowledgeNode
from learning_ext.pages.study_workbench import StudyWorkbenchPage


def _page():
    page = object.__new__(StudyWorkbenchPage)
    page._prep_kicked = set()
    page._pending_nodes = {}
    page._pending_node = None
    page.load_outputs = list(range(13))
    return page


def test_project_settings_include_safe_delete_events():
    ui = inspect.getsource(StudyWorkbenchPage.on_building_ui)
    events = inspect.getsource(StudyWorkbenchPage.on_register_events)

    assert 'elem_id="le-project-settings"' in ui
    assert 'elem_id="le-delete-confirm"' in ui
    assert "self.delete_confirm.input" in events
    assert "self.project_id.input" in events
    assert "self._delete_current_project" in events
    assert "concurrency_limit=1" in events


def test_delete_requires_exact_confirmation(session, sample_project, monkeypatch):
    import learning_ext.pages.study_workbench as module

    monkeypatch.setattr(module, "engine", session.get_bind())
    page = _page()
    monkeypatch.setattr(page, "_auto_init", lambda: pytest.fail("确认失败不应刷新页面"))

    result = page._delete_current_project(sample_project.id, "delete")

    assert len(result) == 16
    assert "DELETE" in result[-1]
    assert result[-2]["interactive"] is False
    assert session.get(LearningProject, sample_project.id) is not None


def test_delete_is_refused_while_preparation_is_busy(session, sample_project, monkeypatch):
    import learning_ext.pages.study_workbench as module
    from learning_ext.progress import prep

    monkeypatch.setattr(module, "engine", session.get_bind())
    monkeypatch.setattr(prep, "is_busy", lambda _pid: True)
    page = _page()

    result = page._delete_current_project(sample_project.id, "DELETE")

    assert "正在备课" in result[-1]
    assert result[-2]["interactive"] is True
    assert session.get(LearningProject, sample_project.id) is not None


def test_delete_rejects_another_users_project(session, sample_project, monkeypatch):
    import learning_ext.pages.study_workbench as module

    other = LearningProject(user_id="someone-else", topic="其他用户项目", title="其他用户项目")
    session.add(other)
    session.commit()
    monkeypatch.setattr(module, "engine", session.get_bind())
    page = _page()

    result = page._delete_current_project(other.id, "DELETE")

    assert "无权删除" in result[-1]
    assert session.get(LearningProject, other.id) is not None
    assert session.get(LearningProject, sample_project.id) is not None


def test_delete_switches_to_the_remaining_project(session, sample_project, monkeypatch):
    import learning_ext.pages.study_workbench as module

    remaining = LearningProject(user_id="default", topic="保留项目", title="保留项目", status="active")
    session.add(remaining)
    session.commit()
    monkeypatch.setattr(module, "engine", session.get_bind())
    deleted_id = sample_project.id
    page = _page()
    page._prep_kicked = {deleted_id}

    result = page._delete_current_project(deleted_id, "DELETE")

    session.expire_all()
    assert session.get(LearningProject, deleted_id) is None
    assert result[3] == remaining.id
    assert result[13] == ""
    assert result[14]["interactive"] is False
    assert "已删除项目" in result[15]
    assert deleted_id not in page._prep_kicked


def test_delete_last_project_clears_project_and_course_choices(session, sample_project, monkeypatch):
    import learning_ext.pages.study_workbench as module

    monkeypatch.setattr(module, "engine", session.get_bind())
    page = _page()

    result = page._delete_current_project(sample_project.id, "DELETE")

    assert session.exec(select(LearningProject)).all() == []
    assert result[0]["choices"] == []
    assert result[0]["value"] is None
    assert result[2]["choices"] == []
    assert result[2]["value"] is None
    assert result[3] is None
    assert "创建学习路线" in result[6]


def test_delete_project_also_cascades_annotations(session, sample_project):
    from learning_ext.project_ops import delete_project

    node = session.exec(select(KnowledgeNode)).first()
    annotation = NodeAnnotation(
        user_id="default",
        project_id=sample_project.id,
        node_id=node.id,
        quote="原文",
        body="一条批注",
    )
    session.add(annotation)
    session.commit()

    result = delete_project(session, sample_project.id)

    assert result["deleted"]["annotations"] == 1
    assert session.exec(select(NodeAnnotation)).all() == []
