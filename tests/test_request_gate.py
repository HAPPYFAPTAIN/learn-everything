import threading
import time

import pytest

from learning_ext.llm.request_gate import RequestGate, background_requests


def wait_for_queue(gate, length):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        with gate._condition:
            if len(gate._waiting) == length:
                return
        time.sleep(.005)
    pytest.fail('Request did not join queue')


def test_foreground_precedes_queued_background_without_parallel_requests():
    gate = RequestGate()
    order = []

    def background():
        with background_requests(), gate:
            order.append('background')

    def foreground():
        with gate:
            order.append('foreground')

    with gate:
        bg = threading.Thread(target=background, daemon=True)
        bg.start()
        wait_for_queue(gate, 1)
        fg = threading.Thread(target=foreground, daemon=True)
        fg.start()
        wait_for_queue(gate, 2)
        assert order == []
    bg.join(2)
    fg.join(2)
    assert order == ['foreground', 'background']
    assert not bg.is_alive() and not fg.is_alive()


def test_exception_releases_request_slot():
    gate = RequestGate()
    with pytest.raises(ValueError), gate:
        raise ValueError('test')
    finished = threading.Event()

    def next_request():
        with gate:
            finished.set()

    worker = threading.Thread(target=next_request, daemon=True)
    worker.start()
    worker.join(2)
    assert finished.is_set()
