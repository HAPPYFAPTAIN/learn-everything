from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from learning_ext.chat_recovery import configure_chat_recovery
from learning_ext.local_embeddings import LocalEmbeddingUnavailable


@pytest.fixture(autouse=True)
def offline_direct_chat(monkeypatch):
    """检索失败时的直连兜底默认也失败，避免测试访问真实模型服务。"""
    def offline(*args, **kwargs):
        raise RuntimeError('offline')
    monkeypatch.setattr('learning_ext.llm.chat', offline)


def page_for(stream):
    page = SimpleNamespace(chat_fn=stream, check_and_suggest_name_conv=Mock(return_value=('name', True)),
                           suggest_chat_conv=Mock(return_value=('suggestions', [])))
    configure_chat_recovery(page)
    return page


def test_failed_retrieval_replaces_thinking_without_followup_model_calls():
    state = {'app': {}}
    original = [('question', None)]
    closed = []
    def stream(chat_history, chat_state):
        try:
            yield [('question', 'Thinking ...')], '', {}, None, chat_state
            raise LocalEmbeddingUnavailable('本地检索服务未启动，请启动 Ollama。')
        finally:
            closed.append(True)
    page = page_for(stream)
    outputs = list(page.chat_fn(original, state))
    history, refs, plot, _, returned_state = outputs[-1]
    assert 'Thinking' not in history[-1][1]
    assert '启动 Ollama' in history[-1][1]
    assert '重新发送' in history[-1][1]
    assert refs == '' and plot['visible'] is False and returned_state is state
    assert original == [('question', None)] and closed == [True]
    assert page.check_and_suggest_name_conv(history)[1] is False
    assert page.suggest_chat_conv({}, 'auto', history, True)[1] == []


def test_midstream_failure_preserves_partial_answer_and_hides_exception_details():
    def stream(chat_history, chat_state):
        yield [('question', 'Already answered part')], 'citation', {}, None, chat_state
        raise RuntimeError('private response with secret')
    page = page_for(stream)
    result = list(page.chat_fn([('question', None)], {'app': {}}))[-1]
    assert result[0][-1][1].startswith('Already answered part')
    assert 'secret' not in result[0][-1][1] and 'RuntimeError' not in result[0][-1][1]
    assert result[1] == 'citation'


def test_setup_failure_and_next_turn_are_independent():
    calls = 0
    def stream(chat_history, chat_state):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError('connection selection failed')
        yield [('question', 'Answer')], '', {}, None, chat_state
    page = page_for(stream)
    history = [('question', None)]
    assert '回答暂时中断' in list(page.chat_fn(history, {}))[-1][0][-1][1]
    success = list(page.chat_fn(history, {}))[-1][0]
    assert success[-1][1] == 'Answer'
    assert page.check_and_suggest_name_conv(success) == ('name', True)


def test_cancellation_is_not_reported_as_a_model_failure():
    closed = []
    def stream(chat_history, chat_state):
        try:
            yield [('question', 'Thinking ...')], '', {}, None, chat_state
            yield [('question', 'Answer')], '', {}, None, chat_state
        finally:
            closed.append(True)
    page = page_for(stream)
    iterator = page.chat_fn([('question', None)], {})
    next(iterator)
    iterator.close()
    assert closed == [True]


def test_cleanup_error_does_not_replace_friendly_failure():
    class FailingStream:
        def __iter__(self):
            return self
        def __next__(self):
            raise LocalEmbeddingUnavailable('请启动 Ollama 后重试。')
        def close(self):
            raise RuntimeError('private cleanup details')
    def stream(chat_history, chat_state):
        return FailingStream()
    page = page_for(stream)
    result = list(page.chat_fn([('question', None)], {}))[-1]
    assert '请启动 Ollama' in result[0][-1][1]
    assert 'private' not in result[0][-1][1]


def test_retrieval_failure_falls_back_to_direct_streaming_answer(monkeypatch):
    def direct(prompt, *, system=None, stream=False, **kwargs):
        assert prompt == 'question'
        assert stream is True
        for chunk in ['机器学习', '是一种方法']:
            yield chunk

    monkeypatch.setattr('learning_ext.llm.chat', direct)

    def stream(chat_history, chat_state):
        yield [('question', 'Thinking ...')], '', {}, None, chat_state
        raise LocalEmbeddingUnavailable('请启动 Ollama。')

    page = page_for(stream)
    outputs = list(page.chat_fn([('question', None)], {}))
    history, refs, plot, _, _ = outputs[-1]
    assert history[-1][1].startswith('机器学习是一种方法')
    assert '本地资料检索暂时不可用' in history[-1][1]
    assert '回答暂时中断' not in history[-1][1]
    assert refs == '' and plot['visible'] is False
    assert outputs[0][0][-1][1] == 'Thinking ...'
    assert [item[0][-1][1] for item in outputs][-3:-1] == ['机器学习', '机器学习是一种方法']


def test_retrieval_failure_reuses_saved_thinking_preferences(monkeypatch):
    seen = {}

    def direct(prompt, *, system=None, stream=False, effort=None, show_thinking=False, **kwargs):
        seen.update(effort=effort, show_thinking=show_thinking)
        yield '回答'

    monkeypatch.setattr('learning_ext.llm.chat', direct)

    def stream(chat_history, chat_state):
        yield [('question', 'Thinking ...')], '', {}, None, chat_state
        raise LocalEmbeddingUnavailable('请启动 Ollama。')

    page = page_for(stream)
    state = {'learning_chat_thinking': {'effort': 'max', 'show_thinking': True}}
    history, _, _, _, _ = list(page.chat_fn([('question', None)], state))[-1]
    assert seen == {'effort': 'max', 'show_thinking': True}
    assert history[-1][1].startswith('回答')


def test_direct_fallback_ignores_damaged_thinking_preferences(monkeypatch):
    seen = {}

    def direct(prompt, *, system=None, stream=False, effort=None, show_thinking=False, **kwargs):
        seen.update(effort=effort, show_thinking=show_thinking)
        yield '回答'

    monkeypatch.setattr('learning_ext.llm.chat', direct)

    def stream(chat_history, chat_state):
        yield [('question', 'Thinking ...')], '', {}, None, chat_state
        raise LocalEmbeddingUnavailable('请启动 Ollama。')

    page = page_for(stream)
    state = {'learning_chat_thinking': {'effort': 'ultra', 'show_thinking': 'yes'}}
    list(page.chat_fn([('question', None)], state))
    assert seen == {'effort': 'low', 'show_thinking': False}


def test_direct_fallback_failure_keeps_friendly_notice(monkeypatch):
    def stream(chat_history, chat_state):
        yield [('question', 'Thinking ...')], '', {}, None, chat_state
        raise LocalEmbeddingUnavailable('请启动 Ollama。')

    page = page_for(stream)
    history, refs, plot, _, _ = list(page.chat_fn([('question', None)], {}))[-1]
    assert '回答暂时中断' in history[-1][1]
    assert '请启动 Ollama' in history[-1][1]
    assert '重新发送' in history[-1][1]
    assert 'offline' not in history[-1][1]
