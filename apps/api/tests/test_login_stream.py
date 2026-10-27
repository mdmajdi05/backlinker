"""The live view of the login browser.

The browser itself is covered by ``test_project_login.py``.  These tests cover
the transport of the remote view: the frame hub, the one time stream tickets,
the WebSocket handshake and the mapping of pointer / keyboard events.  No real
browser is started - a fake page records what the bridge would do.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.config import settings
from app.services import login_browser, login_stream
from tests.conftest import API

# ---------------------------------------------------------------------------
# Frame hub
# ---------------------------------------------------------------------------


def test_the_frame_hub_keeps_the_newest_frame() -> None:
    view = login_stream.RemoteView(width=800, height=600)
    assert view.latest() == (0, None)

    view.publish(b"first", width=1024, height=768)
    seq_one, frame_one = view.latest()
    view.publish(b"second")

    seq_two, frame_two = view.latest()
    assert (seq_one, frame_one) == (1, b"first")
    assert seq_two == 2
    assert frame_two == b"second"
    # The frame metadata resizes the coordinate system of the viewer.
    assert (view.width, view.height) == (1024, 768)

    view.close()
    assert view.closed is True
    assert view.latest() == (2, None)


def test_the_input_queue_is_bounded_and_keeps_the_newest_event() -> None:
    view = login_stream.RemoteView()
    for index in range(login_stream.MAX_INPUT_EVENTS + 10):
        assert view.push_input({"type": "mouse", "x": index}) is True

    events = view.drain()
    assert len(events) == login_stream.MAX_INPUT_EVENTS
    # The oldest events were dropped, the newest position survived.
    assert events[-1]["x"] == login_stream.MAX_INPUT_EVENTS + 9
    assert view.dropped_inputs >= 10
    assert view.drain() == []

    view.close()
    assert view.push_input({"type": "mouse"}) is False


# ---------------------------------------------------------------------------
# Tickets
# ---------------------------------------------------------------------------


def test_a_stream_ticket_is_single_use_and_bound_to_its_project() -> None:
    login_stream.reset_tickets()
    issued = login_stream.issue_ticket("project-1", "user-1", ttl=30)

    assert issued["ticket"]
    assert issued["expires_in"] > 0

    # A different project cannot redeem it.
    assert login_stream.redeem_ticket(issued["ticket"], "project-2") is None
    # The failed attempt consumed the ticket on purpose.
    assert login_stream.redeem_ticket(issued["ticket"], "project-1") is None

    issued = login_stream.issue_ticket("project-1", "user-1", ttl=30)
    assert login_stream.redeem_ticket(issued["ticket"], "project-1") == "user-1"
    assert login_stream.redeem_ticket(issued["ticket"], "project-1") is None


def test_an_expired_ticket_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    login_stream.reset_tickets()
    issued = login_stream.issue_ticket("project-1", "user-1", ttl=5)

    later = time.time() + 10
    monkeypatch.setattr(login_stream.time, "time", lambda: later)

    assert login_stream.redeem_ticket(issued["ticket"], "project-1") is None


def test_an_empty_ticket_is_rejected() -> None:
    assert login_stream.redeem_ticket("", "project-1") is None


# ---------------------------------------------------------------------------
# Selecting the surface
# ---------------------------------------------------------------------------


def _window(view: str) -> login_browser.LoginWindow:
    return login_browser.LoginWindow(
        "project-1",
        "https://accounts.google.com/",
        mode="google",
        website_id=None,
        email_hint=None,
        view=view,
    )


def test_auto_opens_a_native_window_on_a_local_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "desktop")
    monkeypatch.setattr(login_browser, "display_available", lambda: True)
    window = _window("auto")

    window._plan_view()

    assert window.view == "native"
    assert window.headless is False
    assert window.warning is None


def test_a_hosted_backend_streams_instead_of_opening_a_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "environment", "cloud")
    monkeypatch.setattr(login_browser, "display_available", lambda: True)
    monkeypatch.setattr(login_browser, "ensure_display", lambda: True)
    window = _window("auto")

    window._plan_view()

    assert window.view == "remote"
    assert window.headless is False
    assert window.warning is None


def test_a_remote_window_answers_with_the_stream_view_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The HTTP response must not race the browser thread of the window."""
    monkeypatch.setattr(login_browser, "display_available", lambda: True)

    window = _window("remote")

    assert window.view == "remote"
    assert window.describe()["view"] == "remote"


