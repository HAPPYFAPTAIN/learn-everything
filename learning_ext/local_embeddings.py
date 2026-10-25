from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import logging
import os
from pathlib import Path
import subprocess
import threading
import time
from urllib.parse import urlsplit

LOCAL_NAME = 'local-ollama'
_READY_LOCK = threading.Lock()
_READY_TIMEOUT = 12
_LOCAL_TRANSPORTS = ContextVar('local_embedding_transports', default=None)
_LAST_START = float('-inf')
_STARTED_PROCESS = None
_LOG = logging.getLogger(__name__)


class LocalEmbeddingUnavailable(RuntimeError):
    pass


def _standard_local_address(base_url):
    try:
        url = urlsplit(str(base_url).strip())
        return (url.scheme == 'http' and url.hostname in {'localhost', '127.0.0.1', '::1'}
                and url.port == 11434 and url.path.rstrip('/') == '/v1'
                and not any((url.username, url.password, url.query, url.fragment)))
    except ValueError:
        return False


def _installed_ollama():
    if os.name != 'nt':
        return None
    roots = [Path(root) / suffix for root, suffix in (
        (os.environ.get('LOCALAPPDATA'), 'Programs/Ollama'),
        (os.environ.get('ProgramFiles'), 'Ollama'),
    ) if root and Path(root).is_absolute()]
    return next((root / 'ollama.exe' for root in roots if (root / 'ollama.exe').is_file()), None)


def _local_models():
    import requests
    with requests.Session() as session:
        session.trust_env = False
        reply = session.get('http://127.0.0.1:11434/api/tags', timeout=(1, 2))
        reply.raise_for_status()
        data = reply.json()
    if not isinstance(data, dict) or not isinstance(data.get('models'), list):
        raise LocalEmbeddingUnavailable('本地检索服务的响应无效，请重新启动 Ollama 后再试。')
    return {str(item.get('name') or item.get('model') or '') for item in data['models'] if isinstance(item, dict)}


@contextmanager
def _readiness_turn():
    deadline = time.monotonic() + _READY_TIMEOUT
    if not _READY_LOCK.acquire(timeout=_READY_TIMEOUT):
        raise LocalEmbeddingUnavailable('本地检索服务正在恢复。请稍后重新发送问题。')
    try:
        if time.monotonic() >= deadline:
            raise LocalEmbeddingUnavailable('本地检索服务正在恢复。请稍后重新发送问题。')
        yield deadline
    finally:
        _READY_LOCK.release()


def ensure_local_embeddings(base_url, model):
    global _LAST_START, _STARTED_PROCESS
    if not _standard_local_address(base_url):
        return
    import requests
    with _readiness_turn() as deadline:
        try:
            available = _local_models()
        except requests.ConnectionError:
            executable = _installed_ollama()
            if not executable:
                raise LocalEmbeddingUnavailable('本地检索服务未启动。请启动 Ollama，或在「模型配置」设置可用的资料检索模型。') from None
            now = time.monotonic()
            if now >= deadline:
                raise LocalEmbeddingUnavailable('本地检索服务尚未就绪。请检查 Ollama 后重新发送问题。') from None
            if now - _LAST_START >= 15 and (_STARTED_PROCESS is None or _STARTED_PROCESS.poll() is not None):
                _LAST_START = now
                try:
                    _STARTED_PROCESS = subprocess.Popen(
                        [str(executable), 'serve'], stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        env={**os.environ, 'OLLAMA_HOST': '127.0.0.1:11434'},
                    )
                    _LOG.info('local_embedding_service_started pid=%s', _STARTED_PROCESS.pid)
                except OSError:
                    raise LocalEmbeddingUnavailable('无法启动本地检索服务。请手动打开 Ollama 后重新发送问题。') from None
            while True:
                if time.monotonic() >= deadline:
                    raise LocalEmbeddingUnavailable('本地检索服务尚未就绪。请检查 Ollama 后重新发送问题。') from None
                try:
                    available = _local_models()
                    break
                except requests.ConnectionError:
                    if time.monotonic() >= deadline:
                        raise LocalEmbeddingUnavailable('本地检索服务尚未就绪。请检查 Ollama 后重新发送问题。') from None
                    time.sleep(min(.2, max(0, deadline - time.monotonic())))
                except requests.RequestException:
                    raise LocalEmbeddingUnavailable('本地检索服务暂时没有响应。请检查 Ollama 后重新发送问题。') from None
        except requests.RequestException:
            raise LocalEmbeddingUnavailable('本地检索服务暂时没有响应。请检查 Ollama 后重新发送问题。') from None
        name = str(model or '').strip()
        aliases = {name, name + ':latest'} if ':' not in name.rsplit('/', 1)[-1] else {name}
        if not name or not aliases.intersection(available):
            raise LocalEmbeddingUnavailable('尚未找到已配置的本地向量模型。请在 Ollama 安装该模型，或到「模型配置」选择已有的资料检索模型。')


