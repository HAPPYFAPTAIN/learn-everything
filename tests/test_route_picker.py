from __future__ import annotations

import json
from unittest.mock import MagicMock

import gradio as gr
import pytest


@pytest.fixture
def route_page(session, monkeypatch):
    import learning_ext.pages.path_generator as module

    monkeypatch.setattr(module, "engine", session.get_bind())
    return module.PathGeneratorPage(MagicMock())


def test_picker_labels_name_and_progress_but_keeps_stable_id(route_page):
    rows = [[17, "用 Python 整理表格", "2/8 (25%)", "2026-10-26 10:00"]]
    picker, empty = route_page._picker_updates(rows, 17)

    assert picker["choices"] == [("用 Python 整理表格\n2/8 节已完成", 17)]
    assert picker["value"] == 17
    assert picker["visible"] is True
    assert empty["visible"] is False


def test_picker_does_not_select_a_route_that_was_removed(route_page):
    picker, empty = route_page._picker_updates([], 17)

    assert picker["value"] is None
    assert picker["visible"] is False
    assert empty["visible"] is True


def test_selected_route_loads_by_radio_value(route_page, sample_project):
    markdown, raw, project_id, status = route_page._handle_load(sample_project.id)

    assert project_id == sample_project.id
    assert "入门概念" in markdown
    assert len(json.loads(raw)["nodes"]) == 3
    assert not status
    picker, _ = route_page._refresh_picker(project_id)
    assert picker["value"] == project_id


def test_missing_route_is_not_treated_as_an_active_empty_route(route_page):
    markdown, raw, project_id, status = route_page._handle_load(999999)

    assert project_id is None
    assert raw == "{}"
    assert markdown == ""
    assert "加载失败" in status


def test_switching_resets_destructive_confirmation_and_old_export(route_page, sample_project):
    picker, _, confirmation, export, token = route_page._sync_route_selection(sample_project.id)

    assert picker["value"] == sample_project.id
    assert confirmation["value"] == ""
    assert export["value"] is None
    assert export["visible"] is False
    assert token is None


def test_delete_without_confirmation_preserves_current_route(route_page, sample_project):
    picker, _, markdown, raw, current, status, confirmation, token = (
        route_page._handle_delete_selection(sample_project.id, "", sample_project.id)
    )

    assert picker["value"] == sample_project.id
    assert "DELETE" in status
    for update in (markdown, raw, current, confirmation, token):
        assert update == gr.update()


def test_deleting_last_route_clears_current_and_stops_preparation(route_page, sample_project):
    picker, empty, markdown, raw, current, status, confirmation, token = (
        route_page._handle_delete_selection(sample_project.id, "DELETE", sample_project.id, sample_project.id)
    )

    assert picker["value"] is None
    assert picker["choices"] == []
    assert empty["visible"] is True
    assert "暂无学习路线" in markdown
    assert raw == "{}"
    assert current is None
    assert "已删除项目" in status
    assert confirmation == ""
    assert token is None
    assert route_page._load_preparation(current) == ("", {}, gr.update(active=False))


def test_deleting_current_route_opens_another_route(route_page, sample_project, session):
    from learning_ext.path_generator import import_roadmap_bundle, load_roadmap

    remaining = import_roadmap_bundle(session, load_roadmap(session, sample_project.id))
    picker, _, markdown, raw, current, status, _, token = route_page._handle_delete_selection(
        sample_project.id, "DELETE", sample_project.id, sample_project.id
    )

    assert current == remaining.id
    assert picker["value"] == remaining.id
    assert len(picker["choices"]) == 1
    assert "入门概念" in markdown
    assert len(json.loads(raw)["nodes"]) == 3
    assert "已删除项目" in status
    assert token is None


@pytest.mark.parametrize("current_is_new_route", [False, True])
def test_stale_delete_confirmation_cannot_delete_newly_selected_route(
    route_page, sample_project, session, current_is_new_route
):
    from learning_ext.db.models import LearningProject
    from learning_ext.path_generator import import_roadmap_bundle, load_roadmap

    other = import_roadmap_bundle(session, load_roadmap(session, sample_project.id))
    current_id = other.id if current_is_new_route else sample_project.id
    picker, _, markdown, raw, current, status, confirmation, token = route_page._handle_delete_selection(
        other.id, "DELETE", current_id, sample_project.id
    )

    assert current == gr.update()
    assert picker["value"] == current_id
    assert markdown == gr.update()
    assert raw == gr.update()
    assert "重新输入 DELETE" in status
    assert confirmation == ""
    assert token is None
    session.expire_all()
    assert session.get(LearningProject, other.id) is not None
    assert session.get(LearningProject, sample_project.id) is not None


