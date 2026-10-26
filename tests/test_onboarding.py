from unittest.mock import MagicMock

import pytest
import requests

import learning_ext.onboarding as onboarding


def test_goal_summary_escapes_input_and_accepts_zero_experience():
    result = onboarding.goal_summary('<script>alert(1)</script>', '', 3)
    assert '<script>' not in result
    assert '&lt;script&gt;' in result
    assert '从基础开始' in result
    assert '每周 3 小时' in result


def test_empty_goal_stays_on_first_step():
    result = onboarding.GuidedHomePage(None)._confirm(' ', '', 3)
    assert result[0] == {'__type__': 'update'}
    assert '写下你想学会的事' in result[5]


@pytest.mark.parametrize('configured', [False, True])
def test_confirmation_reflects_actual_config(monkeypatch, configured):
    monkeypatch.setattr(onboarding, 'connection_configured', lambda: configured)
    result = onboarding.GuidedHomePage(None)._confirm('Python', '', 3)
    assert result[0]['visible'] is False
    assert result[1]['visible'] is True
    assert ('生成学习路线' if configured else '连接 AI') in result[4]['value']
    assert 'aria-current=step' in result[6]


def test_unconfigured_handoff_preserves_existing_route(monkeypatch):
    monkeypatch.setattr(onboarding, 'connection_configured', lambda: False)
    result = onboarding.GuidedHomePage(None)._handoff('Python', '', 3)
    assert all(item == {'__type__': 'update'} for item in result[:8])
    assert 'quick-setup-tab' in result[-1]


def test_configured_handoff_carries_goal_and_clears_stale_preview(monkeypatch):
    monkeypatch.setattr(onboarding, 'connection_configured', lambda: True)
    result = onboarding.GuidedHomePage(None)._handoff(' Python ', ' 零基础 ', 3)
    assert result[:5] == ('Python', '零基础', 'Python', 3.0, '{}')
    assert result[6:8] == ('', None)
    assert 'learning-path-tab' in result[-1]
    assert 'data-le-flow-stage="preview"' in result[-1]


def test_same_destination_can_be_reopened():
    assert onboarding.flow_target('quick-setup-tab') != onboarding.flow_target('quick-setup-tab')


def test_course_handoff_selects_requested_project(session, monkeypatch):
    from learning_ext.db.models import LearningProject
    import learning_ext.pages.study_workbench as module

    first = LearningProject(user_id='default', topic='First')
    second = LearningProject(user_id='default', topic='Second')
    session.add(first)
    session.add(second)
    session.commit()
    monkeypatch.setattr(module, 'engine', session.get_bind())
    monkeypatch.setattr(module, 'get_project_progress', lambda *args: {'done': 0, 'total': 0})
    page = module.StudyWorkbenchPage(MagicMock())
    monkeypatch.setattr(page, '_kick_project_prep', lambda *args: None)
    monkeypatch.setattr(page, '_load_env', lambda *args: ('', ''))
    monkeypatch.setattr(page, '_build_nodes_data', lambda *args: [])
    monkeypatch.setattr(page, '_timer_update', lambda: {})
    assert page._auto_init(first.id)[3] == first.id
    assert page._auto_init()[3] == second.id


@pytest.mark.parametrize('exc,phrase', [(requests.exceptions.ProxyError('secret proxy details'), '代理'),
                                     (requests.exceptions.Timeout('raw trace'), '超时'),
                                     (requests.exceptions.ConnectionError('raw trace'), '网络')])
def test_connection_errors_are_actionable_without_raw_trace(monkeypatch, exc, phrase):
    from learning_ext.pages.quick_setup import _test_llm

    def fail(*args, **kwargs):
        raise exc

    monkeypatch.setattr(requests, 'post', fail)
    message, reply = _test_llm('https://example.com/v1', 'test-key', 'test')
    assert phrase in message
    assert 'raw trace' not in message and 'secret' not in message
    assert reply == ''


def test_bad_connection_fields_do_not_send_request(monkeypatch):
    from learning_ext.pages.quick_setup import _test_llm

    monkeypatch.setattr(requests, 'post', lambda *a, **kw: pytest.fail('unexpected request'))
    assert '模型名称' in _test_llm('https://example.com', 'test', '')[0]
    assert '接口地址' in _test_llm('missing-scheme', 'test', 'test')[0]


def test_generation_clears_stale_save_and_disables_duplicate_requests():
    from learning_ext.pages.path_generator import PathGeneratorPage

    result = PathGeneratorPage._begin_generation()
    assert result[:5] == (None, '', '', '{}', '')
    assert result[5]['visible'] is True
    assert 'role="status"' in result[5]['value']
    assert result[6]['interactive'] is False
    assert result[7]['interactive'] is False
    assert PathGeneratorPage._save_availability(result[3])['visible'] is False


@pytest.mark.parametrize('success', [True, False])
def test_preview_finishes_waiting_on_success_or_error(monkeypatch, success):
    from learning_ext.pages.path_generator import PathGeneratorPage

    page = object.__new__(PathGeneratorPage)
    expected = ('Preview', '{"nodes":[{}]}', 'Ready') if success else ('', '{}', 'Failed')
    monkeypatch.setattr(page, '_handle_generate', lambda *args: expected)
    result = page._generate_preview('Python', '', '', 3)
    assert result[:3] == expected
    assert result[3]['visible'] is False
    assert result[4]['interactive'] is True
    assert result[5]['interactive'] is True


def test_resume_identifies_latest_active_course_with_nodes(session, sample_project, monkeypatch):
    import ktem.db.engine as engine_module
    from learning_ext.db.models import LearningProject

    monkeypatch.setattr(engine_module, 'engine', session.get_bind())
    empty = LearningProject(user_id='default', topic='Empty draft')
    session.add(empty)
    session.commit()
    visible, markup, pid, rail_html = onboarding.GuidedHomePage._resume_info()
    assert visible['visible'] is True
    assert pid == sample_project.id
    assert sample_project.topic in markup
    assert "本周节奏" in rail_html


def test_saved_route_only_offers_opening_course():
    from learning_ext.pages.path_generator import PathGeneratorPage

    save, regenerate, open_course, note = PathGeneratorPage._route_actions('{"nodes":[{}]}', 9)
    assert save['visible'] is False and save['interactive'] is False
    assert regenerate['visible'] is False
    assert open_course['visible'] is True


def test_empty_route_hides_decisions_and_save_note():
    from learning_ext.pages.path_generator import PathGeneratorPage

    updates = PathGeneratorPage._route_actions('{}', None)
    assert all(update['visible'] is False for update in updates)
