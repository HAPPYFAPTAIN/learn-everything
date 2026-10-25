from unittest.mock import Mock

import gradio as gr
import pytest

from learning_ext.model_platforms import connection_error, detect_platform, model_ids, platform_draft, profile_for


@pytest.fixture(autouse=True)
def isolated_connections(monkeypatch, tmp_path):
    from learning_ext import connection_store
    monkeypatch.setattr(connection_store, "STORE_FILE", tmp_path / "connections.dpapi")


def test_platform_detection_preserves_existing_special_endpoints():
    saved = dict(base_url="https://open.bigmodel.cn/api/coding/paas/v4", api_key="private", chat_model="my-model", embed_model="")
    assert detect_platform(saved["base_url"]) == "bigmodel"
    assert profile_for("bigmodel", saved["base_url"]) == "自定义地址"
    assert platform_draft("bigmodel", saved) == saved
    draft = platform_draft("qwen", saved)
    assert draft["api_key"] == ""
    assert draft["base_url"].startswith("https://dashscope.")
    assert detect_platform("https://workspace.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1") == "qwen"
    assert detect_platform("http://localhost:8080/v1") == "custom"
    assert detect_platform("http://[::1]:11434/v1") == "ollama"


def test_model_list_deduplicates_and_skips_non_chat_models():
    assert model_ids({"data": [{"id":"chat-a"}, {"id":"chat-a"}, {"id":"text-embedding-3"}, {"id":12}, {}]}) == ["chat-a"]
    assert connection_error("http://localhost:11434/v1", "", "local-model") == ""
    assert connection_error("https://example.com/v1", "", "x")
    assert connection_error("https://example.com/v1", "key\nOTHER=x", "x")


def test_model_refresh_preserves_manual_choice_and_never_follows_redirects(monkeypatch):
    from learning_ext.pages import quick_setup as module
    response = Mock(status_code=200)
    response.json.return_value = {"data": [{"id":"new-model"}]}
    get = Mock(return_value=response)
    monkeypatch.setattr("requests.get", get)
    update, message = module._fetch_models("https://example.com/v1", "secret", "manual-model")
    assert update["value"] == "manual-model"
    assert update["choices"] == ["manual-model", "new-model"]
    assert get.call_args.kwargs["allow_redirects"] is False
    response.status_code = 401
    assert module._fetch_models("https://example.com/v1", "secret", "manual-model")[0] == gr.update()
    response.status_code = 200
    response.json.return_value = []
    assert module._fetch_models("https://example.com/v1", "secret", "manual-model")[0] == gr.update()


def test_failed_validation_does_not_replace_saved_connection(monkeypatch):
    from learning_ext.pages import quick_setup as module
    saved = dict(base_url="https://old.example/v1", api_key="old-key", chat_model="old", embed_model="")
    monkeypatch.setattr(module, "_read_env", lambda: saved.copy())
    monkeypatch.setattr(module, "_test_llm", lambda *args: ("连接失败", ""))
    write = Mock()
    monkeypatch.setattr(module, "_write_env", write)
    page = object.__new__(module.QuickSetupPage)
    monkeypatch.setattr(page, "_build_status", lambda current: current["chat_model"])
    result = page._save("new-key", "https://new.example/v1", "new", "")
    write.assert_not_called()
    assert result[2] == saved


def test_platform_ui_builds_with_current_configuration(monkeypatch):
    from learning_ext.pages import quick_setup as module
    saved = dict(base_url="https://open.bigmodel.cn/api/coding/paas/v4", api_key="private", chat_model="my-model", embed_model="")
    monkeypatch.setattr(module, "_read_env", lambda: saved.copy())
    monkeypatch.setattr(module.QuickSetupPage, "_build_status", lambda self, current: "saved")
    with gr.Blocks():
        page = module.QuickSetupPage(Mock())
        page.on_building_ui()
        page.on_register_events()
        assert page.provider.value == "bigmodel"
        assert page.base_url.value == saved["base_url"]
        assert page.chat_model.value == "my-model"
        changes = page._provider_changed("gemini", saved)
        assert changes[3]["value"] == ""
        assert changes[2]["value"] is None


