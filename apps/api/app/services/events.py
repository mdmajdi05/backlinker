"""Real-time event bus + activity log.

Events are persisted (so the activity feed survives restarts) and published to
in-process subscribers (SSE / WebSocket). Publishing is thread-safe so worker
threads can emit events while the API serves requests.
"""

from __future__ import annotations

import asyncio
import threading
from collections import deque
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.base import utcnow
from app.db.models import TaskEvent

log = get_logger(__name__)

MAX_RECENT = 500


class EventBus:
    """Fan-out event bus with thread safe publishing."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue] = []
        self._recent: deque[dict[str, Any]] = deque(maxlen=MAX_RECENT)
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._recent.append(payload)
            subscribers = list(self._subscribers)
        for queue in subscribers:
            try:
                if self._loop is not None and self._loop.is_running():
                    self._loop.call_soon_threadsafe(queue.put_nowait, payload)
                else:
                    queue.put_nowait(payload)
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("event publish failed", extra={"extra_fields": {"error": str(exc)}})

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._recent)
        return items[-limit:][::-1]

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        with self._lock:
            self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            if queue in self._subscribers:
                self._subscribers.remove(queue)


bus = EventBus()


def record_event(
    db: Session,
    event_type: str,
    message: str,
    *,
    level: str = "INFO",
    task_id: str | None = None,
    project_id: str | None = None,
    website_id: str | None = None,
    execution_environment: str | None = None,
    metadata: dict[str, Any] | None = None,
    commit: bool = True,
) -> TaskEvent:
    """Persist an event and publish it to live subscribers."""
    event = TaskEvent(
        event_type=event_type,
        message=message,
        level=level,
        task_id=task_id,
        project_id=project_id,
        website_id=website_id,
        execution_environment=execution_environment,
        meta=metadata or {},
        created_at=utcnow(),
    )
    db.add(event)
    if commit:
        db.commit()
    else:
        db.flush()
    bus.publish(
        {
            "id": event.id,
            "event_type": event.event_type,
            "message": event.message,
            "level": event.level,
            "task_id": event.task_id,
            "project_id": event.project_id,
            "website_id": event.website_id,
            "execution_environment": event.execution_environment,
            "metadata": event.meta,
            "created_at": (event.created_at or datetime.now(UTC)).isoformat(),
        }
    )
    return event


async def event_stream(project_id: str | None = None) -> AsyncIterator[dict[str, Any]]:
    """Async generator used by the SSE endpoint."""
    queue = bus.subscribe()
    try:
        yield {"event": "connected", "data": {"project_id": project_id}}
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=15.0)
            except TimeoutError:
                yield {"event": "ping", "data": {"ts": utcnow().isoformat()}}
                continue
            if project_id and payload.get("project_id") and payload["project_id"] != project_id:
                continue
            yield {"event": payload.get("event_type", "message"), "data": payload}
    finally:
        bus.unsubscribe(queue)
