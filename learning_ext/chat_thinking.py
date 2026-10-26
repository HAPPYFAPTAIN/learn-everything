"""思考强度与思考过程显示。

思考偏好随模型选择一起保存在连接 token 的第三项，并用 ContextVar
按每条问答流隔离，避免并发请求互相改写默认模型的行为。
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from html import escape
import re
from typing import Mapping

EFFORTS = ("low", "high", "max")
DEFAULT_EFFORT = "low"
DEFAULT_PREFERENCES = {"effort": DEFAULT_EFFORT, "show_thinking": False}
EFFORT_MODELS = ("kimi-k3.1", "glm-5.3")
STATE_KEY = "learning_chat_thinking"
SUMMARY = "思考过程"
REASONING_CLASS = "le-reasoning"

_THINKING_OPEN = f'<details class="{REASONING_CLASS}"><summary>{SUMMARY}</summary><blockquote>'
_THINKING_CLOSE = "</blockquote></details>"
_THINKING_PREFIX = re.compile(
    r"^\s*"
    + re.escape(_THINKING_OPEN)
    + r".*?"
    + re.escape(_THINKING_CLOSE)
    + r"(?:\r?\n){0,2}",
    re.S,
)

_current = ContextVar("learning_chat_thinking", default=None)


def default_preferences():
    return dict(DEFAULT_PREFERENCES)


def normalize_preferences(value=None):
    """校验偏好；缺省项取默认值，坏值抛出可直接展示的错误。"""
    if value is None:
        return default_preferences()
    if not isinstance(value, Mapping):
        raise ValueError("思考偏好无效：应为包含思考强度和显示开关的设置。")
    unknown = sorted(str(key) for key in set(value) - {"effort", "show_thinking"})
    if unknown:
        raise ValueError(f"思考偏好无效：包含未知设置 {'、'.join(unknown)}。")
    effort = value.get("effort", DEFAULT_EFFORT)
    if not isinstance(effort, str) or effort not in EFFORTS:
        raise ValueError("思考偏好无效：思考强度只能是 low、high 或 max。")
    show_thinking = value.get("show_thinking", False)
    if not isinstance(show_thinking, bool):
        raise ValueError("思考偏好无效：思考过程开关只能是开或关。")
    return {"effort": effort, "show_thinking": show_thinking}


def set_preferences(value=None):
    return _current.set(normalize_preferences(value))


def reset_preferences(token):
    _current.reset(token)


@contextmanager
def using(value=None):
    token = set_preferences(value)
    try:
        yield
    finally:
        reset_preferences(token)


def current_preferences():
    value = _current.get()
    return dict(value) if value else default_preferences()


def remember(state, preferences):
    """把本次偏好写入 chat_state，供中断兜底继续使用。"""
    if isinstance(state, dict):
        state[STATE_KEY] = normalize_preferences(preferences)


def from_state(state):
    """读取 chat_state 中的偏好；缺失或损坏时安静回落到默认值。"""
    if not isinstance(state, Mapping):
        return default_preferences()
    try:
        return normalize_preferences(state.get(STATE_KEY))
    except ValueError:
        return default_preferences()


def model_name(model):
    return str(model or "").strip().lower().split("/")[-1]


def supports_effort(model):
    name = model_name(model)
    return any(name.startswith(prefix) for prefix in EFFORT_MODELS)


def effort_for(model, effort=DEFAULT_EFFORT):
    """支持的模型返回合法强度，其他模型返回 None（不发送参数）。"""
    if not supports_effort(model):
        return None
    value = str(effort or "").strip().lower()
    return value if value in EFFORTS else DEFAULT_EFFORT


def apply_effort(params, model, effort=DEFAULT_EFFORT):
    result = dict(params)
    value = effort_for(model, effort)
    if value:
        result["reasoning_effort"] = value
    return result


def thinking_html(reasoning):
    text = escape(str(reasoning or "")).strip()
    if not text:
        return ""
    return f"{_THINKING_OPEN}{text}{_THINKING_CLOSE}"


def strip_reasoning_prefix(content):
    """去掉消息开头本应用生成的思考块，只用于发回模型的请求文本。"""
    if not isinstance(content, str) or "<details" not in content:
        return content
    match = _THINKING_PREFIX.match(content)
    if not match:
        return content
    return content[match.end():]


def stream_with_thinking(chunks):
    """把真实 reasoning_content 折叠成一段 HTML 前缀，正文与日志字段保持原样。"""
    pending = []
    started = False
    last = None
    for chunk in chunks:
        last = chunk
        choice, content, reasoning = _delta(chunk)
        if choice is None:
            yield chunk
            continue
        if isinstance(reasoning, str) and reasoning and not started:
            pending.append(reasoning)
        if content:
            if pending:
                block = _take_block(pending)
                pending = []
                started = True
                if block:
                    yield _content_chunk(chunk, block)
            yield chunk
        elif (
            reasoning
            and not _has_calls(choice)
            and getattr(choice, "finish_reason", None) is None
        ):
            continue
        else:
            if pending and getattr(choice, "finish_reason", None) is not None:
                block = _take_block(pending)
                pending = []
                started = True
                if block:
                    yield _content_chunk(chunk, block)
            yield chunk
    if pending:
        block = _take_block(pending)
        if block:
            yield _content_chunk(last, block)


def _take_block(pending):
    return thinking_html("".join(pending))


def _delta(chunk):
    choices = getattr(chunk, "choices", None) or ()
    if not choices:
        return None, None, None
    choice = choices[0]
    delta = getattr(choice, "delta", None)
    if delta is None:
        return choice, None, None
    return choice, getattr(delta, "content", None), getattr(delta, "reasoning_content", None)


def _has_calls(choice):
    delta = getattr(choice, "delta", None)
    return bool(getattr(delta, "tool_calls", None) or getattr(delta, "function_call", None))


def _content_chunk(template, text):
    from openai.types.chat.chat_completion_chunk import (
        ChatCompletionChunk,
        Choice,
        ChoiceDelta,
    )

    return ChatCompletionChunk(
        id=str(getattr(template, "id", "") or "learning-thinking"),
        object="chat.completion.chunk",
        created=int(getattr(template, "created", 0) or 0),
        model=str(getattr(template, "model", "") or ""),
        choices=[
            Choice(index=0, delta=ChoiceDelta(content=text), finish_reason=None)
        ],
    )


def render_text_stream(resp, show_thinking=False):
    """把 OpenAI 流式响应转成文本片段；开启显示时先输出思考 HTML。"""
    chunks = stream_with_thinking(resp) if show_thinking else resp
    for chunk in chunks:
        choices = getattr(chunk, "choices", None) or ()
        if choices and choices[0].finish_reason == "length":
            raise RuntimeError("模型输出达到长度上限，请缩小问题范围后重试。")
        if choices and choices[0].delta.content:
            yield choices[0].delta.content
