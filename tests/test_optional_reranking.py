import sys
from types import SimpleNamespace

import pytest

from learning_ext.optional_reranking import configure_optional_reranking, missing_service_credentials


@pytest.mark.parametrize('key,missing', [('', True), (None, True), ('placeholder-test', True), ('configured-test-key', False)])
def test_cloud_credentials(key, missing):
    assert missing_service_credentials({'__type__': 'kotaemon.rerankings.CohereReranking', 'api_key': key}) is missing


def test_local_reranker_does_not_require_cloud_key():
    assert not missing_service_credentials({'__type__': 'kotaemon.rerankings.TeiFastReranking'})


def test_guard_preserves_settings_and_configured_rerankers(monkeypatch):
    class Retriever:
        @classmethod
        def get_pipeline(cls, user_settings, index_settings, selected):
            return user_settings, selected

    spec = {'__type__': 'kotaemon.rerankings.CohereReranking', 'api_key': 'placeholder-test'}
    manager = SimpleNamespace(get_default_name=lambda: 'cohere', info=lambda: {'cohere': {'spec': spec}})
    monkeypatch.setitem(sys.modules, 'ktem.index.file.pipelines', SimpleNamespace(DocumentRetrievalPipeline=Retriever))
    monkeypatch.setitem(sys.modules, 'ktem.rerankings.manager', SimpleNamespace(reranking_models_manager=manager))
    configure_optional_reranking()
    configure_optional_reranking()
    original = {'use_reranking': True, 'num_retrieval': 10}
    actual, selected = Retriever.get_pipeline(original, {}, ['test-file'])
    assert actual == {'use_reranking': False, 'num_retrieval': 10}
    assert original['use_reranking'] is True
    assert selected == ['test-file']
    spec['api_key'] = 'configured-test-key'
    assert Retriever.get_pipeline(original, {}, selected)[0] is original
