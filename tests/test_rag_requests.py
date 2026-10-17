import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from learning_ext.rag_requests import serialized_call, serialized_async_call, serialized_stream
from learning_ext.llm.client import _REQUEST_SLOT


def test_sync_parallel_calls_share_one_slot():
    active = 0
    peak = 0
    @serialized_call
    def call():
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        time.sleep(0.01)
        active -= 1
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: call(), range(4)))
    assert peak == 1


def test_failure_releases_slot():
    @serialized_call
    def fail():
        raise RuntimeError("expected")
    with pytest.raises(RuntimeError):
        fail()
    assert _REQUEST_SLOT.acquire(blocking=False)
    _REQUEST_SLOT.release()


def test_stream_cancel_releases_slot_and_closes_iterator():
    closed = []
    @serialized_stream
    def stream():
        try:
            yield "one"
            yield "two"
        finally:
            closed.append(True)
    iterator = stream()
    assert next(iterator) == "one"
    assert not _REQUEST_SLOT.acquire(blocking=False)
    iterator.close()
    assert closed == [True]
    assert _REQUEST_SLOT.acquire(blocking=False)
    _REQUEST_SLOT.release()


def test_async_cancellation_does_not_leak_or_release_others_slot():
    @serialized_async_call
    async def call():
        return "ok"
    async def run():
        with _REQUEST_SLOT:
            task = asyncio.create_task(call())
            await asyncio.sleep(0.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not _REQUEST_SLOT.acquire(blocking=False)
        assert await call() == "ok"
    asyncio.run(run())
