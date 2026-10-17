import asyncio
from functools import wraps

from learning_ext.llm.client import _REQUEST_SLOT


def serialized_call(original):
    @wraps(original)
    def wrapped(*args, **kwargs):
        with _REQUEST_SLOT:
            return original(*args, **kwargs)
    return wrapped


def serialized_async_call(original):
    @wraps(original)
    async def wrapped(*args, **kwargs):
        while not _REQUEST_SLOT.acquire(blocking=False):
            await asyncio.sleep(0.05)
        try:
            return await original(*args, **kwargs)
        finally:
            _REQUEST_SLOT.release()
    return wrapped


def serialized_stream(original):
    @wraps(original)
    def wrapped(*args, **kwargs):
        with _REQUEST_SLOT:
            iterator = original(*args, **kwargs)
            try:
                yield from iterator
            finally:
                close = getattr(iterator, "close", None)
                if close:
                    close()
    return wrapped


def configure_rag_requests():
    from kotaemon.llms.chats.openai import BaseChatOpenAI

    if getattr(BaseChatOpenAI, "_learning_serialized", False):
        return
    BaseChatOpenAI.invoke = serialized_call(BaseChatOpenAI.invoke)
    BaseChatOpenAI.ainvoke = serialized_async_call(BaseChatOpenAI.ainvoke)
    BaseChatOpenAI.stream = serialized_stream(BaseChatOpenAI.stream)
    BaseChatOpenAI._learning_serialized = True
