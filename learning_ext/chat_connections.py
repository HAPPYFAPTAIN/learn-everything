from __future__ import annotations

import base64
import binascii
import json
from contextvars import ContextVar
from functools import wraps
from inspect import signature

import gradio as gr

from learning_ext import chat_thinking, connection_store
from learning_ext.model_platforms import PLATFORMS, connection_error, request_key, profile_for

_CHAT_LLM = ContextVar("learning_chat_llm", default=None)
PREFIX = "saved-connection:"


def model_token(record_id, model, preferences=None):
    if not isinstance(record_id, str) or not isinstance(model, str):
        raise ValueError("连接选择已失效，请重新选择。")
    selection = [record_id, model, chat_thinking.normalize_preferences(preferences)]
    return PREFIX + base64.urlsafe_b64encode(json.dumps(selection, ensure_ascii=False).encode()).decode()


def default_model_token(preferences=None):
    return model_token("", "", preferences)


def parse_selection(token):
    """解出 (连接 id, 模型名, 偏好)；旧两项 token 自动补默认偏好。"""
    if not isinstance(token, str) or not token.startswith(PREFIX):
        raise ValueError("连接选择已失效，请重新选择。")
    try:
        selection = json.loads(base64.b64decode(token[len(PREFIX):], altchars=b"-_", validate=True))
        if not isinstance(selection, list) or len(selection) not in (2, 3):
            raise ValueError("Invalid model selection")
        record_id, model = selection[0], selection[1]
        if not all(isinstance(value, str) for value in (record_id, model)):
            raise ValueError("Invalid model selection")
        if not record_id and model:
            raise ValueError("Invalid model selection")
    except (ValueError, TypeError, UnicodeError, binascii.Error) as exc:
        raise ValueError("连接选择已失效，请重新选择。") from exc
    preferences = chat_thinking.normalize_preferences(selection[2] if len(selection) == 3 else None)
    return record_id, model, preferences


def preferences_of(token):
    try:
        return parse_selection(token)[2]
    except (ValueError, TypeError):
        return chat_thinking.default_preferences()


def token_with_preferences(token, preferences):
    record_id, model, _ = parse_selection(token)
    return model_token(record_id, model, preferences)


def is_default_selection(token):
    return parse_selection(token)[0] == ""


def resolve_selection(token):
    """返回 (模型实例或 None, 偏好)；默认连接不带凭据，仍走原默认模型。"""
    record_id, model, preferences = parse_selection(token)
    if not record_id:
        return None, preferences
    record = connection_store.find_connection(record_id=record_id)
    if not record:
        raise ValueError("已保存的连接不存在，请重新选择。")
    error = connection_error(record["base_url"], record["api_key"], model)
    if error:
        raise ValueError(error)
    from kotaemon.llms import ChatOpenAI
    llm = ChatOpenAI(base_url=record["base_url"], api_key=request_key(record["base_url"], record["api_key"]),
                     model=model, temperature=0.3, timeout=120)
    return llm, preferences


def selection_for(token):
    """非 token 的旧值（空字符串）按默认连接处理，保持历史对话可用。"""
    if not isinstance(token, str) or not token.startswith(PREFIX):
        return None, chat_thinking.default_preferences()
    return resolve_selection(token)


def resolve_model(token):
    return selection_for(token)[0]


def configure_model_routing(page):
    from ktem.llms.manager import LLMManager
    if not getattr(LLMManager, "_learning_context_models", False):
        original_get = LLMManager.get
        original_default = LLMManager.get_default

        def get(manager, key, default=None):
            if isinstance(key, str) and key.startswith(PREFIX):
                llm = _CHAT_LLM.get()
                if llm is not None:
                    return llm
                if is_default_selection(key):
                    return original_get(manager, key, default) or original_default(manager)
                return resolve_model(key)
            return original_get(manager, key, default)

        def get_default(manager):
            return _CHAT_LLM.get() or original_default(manager)

        LLMManager.get = get
        LLMManager.get_default = get_default
        LLMManager._learning_context_models = True

    original = page.chat_fn
    call_signature = signature(original)

    @wraps(original)
    def chat(*args, **kwargs):
        bound = call_signature.bind(*args, **kwargs)
        llm, preferences = selection_for(bound.arguments.get("llm_type"))
        chat_thinking.remember(bound.arguments.get("chat_state"), preferences)
        iterator = original(*args, **kwargs)
        try:
            while True:
                llm_context = _CHAT_LLM.set(llm)
                preferences_context = chat_thinking.set_preferences(preferences)
                try:
                    item = next(iterator)
                except StopIteration:
                    return
                finally:
                    chat_thinking.reset_preferences(preferences_context)
                    _CHAT_LLM.reset(llm_context)
                yield item
        finally:
            iterator.close()

    page.chat_fn = chat


