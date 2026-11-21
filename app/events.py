"""Server-sent events for the owner UI (M).

Any module in this process (webhook receiver, payout poller, approval, call-back)
calls `publish(type, **data)`; every open browser tab receives it on /api/events.
Events carry a `message_key` + `vars` so the UI renders them in the owner's
language through the templates (never free text).
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import deque
from typing import AsyncIterator

_subscribers: set[asyncio.Queue] = set()
_lock = threading.Lock()
_history: deque = deque(maxlen=200)
_loop: asyncio.AbstractEventLoop | None = None
_seq = 0


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def publish(type: str, **data) -> dict:
    """Thread-safe: callable from sync code, background threads or async routes."""
    global _seq
    with _lock:
        _seq += 1
        event = {"id": _seq, "type": type, "at": time.time(), **data}
        _history.append(event)
        subs = list(_subscribers)
    for q in subs:
        if _loop is not None and _loop.is_running():
            _loop.call_soon_threadsafe(q.put_nowait, event)
        else:  # pragma: no cover
            q.put_nowait(event)
    return event


def history() -> list[dict]:
    with _lock:
        return list(_history)


async def stream(last_id: int = 0) -> AsyncIterator[str]:
    q: asyncio.Queue = asyncio.Queue()
    with _lock:
        _subscribers.add(q)
        backlog = [e for e in _history if e["id"] > last_id]
    try:
        for e in backlog:
            yield _fmt(e)
        while True:
            try:
                e = await asyncio.wait_for(q.get(), timeout=15)
                yield _fmt(e)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
    finally:
        with _lock:
            _subscribers.discard(q)


def _fmt(e: dict) -> str:
    return f"id: {e['id']}\nevent: {e['type']}\ndata: {json.dumps(e, default=str, ensure_ascii=False)}\n\n"
