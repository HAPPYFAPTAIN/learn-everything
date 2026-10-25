import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import requests

from learning_ext import local_embeddings as local


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(local, '_LAST_START', float('-inf'))
    monkeypatch.setattr(local, '_STARTED_PROCESS', None)
    monkeypatch.setattr(local, '_installed_ollama', Mock(return_value=Path('C:/installed/Ollama/ollama.exe')))
    monkeypatch.setattr(local.subprocess, 'Popen', Mock(return_value=SimpleNamespace(pid=42, poll=lambda: None)))


@pytest.mark.parametrize('url', ['https://example.invalid/v1', 'http://127.0.0.1:8080/v1',
                                'http://localhost:11434/proxy/v1', 'http://localhost:11434/v1?key=x'])
def test_remote_or_custom_service_never_starts_local_process(url, monkeypatch):
    probe = Mock(side_effect=AssertionError('No probe allowed'))
    monkeypatch.setattr(local, '_local_models', probe)
    local.ensure_local_embeddings(url, 'model')
    probe.assert_not_called()
    local.subprocess.Popen.assert_not_called()


def test_ready_model_and_latest_alias_need_no_launch(monkeypatch):
    monkeypatch.setattr(local, '_local_models', lambda: {'namespace/model:latest'})
    for name in ('namespace/model', 'namespace/model:latest'):
        local.ensure_local_embeddings('http://localhost:11434/v1', name)
    with pytest.raises(local.LocalEmbeddingUnavailable, match='尚未找到'):
        local.ensure_local_embeddings('http://localhost:11434/v1', 'namespace/model:other')
    local.subprocess.Popen.assert_not_called()


def test_concurrent_requests_start_only_one_hidden_service(monkeypatch):
    state = {'ready': False}
    def probe():
        if not state['ready']:
            raise requests.ConnectionError('not running')
        return {'qwen3-embedding:4b'}
    def spawn(*args, **kwargs):
        state['ready'] = True
        assert args[0] == [str(Path('C:/installed/Ollama/ollama.exe')), 'serve']
        assert kwargs['creationflags'] == local.subprocess.CREATE_NO_WINDOW
        assert kwargs['env']['OLLAMA_HOST'] == '127.0.0.1:11434'
        return SimpleNamespace(pid=42, poll=lambda: None)
    monkeypatch.setattr(local, '_local_models', probe)
    local.subprocess.Popen.side_effect = spawn
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: local.ensure_local_embeddings('http://127.0.0.1:11434/v1', 'qwen3-embedding:4b'), range(4)))
    assert local.subprocess.Popen.call_count == 1


def test_missing_install_and_model_have_actionable_errors(monkeypatch):
    monkeypatch.setattr(local, '_local_models', Mock(side_effect=requests.ConnectionError('offline')))
    monkeypatch.setattr(local, '_installed_ollama', lambda: None)
    with pytest.raises(local.LocalEmbeddingUnavailable, match='启动 Ollama'):
        local.ensure_local_embeddings('http://127.0.0.1:11434/v1', 'model')
    local.subprocess.Popen.assert_not_called()


def test_local_probe_never_uses_environment_proxy(monkeypatch):
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.get.return_value.json.return_value = {'models': [{'name': 'model:latest'}]}
    monkeypatch.setattr(requests, 'Session', Mock(return_value=session))
    assert local._local_models() == {'model:latest'}
    assert session.trust_env is False
    assert session.get.call_args.kwargs['timeout'] == (1, 2)


def test_installing_hook_is_inert_and_checks_only_active_local_calls(monkeypatch):
    from kotaemon.embeddings import OpenAIEmbeddings
    monkeypatch.setattr(OpenAIEmbeddings, '_learning_local_ready', False, raising=False)
    monkeypatch.setattr(OpenAIEmbeddings, 'invoke', lambda self, value: value)
    monkeypatch.setattr(OpenAIEmbeddings, 'prepare_client', OpenAIEmbeddings.prepare_client)
    async def ainvoke(self, value):
        return value
    monkeypatch.setattr(OpenAIEmbeddings, 'ainvoke', ainvoke)
    ensure = Mock()
    monkeypatch.setattr(local, 'ensure_local_embeddings', ensure)
    monkeypatch.setattr(local, 'local_embedding_active', lambda: True)
    local.configure_local_embedding_runtime()
    local.configure_local_embedding_runtime()
    ensure.assert_not_called()
    obj = SimpleNamespace(base_url='http://127.0.0.1:11434/v1', model='model')
    assert OpenAIEmbeddings.invoke(obj, 'sync') == 'sync'
    assert asyncio.run(OpenAIEmbeddings.ainvoke(obj, 'async')) == 'async'
    assert ensure.call_count == 2
    obj.base_url = 'https://example.invalid/v1'
    OpenAIEmbeddings.invoke(obj, 'remote')
    obj.base_url = 'http://127.0.0.1:11434/v1'
    monkeypatch.setattr(local, 'local_embedding_active', lambda: False)
    OpenAIEmbeddings.invoke(obj, 'inactive')
    assert ensure.call_count == 2