def saved_choices():
    choices = [("跟随默认连接", "(default)")]
    try:
        records = connection_store.list_connections()
    except Exception:
        return choices
    for record in records:
        provider = record["provider"]
        profile = profile_for(provider, record["base_url"])
        if profile == "自定义地址":
            profile = "Coding" if "/coding/" in record["base_url"] else record["base_url"].split("://", 1)[-1]
        choices.append((f'{PLATFORMS[provider]["name"]} · {profile}', record["id"]))
    return choices


def choose_connection(record_id, preferences=None):
    preferences = chat_thinking.normalize_preferences(preferences)
    if record_id == "(default)" or not record_id:
        return gr.update(choices=[], value=None, interactive=False), default_model_token(preferences), ""
    record = connection_store.find_connection(record_id=record_id)
    if not record:
        return gr.update(choices=[], value=None, interactive=False), default_model_token(preferences), "该连接已不可用，请重新选择。"
    model = record["chat_model"]
    choices = list(dict.fromkeys([model, *PLATFORMS[record["provider"]]["models"]]))
    choices = [item for item in choices if item]
    return gr.update(choices=choices, value=model or None, interactive=True), model_token(record_id, model, preferences), ""


def choose_model(record_id, model, preferences=None):
    preferences = chat_thinking.normalize_preferences(preferences)
    if record_id == "(default)":
        return "(default)", default_model_token(preferences)
    record = connection_store.find_connection(record_id=record_id)
    if not record:
        raise gr.Error("该连接已不可用，请重新选择。")
    error = connection_error(record["base_url"], record["api_key"], model or "")
    if error:
        raise gr.Error(error)
    return model_token(record_id, model, preferences), ""


def default_chat_model(active=None):
    """默认连接实际使用的模型名，只用于前端判断思考强度是否可选。"""
    if active is None:
        try:
            from learning_ext.pages.quick_setup import _read_env

            active = _read_env()
        except Exception:
            active = {}
    model = str((active or {}).get("chat_model") or "").strip()
    if model:
        return model
    from learning_ext.llm.client import _load_config

    return str(_load_config().get("chat_model") or "").strip()


def configure_chat_connections(app, page):
    from learning_ext.pages.quick_setup import _read_env
    active = _read_env()
    try:
        records = connection_store.list_connections()
    except Exception:
        records = []
    initial = next((record["id"] for record in records
                    if all(record.get(field) == active.get(field, "") for field in connection_store.FIELDS)), "(default)")
    initial_model, initial_token, _ = choose_connection(initial)
    page.model_type.visible = False
    page.model_type.allow_custom_value = True
    page.model_type.elem_id = "le-chat-model-token"
    page.model_type.value = initial_token
    from html import escape
    default_model = default_chat_model(active)
    with gr.Column(elem_id="le-chat-connection-controls"):
        with gr.Row():
            page.saved_connection = gr.Dropdown(label="回答平台", choices=saved_choices(), value=initial, scale=1, min_width=160)
            page.saved_model = gr.Dropdown(label="回答模型", choices=initial_model["choices"], value=initial_model["value"], allow_custom_value=True, interactive=initial_model["interactive"], scale=1, min_width=140)
            refresh = gr.Button("刷新模型", size="sm", scale=0, min_width=38, elem_id="le-chat-model-refresh")
        status = gr.Markdown("", elem_id="le-chat-connection-status")
        page.default_model = gr.HTML(f"<span>{escape(default_model)}</span>", elem_id="le-chat-default-model", visible=False)

    def refresh_connections(current, model, token):
        preferences = preferences_of(token)
        choices = saved_choices()
        value = current if current in {value for _, value in choices} else "(default)"
        update, new_token, message = choose_connection(value, preferences)
        if value == current and value != "(default)" and model:
            update["choices"] = list(dict.fromkeys([model, *update["choices"]]))
            update["value"] = model
            new_token = model_token(value, model, preferences)
        return gr.update(choices=choices, value=value), update, new_token, message

    app._tabs["chat-tab"].select(refresh_connections, [page.saved_connection,page.saved_model,page.model_type],
                                  [page.saved_connection,page.saved_model,page.model_type,status], show_progress="hidden")
    page.saved_connection.input(choose_connection, [page.saved_connection], [page.saved_model,page.model_type,status], show_progress="hidden")
    page.saved_model.input(choose_model, [page.saved_connection,page.saved_model], [page.model_type,status], show_progress="hidden")

    def fetch(record_id, model):
        from learning_ext.pages.quick_setup import _fetch_models
        record = connection_store.find_connection(record_id=record_id)
        if not record:
            return gr.update(), "先选择一个已保存的平台。"
        return _fetch_models(record["base_url"], record["api_key"], model)

    refresh.click(fetch, [page.saved_connection,page.saved_model], [page.saved_model,status], show_progress="minimal")
    configure_model_routing(page)
    from learning_ext.chat_recovery import configure_chat_recovery
    configure_chat_recovery(page)
