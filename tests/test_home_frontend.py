from datetime import datetime, timedelta
import inspect
from pathlib import Path
import re

from sqlmodel import select

import learning_ext.onboarding as onboarding
from learning_ext.db.models import Card, KnowledgeNode
from learning_ext.progress.study import sort_nodes_by_code


def _use_test_engine(session, monkeypatch):
    import ktem.db.engine as engine_module

    monkeypatch.setattr(engine_module, "engine", session.get_bind())


def _project_nodes(session, project_id):
    nodes = session.exec(
        select(KnowledgeNode).where(KnowledgeNode.project_id == project_id)
    ).all()
    return sort_nodes_by_code(list(nodes))


def test_resume_without_course_keeps_three_value_new_user_contract(session, monkeypatch):
    _use_test_engine(session, monkeypatch)

    result = onboarding.GuidedHomePage._resume_info()

    assert len(result) == 3
    assert result[0]["visible"] is False
    assert result[1] == ""
    assert result[2] is None


def test_resume_zero_progress_and_no_cards_has_real_fallbacks(
    session, sample_project, monkeypatch
):
    _use_test_engine(session, monkeypatch)
    nodes = _project_nodes(session, sample_project.id)

    visible, markup, project_id = onboarding.GuidedHomePage._resume_info()

    assert visible["visible"] is True
    assert project_id == sample_project.id
    assert f"已掌握 0 / {len(nodes)} 节" in markup
    assert 'aria-valuenow="0"' in markup
    assert f'<span>{nodes[0].code}</span>{nodes[0].title}' in markup
    assert "<strong>0 <span>张</span></strong>" in markup
    assert "暂无复习卡" not in markup
    assert '<div class="le-resume-review"><small>待复习</small>' in markup


def test_resume_renders_real_progress_next_lesson_and_due_count(
    session, sample_project, monkeypatch
):
    _use_test_engine(session, monkeypatch)
    nodes = _project_nodes(session, sample_project.id)
    nodes[0].status = "mastered"
    sample_project.topic = 'Python <数据> & "AI"'
    now = datetime.utcnow()
    session.add(nodes[0])
    session.add(sample_project)
    session.add_all(
        [
            Card(
                user_id="default",
                project_id=sample_project.id,
                node_id=nodes[0].id,
                front="到期卡",
                back="答案",
                next_review=now - timedelta(hours=1),
            ),
            Card(
                user_id="default",
                project_id=sample_project.id,
                node_id=nodes[0].id,
                front="未到期卡",
                back="答案",
                next_review=now + timedelta(days=1),
            ),
            Card(
                user_id="default",
                project_id=sample_project.id,
                node_id=nodes[0].id,
                front="暂停卡",
                back="答案",
                next_review=now - timedelta(hours=1),
                suspended=True,
            ),
        ]
    )
    session.commit()

    result = onboarding.GuidedHomePage._resume_info()
    visible, markup, project_id = result

    assert len(result) == 3
    assert visible["visible"] is True
    assert project_id == sample_project.id
    assert "Python &lt;数据&gt; &amp; &quot;AI&quot;" in markup
    assert "Python <数据>" not in markup
    assert f"已掌握 1 / {len(nodes)} 节" in markup
    expected_pct = round(100 / len(nodes), 1)
    assert f"{expected_pct:g}%" in markup
    assert f'<span>{nodes[1].code}</span>{nodes[1].title}' in markup
    assert "<strong>1 <span>张</span></strong>" in markup
    assert "现在可以复习" not in markup
    assert '<div class="le-resume-review"><small>待复习</small>' in markup


def test_resume_card_precedes_hero_without_changing_event_contract():
    source = inspect.getsource(onboarding.GuidedHomePage.on_building_ui)
    events = inspect.getsource(onboarding.GuidedHomePage.on_register_events)

    assert source.index('elem_id="le-resume-row"') < source.index("gr.HTML(HERO)")
    assert 'self.resume_btn = gr.Button("继续学习 →", variant="primary"' in source
    assert "self._app.app.load(self._resume_info" in events
    assert "self.resume_btn.click(wb._auto_init" in events


def test_navigation_exposes_primary_learning_tabs_and_keeps_existing_jump_behavior():
    js = Path("learning_ext/assets/onboarding.js").read_text(encoding="utf-8")

    def names(variable):
        match = re.search(rf"const {variable} = \[(.*?)\];", js)
        assert match is not None
        return re.findall(r"'([^']+)'", match.group(1))

    assert names("primary") == [
        "learning-guide-tab-button",
        "learning-workbench-tab-button",
        "learning-review-tab-button",
        "learning-quiz-tab-button",
    ]
    secondary = names("secondary")
    assert "learning-path-tab-button" in secondary
    assert "learning-review-tab-button" not in secondary
    assert "learning-quiz-tab-button" not in secondary
    assert "button.hidden = !more && !button.classList.contains('selected')" in js
    assert "localStorage.setItem('le.nav.more'" in js
    assert "if (target) target.hidden = false" in js


def test_home_accessibility_and_returning_layout_hooks_exist():
    js = Path("learning_ext/assets/onboarding.js").read_text(encoding="utf-8")
    css = Path("learning_ext/assets/home.css").read_text(encoding="utf-8")
    nav_css = Path("learning_ext/assets/nav.css").read_text(encoding="utf-8")

    assert "feedback.setAttribute('role', 'alert')" in js
    assert "feedback.setAttribute('aria-live', 'assertive')" in js
    assert "button.setAttribute('aria-pressed', String(selected))" in js
    assert "String(button.dataset.leSelected === 'true')" in js
    assert "#le-guided-home:has(.le-resume-strip) .le-discovery-hero" in css
    assert "#le-guided-home:has(.le-resume-strip) .le-hero-art{display:none}" in css
    assert "#le-guided-home:has(.le-resume-strip) .le-direction-art{display:none}" in css
    assert "le-resume-progress-track" in css
    assert "@media(max-width:800px)" in css
    assert "#le-more-nav[aria-expanded]" in nav_css
