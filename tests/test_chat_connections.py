from types import SimpleNamespace
from unittest.mock import Mock
import base64
import json

import gradio as gr
import pytest

from learning_ext import chat_thinking
from learning_ext import chat_connections as chat


def raw_token(selection):
    return chat.PREFIX + base64.urlsafe_b64encode(json.dumps(selection).encode()).decode()


def manager_for(monkeypatch, models=None):
    from ktem.llms.manager import LLMManager

    monkeypatch.setattr(LLMManager, "get", LLMManager.get)
    monkeypatch.setattr(LLMManager, "get_default", LLMManager.get_default)
    monkeypatch.setattr(LLMManager, "_learning_context_models", False, raising=False)
    manager = object.__new__(LLMManager)
    manager._models = models or {"default": "GLOBAL"}
    manager._default = "default"
    return manager


def test_saved_choices_switch_model_without_exposing_credentials(monkeypatch):
    record = dict(provider="deepseek", api_key="secret", base_url="https://api.deepseek.com/v1", chat_model="deepseek-chat")
    monkeypatch.setattr(chat.connection_store, "find_connection", lambda **kw: record)
    update, token, _ = chat.choose_connection("record-one")
    assert update["value"] == "deepseek-chat"
    assert "secret" not in token and "api.deepseek" not in token
    token, _ = chat.choose_model("record-one", "deepseek-reasoner")
    model = chat.resolve_model(token)
    assert model.model == "deepseek-reasoner"
    assert model.base_url == record["base_url"]
    assert model.api_key == "secret"


def test_thinking_preferences_round_trip_through_the_model_token(monkeypatch):
    record = dict(provider="kimi", api_key="secret", base_url="https://api.moonshot.cn/v1", chat_model="kimi-k3.1-pro")
    monkeypatch.setattr(chat.connection_store, "find_connection", lambda **kw: record)
    preferences = {"effort": "max", "show_thinking": True}
    token = chat.model_token("record-one", "kimi-k3.1-pro", preferences)
    selection = json.loads(base64.urlsafe_b64decode(token[len(chat.PREFIX):]))
    assert selection == ["record-one", "kimi-k3.1-pro", preferences]
    llm, parsed = chat.resolve_selection(token)
    assert llm.model == "kimi-k3.1-pro" and parsed == preferences
    assert chat.preferences_of(token) == preferences
    assert chat.token_with_preferences(token, {"effort": "high", "show_thinking": False}) != token
    assert json.loads(base64.urlsafe_b64decode(chat.token_with_preferences(token, {"effort": "high", "show_thinking": False})[len(chat.PREFIX):]))[2] == {"effort": "high", "show_thinking": False}


def test_legacy_two_item_token_uses_default_preferences(monkeypatch):
    record = dict(provider="deepseek", api_key="secret", base_url="https://api.deepseek.com/v1", chat_model="deepseek-chat")
    monkeypatch.setattr(chat.connection_store, "find_connection", lambda **kw: record)
    token = raw_token(["record-one", "deepseek-reasoner"])
    llm, preferences = chat.resolve_selection(token)
    assert llm.model == "deepseek-reasoner"
    assert preferences == {"effort": "low", "show_thinking": False}


def test_default_preferences_token_carries_no_credentials(monkeypatch):
    monkeypatch.setattr(chat.connection_store, "find_connection", Mock(side_effect=AssertionError("default must not load credentials")))
    token = chat.default_model_token({"effort": "high", "show_thinking": True})
    selection = json.loads(base64.urlsafe_b64decode(token[len(chat.PREFIX):]))
    assert selection == ["", "", {"effort": "high", "show_thinking": True}]
    assert "https" not in token and "secret" not in token
    assert chat.resolve_model(token) is None


def test_default_token_routes_to_the_real_default_without_returning_none(monkeypatch):
    manager = manager_for(monkeypatch)
    monkeypatch.setattr(chat.connection_store, "find_connection", Mock(side_effect=AssertionError("default must not load credentials")))
    chat.configure_model_routing(SimpleNamespace(chat_fn=lambda llm_type, chat_state: iter(())))
    token = chat.default_model_token()
    assert manager.get(token, "DEFAULT-LLM") == "DEFAULT-LLM"
    assert manager.get(token) == "GLOBAL"
    assert manager.get_default() == "GLOBAL"


def test_saved_token_routes_to_the_saved_connection(monkeypatch):
    manager = manager_for(monkeypatch)
    record = dict(provider="kimi", api_key="secret", base_url="https://api.moonshot.cn/v1", chat_model="kimi-k3.1-pro")
    find = Mock(return_value=record)
    monkeypatch.setattr(chat.connection_store, "find_connection", find)
    chat.configure_model_routing(SimpleNamespace(chat_fn=lambda llm_type, chat_state: iter(())))
    token = chat.model_token("record-one", "kimi-k3.1-pro", {"effort": "high", "show_thinking": False})
    resolved = manager.get(token, "DEFAULT-LLM")
    assert resolved.model == "kimi-k3.1-pro" and resolved.api_key == "secret"
    find.assert_called()
    assert manager.get(token).model == "kimi-k3.1-pro"


