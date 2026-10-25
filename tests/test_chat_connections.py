from types import SimpleNamespace
from unittest.mock import Mock
import base64
import json

import pytest

from learning_ext import chat_connections as chat


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


def test_chat_routing_is_scoped_to_each_stream_not_global_default(monkeypatch):
    from ktem.llms.manager import LLMManager
    # Restore the class after testing the installation hook.
    monkeypatch.setattr(LLMManager, "get", LLMManager.get)
    monkeypatch.setattr(LLMManager, "get_default", LLMManager.get_default)
    monkeypatch.setattr(LLMManager, "_learning_context_models", False, raising=False)
    manager = object.__new__(LLMManager)
    manager._models = {"default": "GLOBAL"}
    manager._default = "default"
    monkeypatch.setattr(chat, "resolve_model", lambda token: token if token != "(default)" else None)
    def stream(llm_type):
        yield manager.get_default()
        yield manager.get_default()
    page = SimpleNamespace(chat_fn=stream)
    chat.configure_model_routing(page)
    one = page.chat_fn("MODEL-A")
    two = page.chat_fn("MODEL-B")
    assert next(one) == "MODEL-A"
    assert manager.get_default() == "GLOBAL"
    assert next(two) == "MODEL-B"
    assert next(one) == "MODEL-A"
    one.close()
    two.close()
    assert manager.get_default() == "GLOBAL"


def test_missing_saved_connection_does_not_send_to_default(monkeypatch):
    import pytest
    monkeypatch.setattr(chat.connection_store, "find_connection", lambda **kw: None)
    with pytest.raises(ValueError):
        chat.resolve_model(chat.model_token("missing", "model"))


@pytest.mark.parametrize("selection", [None, {}, [], ["id"], ["id", "model", "extra"],
                                      ["id", None], ["id", 42], ["", "model"]])
def test_invalid_saved_model_selection_is_rejected_before_loading_credentials(selection, monkeypatch):
    monkeypatch.setattr(chat.connection_store, "find_connection", Mock(side_effect=AssertionError("Must validate selection first")))
    token = chat.PREFIX + base64.urlsafe_b64encode(json.dumps(selection).encode()).decode()
    with pytest.raises(ValueError, match="连接选择已失效"):
        chat.resolve_model(token)


@pytest.mark.parametrize("payload", ["!broken!", "a", "_w=="])
def test_damaged_saved_model_token_has_recoverable_message(payload):
    with pytest.raises(ValueError, match="连接选择已失效"):
        chat.resolve_model(chat.PREFIX + payload)
