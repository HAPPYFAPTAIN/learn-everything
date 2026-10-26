"""LLM 调用封装 (直连版)。

直接读取 kotaemon/.env 的 OpenAI 兼容配置，用 openai SDK 调用，
完全绕过 Kotaemon 的 llms manager，避免运行时更新和 PromptType 等 import 问题。

配置来源 (按优先级)：
    1. kotaemon/.env 文件 (由「⚡ 模型配置」页写入)
    2. 进程环境变量 (Kotaemon 启动时 decouple 已加载)
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Iterator, Optional

# .env 路径
_ENV_FILE = Path(__file__).resolve().parent.parent.parent / "kotaemon" / ".env"

# 配置缓存 (5 秒内复用，配置页保存后最多 5 秒生效)
_cache: dict = {"ts": 0.0, "data": {}}
_CACHE_TTL = 5.0
from learning_ext.llm.request_gate import RequestGate

_REQUEST_SLOT = RequestGate()


def invalidate_cache() -> None:
    """强制清空配置缓存, 让 .env 改动立即生效。配置页保存后调用。"""
    _cache["data"] = {}
    _cache["ts"] = 0.0


def _parse_env_file() -> dict:
    """解析 .env 文件为 dict"""
    data: dict[str, str] = {}
    if not _ENV_FILE.exists():
        return data
    try:
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip().strip("\"'")
    except Exception:
        pass
    return data


def _load_config() -> dict:
    """加载 LLM 配置 (.env 文件 + 环境变量，带缓存)"""
    now = time.time()
    if now - _cache["ts"] < _CACHE_TTL and _cache["data"]:
        return _cache["data"]

    file_cfg = _parse_env_file()
    cfg = {
        "api_key": (
            file_cfg.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
        ),
        "base_url": (
            file_cfg.get("OPENAI_API_BASE")
            or os.environ.get("OPENAI_API_BASE", "")
            or "https://api.openai.com/v1"
        ),
        "chat_model": (
            file_cfg.get("OPENAI_CHAT_MODEL")
            or os.environ.get("OPENAI_CHAT_MODEL", "")
            or "gpt-4o-mini"
        ),
        "embed_model": (
            file_cfg.get("OPENAI_EMBEDDINGS_MODEL")
            or os.environ.get("OPENAI_EMBEDDINGS_MODEL", "")
        ),
    }
    # 过滤占位符
    if "请在UI" in cfg["api_key"] or "YOUR" in cfg["api_key"]:
        cfg["api_key"] = ""
    _cache["data"] = cfg
    _cache["ts"] = now
    return cfg


def _get_client():
    """构造 openai 客户端"""
    from openai import OpenAI

    cfg = _load_config()
    if not cfg["api_key"]:
        raise RuntimeError(
            "未配置 API Key。请到「⚡ 模型配置」Tab 填入 API Key 并保存。"
        )
    # timeout: 连接 10s, 读取 120s (LLM 生成可能慢)
    return (
        OpenAI(
            api_key=cfg["api_key"],
            base_url=cfg["base_url"],
            timeout=120.0,
            max_retries=0,
        ),
        cfg,
    )


def chat(
    prompt: str,
    *,
    system: Optional[str] = None,
    model_name: Optional[str] = None,
    temperature: float = 0.3,
    stream: bool = False,
    max_tokens: Optional[int] = None,
    retries: int = 2,
    effort: Optional[str] = None,
    show_thinking: bool = False,
    purpose: str = "default",
) -> str | Iterator[str]:
    """单轮对话 (带超时 + 自动重试)。

    Args:
        prompt: 用户消息
        system: 可选系统提示
        model_name: 模型名 (None 用 .env 默认)
        temperature: 温度
        stream: 流式返回
        max_tokens: 最大输出 token
        retries: 失败重试次数 (网络瞬断/限流时)
        effort: 思考强度 low/high/max，仅支持的模型发送该参数
        show_thinking: 是否把模型返回的 reasoning_content 显示为思考过程
    """
    import logging
    import time

    from learning_ext import chat_thinking
    from learning_ext.model_platforms import adapt_chat_params

    log = logging.getLogger("learning_ext.llm")

    preferences = chat_thinking.normalize_preferences({
        "effort": chat_thinking.DEFAULT_EFFORT if effort is None else effort,
        "show_thinking": show_thinking,
    })
    client, cfg = _get_client()
    model = model_name or cfg["chat_model"]
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
        if model.lower().startswith("glm-5"):
            kwargs["max_tokens"] = max(8192, max_tokens * 3)

    kwargs = chat_thinking.apply_effort(kwargs, model, preferences["effort"])
    kwargs = adapt_chat_params(cfg["base_url"], kwargs)
    from learning_ext import reasoning_settings
    kwargs = reasoning_settings.apply(kwargs, cfg["base_url"], purpose)

    if stream:
        def generate():
            # 流式也要重试：代理/上游偶发抽风时，只要还没吐字就可以整体重来
            attempt = 0
            while True:
                emitted = False
                try:
                    with _REQUEST_SLOT:
                        with client.chat.completions.create(stream=True, **kwargs) as response:
                            for piece in _stream_iter(response, preferences["show_thinking"]):
                                emitted = True
                                yield piece
                    return
                except Exception as exc:  # noqa: BLE001
                    if emitted or attempt >= retries or not _transient(exc):
                        log.error(
                            "LLM 流式调用失败 | model=%s | base_url=%s | %s: %s",
                            model,
                            cfg.get("base_url"),
                            type(exc).__name__,
                            str(exc)[:500],
                        )
                        raise RuntimeError(friendly_error(exc)) from exc
                    wait = 1.2 * (attempt + 1)
                    log.warning(
                        "LLM 流式失败(%s)，%.1fs 后重试(%d/%d)：%s",
                        type(exc).__name__,
                        wait,
                        attempt + 1,
                        retries,
                        str(exc)[:200],
                    )
                    time.sleep(wait)
                    attempt += 1
        return generate()

    # 非流式: 带重试
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with _REQUEST_SLOT:
                resp = client.chat.completions.create(**kwargs)
            if resp.choices[0].finish_reason == "length":
                raise RuntimeError(
                    "模型输出达到长度上限，内容尚未完整生成。请减少本次任务范围或提高输出额度后重试。"
                )
            content = resp.choices[0].message.content or ""
            if preferences["show_thinking"]:
                block = chat_thinking.thinking_html(
                    getattr(resp.choices[0].message, "reasoning_content", None)
                )
                if block:
                    content = f"{block}\n\n{content}" if content.strip() else block
            if not content.strip():
                raise RuntimeError(
                    f"模型 `{model}` 返回了空回复。可能是模型名错误或内容被过滤。"
                    "请到「模型配置」检查模型名称和输出额度。"
                )
            return content
        except RuntimeError:
            raise  # 空回复不重试, 直接抛
        except Exception as e:
            last_err = e
            err_type = type(e).__name__
            # 限流/超时/连接错误/上游不可用 才重试; 鉴权错误不重试
            retryable = _transient(e)
            if not retryable or attempt == retries:
                log.error(
                    "LLM 调用失败 | model=%s | base_url=%s | prompt=%d字 | %s: %s",
                    model,
                    cfg.get("base_url"),
                    len(prompt or ""),
                    err_type,
                    str(e)[:500],
                )
                raise RuntimeError(friendly_error(e)) from e
            wait = (5 if "ratelimit" in err_type.lower() else 1) * 2**attempt
            log.warning(
                f"LLM 调用失败 ({err_type}), {wait}s 后重试 ({attempt + 1}/{retries}): {e}"
            )
            time.sleep(wait)
    raise RuntimeError(friendly_error(last_err) if last_err else "模型调用失败")


def _stream_iter(resp, show_thinking: bool = False) -> Iterator[str]:
    from learning_ext.chat_thinking import render_text_stream

    yield from render_text_stream(resp, show_thinking)


# ---- 错误归类：把底层报错翻译成用户看得懂的一句话 ----

_TRANSIENT_KEYWORDS = (
    "timeout",
    "timed out",
    "connection",
    "connect",
    "ratelimit",
    "rate limit",
    "temp",
    "unavailable",
    "overloaded",
    "router_error",
    "upstream",
    "502",
    "503",
    "504",
    "proxy",
    "ssl",
    "reset by peer",
    "econn",
)

_FRIENDLY_RULES = [
    (r"401|invalid.*api.?key|incorrect api key|authentication",
     "API Key 无效或已过期，请到「⚡ 模型配置」更新后重试。"),
    (r"403", "接口拒绝访问（403），检查 Key 权限或该模型是否已开通。"),
    (r"429|ratelimit|rate limit", "请求太频繁（被限流），等几秒再试。"),
    (r"insufficient|balance|quota|arrears|欠费", "账户余额或额度不足，请到服务商后台充值后再试。"),
    (r"router_error|upstream|unavailable|bad gateway|service unavailable|502|503|504",
     "模型服务临时不可达（上游或网络波动），稍等再试；若反复出现，多半是中转代理不稳定。"),
    (r"timeout|timed out|超时", "请求超时（网络较慢或上游拥塞），稍后重试。"),
    (r"connection|proxy|ssl|reset by peer|econn", "连不上模型服务（网络或代理问题），检查代理是否正常。"),
]


def _transient(exc: Exception) -> bool:
    """网络抖动/限流/上游不可用这类值得重试的错误。"""
    text = f"{type(exc).__name__} {exc}".lower()
    return any(kw in text for kw in _TRANSIENT_KEYWORDS)


def friendly_error(exc: Exception) -> str:
    """给界面看的错误说明，原始信息保留在括号里方便排查。"""
    text = f"{type(exc).__name__}: {exc}".lower()
    for pattern, message in _FRIENDLY_RULES:
        if re.search(pattern, text):
            return f"{message}（原始信息：{str(exc)[:160]}）"
    return f"模型调用失败：{type(exc).__name__}: {str(exc)[:200]}"


def stream_tool_response(messages, tools, *, selection=None):
    from learning_ext.chat_messages import sanitize_messages
    from learning_ext.model_platforms import adapt_chat_params
    from learning_ext import chat_connections, chat_thinking, connection_store
    preferences = chat_thinking.default_preferences()
    if selection:
        record_id, model, preferences = chat_connections.parse_selection(selection)
    else:
        record_id = ""
    if record_id:
        from openai import OpenAI
        from learning_ext.model_platforms import request_key
        record = connection_store.find_connection(record_id=record_id)
        if not record:
            raise ValueError("连接已被删除，请重新选择模型。")
        cfg = {"base_url": record["base_url"], "chat_model": model}
        client = OpenAI(api_key=request_key(record["base_url"], record["api_key"]),
                        base_url=record["base_url"], timeout=120.0, max_retries=0)
    else:
        client, cfg = _get_client()
    params = adapt_chat_params(cfg["base_url"], {"model": cfg["chat_model"],
        "messages": sanitize_messages(messages), "tools": tools, "tool_choice": "auto", "temperature": 0.3})
    if selection:
        params = chat_thinking.apply_effort(params, cfg["chat_model"], preferences["effort"])
    from learning_ext import reasoning_settings
    params = reasoning_settings.apply(params, cfg["base_url"], "coach")
    try:
        with _REQUEST_SLOT:
            with client.chat.completions.create(stream=True, **params) as response:
                yield from response
    finally:
        client.close()


def chat_json(
    prompt: str,
    *,
    system: Optional[str] = None,
    model_name: Optional[str] = None,
    purpose: str = "default",
) -> dict | list:
    """要求 LLM 返回 JSON 并解析 (容错提取)。

    自动剥离 markdown ```json 代码块标记。
    Returns:
        解析后的 dict 或 list
    """
    raw = chat(prompt, system=system, model_name=model_name, temperature=0.1, purpose=purpose)
    # 剥 markdown 代码块
    cleaned = re.sub(r"```(?:json)?\s*", "", raw)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip())
    # 尝试直接解析
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # 容错：提取首个 JSON 块 (支持 {} 和 [])
    for pattern in [r"\{[\s\S]*\}", r"\[[\s\S]*\]"]:
        match = re.search(pattern, cleaned)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                continue
    raise ValueError(
        f"LLM 未返回有效 JSON。模型: {_load_config()['chat_model']}\n"
        f"原始回复前 500 字: {raw[:500]}"
    )


def get_llm(model_name: Optional[str] = None):
    """兼容接口：返回一个简单的可调用对象 (带 .invoke/.stream)。

    供少量仍按 Kotaemon 风格调用的代码使用。
    """

    class _LLMWrapper:
        def __init__(self, model: str):
            self.model = model

        def invoke(self, prompt: str, *, system: Optional[str] = None) -> str:
            return chat(prompt, system=system, model_name=self.model)

        def stream(self, prompt: str, *, system: Optional[str] = None):
            return chat(prompt, system=system, model_name=self.model, stream=True)

        def __call__(self, prompt: str, *, system: Optional[str] = None) -> str:
            return chat(prompt, system=system, model_name=self.model)

    return _LLMWrapper(model_name or _load_config()["chat_model"])