def configure_local_embedding_runtime():
    from kotaemon.embeddings import OpenAIEmbeddings
    if getattr(OpenAIEmbeddings, '_learning_local_ready', False):
        return
    original_invoke, original_ainvoke = OpenAIEmbeddings.invoke, OpenAIEmbeddings.ainvoke
    original_client = OpenAIEmbeddings.prepare_client

    def enabled(instance):
        return _standard_local_address(instance.base_url) and local_embedding_active()

    def prepare(instance):
        if enabled(instance):
            ensure_local_embeddings(instance.base_url, instance.model)

    @wraps(original_client)
    def prepare_client(instance, async_version=False):
        if not enabled(instance):
            return original_client(instance, async_version=async_version)
        import httpx
        from openai import AsyncOpenAI, OpenAI
        transport = httpx.AsyncClient if async_version else httpx.Client
        client = AsyncOpenAI if async_version else OpenAI
        connection = transport(trust_env=False)
        owned = _LOCAL_TRANSPORTS.get()
        if owned is not None:
            owned.append(connection)
        return client(
            api_key=instance.api_key, organization=instance.organization,
            base_url='http://127.0.0.1:11434/v1', timeout=instance.timeout,
            max_retries=instance.max_retries_, http_client=connection,
        )

    @wraps(original_invoke)
    def invoke(instance, *args, **kwargs):
        prepare(instance)
        owned = []
        token = _LOCAL_TRANSPORTS.set(owned)
        try:
            return original_invoke(instance, *args, **kwargs)
        finally:
            _LOCAL_TRANSPORTS.reset(token)
            for connection in owned:
                try:
                    connection.close()
                except Exception as error:
                    _LOG.warning('local_embedding_cleanup_failed type=%s', type(error).__name__)

    @wraps(original_ainvoke)
    async def ainvoke(instance, *args, **kwargs):
        await asyncio.to_thread(prepare, instance)
        owned = []
        token = _LOCAL_TRANSPORTS.set(owned)
        try:
            return await original_ainvoke(instance, *args, **kwargs)
        finally:
            _LOCAL_TRANSPORTS.reset(token)
            for connection in owned:
                try:
                    await connection.aclose()
                except Exception as error:
                    _LOG.warning('local_embedding_cleanup_failed type=%s', type(error).__name__)

    OpenAIEmbeddings.invoke, OpenAIEmbeddings.ainvoke = invoke, ainvoke
    OpenAIEmbeddings.prepare_client = prepare_client
    OpenAIEmbeddings._learning_local_ready = True


def local_embedding_active():
    from ktem.embeddings.manager import embedding_models_manager as manager
    return getattr(manager, 'get_default_name', lambda: None)() == LOCAL_NAME


def configure_local_embeddings(model='qwen3-embedding:4b'):
    import requests
    from ktem.embeddings.manager import embedding_models_manager as manager
    from theflow.settings import settings
    import sqlite3
    from pathlib import Path

    model = model.strip()
    if not model:
        return '请填写本地向量模型名称。'
    existing = manager.info().get(LOCAL_NAME, {}).get('spec', {})
    same_model = local_embedding_active() and existing.get('model') == model
    path = Path(settings.KH_VECTORSTORE['path']) / 'chroma.sqlite3'
    if path.exists() and not same_model:
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as conn:
            if conn.execute('select count(*) from embeddings').fetchone()[0]:
                return '资料库已有向量，不能直接更换模型。请先备份并迁移索引，避免检索结果不兼容。'
    try:
        response = requests.post('http://127.0.0.1:11434/v1/embeddings', json={
            'model': model, 'input': '本地资料检索连接测试'
        }, timeout=120)
        response.raise_for_status()
        dimensions = len(response.json()['data'][0]['embedding'])
        if not dimensions:
            return '本地模型没有返回有效向量。'
        spec = {'__type__': 'kotaemon.embeddings.OpenAIEmbeddings',
                'base_url': 'http://127.0.0.1:11434/v1', 'api_key': 'ollama',
                'model': model, 'timeout': 120}
        if LOCAL_NAME in manager:
            manager.update(LOCAL_NAME, spec=spec, default=True)
        else:
            manager.add(LOCAL_NAME, spec=spec, default=True)
        return f'本地资料检索已启用：{model}（{dimensions} 维）。对话仍使用原来的模型。'
    except requests.ConnectionError:
        return '无法连接本地 Ollama，请先启动 Ollama 后重试。'
    except Exception as error:
        return f'本地向量模型连接失败（{type(error).__name__}），请确认模型名称与 Ollama 状态。'
