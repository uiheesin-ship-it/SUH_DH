"""Tiny in-memory TTL cache shared across requests.

Free data sources (Yahoo Finance, Finviz) rate-limit aggressively, so we
cache results for a short period instead of hitting them on every request.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

_lock = threading.Lock()
_store: dict[str, tuple[float, Any]] = {}


def get_or_set(key: str, ttl: float, producer: Callable[[], Any]) -> Any:
    """Return cached value for ``key`` or compute it with ``producer``.

    The producer is run outside the lock so a slow network call does not block
    other cache keys, but each key is recomputed at most once per TTL window.
    """
    now = time.time()
    with _lock:
        hit = _store.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]

    value = producer()  # may raise; caller decides how to handle

    with _lock:
        _store[key] = (time.time(), value)
    return value


def peek(key: str, ttl: float) -> Any | None:
    """Return a still-fresh cached value, or None."""
    with _lock:
        hit = _store.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    return None


def clear() -> None:
    with _lock:
        _store.clear()
