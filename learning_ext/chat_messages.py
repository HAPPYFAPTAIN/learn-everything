from collections.abc import Mapping

from learning_ext.chat_thinking import strip_reasoning_prefix


def sanitize_messages(messages):
    cleaned = []
    for message in messages:
        content = message.get("content")
        if message.get("role") == "assistant" and isinstance(content, str):
            stripped = strip_reasoning_prefix(content)
            if stripped != content:
                message = {**message, "content": stripped}
                content = stripped
        empty = content is None or (
            isinstance(content, str) and not content.strip()
        ) or (isinstance(content, (list, tuple, dict)) and not content)
        if (
            message.get("role") == "assistant"
            and empty
            and not message.get("tool_calls")
            and not message.get("function_call")
        ):
            continue
        cleaned.append(message)
    if not cleaned:
        raise ValueError("没有有效消息：请提供用户问题，不能只发送空的 AI 回复。")
    return cleaned


def prepare_messages(messages):
    from kotaemon.base import BaseMessage, HumanMessage

    if isinstance(messages, str):
        messages = [HumanMessage(content=messages)]
    elif isinstance(messages, BaseMessage):
        messages = [messages]
    payloads = []
    for message in messages:
        payload = dict(message.to_openai_format())
        if payload.get("role") == "assistant":
            extra = getattr(message, "additional_kwargs", {})
            for key in ("tool_calls", "function_call"):
                if not payload.get(key) and extra.get(key):
                    payload[key] = extra[key]
            if not payload.get("tool_calls"):
                calls = getattr(message, "tool_calls", None)
                if calls:
                    import json

                    payload["tool_calls"] = [
                        {
                            "id": call["id"],
                            "type": "function",
                            "function": {
                                "name": call["name"],
                                "arguments": json.dumps(call["args"], ensure_ascii=False),
                            },
                        }
                        if isinstance(call, Mapping) and "args" in call
                        else call
                        for call in calls
                    ]
        payloads.append(payload)
    return sanitize_messages(payloads)