def test_opencode_go_uses_subscription_catalog_and_filters_protocols(monkeypatch):
    from learning_ext.model_platforms import PLATFORMS, compatible_model, models_url
    from learning_ext.pages import quick_setup as module
    go = PLATFORMS["opencode"]["profiles"]["Go / Go Plus · 订阅"]
    assert models_url(go) == "https://opencode.ai/inference/go/v1/models"
    assert models_url("https://opencode.ai/inference/openai/v1") == "https://opencode.ai/inference/v1/models"
    assert compatible_model(go, "glm-5.3-flash")
    assert compatible_model(go, "minimax-m3.1-flash")
    assert not compatible_model(go, "minimax-m3")
    assert not compatible_model(go, "gpt-6-luna")
    response = Mock(status_code=200)
    response.json.return_value = {"data":[{"id":"glm-5.3-flash"},{"id":"gpt-6-luna"},{"id":"claude-haiku-5-5"}]}
    get = Mock(return_value=response)
    monkeypatch.setattr("requests.get", get)
    update, _ = module._fetch_models(go, "", None)
    assert update["choices"] == ["glm-5.3-flash"]
    assert get.call_args.args[0] == models_url(go)
    assert "Authorization" not in get.call_args.kwargs["headers"]


def test_provider_params_work_for_test_learning_and_history_replay(monkeypatch):
    from learning_ext.model_platforms import adapt_chat_params
    from learning_ext.chat_compat import _guard_params
    from learning_ext.pages import quick_setup as module
    from types import SimpleNamespace
    base = "https://opencode.ai/inference/go/openai/v1"
    messages = [{"role":"user","content":"Explain a Python loop"}]
    params = {"model":"kimi-k3.1-pro", "temperature":0.3, "messages":messages}
    adapted = adapt_chat_params(base, params)
    assert "temperature" not in adapted
    assert "temperature" in params
    assert adapted["reasoning_effort"] == "low"
    assert adapted["extra_headers"]["User-Agent"] == "LearnEverything/1.0"
    followup = adapt_chat_params(base, {**params,"messages":[*messages,{"role":"assistant","content":"A loop repeats."},{"role":"user","content":"An example?"}]})
    assert adapted["extra_headers"]["x-opencode-session"] == followup["extra_headers"]["x-opencode-session"]
    guarded = _guard_params(lambda self, **kwargs: kwargs)(SimpleNamespace(base_url=base), **params)
    assert guarded == adapted
    assert "extra_headers" not in adapt_chat_params("https://api.moonshot.cn/v1",params)
    response = Mock(status_code=200)
    response.json.return_value = {"choices":[{"message":{"content":"你好"}}]}
    post = Mock(return_value=response)
    monkeypatch.setattr("requests.post", post)
    assert module._test_llm(base,"test-key","kimi-k3.1-pro")[1] == "你好"
    assert "extra_headers" not in post.call_args.kwargs["json"]
    assert post.call_args.kwargs["headers"]["User-Agent"] == "LearnEverything/1.0"


def test_catalog_has_regional_endpoints_and_no_embedded_credentials():
    from learning_ext.model_platforms import PLATFORMS, origin
    assert len(PLATFORMS) >= 30
    assert set(PLATFORMS["minimax"]["profiles"]) == {"中国站","国际站"}
    assert set(PLATFORMS["kimi"]["profiles"]) == {"中国站","国际站"}
    for cfg in PLATFORMS.values():
        assert cfg["group"] in {"国内平台","海外平台","聚合中转","本地服务"}
        for base in cfg["profiles"].values():
            if base:
                assert origin(base)[0] in {"http","https"}
                assert not connection_error(base,"test-key")
