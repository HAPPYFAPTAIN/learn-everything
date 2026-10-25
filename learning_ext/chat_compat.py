from functools import wraps

from learning_ext.chat_messages import prepare_messages, sanitize_messages
from learning_ext.model_platforms import adapt_chat_params


def _prepare_message(self, messages):
    return prepare_messages(messages)


def _guard_params(original):
    @wraps(original)
    def guarded(self, **kwargs):
        if "messages" in kwargs:
            kwargs["messages"] = sanitize_messages(kwargs["messages"])
        return adapt_chat_params(getattr(self, "base_url", None), original(self, **kwargs))

    return guarded


def _endpoint_run(self, messages, **kwargs):
    import requests
    from kotaemon.base import LLMInterface

    payload = {"messages": prepare_messages(messages)}
    reply = requests.post(self.endpoint_url, json=payload, timeout=(10, 120))
    reply.raise_for_status()
    response = reply.json()
    candidates = [
        choice["message"].get("content")
        for choice in response["choices"]
        if choice["message"].get("content")
    ]
    usage = response.get("usage") or {}
    prompt_tokens = usage.get("prompt_tokens") or 0
    completion_tokens = usage.get("completion_tokens") or 0
    return LLMInterface(
        content=candidates[0] if candidates else "",
        candidates=candidates,
        completion_tokens=completion_tokens,
        total_tokens=usage.get("total_tokens") or prompt_tokens + completion_tokens,
        prompt_tokens=prompt_tokens,
    )


def configure_chat_compat():
    from kotaemon.llms.chats.endpoint_based import EndpointChatLLM
    from kotaemon.llms.chats.openai import (
        AzureChatOpenAI,
        BaseChatOpenAI,
        ChatOpenAI,
        StructuredOutputChatOpenAI,
    )

    if getattr(BaseChatOpenAI, "_learning_message_guard", False):
        return
    BaseChatOpenAI.prepare_message = _prepare_message
    for cls in (ChatOpenAI, StructuredOutputChatOpenAI, AzureChatOpenAI):
        cls.prepare_params = _guard_params(cls.prepare_params)
    EndpointChatLLM.run = _endpoint_run
    BaseChatOpenAI._learning_message_guard = True
    print("[learning_ext] Chat message validation enabled (OpenAI/Azure/Endpoint)", flush=True)
