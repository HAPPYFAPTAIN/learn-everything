from contextlib import contextmanager
from contextvars import ContextVar
from threading import Condition
from time import monotonic


_background = ContextVar("le_background_request", default=False)


@contextmanager
def background_requests():
    token = _background.set(True)
    try:
        yield
    finally:
        _background.reset(token)


class RequestGate:
    """保持单请求串行，让排队中的用户请求先于后台备课。"""

    def __init__(self):
        self._condition = Condition()
        self._waiting = []
        self._active = False

    def __enter__(self):
        self.acquire()
        return self

    def acquire(self, blocking=True, timeout=None):
        if not blocking and timeout is not None:
            raise ValueError("can't specify timeout for non-blocking acquire")
        ticket = (object(), _background.get())
        with self._condition:
            if not blocking:
                if self._active or self._waiting:
                    return False
                self._active = True
                return True
            deadline = None if timeout is None else monotonic() + timeout
            self._waiting.append(ticket)
            try:
                while self._active or self._next() is not ticket:
                    remaining = None if deadline is None else deadline - monotonic()
                    if remaining is not None and remaining <= 0:
                        self._waiting.remove(ticket)
                        self._condition.notify_all()
                        return False
                    self._condition.wait(remaining)
                self._waiting.remove(ticket)
                self._active = True
            except BaseException:
                self._waiting.remove(ticket)
                self._condition.notify_all()
                raise
        return True

    def _next(self):
        return next((ticket for ticket in self._waiting if not ticket[1]), self._waiting[0])

    def __exit__(self, *exc):
        self.release()

    def release(self):
        with self._condition:
            if not self._active:
                raise ValueError("request slot released too many times")
            self._active = False
            self._condition.notify_all()

