"""In-process event bus: worker threads publish, WebSocket clients subscribe."""
from __future__ import annotations

import asyncio
import collections
import json
import logging
import threading
from datetime import datetime

log = logging.getLogger("events")


class EventBus:
    def __init__(self, history: int = 200):
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = threading.Lock()
        self.activity = collections.deque(maxlen=history)  # recent activity feed for the dashboard

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def _deliver(self, message: str) -> None:
        with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(message)

    def publish(self, event_type: str, data: dict, activity: str | None = None, level: str = "info") -> None:
        """Thread-safe publish. ``activity`` adds a human readable line to the activity feed."""
        ts = datetime.now().isoformat(timespec="seconds")
        if activity:
            item = {"time": ts, "message": activity, "level": level, "type": event_type}
            self.activity.appendleft(item)
            self._send({"type": "activity", "data": item, "time": ts})
        self._send({"type": event_type, "data": data, "time": ts})

    def _send(self, payload: dict) -> None:
        if self._loop is None:
            return
        message = json.dumps(payload, default=str)
        try:
            self._loop.call_soon_threadsafe(self._deliver, message)
        except RuntimeError:
            pass  # loop closed during shutdown


bus = EventBus()