def test_chat_routing_is_scoped_to_each_stream_not_global_default(monkeypatch):
    manager = manager_for(monkeypatch)
    monkeypatch.setattr(chat, "selection_for", lambda token: (token, chat_thinking.default_preferences()))

    def stream(llm_type, chat_state):
        yield manager.get_default()
        yield manager.get_default()

    page = SimpleNamespace(chat_fn=stream)
    chat.configure_model_routing(page)
    one = page.chat_fn("MODEL-A", {})
    two = page.chat_fn("MODEL-B", {})
    assert next(one) == "MODEL-A"
    assert manager.get_default() == "GLOBAL"
    assert next(two) == "MODEL-B"
    assert next(one) == "MODEL-A"
    one.close()
    two.close()
    assert manager.get_default() == "GLOBAL"


def test_thinking_preferences_are_scoped_to_each_stream(monkeypatch):
    manager = manager_for(monkeypatch)
    record = dict(provider="kimi", api_key="secret", base_url="https://api.moonshot.cn/v1", chat_model="kimi-k3.1-pro")
    monkeypatch.setattr(chat.connection_store, "find_connection", lambda **kw: record)

    def stream(llm_type, chat_state):
        yield manager.get_default().model, chat_thinking.current_preferences()
        yield manager.get_default().model, chat_thinking.current_preferences()

    page = SimpleNamespace(chat_fn=stream)
    chat.configure_model_routing(page)
    state_fast, state_calm = {}, {}
    fast = page.chat_fn(chat.model_token("record-one", "kimi-k3.1-pro", {"effort": "max", "show_thinking": True}), state_fast)
    calm = page.chat_fn(chat.model_token("record-one", "kimi-k3.1-pro", {"effort": "low", "show_thinking": False}), state_calm)
    assert next(fast) == ("kimi-k3.1-pro", {"effort": "max", "show_thinking": True})
    assert next(calm) == ("kimi-k3.1-pro", {"effort": "low", "show_thinking": False})
    assert next(fast) == ("kimi-k3.1-pro", {"effort": "max", "show_thinking": True})
    assert state_fast["learning_chat_thinking"] == {"effort": "max", "show_thinking": True}
    assert state_calm["learning_chat_thinking"] == {"effort": "low", "show_thinking": False}
    fast.close()
    calm.close()
    assert chat_thinking.current_preferences() == {"effort": "low", "show_thinking": False}


@pytest.mark.parametrize(
    "preferences",
    [
        {"effort": "ultra", "show_thinking": False},
        {"effort": "high", "show_thinking": "yes"},
        {"effort": "high", "show_thinking": False, "temperature": 1},
        "fast",
    ],
)
def test_invalid_thinking_preferences_have_clear_error(preferences, monkeypatch):
    find = Mock(side_effect=AssertionError("Must validate preferences first"))
    monkeypatch.setattr(chat.connection_store, "find_connection", find)
    token = raw_token(["record-one", "kimi-k3.1-pro", preferences])
    with pytest.raises(ValueError, match="思考偏好无效"):
        chat.resolve_model(token)
    with pytest.raises(ValueError, match="思考偏好无效"):
        chat.model_token("record-one", "kimi-k3.1-pro", preferences)


def test_missing_saved_connection_does_not_send_to_default(monkeypatch):
    monkeypatch.setattr(chat.connection_store, "find_connection", lambda **kw: None)
    with pytest.raises(ValueError):
        chat.resolve_model(chat.model_token("missing", "model"))


@pytest.mark.parametrize("selection", [None, {}, [], ["id"], ["id", "model", "extra", "more"],
                                      ["id", None], ["id", 42], ["", "model"]])
def test_invalid_saved_model_selection_is_rejected_before_loading_credentials(selection, monkeypatch):
    monkeypatch.setattr(chat.connection_store, "find_connection", Mock(side_effect=AssertionError("Must validate selection first")))
    with pytest.raises(ValueError, match="连接选择已失效"):
        chat.resolve_model(raw_token(selection))


@pytest.mark.parametrize("payload", ["!broken!", "a", "_w=="])
def test_damaged_saved_model_token_has_recoverable_message(payload):
    with pytest.raises(ValueError, match="连接选择已失效"):
        chat.resolve_model(chat.PREFIX + payload)


def test_hidden_components_publish_token_and_default_model(monkeypatch):
    from learning_ext.pages import quick_setup

    monkeypatch.setattr(quick_setup, "_read_env", lambda: {"base_url": "", "api_key": "", "chat_model": "kimi-k3.1-pro", "embed_model": ""})
    monkeypatch.setattr(chat.connection_store, "list_connections", lambda: [])
    monkeypatch.setattr(chat, "configure_model_routing", lambda page: None)
    monkeypatch.setattr("learning_ext.chat_recovery.configure_chat_recovery", lambda page: None)
    with gr.Blocks():
        with gr.Tabs():
            with gr.Tab("问答") as tab:
                gr.Markdown("chat")
        page = SimpleNamespace(
            model_type=gr.Dropdown(choices=[], value=None),
            chat_fn=lambda llm_type, chat_state: iter(()),
        )
        app = SimpleNamespace(_tabs={"chat-tab": tab})
        chat.configure_chat_connections(app, page)
    assert page.model_type.elem_id == "le-chat-model-token"
    assert page.model_type.value.startswith(chat.PREFIX)
    assert chat.parse_selection(page.model_type.value)[:2] == ("", "")
    assert page.default_model.elem_id == "le-chat-default-model"
    assert page.default_model.visible is False
    assert "kimi-k3.1-pro" in page.default_model.value
    assert "https" not in page.default_model.value and "secret" not in page.default_model.value
    assert page.saved_model.label == "回答模型"
