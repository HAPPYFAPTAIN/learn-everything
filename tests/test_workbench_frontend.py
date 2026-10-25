from pathlib import Path
from types import SimpleNamespace
import inspect


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_CSS = ROOT / "learning_ext/assets/workbench.css"
WORKBENCH_JS = ROOT / "learning_ext/assets/workbench.js"


def _compact(source):
    return "".join(source.split())


def _block(source, marker):
    start = source.index(marker)
    opening = source.index("{", start)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError(f"Unclosed block: {marker}")


def test_toolbar_grid_breakpoint_matches_single_column_workbench():
    css = WORKBENCH_CSS.read_text(encoding="utf-8")
    toolbar = _compact(_block(css, "@media(max-width:1000px){#le-left-col"))
    workbench = _compact(_block(css, "@media(max-width:1000px){#le-workbench-row"))

    assert "display:grid!important" in toolbar
    assert "grid-template-columns:minmax(0,1fr)minmax(0,1fr)!important" in toolbar
    assert "width:auto!important;min-width:0!important" in toolbar
    assert "#le-left-col#le-project-picker{width:100%!important}" in toolbar
    assert "grid-template-columns:minmax(0,1fr)!important" in workbench
    assert "@media(max-width:900px){#le-left-col" not in _compact(css)


def test_mobile_toolbar_keeps_progress_and_admin_on_one_row():
    css = WORKBENCH_CSS.read_text(encoding="utf-8")
    block = _compact(_block(css, "@media(max-width:650px){#le-left-col"))

    assert "grid-template-columns:minmax(0,1fr)auto!important" in block
    assert "#le-left-col>.form{grid-column:1/-1!important}" in block
    assert "#le-left-col#le-course-progress{grid-column:1!important}" in block
    assert "#le-course-admin{grid-column:2!important}" in block


def test_small_outline_defaults_closed_and_preserves_manual_choice():
    css = WORKBENCH_CSS.read_text(encoding="utf-8")
    js = _compact(WORKBENCH_JS.read_text(encoding="utf-8"))
    small_layout = _compact(_block(css, "@media(max-width:1000px){#le-workbench-row"))

    assert "nav=document.createElement('details')" in js
    assert "nav.open=innerWidth>1000" in js
    assert "constSMALL_KEY='le.toc.mobileOpen'" in js
    assert "nav.addEventListener('toggle'" in js
    assert "localStorage.setItem(SMALL_KEY,open?'1':'0')" in js
    assert "setOpen(nav,desktop||storedSmallOpen()===true)" in js
    assert "#le-lesson-outline" in small_layout
    assert "display:none" not in small_layout


def test_long_course_navigation_tracks_position_and_reuses_master_event():
    js = _compact(WORKBENCH_JS.read_text(encoding="utf-8"))
    import learning_ext.pages.study_workbench as module

    ui_source = inspect.getsource(module.StudyWorkbenchPage.on_building_ui)
    event_source = inspect.getsource(module.StudyWorkbenchPage.on_register_events)
    master_event = event_source[
        event_source.index("self.master_btn.click("):event_source.index("self.gate_quiz_btn.click(")
    ]

    assert "window.addEventListener('scroll',scheduleCurrent" in js
    assert "markCurrent(buttons[index])" in js
    assert "b.hidden=!active||masterVisible" in js
    assert "document.getElementById('le-master-btn')" in js
    assert "if(current)current.click()" in js
    assert 'elem_id="le-master-btn"' in ui_source
    assert "fn=self._try_master" in master_event


def test_hidden_bridges_skip_tab_order_without_removing_click_events():
    import learning_ext.pages.study_workbench as module

    selected = _compact(_block(module.WORKBENCH_CSS, "#le-selected-term"))
    css = WORKBENCH_CSS.read_text(encoding="utf-8")
    rewrite = _compact(_block(css, "#le-rewrite-bridge"))
    timed = _compact(_block(css, "#le-time-bridge"))
    event_source = inspect.getsource(module.StudyWorkbenchPage.on_register_events)

    for rule in (selected, rewrite, timed):
        assert "visibility:hidden!important" in rule
    assert "#le-anno-bridge" in timed
    assert "#le-snooze-bridge" in timed
    for trigger in ("rewrite", "anno", "time", "snooze"):
        assert f"self.{trigger}_trigger.click" in event_source


def test_prep_tracking_is_initialized_for_object_new_pages(monkeypatch):
    import learning_ext.pages.study_workbench as module
    from learning_ext.progress import prep

    class EmptySession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def exec(self, *args):
            return SimpleNamespace(all=lambda: [])

    sessions = []
    starts = []

    def session_factory(_engine):
        session = EmptySession()
        sessions.append(session)
        return session

    monkeypatch.setattr(module, "Session", session_factory)
    monkeypatch.setattr(prep, "start", lambda *args: starts.append(args))
    page = object.__new__(module.StudyWorkbenchPage)

    page._kick_project_prep(17, "topic")
    page._kick_project_prep(17, "topic")

    assert page._prep_kicked == {17}
    assert len(sessions) == 1
    assert starts == []
