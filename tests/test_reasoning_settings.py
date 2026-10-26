import json
from types import SimpleNamespace

import pytest

from learning_ext import reasoning_settings as settings


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "STORE_FILE", tmp_path / "reasoning.json")


def test_preferences_persist_per_purpose_and_validate():
    values = settings.load()
    assert set(values.values()) == {"auto"}
    values.update(qa="off", lesson="on", summary="off")
    settings.save(values)
    assert settings.load() == values
    assert json.loads(settings.STORE_FILE.read_text())["version"] == 1
    with pytest.raises(ValueError):
        settings.save({"qa": "off"})
    assert settings.load() == values


def test_malformed_saved_mode_falls_back_without_breaking_requests():
    settings.STORE_FILE.write_text(json.dumps({"version": 1, "purposes": {"qa": []}}))
    assert settings.load()["qa"] == "auto"


@pytest.mark.parametrize("url,model,key", [
    ("https://open.bigmodel.cn/api/paas/v4", "glm-4.7", "thinking"),
    ("https://api.deepseek.com/v1", "deepseek-flash", "thinking"),
    ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus", "enable_thinking"),
])
def test_toggle_changes_payload_without_mutating_other_options(url, model, key):
    source = {"model": model, "reasoning_effort": "high", "extra_body": {"keep": 1}}
    disabled = settings.apply(source, url, "qa", "off")
    assert "reasoning_effort" not in disabled
    assert disabled["extra_body"][key] == (False if key == "enable_thinking" else {"type": "disabled"})
    assert disabled["extra_body"]["keep"] == 1
    assert source["extra_body"] == {"keep": 1}
    enabled = settings.apply(source, url, "qa", "on")
    assert enabled["extra_body"][key] == (True if key == "enable_thinking" else {"type": "enabled"})


def test_forced_model_uses_low_effort_and_explains_limitation():
    url = "https://open.bigmodel.cn/api/coding/paas/v4"
    params = settings.apply({"model": "glm-5.3-flash", "reasoning_effort": "max"}, url, "summary", "off")
    assert params["extra_body"]["thinking"]["type"] == "enabled"
    assert params["reasoning_effort"] == "low"
    assert "不会真正关闭" in settings.capability_note(url, "glm-5.3-flash")


def test_unknown_endpoint_and_auto_do_not_inject_parameters():
    source = {"model": "other-model", "temperature": 0.3}
    assert settings.apply(source, "https://example.com/v1", "qa", "off") == source
    assert settings.apply(source, "https://api.deepseek.com", "qa", "auto") == source


def test_regular_chat_and_json_respect_purpose(monkeypatch):
    from learning_ext.llm import client
    values = settings.load()
    values.update(qa="on", summary="off")
    settings.save(values)
    sent = []
    def create(**kwargs):
        sent.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content='{"ok":true}'))])
    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(client, "_get_client", lambda: (fake, {"base_url": "https://api.deepseek.com/v1", "chat_model": "deepseek-flash"}))
    client.chat("test", purpose="qa")
    assert client.chat_json("test", purpose="summary") == {"ok": True}
    assert sent[0]["extra_body"]["thinking"]["type"] == "enabled"
    assert sent[1]["extra_body"]["thinking"]["type"] == "disabled"


def test_knowledge_qa_final_payload_uses_qa_settings():
    from learning_ext.chat_compat import _guard_params
    values = settings.load()
    values["qa"] = "off"
    settings.save(values)
    instance = SimpleNamespace(base_url="https://open.bigmodel.cn/api/paas/v4")
    prepare = _guard_params(lambda self, **kwargs: {"model": "glm-5.2", "reasoning_effort": "max", **kwargs})
    result = prepare(instance, messages=[{"role": "user", "content": "hello"}])
    assert result["extra_body"]["thinking"]["type"] == "disabled"
    assert "reasoning_effort" not in result


def test_coach_stream_uses_its_own_setting(monkeypatch):
    from learning_ext.llm import client
    values = settings.load()
    values.update(qa="on", coach="off")
    settings.save(values)
    sent = []
    class Response:
        def __enter__(self):
            return iter(["chunk"])
        def __exit__(self, *args):
            pass
    def create(**kwargs):
        sent.append(kwargs)
        return Response()
    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=lambda: None)
    monkeypatch.setattr(client, "_get_client", lambda: (fake, {"base_url": "https://api.deepseek.com/v1", "chat_model": "deepseek-flash"}))
    assert list(client.stream_tool_response([{"role": "user", "content": "hello"}], [])) == ["chunk"]
    assert sent[0]["extra_body"]["thinking"]["type"] == "disabled"
