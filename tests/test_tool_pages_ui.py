from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import MagicMock

import gradio as gr
import pytest
from sqlmodel import select


def test_tool_page_intros_are_compact_and_keep_headings():
    from learning_ext.page_design import _PAGES, page_intro

    assert set(_PAGES) == {"route", "review", "quiz", "dashboard", "setup", "library", "help"}
    for kind, (label, title) in _PAGES.items():
        html = page_intro(kind)
        assert f"le-editorial-{kind}" in html
        assert f'<span class="le-section-label">{label}</span>' in html
        assert f"<h1>{title}</h1>" in html
        assert 'class="le-editorial-art" aria-hidden="true"' in html

    css = Path("learning_ext/assets/pages.css").read_text(encoding="utf-8")
    header = css.split(".gradio-container .le-editorial-head{", 1)[1].split("}", 1)[0]
    assert "min-height:96px" in header
    assert "padding:12px 24px" in header
    assert "min-height:220px" not in css
    assert "min-height:180px" not in css
    assert "min-height:88px" in css


def test_quiz_options_are_collapsed_and_generation_wiring_is_unchanged():
    from learning_ext.pages.quiz import QuizPage

    with gr.Blocks() as blocks:
        page = QuizPage(MagicMock())
        page.on_building_ui()

    options = next(
        block
        for block in blocks.blocks.values()
        if isinstance(block, gr.Accordion) and block.label == "题量与题型 · 5 题 / 混合"
    )
    assert options.open is False
    assert page.count.value == 5
    assert page.qtype.value == "mixed"
    assert page.btn_gen.value == "开始测验 →"

    events = inspect.getsource(QuizPage.on_register_events)
    generate_event = events.split("self.btn_gen.click(", 1)[1].split("self.resume.click(", 1)[0]
    assert generate_event.count("self._generate") == 1
    for component in ("self.project_id", "self.scope", "self.node_pick", "self.chapter_pick", "self.progress_pick", "self.count", "self.qtype"):
        assert component in generate_event


def test_review_empty_state_requires_section_and_never_auto_generates(session, sample_project, monkeypatch):
    import learning_ext.pages.review as module
    from learning_ext.db.models import KnowledgeNode

    monkeypatch.setattr(module, "engine", session.get_bind())
    monkeypatch.setattr(
        module,
        "generate_cards_from_node",
        lambda *args, **kwargs: pytest.fail("选择复习范围时不应生成卡片"),
    )
    with gr.Blocks():
        page = module.ReviewPage(MagicMock())
        page.on_building_ui()

    assert page.gen_cards.value == "生成卡片（5 张）"
    assert page.gen_cards.variant == "primary"
    assert page.gen_cards.visible is False

    project_id = str(sample_project.id)
    page._on_project_change(project_id)
    project_empty = page._preview(project_id, module.ALL_NODES)
    assert "复习哪一节" in project_empty[0]
    assert "具体一节" in project_empty[0]
    assert project_empty[7]["visible"] is False
    assert project_empty[7]["interactive"] is False

    node = session.exec(select(KnowledgeNode)).first()
    section_empty = page._preview(project_id, str(node.id))
    assert "生成卡片（5 张）" in section_empty[0]
    assert section_empty[7]["visible"] is True
    assert section_empty[7]["interactive"] is True


def test_dashboard_next_step_precedes_metrics_and_zero_mastered_is_neutral(session, sample_project):
    from learning_ext.pages.dashboard import DashboardPage

    page = object.__new__(DashboardPage)
    html = page._dashboard_outputs(session, sample_project.id, "")[1]
    assert html.index("le-dashboard-next") < html.index("le-metrics")
    assert 'class="le-metric le-metric-mastered is-empty"' in html

    metrics = {
        "total_nodes": 2,
        "mastered_nodes": 1,
        "avg_mastery": 0.5,
        "week_minutes": 30,
        "due_cards": 1,
        "total_cards": 2,
    }
    populated = page._render_metrics(metrics)
    assert 'class="le-metric le-metric-mastered"' in populated
    assert "is-empty" not in populated

    css = Path("learning_ext/assets/pages.css").read_text(encoding="utf-8")
    assert ".le-metric-mastered:not(.is-empty)" in css
    assert ".le-metric:nth-child(2)" not in css
