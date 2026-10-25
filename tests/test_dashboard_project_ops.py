from __future__ import annotations

from sqlmodel import select
from unittest.mock import MagicMock
import pytest


@pytest.mark.parametrize("enabled", [False, True])
def test_demo_creation_is_only_exposed_when_explicitly_enabled(monkeypatch, enabled):
    import gradio as gr
    from learning_ext.pages.dashboard import DashboardPage

    monkeypatch.setenv("LE_ENABLE_DEMO", "1" if enabled else "0")
    page = object.__new__(DashboardPage)
    with gr.Blocks():
        page.on_building_ui()
    assert (page.seed_btn is not None) is enabled
    assert page.export_btn is not None


def test_seed_demo_learning_data_is_repeatable(session):
    from learning_ext.dashboard.service import build_dashboard_data, seed_demo_learning_data
    from learning_ext.db.models import Card, KnowledgeNode, LearningProject, ProgressRecord

    first = seed_demo_learning_data(session)
    second = seed_demo_learning_data(session)

    projects = session.exec(select(LearningProject)).all()
    nodes = session.exec(select(KnowledgeNode)).all()
    cards = session.exec(select(Card)).all()
    progress = session.exec(select(ProgressRecord)).all()
    summary = build_dashboard_data(session, project_id=second.id)

    assert first.title == "学习看板测试项目"
    assert len(projects) == 1
    assert len(nodes) >= 8
    assert len(cards) >= 6
    assert len(progress) >= 10
    assert summary["metrics"]["total_nodes"] == len(nodes)
    assert summary["metrics"]["mastered_nodes"] >= 2
    assert summary["metrics"]["week_minutes"] > 0


def test_delete_project_cascades_learning_data(session):
    from learning_ext.dashboard.service import seed_demo_learning_data
    from learning_ext.db.models import (
        Card,
        DailyReport,
        KnowledgeEdge,
        KnowledgeNode,
        LearningProject,
        NodeNote,
        NodeResource,
        ProgressRecord,
        Quiz,
        QuizAttempt,
        QuizQuestion,
        ReviewLog,
        Task,
    )
    from learning_ext.project_ops import delete_project

    project = seed_demo_learning_data(session)

    result = delete_project(session, project.id)

    assert result["project_id"] == project.id
    assert result["deleted"]["projects"] == 1
    assert session.get(LearningProject, project.id) is None
    for model in (
        Card,
        DailyReport,
        KnowledgeEdge,
        KnowledgeNode,
        NodeNote,
        NodeResource,
        ProgressRecord,
        Quiz,
        QuizAttempt,
        QuizQuestion,
        ReviewLog,
        Task,
    ):
        assert session.exec(select(model)).all() == []


def test_delete_project_missing_id_raises(session):
    from learning_ext.project_ops import delete_project

    try:
        delete_project(session, 99999)
    except ValueError as exc:
        assert "Project 99999 not found" in str(exc)
    else:
        raise AssertionError("delete_project should reject missing projects")


def test_path_page_delete_project_requires_delete_confirmation(
    session, sample_project, monkeypatch
):
    import learning_ext.pages.path_generator as path_page_module
    from learning_ext.db.models import LearningProject
    from learning_ext.pages.path_generator import PathGeneratorPage

    monkeypatch.setattr(path_page_module, "engine", session.get_bind())
    page = PathGeneratorPage(MagicMock())

    _, status = page._handle_delete_project(sample_project.id, "")

    assert "DELETE" in status
    assert session.get(LearningProject, sample_project.id) is not None


def test_path_page_delete_project_removes_project(session, sample_project, monkeypatch):
    import learning_ext.pages.path_generator as path_page_module
    from learning_ext.db.models import LearningProject
    from learning_ext.pages.path_generator import PathGeneratorPage

    monkeypatch.setattr(path_page_module, "engine", session.get_bind())
    page = PathGeneratorPage(MagicMock())
    project_id = sample_project.id

    rows, status = page._handle_delete_project(project_id, "DELETE")

    assert "已删除项目" in status
    assert rows == []
    session.expire_all()
    assert session.get(LearningProject, project_id) is None


def test_dashboard_page_seed_demo_data_outputs_dashboard(session, monkeypatch):
    import learning_ext.pages.dashboard as dashboard_page_module
    from learning_ext.pages.dashboard import DashboardPage

    monkeypatch.setattr(dashboard_page_module, "engine", session.get_bind())
    page = DashboardPage(MagicMock())

    project_update, metrics_html, status_md, fig, report, status = page._seed_demo_data()

    assert project_update["choices"]
    assert "知识点总数" in metrics_html
    assert "已掌握" in status_md
    assert "le-activity-chart" in fig
    assert "今日学习日报" in report
    assert "演示项目已创建" in status


def test_dashboard_page_registers_no_arg_events_with_empty_inputs():
    from learning_ext.pages.dashboard import DashboardPage

    app = MagicMock()
    page = DashboardPage(app)
    page.project_id = MagicMock()
    page.refresh_btn = MagicMock()
    page.seed_btn = MagicMock()
    page.metric_html = MagicMock()
    page.status_md = MagicMock()
    page.heatmap = MagicMock()
    page.period = MagicMock()
    page.export_btn = MagicMock()
    page.export_file = MagicMock()
    page.export_status = MagicMock()
    page.report = MagicMock()
    page.status = MagicMock()

    page.on_register_events()

    assert page.seed_btn.click.call_args.kwargs["inputs"] == []
    assert app.app.load.call_args.kwargs["inputs"] == []


def test_activity_ranges_and_full_export(session, monkeypatch):
    import csv
    from datetime import datetime, timedelta
    from pathlib import Path
    import learning_ext.pages.dashboard as module
    from learning_ext.db.models import LearningProject, ProgressRecord
    monkeypatch.setattr(module, "engine", session.get_bind())
    project = LearningProject(user_id="default", title="时长测试", topic="时长测试")
    other = LearningProject(user_id="someone-else", title="其他", topic="其他")
    session.add_all([project, other]); session.commit()
    for ago, minutes in [(0, 7), (2, 11), (20, 13), (45, 17)]:
        session.add(ProgressRecord(user_id="default", project_id=project.id, metric="study_minutes", value=minutes, recorded_at=datetime.utcnow()-timedelta(days=ago)))
    session.add(ProgressRecord(user_id="default", project_id=project.id, metric="mastery", value=0.8))
    session.commit()
    page = module.DashboardPage(MagicMock())
    three = page._activity_rows(session, project.id, 3)
    thirty = page._activity_rows(session, project.id, 30)
    assert len(three) == 3 and sum(x["minutes"] for x in three) == 18
    assert len(thirty) == 30 and sum(x["minutes"] for x in thirty) == 31
    assert not page._activity_records(session, other.id)
    update, message = page._export_activity(str(project.id))
    path = Path(update["value"])
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        assert len(rows) == 5
        assert sum(float(row[4]) for row in rows[1:]) == 48
        assert "4 条" in message
    finally:
        path.unlink(); path.parent.rmdir()
    update, message = page._export_activity(str(other.id))
    assert update["value"] is None and not update["visible"]
