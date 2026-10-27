"""Live view of the login browser and the tickets that authorise it.

The login window is a real Chromium window on the machine that runs the
backend.  A desktop app on that machine can simply show it; a web client (or a
desktop app that talks to a hosted backend) cannot.  This module carries the
small amount of state needed to stream that window to a remote client:

* :class:`RemoteView` stores the newest JPEG frame and a bounded queue of
  pointer / keyboard events.  The browser thread publishes frames and drains
  the queue; the WebSocket route only touches the thread safe methods.
* Short lived, single use **stream tickets**.  A ticket is bound to one project
  and one user, is consumed when the WebSocket connects and never contains the
  long lived JWT.  A browser can therefore reconnect without leaking the
  session token into a URL or a proxy log.

Everything here lives in the backend process, just like the window manager in
:mod:`app.services.login_browser`.  A deployment that runs several workers has
to keep the login window and its stream on one worker (see the docs).
"""

from __future__ import annotations

import queue
import secrets
import threading
import time
from typing import Any

#: Input events are cheap to drop: a stale mouse move is useless anyway.
MAX_INPUT_EVENTS = 240


class RemoteView:
    """The newest frame and the input queue of one login window."""

    def __init__(self, *, width: int = 1280, height: int = 900) -> None:
        self.width = int(width)
        self.height = int(height)
        self._lock = threading.Lock()
        self._frame: bytes | None = None
        self._seq = 0
        self._frame_at = 0.0
        self._inputs: queue.Queue[dict[str, Any]] = queue.Queue(
            maxsize=MAX_INPUT_EVENTS
        )
        self._closed = False
        self._dropped = 0

    # -- frames -------------------------------------------------------
    def publish(
        self,
        data: bytes,
        *,
        width: int | None = None,
        height: int | None = None,
    ) -> None:
        """Store a new JPEG frame (called from the Playwright thread)."""
        if not data:
            return
        with self._lock:
            if self._closed:
                return
            self._frame = data
            self._seq += 1
            self._frame_at = time.time()
            if width and height:
                self.width = int(width)
                self.height = int(height)

    def latest(self) -> tuple[int, bytes | None]:
        """Return ``(sequence, frame)``; the sequence changes per frame."""
        with self._lock:
            return self._seq, self._frame

    @property
    def last_frame_at(self) -> float:
        with self._lock:
            return self._frame_at

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    # -- input --------------------------------------------------------
    def push_input(self, event: dict[str, Any]) -> bool:
        """Queue one input event.  When the queue is full the oldest goes."""
        if self._closed:
            return False
        try:
            self._inputs.put_nowait(event)
            return True
        except queue.Full:
            with self._lock:
                self._dropped += 1
            try:
                # Keep the newest pointer position; a dropped move is harmless.
                self._inputs.get_nowait()
                self._inputs.put_nowait(event)
            except (queue.Empty, queue.Full):
                return False
            return True

    def drain(self) -> list[dict[str, Any]]:
        """Take every queued input event (called from the browser thread)."""
        events: list[dict[str, Any]] = []
        while len(events) < MAX_INPUT_EVENTS:
            try:
                events.append(self._inputs.get_nowait())
            except queue.Empty:
                break
        return events

    @property
    def dropped_inputs(self) -> int:
        with self._lock:
            return self._dropped

    def close(self) -> None:
        """Mark the view closed; pending WebSockets finish on their own."""
        with self._lock:
            self._closed = True
            self._frame = None
        while True:
            try:
                self._inputs.get_nowait()
            except queue.Empty:
                break


# ---------------------------------------------------------------------------
# Stream tickets
# ---------------------------------------------------------------------------

#: A ticket only has to survive the trip from the HTTP response to the
#: WebSocket handshake.  Short enough that a leaked URL is useless.
DEFAULT_TICKET_TTL = 90

_TICKETS: dict[str, tuple[str, str, float]] = {}
_TICKET_LOCK = threading.Lock()


def issue_ticket(
    project_id: str, user_id: str, *, ttl: int = DEFAULT_TICKET_TTL
) -> dict[str, Any]:
    """Create a single use ticket for the stream of one project."""
    token = secrets.token_urlsafe(32)
    expires_at = time.time() + max(5, int(ttl))
    _purge_expired()
    with _TICKET_LOCK:
        _TICKETS[token] = (project_id, str(user_id or ""), expires_at)
    return {
        "ticket": token,
        "expires_in": max(0, int(expires_at - time.time())),
        "expires_at": expires_at,
    }


def redeem_ticket(ticket: str, project_id: str) -> str | None:
    """Consume a ticket.  Returns the user id when it is valid for ``project_id``."""
    if not ticket:
        return None
    _purge_expired()
    with _TICKET_LOCK:
        entry = _TICKETS.pop(ticket, None)
    if entry is None:
        return None
    bound_project, user_id, expires_at = entry
    if bound_project != project_id or expires_at < time.time():
        return None
    return user_id


def _purge_expired() -> None:
    now = time.time()
    with _TICKET_LOCK:
        expired = [key for key, value in _TICKETS.items() if value[2] < now]
        for key in expired:
            _TICKETS.pop(key, None)


def reset_tickets() -> None:
    """Drop every ticket (used by tests and a full logout)."""
    with _TICKET_LOCK:
        _TICKETS.clear()
