import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace as NS

import pytest
import learning_ext.llm.client as client


def install(monkeypatch, create):
    monkeypatch.setattr(client, '_REQUEST_SLOT', threading.BoundedSemaphore(1))
    monkeypatch.setattr(client, '_get_client', lambda: (NS(chat=NS(completions=NS(create=create))), {'chat_model': 'test'}))


def test_foreground_and_background_requests_do_not_overlap(monkeypatch):
    counts = {'active': 0, 'peak': 0}
    lock = threading.Lock()
    def create(**kwargs):
        with lock:
            counts['active'] += 1
            counts['peak'] = max(counts.values())
        time.sleep(.02)
        with lock:
            counts['active'] -= 1
        return NS(choices=[NS(finish_reason='stop', message=NS(content='ok'))])
    install(monkeypatch, create)
    with ThreadPoolExecutor(max_workers=5) as pool:
        assert list(pool.map(client.chat, ['test'] * 5)) == ['ok'] * 5
    assert counts['peak'] == 1


def test_failed_request_releases_slot(monkeypatch):
    def create(**kwargs):
        raise RuntimeError('test failure')
    install(monkeypatch, create)
    with pytest.raises(RuntimeError, match='test failure'):
        client.chat('test')
    assert client._REQUEST_SLOT.acquire(blocking=False)
    client._REQUEST_SLOT.release()


def test_cancelled_stream_closes_response_and_releases_slot(monkeypatch):
    class Response:
        closed = False
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.closed = True
        def __iter__(self):
            for text in ['first', 'second']:
                yield NS(choices=[NS(finish_reason=None, delta=NS(content=text))])
    response = Response()
    install(monkeypatch, lambda **kwargs: response)
    stream = client.chat('test', stream=True)
    assert next(stream) == 'first'
    assert not client._REQUEST_SLOT.acquire(blocking=False)
    stream.close()
    assert response.closed
    assert client._REQUEST_SLOT.acquire(blocking=False)
    client._REQUEST_SLOT.release()