def test_a_headless_backend_warns_that_google_may_refuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "environment", "cloud")
    monkeypatch.setattr(login_browser, "display_available", lambda: False)
    monkeypatch.setattr(login_browser, "ensure_display", lambda: False)
    window = _window("remote")

    window._plan_view()

    assert window.view == "remote"
    assert window.headless is True
    assert window.warning == login_browser.HEADLESS_WARNING


def test_native_falls_back_to_streaming_without_a_display(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(login_browser, "display_available", lambda: False)
    monkeypatch.setattr(login_browser, "ensure_display", lambda: True)
    window = _window("native")

    window._plan_view()

    assert window.view == "remote"
    assert window.headless is False
    assert "no display" in (window.warning or "")


def test_the_login_browser_installs_the_runtime_on_first_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh desktop bundle has no Playwright - the login must install it."""
    window = _window("remote")
    calls: list[str] = []

    monkeypatch.setattr(
        login_browser.browser_service, "runtime_ready", lambda: False
    )

    def fake_install(*_args: Any, **_kwargs: Any) -> tuple[bool, str]:
        calls.append("install")
        window.final_message = window.final_message  # still preparing
        return True, "installed"

    monkeypatch.setattr(login_browser.browser_service, "install_runtime", fake_install)
    monkeypatch.setattr(
        login_browser, "ensure_playwright_path", lambda: calls.append("path")
    )

    sync_playwright = login_browser._load_sync_playwright(window)

    assert callable(sync_playwright)
    # The path is refreshed once before the check and once after the install.
    assert calls == ["path", "install", "path"]
    assert window.final_message == "The browser is ready. Opening the login window…"


def test_a_failed_runtime_install_is_reported_honestly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = _window("remote")
    monkeypatch.setattr(
        login_browser.browser_service, "runtime_ready", lambda: False
    )
    monkeypatch.setattr(
        login_browser.browser_service,
        "install_runtime",
        lambda *_args, **_kwargs: (False, "no network"),
    )
    monkeypatch.setattr(login_browser, "ensure_playwright_path", lambda: None)

    with pytest.raises(RuntimeError) as error:
        login_browser._load_sync_playwright(window)

    assert "no network" in str(error.value)
    assert window.final_message == login_browser.RUNTIME_MISSING


def test_an_open_native_window_can_be_switched_to_streaming() -> None:
    window = _window("native")
    window.view = "native"
    window.running = True

    window.request_stream()

    assert window.view == "remote"
    assert window.describe()["stream_available"] is True


# ---------------------------------------------------------------------------
# First-run preparation progress
# ---------------------------------------------------------------------------


def test_describe_exposes_the_download_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import browser as browser_service

    window = _window("remote")
    window.running = True
    browser_service.reset_runtime_progress()
    browser_service._set_progress(
        "browser",
        "Downloading Chromium…",
        percent=55.0,
        detail="55% of 104.1 MiB",
    )

    try:
        preparing = window.describe()["preparing"]

        assert preparing is not None
        assert preparing["phase"] == "browser"
        assert preparing["percent"] == 55.0
        assert preparing["message"] == "Downloading Chromium…"
        assert preparing["detail"] == "55% of 104.1 MiB"
        assert preparing["elapsed"] >= 0
    finally:
        browser_service.reset_runtime_progress()


def test_a_window_that_already_has_the_runtime_says_it_is_starting() -> None:
    from app.services import browser as browser_service

    window = _window("remote")
    window.running = True
    browser_service.reset_runtime_progress()

    preparing = window.describe()["preparing"]

    assert preparing is not None
    assert preparing["phase"] == "starting"
    assert preparing["percent"] is None


def test_a_ready_window_no_longer_reports_preparation() -> None:
    window = _window("remote")
    window.running = True
    window.preparing = False

    assert window.describe()["preparing"] is None


# ---------------------------------------------------------------------------
# Input mapping
# ---------------------------------------------------------------------------


class _FakeMouse:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def move(self, x: float, y: float) -> None:
        self.calls.append(("move", x, y))

    def down(self, *, button: str) -> None:
        self.calls.append(("down", button))

    def up(self, *, button: str) -> None:
        self.calls.append(("up", button))

    def click(self, x: float, y: float, *, button: str, click_count: int) -> None:
        self.calls.append(("click", x, y, button, click_count))

    def wheel(self, dx: float, dy: float) -> None:
        self.calls.append(("wheel", dx, dy))


class _FakeKeyboard:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def down(self, key: str) -> None:
        self.calls.append(("down", key))

    def up(self, key: str) -> None:
        self.calls.append(("up", key))

    def insert_text(self, text: str) -> None:
        self.calls.append(("text", text))


class _FakeStreamPage:
    def __init__(self) -> None:
        self.mouse = _FakeMouse()
        self.keyboard = _FakeKeyboard()
        self.tabs: list[str] = []

    def go_back(self) -> None:
        self.tabs.append("back")

    def go_forward(self) -> None:
        self.tabs.append("forward")

    def reload(self) -> None:
        self.tabs.append("reload")


def test_pointer_and_keyboard_events_are_mapped_to_playwright() -> None:
    window = _window("remote")
    page = _FakeStreamPage()

    window._dispatch_input(page, {"type": "mouse", "action": "move", "x": 10, "y": 20})
    window._dispatch_input(page, {"type": "mouse", "action": "click", "x": 99999, "y": -5})
    window._dispatch_input(page, {"type": "mouse", "action": "wheel", "dx": 0, "dy": 120})
    window._dispatch_input(
        page,
        {"type": "key", "action": "down", "key": "a", "modifiers": ["Control"]},
    )
    window._dispatch_input(
        page,
        {"type": "key", "action": "up", "key": "a", "modifiers": ["Control"]},
    )
    # Releasing Control itself must release the held modifier, even though the
    # keyup event reports no modifiers any more.
    window._dispatch_input(
        page, {"type": "key", "action": "up", "key": "Control", "modifiers": []}
    )
    window._dispatch_input(page, {"type": "text", "text": "hello"})
    window._dispatch_input(page, {"type": "navigate", "action": "back"})

    assert ("move", 10.0, 20.0) in page.mouse.calls
    # Coordinates are clamped to the configured viewport.
    assert ("click", 1279.0, 0.0, "left", 1) in page.mouse.calls
    assert ("wheel", 0.0, 120.0) in page.mouse.calls
    assert page.keyboard.calls == [
        ("down", "Control"),
        ("down", "a"),
        ("up", "a"),
        ("up", "Control"),
        ("text", "hello"),
    ]
    assert page.tabs == ["back"]


def test_an_unknown_event_is_ignored() -> None:
    window = _window("remote")
    page = _FakeStreamPage()

    window._dispatch_input(page, {"type": "something-else"})
    window._dispatch_input(page, {"type": "text", "text": ""})

    assert page.mouse.calls == []
    assert page.keyboard.calls == []


# ---------------------------------------------------------------------------
# HTTP and WebSocket routes
# ---------------------------------------------------------------------------


def _project(client: TestClient) -> dict:
    response = client.post(
        f"{API}/projects",
        json={"name": "Stream project", "target_website": "https://stream.example"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _add_website(client: TestClient, project_id: str, url: str) -> dict:
    response = client.post(
        f"{API}/projects/{project_id}/campaign/websites", json={"text": url}
    )
    assert response.status_code == 200, response.text
    return response.json()["results"][0]


def test_the_site_login_route_passes_the_requested_view(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(authenticated_client)
    added = _add_website(authenticated_client, project["id"], "https://dir.example/add")
    captured: dict[str, Any] = {}

    monkeypatch.setattr(login_browser, "available", lambda: True)

    def fake_start(_project_id: str, _url: str, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"running": True, "view": kwargs.get("view") or "native"}

    monkeypatch.setattr(login_browser, "start", fake_start)

    response = authenticated_client.post(
        f"{API}/projects/{project['id']}/login/sites/{added['website_id']}",
        json={"view": "remote"},
    )

    assert response.status_code == 200, response.text
    assert captured["view"] == "remote"
    assert captured["mode"] == "site"


def test_the_login_detail_exposes_the_live_surface(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(authenticated_client)
    monkeypatch.setattr(
        login_browser,
        "describe_window",
        lambda _project_id: {
            "running": True,
            "view": "remote",
            "headless": False,
            "warning": "headless warning",
            "stream_available": True,
        },
    )

    response = authenticated_client.get(f"{API}/projects/{project['id']}/login")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["view"] == "remote"
    assert body["stream_available"] is True
    assert body["warning"] == "headless warning"


def test_a_ticket_needs_an_open_streaming_window(
    authenticated_client: TestClient,
) -> None:
    project = _project(authenticated_client)

    response = authenticated_client.post(
        f"{API}/projects/{project['id']}/login/stream-ticket"
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "login_window_closed"


def test_a_native_window_cannot_issue_a_stream_ticket(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(authenticated_client)
    monkeypatch.setattr(
        login_browser,
        "describe_window",
        lambda _project_id: {"running": True, "view": "native"},
    )

    response = authenticated_client.post(
        f"{API}/projects/{project['id']}/login/stream-ticket"
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "stream_not_available"


def test_the_ticket_route_returns_a_websocket_path(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(authenticated_client)
    monkeypatch.setattr(
        login_browser,
        "describe_window",
        lambda _project_id: {"running": True, "view": "remote"},
    )

    response = authenticated_client.post(
        f"{API}/projects/{project['id']}/login/stream-ticket"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ticket"]
    assert body["expires_in"] > 0
    assert body["ws_path"] == f"{API}/projects/{project['id']}/login/stream"
    # The long lived session token is never part of the stream URL.
    assert "access_token" not in body["ws_path"]


def test_a_websocket_without_a_valid_ticket_is_closed(
    authenticated_client: TestClient,
) -> None:
    project = _project(authenticated_client)

    with pytest.raises(WebSocketDisconnect) as error:
        with authenticated_client.websocket_connect(
            f"{API}/projects/{project['id']}/login/stream?ticket=nope"
        ):
            pass

    assert error.value.code == 4401


def test_the_websocket_streams_frames_and_forwards_input(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(authenticated_client)

    class _FakeView:
        width = 800
        height = 600
        closed = False

        def __init__(self) -> None:
            self.inputs: list[dict[str, Any]] = []

        def latest(self) -> tuple[int, bytes]:
            return 1, b"jpeg"

        def push_input(self, event: dict[str, Any]) -> bool:
            self.inputs.append(event)
            return True

    view = _FakeView()
    monkeypatch.setattr(login_stream, "redeem_ticket", lambda *_a, **_k: "user-1")
    monkeypatch.setattr(login_browser, "remote_view", lambda _project_id: view)
    monkeypatch.setattr(
        login_browser,
        "describe_window",
        lambda _project_id: {
            "running": True,
            "view": "remote",
            "headless": False,
            "warning": None,
        },
    )

    with authenticated_client.websocket_connect(
        f"{API}/projects/{project['id']}/login/stream?ticket=ok"
    ) as socket:
        ready = socket.receive_json()
        assert ready["type"] == "ready"
        assert (ready["width"], ready["height"]) == (800, 600)

        frame = socket.receive_json()
        assert frame["type"] == "frame"
        assert socket.receive_bytes() == b"jpeg"

        socket.send_json({"type": "text", "text": "hello"})
        deadline = time.time() + 2
        while not view.inputs and time.time() < deadline:
            time.sleep(0.02)
        assert view.inputs == [{"type": "text", "text": "hello"}]

        view.closed = True
        closed = socket.receive_json()
        assert closed["type"] == "closed"
