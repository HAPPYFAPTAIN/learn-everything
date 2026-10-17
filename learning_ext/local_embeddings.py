from __future__ import annotations

LOCAL_NAME = 'local-ollama'


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
