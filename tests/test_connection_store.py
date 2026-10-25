from unittest.mock import Mock
import os

import pytest

from learning_ext import connection_store as store
from learning_ext.pages import quick_setup as page_module

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI storage")


@pytest.fixture(autouse=True)
def isolated_store(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "STORE_FILE", tmp_path / "connections.dpapi")


def config(url="https://api.deepseek.com/v1", key="test-secret-alpha", model="deepseek-chat"):
    return dict(base_url=url, api_key=key, chat_model=model, embed_model="")


def test_secrets_are_encrypted_and_survive_reload():
    first = config()
    key = store.remember("deepseek", first, verified=True)
    store.remember("kimi", config("https://api.moonshot.cn/v1", "test-secret-beta", "kimi-k3"))
    raw = store.STORE_FILE.read_bytes()
    assert b"test-secret" not in raw
    assert b"api.deepseek.com" not in raw
    assert store.find_connection(record_id=key)["api_key"] == first["api_key"]
    assert len(store.list_connections()) == 2
    assert store.find_connection(provider="deepseek")["verified"]
    assert all("test-secret" not in label for label, _ in store.connection_choices(first))


def test_endpoint_profiles_keep_separate_keys_and_invalidate_modified_verification():
    from learning_ext.model_platforms import PLATFORMS
    profiles = list(PLATFORMS["opencode"]["profiles"].values())
    a = config(profiles[0], "go-key", "glm-5.3-flash")
    b = config(profiles[1], "zen-key", "glm-5.3-flash")
    store.remember("opencode", a, verified=True)
    store.remember("opencode", b)
    assert len(store.list_connections()) == 2
    assert store.find_connection(provider="opencode", base_url=profiles[0])["api_key"] == "go-key"
    store.remember("opencode", {**a, "chat_model":"kimi-k3"})
    assert not store.find_connection(provider="opencode", base_url=profiles[0])["verified"]


def test_corrupt_storage_is_not_overwritten():
    store.STORE_FILE.write_bytes(b"corrupt")
    with pytest.raises(Exception):
        store.remember("deepseek", config())
    assert store.STORE_FILE.read_bytes() == b"corrupt"


def test_provider_switch_remembers_draft_and_restores_each_platform(monkeypatch):
    current = config()
    monkeypatch.setattr(page_module, "_read_env", lambda: current.copy())
    page = object.__new__(page_module.QuickSetupPage)
    kimi = config("https://api.moonshot.cn/v1", "kimi-secret", "kimi-k3")
    store.remember("kimi", kimi)
    result = page._switch_provider("kimi", "deepseek", current["api_key"], current["base_url"], current["chat_model"], "", current)
    assert result[3]["value"] == "kimi-secret"
    assert result[1] == kimi["base_url"]
    restored = page._provider_changed("deepseek", {})
    assert restored[3]["value"] == current["api_key"]
    assert restored[2]["value"] == current["chat_model"]


def test_saved_selection_restores_provider_and_does_not_activate(monkeypatch):
    page = object.__new__(page_module.QuickSetupPage)
    deepseek = config()
    key = store.remember("deepseek", deepseek)
    monkeypatch.setattr(page_module, "_read_env", lambda: {})
    write = Mock()
    monkeypatch.setattr(page_module, "_write_env", write)
    result = page._select_connection(key, "kimi", "kimi-key", "https://api.moonshot.cn/v1", "kimi-k3", "")
    assert len(result) == 15
    assert result[12:14] == ("deepseek", "deepseek")
    assert result[3]["value"] == deepseek["api_key"]
    write.assert_not_called()


def test_verified_connection_activates_without_paid_retest(monkeypatch):
    saved = config()
    store.remember("deepseek", saved, verified=True)
    monkeypatch.setattr(page_module, "_read_env", lambda: saved.copy())
    test = Mock(return_value=("连接成功", "你好"))
    write = Mock()
    monkeypatch.setattr(page_module, "_test_llm", test)
    monkeypatch.setattr(page_module, "_write_env", write)
    monkeypatch.setattr(page_module, "_apply_to_runtime", lambda *args: "ok")
    page = object.__new__(page_module.QuickSetupPage)
    monkeypatch.setattr(page, "_build_status", lambda value: "status")
    result = page._save(saved["api_key"], saved["base_url"], saved["chat_model"], "", "deepseek")
    test.assert_not_called()
    write.assert_called_once_with(saved)
    assert result[2] == saved
    page._save(saved["api_key"], saved["base_url"], "another-model", "", "deepseek")
    test.assert_called_once()
