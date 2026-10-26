from types import SimpleNamespace
import pytest
from learning_ext import chat_connections
from learning_ext.agent import runtime
from learning_ext.llm import client
from learning_ext.pages.coach import CoachPage


def test_model_setting_is_local_and_survives_new_task(monkeypatch):
    monkeypatch.setattr(runtime.Session, 'record', lambda *a, **k: None)
    page = CoachPage(SimpleNamespace())
    monkeypatch.setattr(page, '_model_choices', lambda _: ['glm-5.3-flash'])
    page._configure_model('saved-id', 'glm-5.3-flash', 'high', True)
    token = page.session.model_selection
    assert chat_connections.parse_selection(token) == ('saved-id', 'glm-5.3-flash', {'effort': 'high', 'show_thinking': True})
    list(page._on_clear())
    assert page.session.model_selection == token
    page.session.pending = [{}]
    with pytest.raises(Exception, match='待确认'):
        page._configure_model('saved-id', 'glm-5.3-flash', 'low', False)
    assert page.session.model_selection == token


@pytest.mark.parametrize('show', [False, True])
def test_only_provider_reasoning_is_exposed_when_enabled(monkeypatch, show):
    session = runtime.Session()
    session.model_selection = chat_connections.default_model_token({'effort': 'high', 'show_thinking': show})
    def response(messages, tools, *, selection):
        assert selection == session.model_selection
        for reasoning, content in [('实际返回的思考', None), (None, '回答')]:
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(reasoning_content=reasoning, content=content, tool_calls=[]), finish_reason=None)])
    monkeypatch.setattr(client, 'stream_tool_response', response)
    events = list(runtime._model_stream(session))
    assert any(e['kind'] == 'reasoning' for e in events) == show
    assert any(e['kind'] == 'delta' for e in events)


@pytest.mark.parametrize('model,expected', [('glm-5.3-flash', 'high'), ('other-model', None)])
def test_saved_selection_routes_credentials_and_effort(monkeypatch, model, expected):
    from learning_ext import connection_store
    import openai
    captured = {}
    class Response:
        def __enter__(self): return iter([])
        def __exit__(self, *args): pass
    class Client:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.chat = SimpleNamespace(completions=self)
        def create(self, **kwargs):
            captured['request'] = kwargs
            return Response()
        def close(self): captured['closed'] = True
    monkeypatch.setattr(openai, 'OpenAI', Client)
    monkeypatch.setattr(connection_store, 'find_connection', lambda **_: {'api_key': 'test-only', 'base_url': 'https://example.com/v1'})
    token = chat_connections.model_token('test', model, {'effort': 'high', 'show_thinking': True})
    list(client.stream_tool_response([{'role':'user', 'content':'test'}], [], selection=token))
    assert captured['request']['model'] == model
    assert captured['request'].get('reasoning_effort') == expected
    assert captured['api_key'] == 'test-only'
    assert captured['closed']