def test_local_client_uses_direct_canonical_loopback_without_changing_remote(monkeypatch):
    import httpx
    import openai
    from kotaemon.embeddings import OpenAIEmbeddings
    original = Mock(return_value='remote client')
    monkeypatch.setattr(OpenAIEmbeddings, '_learning_local_ready', False, raising=False)
    for name in ('invoke', 'ainvoke'):
        monkeypatch.setattr(OpenAIEmbeddings, name, getattr(OpenAIEmbeddings, name))
    monkeypatch.setattr(OpenAIEmbeddings, 'prepare_client', original)
    monkeypatch.setattr(local, 'local_embedding_active', lambda: True)
    for name in ('Client', 'AsyncClient'):
        monkeypatch.setattr(httpx, name, Mock(return_value=object()))
    for name in ('OpenAI', 'AsyncOpenAI'):
        monkeypatch.setattr(openai, name, Mock())
    local.configure_local_embedding_runtime()
    instance = SimpleNamespace(base_url='http://[::1]:11434/v1', api_key='ollama',
                               organization=None, timeout=120, max_retries_=0)
    for async_version in (False, True):
        OpenAIEmbeddings.prepare_client(instance, async_version=async_version)
        client = openai.AsyncOpenAI if async_version else openai.OpenAI
        transport = httpx.AsyncClient if async_version else httpx.Client
        transport.assert_called_once_with(trust_env=False)
        assert client.call_args.kwargs['base_url'] == 'http://127.0.0.1:11434/v1'
        assert client.call_args.kwargs['timeout'] == 120
        assert client.call_args.kwargs['max_retries'] == 0
    assert instance.base_url == 'http://[::1]:11434/v1'
    original.assert_not_called()
    instance.base_url = 'https://private.example.invalid/v1'
    assert OpenAIEmbeddings.prepare_client(instance) == 'remote client'
    original.assert_called_once_with(instance, async_version=False)


def test_startup_is_bounded_and_cooldown_does_not_respawn(monkeypatch):
    clock = {'now': 0}
    monkeypatch.setattr(local.time, 'monotonic', lambda: clock['now'])
    monkeypatch.setattr(local.time, 'sleep', lambda seconds: clock.update(now=clock['now'] + seconds))
    monkeypatch.setattr(local, '_local_models', Mock(side_effect=requests.ConnectionError('offline')))
    local.subprocess.Popen.return_value.poll = lambda: 1
    with pytest.raises(local.LocalEmbeddingUnavailable, match='尚未就绪'):
        local.ensure_local_embeddings('http://127.0.0.1:11434/v1', 'model')
    assert 12 <= clock['now'] < 13
    assert local.subprocess.Popen.call_count == 1
    with pytest.raises(local.LocalEmbeddingUnavailable, match='尚未就绪'):
        local.ensure_local_embeddings('http://127.0.0.1:11434/v1', 'model')
    assert local.subprocess.Popen.call_count == 1


def test_concurrent_startup_failure_shares_the_wait_budget(monkeypatch):
    monkeypatch.setattr(local, '_READY_TIMEOUT', .08)
    monkeypatch.setattr(local, '_local_models', Mock(side_effect=requests.ConnectionError('offline')))
    barrier = threading.Barrier(8)
    def request(_):
        barrier.wait()
        started = time.monotonic()
        with pytest.raises(local.LocalEmbeddingUnavailable):
            local.ensure_local_embeddings('http://127.0.0.1:11434/v1', 'model')
        return time.monotonic() - started
    with ThreadPoolExecutor(max_workers=8) as pool:
        durations = list(pool.map(request, range(8)))
    assert max(durations) < .35
    assert local.subprocess.Popen.call_count == 1


@pytest.mark.parametrize('mode', ['sync_success', 'sync_failure', 'async_success', 'async_failure', 'async_cancel'])
def test_owned_clients_close_on_success_failure_and_cancellation(mode, monkeypatch):
    import httpx
    import openai
    from kotaemon.embeddings import OpenAIEmbeddings
    monkeypatch.setattr(OpenAIEmbeddings, '_learning_local_ready', False, raising=False)
    monkeypatch.setattr(OpenAIEmbeddings, 'prepare_client', OpenAIEmbeddings.prepare_client)
    connection = SimpleNamespace(close=Mock(), aclose=AsyncMock())
    for name in ('Client', 'AsyncClient'):
        monkeypatch.setattr(httpx, name, Mock(return_value=connection))
    for name in ('OpenAI', 'AsyncOpenAI'):
        monkeypatch.setattr(openai, name, Mock())
    def invoke(instance):
        OpenAIEmbeddings.prepare_client(instance)
        if mode.endswith('failure'):
            raise RuntimeError('request failed')
        return 'done'
    async def ainvoke(instance):
        OpenAIEmbeddings.prepare_client(instance, async_version=True)
        if mode.endswith('failure'):
            raise RuntimeError('request failed')
        if mode.endswith('cancel'):
            raise asyncio.CancelledError()
        return 'done'
    monkeypatch.setattr(OpenAIEmbeddings, 'invoke', invoke)
    monkeypatch.setattr(OpenAIEmbeddings, 'ainvoke', ainvoke)
    monkeypatch.setattr(local, 'local_embedding_active', lambda: True)
    monkeypatch.setattr(local, 'ensure_local_embeddings', Mock())
    local.configure_local_embedding_runtime()
    instance = SimpleNamespace(base_url='http://localhost:11434/v1', model='model', api_key='ollama',
                               organization=None, timeout=120, max_retries_=0)
    def call():
        return asyncio.run(OpenAIEmbeddings.ainvoke(instance)) if mode.startswith('async') else OpenAIEmbeddings.invoke(instance)
    if mode.endswith('failure'):
        with pytest.raises(RuntimeError, match='request failed'):
            call()
    elif mode.endswith('cancel'):
        with pytest.raises(asyncio.CancelledError):
            call()
    else:
        assert call() == 'done'
    if mode.startswith('async'):
        connection.aclose.assert_awaited_once()
        connection.close.assert_not_called()
    else:
        connection.close.assert_called_once()
        connection.aclose.assert_not_awaited()
    assert local._LOCAL_TRANSPORTS.get() is None
