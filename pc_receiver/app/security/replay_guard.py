from __future__ import annotations

from collections import OrderedDict
from threading import Lock
from time import monotonic
from typing import Callable


class ReplayGuard:
    def __init__(self, ttl_seconds: float, max_entries: int = 4096, clock: Callable[[], float] = monotonic):
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        self._items: OrderedDict[str, float] = OrderedDict()
        self._lock = Lock()

    def contains(self, value: str) -> bool:
        with self._lock:
            self._purge()
            return value in self._items

    def accept(self, value: str) -> bool:
        with self._lock:
            self._purge()
            if value in self._items:
                return False
            self._items[value] = self._clock()
            while len(self._items) > self._max_entries:
                self._items.popitem(last=False)
            return True

    def _purge(self) -> None:
        cutoff = self._clock() - self._ttl
        while self._items and next(iter(self._items.values())) < cutoff:
            self._items.popitem(last=False)
