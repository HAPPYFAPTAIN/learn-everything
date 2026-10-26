import pytest
from sqlmodel import select

from learning_ext.db.models import LearningProject, KnowledgeNode, ProgressRecord
from learning_ext.dashboard.service import seed_demo_learning_data, build_dashboard_data
from learning_ext.project_ops import delete_projects


def test_dimensions_use_real_review_and_graded_results(session):
    project = seed_demo_learning_data(session)
    data = build_dashboard_data(session, project_id=project.id)["dimensions"]
    assert data["review_count"] == 6
    assert data["quiz_count"] == 5
    assert data["accuracy"] == 60
    assert data["tasks_done"] == 1
    assert data["total_minutes"] > 0
    assert data["events"] == sorted(data["events"], key=lambda event: event["at"], reverse=True)


def test_foreign_project_does_not_leak_metrics(session):
    project = seed_demo_learning_data(session, user_id="another-user")
    data = build_dashboard_data(session, project_id=project.id)
    assert data["metrics"]["total_nodes"] == 0
    assert data["dimensions"]["quiz_count"] == 0
    assert data["dimensions"]["accuracy"] is None
    assert data["dimensions"]["events"] == []


def test_batch_delete_validates_every_project_before_mutation(session):
    own = seed_demo_learning_data(session)
    other = seed_demo_learning_data(session, user_id="another-user")
    with pytest.raises(ValueError):
        delete_projects(session, [own.id, other.id])
    assert session.get(LearningProject, own.id) is not None
    assert session.exec(select(KnowledgeNode).where(KnowledgeNode.project_id == own.id)).first()


def test_batch_delete_removes_selected_projects_only(session):
    one = seed_demo_learning_data(session)
    two = LearningProject(user_id="default", title="Delete me", topic="test")
    keep = LearningProject(user_id="default", title="Keep me", topic="test")
    session.add(two)
    session.add(keep)
    session.commit()
    ids = [one.id, two.id]
    result = delete_projects(session, ids + [one.id])
    assert result["count"] == 2
    assert session.get(LearningProject, keep.id)
    assert not session.exec(select(KnowledgeNode).where(KnowledgeNode.project_id.in_(ids))).all()


def test_status_changes_are_recorded_once(session):
    from learning_ext.progress.study import set_node_status
    project = seed_demo_learning_data(session)
    node = session.exec(select(KnowledgeNode).where(KnowledgeNode.project_id == project.id, KnowledgeNode.status == "pending")).first()
    set_node_status(session, node.id, "learning")
    set_node_status(session, node.id, "learning")
    rows = session.exec(select(ProgressRecord).where(ProgressRecord.node_id == node.id, ProgressRecord.metric == "lesson_learning")).all()
    assert len(rows) == 1


def test_batch_confirmation_cannot_delete_changed_selection(session, monkeypatch):
    import learning_ext.pages.path_generator as module
    monkeypatch.setattr(module, "engine", session.get_bind())
    project = seed_demo_learning_data(session)
    page = object.__new__(module.PathGeneratorPage)
    result = page._commit_batch_delete([project.id], [project.id + 1], project.id)
    assert "重新确认" in result[2]
    assert session.get(LearningProject, project.id) is not None