def test_delete_confirmation_only_binds_to_the_loaded_route(route_page):
    assert route_page._bind_delete_confirmation("DELETE", 3, 3) == 3
    assert route_page._bind_delete_confirmation("DELETE", 3, 2) is None
    assert route_page._bind_delete_confirmation("", 3, 3) is None
    clear, token, export = route_page._begin_route_selection()
    assert clear["value"] == ""
    assert token is None
    assert export["value"] is None


def test_refresh_keeps_unsaved_preview(route_page):
    result = route_page._refresh_current_route(None)
    assert all(update == gr.update() for update in result[2:])


def test_refresh_reads_latest_route_and_preparation_without_generation(
    route_page, sample_project, session, monkeypatch
):
    from sqlmodel import select
    from learning_ext.db.models import KnowledgeNode
    from learning_ext.progress import prep

    node = session.exec(select(KnowledgeNode).where(KnowledgeNode.project_id == sample_project.id)).first()
    node.status = "mastered"
    session.add(node)
    session.commit()
    start = MagicMock()
    monkeypatch.setattr(prep, "start", start)
    picker, _, markdown, raw, current, status, _, context, _ = route_page._refresh_current_route(sample_project.id)

    assert picker["value"] == sample_project.id
    assert "1/3 节已完成" in picker["choices"][0][0]
    assert json.loads(raw)["nodes"][0]["status"] == "mastered"
    assert current == sample_project.id
    assert context["pid"] == sample_project.id
    assert not status
    assert "入门概念" in markdown
    start.assert_not_called()


def test_picker_prefers_the_users_goal_over_generated_long_title(route_page, sample_project, session):
    sample_project.topic = "  我想学 Agent 的架构  "
    sample_project.title = "面向初学者的 Agent 架构学习路线，40 小时每周高强度投入，从零完成各项任务。"
    session.add(sample_project)
    session.commit()

    picker, _ = route_page._refresh_picker(sample_project.id)
    assert picker["choices"][0][0].startswith("我想学 Agent 的架构\n")
    assert "高强度" not in picker["choices"][0][0]


@pytest.mark.parametrize("content", [None, "not valid JSON"])
def test_failed_import_preserves_current_selection(route_page, sample_project, tmp_path, content):
    source = None
    if content is not None:
        source = tmp_path / "bad.json"
        source.write_text(content, encoding="utf-8")
    picker, _, markdown, raw, current, status = route_page._handle_import_roadmap_selection(
        source, sample_project.id
    )

    assert picker["value"] == sample_project.id
    assert markdown == raw == current == gr.update()
    assert status


def test_import_adds_and_selects_route(route_page, sample_project, session, tmp_path):
    from learning_ext.path_generator import export_roadmap_bundle

    source = tmp_path / "route.json"
    source.write_text(export_roadmap_bundle(session, sample_project.id), encoding="utf-8")
    picker, empty, markdown, raw, current, status = route_page._handle_import_roadmap_selection(
        source, sample_project.id
    )

    assert current != sample_project.id
    assert picker["value"] == current
    assert len(picker["choices"]) == 2
    assert empty["visible"] is False
    assert "入门概念" in markdown
    assert len(json.loads(raw)["nodes"]) == 3
    assert "已导入" in status


def test_export_selected_route_produces_download(route_page, sample_project, tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.chdir(tmp_path)
    file_update, status = route_page._handle_export_roadmap_selection(sample_project.id)

    assert file_update["visible"] is True
    payload = json.loads(Path(file_update["value"]).read_text(encoding="utf-8"))
    assert payload["project"]["topic"] == sample_project.topic
    assert "已导出" in status


def test_route_picker_events_use_real_radio_input_and_publish_switch(session, monkeypatch):
    import learning_ext.pages.path_generator as module

    monkeypatch.setattr(module, "engine", session.get_bind())
    app = MagicMock()
    switched = lambda: None
    app.get_event.return_value = [{"fn": switched, "inputs": [], "outputs": []}]
    with gr.Blocks() as demo:
        app.app = demo
        page = module.PathGeneratorPage(app)
        page.on_building_ui()
        page.on_register_events()

    assert isinstance(page.project_list, gr.Radio)
    assert not hasattr(page, "load_project_id")
    assert not hasattr(page, "delete_project_id")
    assert not hasattr(page, "export_project_id")
    assert any(fn.fn == switched for fn in demo.fns.values())
    reset_event = next(fn for fn in demo.fns.values() if fn.fn == page._begin_route_selection)
    assert (page.project_list._id, "input") in reset_event.targets
    load_event = next(fn for fn in demo.fns.values() if fn.fn == page._handle_load)
    assert load_event.inputs == [page.project_list]
