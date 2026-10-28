"""The visible login window of a project.

A Google login cannot be completed by an automation without the operator:
passwords, two factor codes and account choosers are human decisions.  This
module therefore opens a **real, visible Chromium window** with the isolated
profile of the project, lets the operator sign in, and exports the resulting
session as an encrypted ``storage_state``.  The same window is reused for a
single directory that asks for a login.

The window is *native* when the backend runs on the machine of the operator
(the desktop app).  A web client, or a desktop app that talks to a hosted
backend, cannot see that window; in that case the same browser is **streamed**
over the WebSocket of :mod:`app.services.login_stream`.  Both paths run the
same browser, the same profile and the same detection code - only the surface
differs.
"""

from __future__ import annotations

import base64
import http.client
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import session_scope
from app.services import browser as browser_service
from app.services import login_stream, project_login
from app.services.browser import ISOLATION_ARGS, ensure_playwright_path

log = get_logger(__name__)

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Google answers this endpoint with the accounts of the browser session (and
# with an error page when there is none).  It is the only reliable way to tell
# a live session from the stale cookies an expired profile keeps.
_GOOGLE_ACCOUNTS_URL = (
    "https://accounts.google.com/ListAccounts"
    "?gpsia=1&source=ChromiumBrowser&json=standard"
)
_GOOGLE_ACCOUNT_PAGE = "https://myaccount.google.com/"
# A signed-out visitor is redirected to this landing page instead of the
# account page.
_GOOGLE_SIGNED_OUT_PATHS = {"/intro"}
# The public "what is a Google Account" landing page a signed-out browser is
# sent to instead of the account page.
_GOOGLE_SIGNED_OUT_LANDING = "/account/about"
_GOOGLE_PROBE_INTERVAL = 12.0
_GOOGLE_PROBE_TIMEOUT_MS = 6_000
_WINDOWS: dict[str, LoginWindow] = {}
_LOCK = threading.Lock()

_VIEWS = ("auto", "native", "remote")

HEADLESS_WARNING = (
    "The login browser runs headless because this backend has no display. "
    "Google may refuse a sign-in from a headless browser. Install Xvfb and "
    "Google Chrome on the server (the app starts Xvfb automatically) for a "
    "reliable login."
)

_XVFB_PROC: subprocess.Popen | None = None
_XVFB_LOCK = threading.Lock()


def is_open(project_id: str) -> bool:
    with _LOCK:
        window = _WINDOWS.get(project_id)
        return window is not None and window.running


def remote_view(project_id: str) -> login_stream.RemoteView | None:
    """The stream of an open login window, or ``None``."""
    with _LOCK:
        window = _WINDOWS.get(project_id)
    if window is None or not window.running or window.view != "remote":
        return None
    return window.remote


def describe_window(project_id: str) -> dict[str, Any]:
    """The state of the window of a project (also when it is closed)."""
    with _LOCK:
        window = _WINDOWS.get(project_id)
    if window is None:
        return {
            "project_id": project_id,
            "running": False,
            "view": None,
            "stream_available": False,
        }
    return window.describe()


def start(
    project_id: str,
    start_url: str,
    *,
    mode: str = "google",
    website_id: str | None = None,
    email_hint: str | None = None,
    view: str | None = None,
) -> dict[str, Any]:
    """Open the login browser of a project (idempotent).

    ``view`` is ``native``, ``remote`` or ``auto`` (the default).  An already
    open native window is switched to streaming when a remote client asks for
    it, so web and desktop can share one window instead of fighting over it.
    """
    requested = _normalise_view(view)
    with _LOCK:
        existing = _WINDOWS.get(project_id)
        if existing is not None and existing.running:
            if mode == "site" and website_id and existing.website_id != website_id:
                existing.stop_event.set()
                existing.done.wait(10)
            else:
                if requested == "remote" and existing.view == "native":
                    existing.request_stream()
                return existing.describe()
        window = LoginWindow(
            project_id,
            start_url,
            mode=mode,
            website_id=website_id,
            email_hint=email_hint,
            view=requested,
        )
        _WINDOWS[project_id] = window
    window.start()
    return window.describe()


def finish(
    project_id: str,
    *,
    save: bool = True,
    expect_mode: str | None = None,
    expect_website: str | None = None,
) -> dict[str, Any]:
    """Ask the window to save its session and close.

    ``expect_mode`` / ``expect_website`` bind the request to the window type it
    belongs to, so a row's "Save login" can never save an unrelated Google
    window (and the UI never reports the wrong login as saved).
    """
    with _LOCK:
        window = _WINDOWS.get(project_id)
    if window is None:
        return {"running": False, "saved": False, "message": "No login window is open."}
    if expect_mode and window.mode != expect_mode:
        return {
            "running": window.running,
            "saved": False,
            "mode": window.mode,
            "website_id": window.website_id,
            "message": "A different login window is open for this project.",
        }
    if expect_website and window.website_id != expect_website:
        return {
            "running": window.running,
            "saved": False,
            "mode": window.mode,
            "website_id": window.website_id,
            "message": "A login window for a different website is open.",
        }
    window.explicit_finish = True
    if not save:
        window.save_on_exit = False
    window.stop_event.set()
    finished = window.done.wait(20)
    result = {
        "running": window.running,
        "saved": window.saved and save,
        "resumed": window.resumed,
        "status": window.final_status,
        "mode": window.mode,
        "view": window.view,
        "website_id": window.website_id,
        "message": window.final_message,
    }
    if not finished:
        # Never leave the caller with the stale "window is open" text: the save
        # is still running, and the card polls until it lands.
        result["message"] = (
            "The login window is taking longer than expected to save. The status "
            "updates automatically as soon as the session is stored."
        )
    return result


def cancel(project_id: str) -> dict[str, Any]:
    """Close the window without saving a new session."""
    with _LOCK:
        window = _WINDOWS.get(project_id)
    if window is None:
        return {"running": False, "saved": False, "message": "No login window is open."}
    window.save_on_exit = False
    window.stop_event.set()
    window.done.wait(20)
    with _LOCK:
        _WINDOWS.pop(project_id, None)
    return {"running": False, "saved": False, "message": "Login window closed."}


def close(project_id: str) -> None:
    """Close a window before its project (and profile) is removed."""
    cancel(project_id)
    with _LOCK:
        _WINDOWS.pop(project_id, None)


def forget(project_id: str) -> None:
    """Close the window and remove the stored profile of the project."""
    cancel(project_id)
    with session_scope() as db:
        project_login.clear_profile(db, project_id, delete_files=True)
    with _LOCK:
        _WINDOWS.pop(project_id, None)


def _normalise_view(view: str | None) -> str:
    value = (view or settings.login_view_mode or "auto").strip().lower()
    return value if value in _VIEWS else "auto"


def display_available() -> bool:
    """Whether a native window can be shown on this machine."""
    if sys.platform.startswith("linux"):
        return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    return sys.platform in ("darwin", "win32")


def _xvfb_display() -> str:
    return os.environ.get("AUTOBL_XVFB_DISPLAY", ":99").strip() or ":99"


def ensure_display() -> bool:
    """Make a display available, starting Xvfb on a headless Linux host.

    A headed Chrome is much more likely to pass a Google sign-in than a
    headless one, so a cloud backend starts a virtual framebuffer when the
    binary is installed.  When Xvfb is missing the caller falls back to a
    headless browser and says so in the UI.
    """
    if display_available():
        return True
    if not sys.platform.startswith("linux"):
        return False
    global _XVFB_PROC
    with _XVFB_LOCK:
        if _XVFB_PROC is not None and _XVFB_PROC.poll() is None:
            os.environ.setdefault("DISPLAY", _xvfb_display())
            return True
        binary = shutil.which("Xvfb")
        if not binary:
            return False
        display = _xvfb_display()
        try:
            proc = subprocess.Popen(  # noqa: S603 - fixed binary from PATH
                [binary, display, "-screen", "0", "1280x900x24", "-nolisten", "tcp"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            return False
        number = display.lstrip(":").split(".")[0]
        socket_path = Path("/tmp/.X11-unix") / f"X{number}"  # noqa: S108 - X11 socket path
        deadline = time.time() + 3.0
        while time.time() < deadline:
            if proc.poll() is not None:
                return False
            if socket_path.exists():
                break
            time.sleep(0.1)
        if proc.poll() is not None:
            return False
        os.environ["DISPLAY"] = display
        _XVFB_PROC = proc
        log.info("started Xvfb for the login window", extra={"extra_fields": {"display": display}})
        return True


class LoginWindow:
    """One Chromium window with the profile of a project."""

    def __init__(
        self,
        project_id: str,
        start_url: str,
        *,
        mode: str,
        website_id: str | None,
        email_hint: str | None,
        view: str = "auto",
    ) -> None:
        self.project_id = project_id
        self.start_url = start_url
        self.mode = mode
        self.website_id = website_id
        self.email_hint = (email_hint or "").strip() or None
        self.requested_view = _normalise_view(view)
        self.view = "native"
        self.headless = False
        self.warning: str | None = None
        self.view, self.warning = self._choose_view()
        self.remote = login_stream.RemoteView(
            width=settings.login_stream_width,
            height=settings.login_stream_height,
        )
        self.stop_event = threading.Event()
        self.done = threading.Event()
        self.running = False
        # A fresh window is not usable until the runtime is installed and the
        # browser has navigated.  The flag lets the UI show *what* is happening
        # (and how far the download is) instead of a silent wait.
        self.preparing = True
        self.preparing_started = time.monotonic()
        self.saved = False
        self.resumed = 0
        self.save_on_exit = True
        self.final_status = project_login.STATUS_LOGIN_OPEN
        self.final_message = "Preparing the login browser…"
        self._thread: threading.Thread | None = None
        self._context: Any = None
        self._cdp: Any = None
        self._stream_page: Any = None
        # Chrome is started by us (not by Playwright) for a visible login, so
        # its process has to be stopped again when the window closes.
        self._chrome_process: subprocess.Popen[bytes] | None = None
        self._held_modifiers: set[str] = set()
        self._last_check = 0.0
        self._connected_once = False
        self.explicit_finish = False
        # The last answer of Google about the session of this profile, and
        # when it was asked.  Cookies alone cannot prove a working login: an
        # expired profile keeps the old ones.
        self._google_probe_result: tuple[bool | None, str | None] | None = None
        self._google_probe_at = 0.0
        # One spare tab is reused for the Google liveness check, so the check
        # never steals the focus of the tab the operator is working in.
        self._probe_page: Any = None
        # A website is only "connected" when its login wall was really seen
        # and then disappeared - a public page is not a login.
        self._saw_wall = False

    # -- lifecycle ----------------------------------------------------
    def start(self) -> None:
        self.running = True
        self._thread = threading.Thread(
            target=self._run, name=f"login-{self.project_id}", daemon=True
        )
        self._thread.start()

    def describe(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "running": self.running,
            "mode": self.mode,
            "view": self.view,
            "headless": self.headless,
            "warning": self.warning,
            "stream_available": bool(self.running and self.view == "remote"),
            "website_id": self.website_id,
            "status": self.final_status,
            "message": self.final_message,
            "preparing": self._preparing_state(),
        }

    def _preparing_state(self) -> dict[str, Any] | None:
        """The progress of the first run, in a shape the UI can render.

        The runtime installer publishes ``phase`` / ``percent`` / ``message``.
        While the browser itself is starting (or when the runtime was already
        installed by an earlier session) there is no download to report, so the
        window tells the UI which step is running now.
        """
        if not self.running or not self.preparing:
            return None
        snapshot = browser_service.runtime_progress()
        phase = str(snapshot.get("phase") or "idle")
        percent = snapshot.get("percent")
        detail = snapshot.get("detail")
        if phase in ("package", "browser"):
            message = str(snapshot.get("message") or "Preparing the login browser…")
        elif phase == "done":
            message = str(
                snapshot.get("message")
                or "The browser is ready. Opening the login window…"
            )
            percent = 100
            detail = None
        else:
            # ``idle`` means this installation already has the runtime.  An
            # old ``error`` belongs to a previous attempt, not to this window.
            phase = "starting"
            message = "Starting the login browser…"
            percent = None
            detail = None
        return {
            "phase": phase,
            "percent": percent,
            "message": message,
            "detail": detail,
            "elapsed": round(time.monotonic() - self.preparing_started, 1),
        }

    def request_stream(self) -> None:
        """Serve the already open native window over the WebSocket as well."""
        if self.view == "native":
            self.view = "remote"
            log.info(
                "login window switched to streaming",
                extra={"extra_fields": {"project_id": self.project_id}},
            )

    # -- runtime selection -------------------------------------------
    def _choose_view(self) -> tuple[str, str | None]:
        """The surface without starting Xvfb (safe to call from the request)."""
        requested = self.requested_view
        if requested == "native":
            if display_available():
                return "native", None
            return (
                "remote",
                "This backend has no display, so the login window is streamed "
                "to this page instead of opening a native window.",
            )
        if (
            requested == "auto"
            and display_available()
            and settings.environment in ("local", "desktop")
        ):
            return "native", None
        return "remote", None

    def _plan_view(self) -> None:
        self.view, self.warning = self._choose_view()
        self.headless = False
        if self.view == "remote" and not ensure_display():
            self.headless = True
            self.warning = HEADLESS_WARNING

    # -- browser workflow ---------------------------------------------
    def _run(self) -> None:
        context = None
        try:
            sync_playwright = _load_sync_playwright(self)
            if self.stop_event.is_set():
                # The operator cancelled while the runtime was being installed;
                # do not open a browser nobody is waiting for.
                self.final_message = "Login window closed before the browser was ready."
                self._settle_status()
                return

            with session_scope() as db:
                # Do not overwrite the last real status (CONNECTED / EXPIRED):
                # the open window is derived from `is_open`, so a crash or a
                # cancel can never leave the project stuck on "window open".
                project_login.get_profile(db, self.project_id, create=True)
            directory = project_login.ensure_profile_dir(self.project_id)
            self._plan_view()
            with sync_playwright() as playwright:
                context = self._launch(playwright, directory)
                self._context = context
                page = context.pages[0] if context.pages else context.new_page()
                if self.view == "remote":
                    # Stream before the first navigation, so a slow start page
                    # never leaves the viewer on a black screen.
                    self._attach_stream(context, page)
                try:
                    page.goto(
                        self.start_url,
                        wait_until="domcontentloaded",
                        timeout=45_000,
                    )
                except Exception as exc:
                    # A slow page is not a fatal error - the operator can still
                    # navigate in the window.
                    log.info(
                        "login window navigation was slow",
                        extra={"extra_fields": {"url": self.start_url, "error": str(exc)}},
                    )

                # The window now exists and has navigated: from here on the
                # operator works in the browser, not in a preparation screen.
                self.preparing = False
                self.final_message = "The login window is open."

                if self.mode == "google":
                    # A background tab is kept for the liveness checks, and the
                    # tab of the operator is put back in front, so no check ever
                    # steals the focus while a password is being typed.
                    with suppress(Exception):
                        self._probe_page = context.new_page()
                        page.bring_to_front()

                while not self.stop_event.is_set():
                    if self._all_pages_closed(context):
                        break
                    self._inspect(context, page)
                    if self.view == "remote":
                        self._stream_tick(context, page)
                    else:
                        self.stop_event.wait(1.0)

                self._save(context)
        except Exception as exc:  # pragma: no cover - depends on the desktop
            log.exception("login window failed")
            self.preparing = False
            self.final_status = project_login.STATUS_ERROR
            self.final_message = f"The login window could not be opened: {exc}"
            with session_scope() as db:
                project_login.set_status(
                    db,
                    self.project_id,
                    project_login.STATUS_ERROR,
                    error=self.final_message,
                )
        finally:
            self.preparing = False
            self._detach_stream()
            with suppress(Exception):
                self.remote.close()
            self._context = None
            with suppress(Exception):
                if context is not None:
                    context.close()
            self._stop_chrome()
            self.running = False
            self.done.set()

    def _launch(self, playwright: Any, directory: Path) -> Any:
        if not self.headless:
            try:
                return self._launch_unflagged_chrome(playwright, directory)
            except Exception:
                # No desktop Chrome, an old version, or Chrome refused to
                # start: fall back to the Playwright managed browser (which
                # Google may refuse for a sign-in - the warning is honest).
                log.warning(
                    "could not start Chrome without automation flags; "
                    "falling back to the Playwright browser",
                    exc_info=True,
                )
                self._stop_chrome()

        launch_kwargs: dict[str, Any] = {
            "user_data_dir": str(directory),
            "headless": self.headless,
            "args": list(ISOLATION_ARGS),
            "viewport": {
                "width": settings.login_stream_width,
                "height": settings.login_stream_height,
            },
            "accept_downloads": False,
        }

        def launch(**extra: Any) -> Any:
            return playwright.chromium.launch_persistent_context(**launch_kwargs, **extra)

        try:
            # The real Google Chrome handles a Google sign-in much more
            # reliably than Playwright's Chromium build.  It still uses the
            # isolated profile of this project, never the personal profile of
            # the user.
            return launch(channel="chrome")
        except Exception:
            try:
                return launch()
            except Exception:
                if self.view != "remote" or self.headless:
                    raise
                # A headed launch failed on this host: stream a headless
                # browser rather than leaving a remote client without a view.
                log.warning("headed login browser unavailable; using headless", exc_info=True)
                self.headless = True
                self.warning = HEADLESS_WARNING
                launch_kwargs["headless"] = True
                return launch()

    def _launch_unflagged_chrome(self, playwright: Any, directory: Path) -> Any:
        """Open the real Chrome without the flags that mark it as automated.

        ``launch_persistent_context`` always passes ``--enable-automation``
        and Playwright exposes ``navigator.webdriver``.  Google refuses a
        sign-in in such a browser ("This browser or app may not be secure").
        Instead, Chrome is started as a normal application with its own
        profile and a local debugging port, and Playwright only *connects* to
        it over CDP.  The operator signs in manually; the session is still
        exported from the same profile.
        """
        context, process = launch_unflagged_chrome(
            playwright,
            directory,
            project_id=self.project_id,
        )
        self._chrome_process = process
        return context

    @staticmethod
    def _clear_stale_profile_lock(directory: Path) -> None:
        """Remove the lock of a Chrome that crashed (only our own profile)."""
        clear_stale_profile_lock(directory)

    def _stop_chrome(self) -> None:
        process = self._chrome_process
        self._chrome_process = None
        if process is None:
            return
        if os.name == "posix":
            # Chrome starts helpers in the same process group; killing only the
            # parent could leave a locked profile behind.
            with suppress(Exception):
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        with suppress(Exception):
            process.terminate()
            process.wait(10)
        if process.poll() is None:
            if os.name == "posix":
                with suppress(Exception):
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            with suppress(Exception):
                process.kill()


    # -- streaming ----------------------------------------------------
    def _stream_tick(self, context: Any, fallback: Any) -> None:
        current = self._current_page(context, fallback)
        if current is not None and current is not self._stream_page:
            self._attach_stream(context, current)
        self._dispatch_inputs(current)
        # Pump the Playwright event loop so the screencast frames are
        # delivered.  A Python `Event.wait` would not run it.
        try:
            current.wait_for_timeout(self._frame_interval_ms())
        except Exception:  # pragma: no cover - page closed while streaming
            self.stop_event.wait(self._frame_interval_ms() / 1000)

    def _frame_interval_ms(self) -> float:
        fps = max(1, min(30, int(settings.login_stream_fps or 10)))
        return max(30, round(1000 / fps))

    def _attach_stream(self, context: Any, page: Any) -> None:
        self._detach_stream()
        if page is None:
            return
        try:
            cdp = context.new_cdp_session(page)
            cdp.send("Page.enable")
            cdp.send(
                "Page.startScreencast",
                {
                    "format": "jpeg",
                    "quality": max(10, min(90, int(settings.login_stream_quality or 60))),
                    "maxWidth": max(320, int(settings.login_stream_width or 1280)),
                    "maxHeight": max(240, int(settings.login_stream_height or 900)),
                    "everyNthFrame": 1,
                },
            )
            cdp.on(
                "Page.screencastFrame",
                lambda params, session=cdp: self._on_frame(session, params),
            )
        except Exception:  # pragma: no cover - depends on the browser build
            log.warning("could not start the browser stream", exc_info=True)
            # Do not retry on every tick for the same page; a page switch or a
            # reload starts a new attempt.
            self._stream_page = page
            return
        self._cdp = cdp
        self._stream_page = page

    def _detach_stream(self) -> None:
        cdp, self._cdp = self._cdp, None
        self._stream_page = None
        self._held_modifiers.clear()
        if cdp is not None:
            with suppress(Exception):
                cdp.send("Page.stopScreencast")
            with suppress(Exception):
                cdp.detach()

    def _on_frame(self, session: Any, params: dict[str, Any]) -> None:
        if session is not self._cdp:
            return
        try:
            data = base64.b64decode(params.get("data") or "")
            metadata = params.get("metadata") or {}
            self.remote.publish(
                data,
                width=metadata.get("deviceWidth"),
                height=metadata.get("deviceHeight"),
            )
        except Exception:  # pragma: no cover - malformed frame
            log.debug("ignored a malformed screencast frame", exc_info=True)
        finally:
            # Without the ack Chromium stops sending frames after the first.
            with suppress(Exception):
                session.send(
                    "Page.screencastFrameAck",
                    {"sessionId": params.get("sessionId")},
                )

    def _dispatch_inputs(self, page: Any) -> None:
        if page is None:
            return
        for event in self.remote.drain():
            try:
                self._dispatch_input(page, event)
            except Exception:  # pragma: no cover - closed page or bad event
                log.debug("ignored a login input event", exc_info=True)

    def _dispatch_input(self, page: Any, event: dict[str, Any]) -> None:
        kind = str(event.get("type") or "")
        if kind == "mouse":
            self._dispatch_mouse(page, event)
        elif kind == "key":
            self._dispatch_key(page, event)
        elif kind == "text":
            text = str(event.get("text") or "")[:2000]
            if text:
                page.keyboard.insert_text(text)
        elif kind == "navigate":
            action = str(event.get("action") or "")
            if action == "back":
                page.go_back()
            elif action == "forward":
                page.go_forward()
            elif action == "reload":
                page.reload()

    def _dispatch_mouse(self, page: Any, event: dict[str, Any]) -> None:
        width = max(1, int(settings.login_stream_width or 1280))
        height = max(1, int(settings.login_stream_height or 900))
        x = _clamp(event.get("x"), 0.0, width - 1)
        y = _clamp(event.get("y"), 0.0, height - 1)
        action = str(event.get("action") or "")
        button = str(event.get("button") or "left")
        if button not in ("left", "right", "middle"):
            button = "left"
        if action == "move":
            page.mouse.move(x, y)
        elif action == "down":
            page.mouse.move(x, y)
            page.mouse.down(button=button)
        elif action == "up":
            page.mouse.move(x, y)
            page.mouse.up(button=button)
        elif action == "click":
            count = int(event.get("click_count") or 1)
            page.mouse.click(x, y, button=button, click_count=max(1, min(3, count)))
        elif action == "wheel":
            page.mouse.wheel(_clamp(event.get("dx"), -4000.0, 4000.0), _clamp(event.get("dy"), -4000.0, 4000.0))

    def _dispatch_key(self, page: Any, event: dict[str, Any]) -> None:
        key = str(event.get("key") or "")[:40]
        if not key:
            return
        action = str(event.get("action") or "")
        modifiers = [
            value
            for value in (event.get("modifiers") or [])
            if value in ("Control", "Alt", "Meta", "Shift")
        ]
        if action == "down":
            for name in modifiers:
                if name not in self._held_modifiers:
                    page.keyboard.down(name)
                    self._held_modifiers.add(name)
            if key not in self._held_modifiers:
                page.keyboard.down(key)
        elif action == "up":
            if key not in self._held_modifiers:
                page.keyboard.up(key)
            # Reconcile the modifiers with the state the client reports, so a
            # modifier whose keyup was missed can never stay stuck down.
            pressed = set(modifiers)
            for name in ("Shift", "Meta", "Alt", "Control"):
                if name in self._held_modifiers and name not in pressed:
                    page.keyboard.up(name)
                    self._held_modifiers.discard(name)

    # -- login detection ----------------------------------------------
    def _inspect(self, context: Any, page: Any) -> None:
        """Detect a completed login and refresh the stored state."""
        if self._connected_once:
            # The session is already saved and the paused work is queued; the
            # window may stay open for the operator without repeating the work.
            return
        now = time.monotonic()
        if now - self._last_check < 3.0:
            return
        self._last_check = now
        try:
            cookies = context.cookies()
        except Exception:  # pragma: no cover - navigation in progress
            return

        if self.mode == "google":
            if not project_login.google_session_present(cookies):
                return
            # Only a live session of the *profile* counts; Google is asked
            # directly instead of guessing from the cookie list.
            alive, email = self._google_probe_cached(context)
            if not alive:
                return
            self._store_google(context, email)
            return

        if self.website_id:
            # Track the wall; a finished site login is only accepted on an
            # explicit Finish (see `_save`).  Navigating to a public page is
            # not proof that the account works.
            current = self._current_page(context, page)
            if "accounts.google.com" in _safe_url(current):
                self._saw_wall = True
                return
            try:
                if project_login.page_requires_login(current):
                    self._saw_wall = True
            except Exception:  # pragma: no cover - closed page
                return

    def _current_page(self, context: Any, fallback: Any) -> Any:
        try:
            pages = [
                item
                for item in context.pages
                if not item.is_closed() and item is not self._probe_page
            ]
        except Exception:  # pragma: no cover - closed page
            pages = [fallback]
        return pages[-1] if pages else fallback

    def _probe_tab(self, context: Any) -> Any:
        """The reusable background tab of the Google liveness check."""
        page = self._probe_page
        if page is not None:
            with suppress(Exception):
                if not page.is_closed():
                    return page
        page = context.new_page()
        self._probe_page = page
        return page

    def _google_probe(self, context: Any) -> tuple[bool | None, str | None]:
        """Ask Google whether this profile has a live signed-in session.

        The cookie list cannot answer that: an expired profile keeps the old
        cookies.  So the app opens a short lived tab in the same profile and
        reads Google's own answer.

        Returns ``(True, email)`` for a working session, ``(False, None)`` when
        Google shows its sign-in page and ``(None, None)`` when the answer could
        not be determined (network error, consent wall, captcha).
        """
        try:
            page = self._probe_tab(context)
            # The account page is the authoritative answer: Google serves it to
            # a signed-in session and redirects everybody else to a public page.
            page.goto(
                _GOOGLE_ACCOUNT_PAGE,
                wait_until="domcontentloaded",
                timeout=_GOOGLE_PROBE_TIMEOUT_MS,
            )
            url = _safe_url(page)
            host = _url_host(url)
            path = urlsplit(url).path.rstrip("/")
            if host == "myaccount.google.com":
                if path in _GOOGLE_SIGNED_OUT_PATHS:
                    # A signed-out visitor is sent to the public landing page.
                    return False, None
                # Google only serves the account page to a signed-in session.
                return True, self._google_email(page)
            if host == "accounts.google.com":
                # Google sent the account page back to the sign-in flow.
                return False, None
            if host in ("google.com", "www.google.com") and path.startswith(
                _GOOGLE_SIGNED_OUT_LANDING
            ):
                # The signed-out landing page of google.com (a browser with
                # only the advertising cookies is redirected here instead of
                # myaccount.google.com).
                return False, None
            log.info(
                "the Google session check ended on an unexpected page",
                extra={"extra_fields": {"project_id": self.project_id, "url": url}},
            )
            return None, None
        except Exception as exc:
            log.info(
                "could not verify the Google session",
                extra={
                    "extra_fields": {
                        "project_id": self.project_id,
                        "error": str(exc),
                    }
                },
            )
            return None, None

    def _google_email(self, page: Any) -> str | None:
        """The address of the signed-in account, when the page shows it."""
        # The account page is a web app: give it a moment to paint, then read
        # the visible text and the labels of the account menu.
        for _attempt in range(2):
            email = _page_email(page)
            if email:
                return email
            with suppress(Exception):
                page.wait_for_timeout(900)
        with suppress(Exception):
            labels = page.locator('[aria-label*="@"]')
            for index in range(min(labels.count(), 5)):
                match = _EMAIL.search(
                    labels.nth(index).get_attribute("aria-label") or ""
                )
                if match:
                    return match.group(0)
        # The Chrome account list is a small, plain fallback.
        with suppress(Exception):
            page.goto(
                _GOOGLE_ACCOUNTS_URL,
                wait_until="domcontentloaded",
                timeout=_GOOGLE_PROBE_TIMEOUT_MS,
            )
            return _page_email(page)
        return None

    def _google_probe_cached(
        self, context: Any, *, max_age: float = _GOOGLE_PROBE_INTERVAL
    ) -> tuple[bool | None, str | None]:
        """The last probe answer, asked again when it is older than ``max_age``."""
        now = time.monotonic()
        if (
            self._google_probe_result is not None
            and now - self._google_probe_at <= max_age
        ):
            return self._google_probe_result
        result = self._google_probe(context)
        self._google_probe_result = result
        self._google_probe_at = time.monotonic()
        log.info(
            "checked the Google session of the login window",
            extra={
                "extra_fields": {
                    "project_id": self.project_id,
                    "signed_in": result[0],
                }
            },
        )
        return result

    def _store_google(
        self, context: Any, email: str | None, *, verified: bool = True
    ) -> None:
        """Persist a session that Google confirmed (or that the operator saved)."""
        try:
            state = context.storage_state()
        except Exception:  # pragma: no cover - browser closing
            return
        with session_scope() as db:
            try:
                project_login.save_storage_state(db, self.project_id, state)
            except project_login.LoginStateConflict:
                # A newer session was stored meanwhile; that one wins.
                db.rollback()
            project_login.set_status(
                db,
                self.project_id,
                project_login.STATUS_CONNECTED,
                email=email or self.email_hint,
            )
            # The login is real: queue the work that stopped at a wall
            # immediately, without waiting for the operator to close the window.
            self.resumed = project_login.resume_login_paused_tasks(
                db, self.project_id
            )
        self.saved = True
        self._connected_once = True
        self.final_status = project_login.STATUS_CONNECTED
        if not verified:
            self.final_message = (
                "The Google session was saved, but Google could not be reached to "
                "verify it. The next task confirms it."
            )
        else:
            self.final_message = (
                f"Google is connected. {self.resumed} paused website(s) queued again."
                if self.resumed
                else "Google is connected."
            )

    def _mark_google_missing(self, message: str) -> None:
        """Store that no usable Google session exists, and say why."""
        with session_scope() as db:
            row = project_login.get_profile(db, self.project_id)
            has_session = bool(row and row.storage_state_encrypted)
            self.final_status = (
                project_login.STATUS_EXPIRED
                if has_session
                else project_login.STATUS_NOT_CONNECTED
            )
            project_login.set_status(
                db, self.project_id, self.final_status, error=message
            )
        self.final_message = message

    def _all_pages_closed(self, context: Any) -> bool:
        try:
            pages = [
                item
                for item in context.pages
                if not item.is_closed() and item is not self._probe_page
            ]
        except Exception:  # pragma: no cover - browser gone
            return True
        return not pages

    def _save(self, context: Any) -> None:
        """Persist the session of the window (unless the operator cancelled)."""
        if not self.save_on_exit:
            self.final_message = "Login window closed without saving."
            self._settle_status()
            return
        try:
            state = context.storage_state()
        except Exception:  # pragma: no cover - browser already gone
            self._settle_status()
            return
        try:
            if self.mode == "google":
                self._save_google(context, state)
            else:
                self._save_site(context, state)
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("could not save the login state")
            self.final_status = project_login.STATUS_ERROR
            self.final_message = f"The login could not be saved: {exc}"
        finally:
            self._settle_status()

    def _save_google(self, context: Any, state: dict[str, Any]) -> None:
        cookies = state.get("cookies") or []
        if self._connected_once:
            # The session was already verified and stored while the window was
            # open; keep the cookies the profile has now.
            self._store_google(context, None)
            return
        if not project_login.google_session_present(cookies):
            self._mark_google_missing(
                "No Google session was found in the login window. Sign in once, "
                "then press Finish again."
            )
            return

        # Finishing is the moment the operator says "I am done": ask Google
        # again instead of reusing an answer from just before the sign-in.
        alive, email = self._google_probe_cached(context, max_age=0.0)
        if alive:
            self._store_google(context, email)
            return
        if alive is None and self.explicit_finish:
            # Google could not be asked (blocked endpoint, consent wall): the
            # operator says the sign-in is done, so keep the session and say
            # honestly that it could not be verified.
            log.warning(
                "saving an unverified Google session",
                extra={"extra_fields": {"project_id": self.project_id}},
            )
            self._store_google(context, email, verified=False)
            return
        self._mark_google_missing(
            "Google still shows its sign-in page, so no login was saved. Sign in "
            "once, wait for your Google account page, then press Finish again."
        )

    def _save_site(self, context: Any, state: dict[str, Any]) -> None:
        current = self._current_page(context, context.pages[0] if context.pages else None)
        accepted = bool(self.website_id and self.explicit_finish and self._saw_wall)
        if accepted:
            try:
                accepted = current is not None and not project_login.page_requires_login(current)
            except Exception:  # pragma: no cover - closed page
                accepted = False
        if not accepted:
            # Nothing proved that the website login worked - say so instead of
            # claiming and saving a login.
            if self.website_id and self._saw_wall:
                with session_scope() as db:
                    project_login.mark_site(
                        db,
                        self.project_id,
                        self.website_id,
                        project_login.SITE_LOGIN_REQUIRED,
                        error="No website session was detected.",
                    )
            self.final_status = project_login.STATUS_NOT_CONNECTED
            self.final_message = (
                "No website session was detected. Sign in on the site, then "
                "press Finish again."
            )
            return

        with session_scope() as db:
            try:
                project_login.save_storage_state(db, self.project_id, state)
            except project_login.LoginStateConflict:
                db.rollback()
            # A directory login is not a Google login: store the cookies, but
            # leave the Google state of the project alone.
            project_login.mark_site(
                db,
                self.project_id,
                self.website_id,
                project_login.SITE_CONNECTED,
                method="SESSION",
                evidence={"finished": True},
            )
            self.resumed = project_login.resume_login_paused_tasks(
                db, self.project_id, website_id=self.website_id
            )
        self.saved = True
        self._connected_once = True
        self.final_status = project_login.STATUS_CONNECTED
        self.final_message = (
            f"Login saved. {self.resumed} paused website(s) queued again."
            if self.resumed
            else "Login saved."
        )

    def _settle_status(self) -> None:
        """Never report or store the transient ``LOGIN_OPEN`` after the window."""
        try:
            with session_scope() as db:
                row = project_login.get_profile(db, self.project_id)
                if row is None:
                    return
                if row.status == project_login.STATUS_LOGIN_OPEN:
                    # Legacy row: the window is gone, so report the real state.
                    row = project_login.set_status(
                        db,
                        self.project_id,
                        project_login.STATUS_CONNECTED
                        if row.storage_state_encrypted
                        else project_login.STATUS_NOT_CONNECTED,
                    )
                if self.final_status == project_login.STATUS_LOGIN_OPEN:
                    self.final_status = row.status
        except Exception:  # pragma: no cover - defensive
            log.warning("could not settle the login status")


RUNTIME_MISSING = (
    "The login browser is being prepared: the app is installing the Playwright "
    "runtime and the Chromium build into the application data directory (first "
    "run only). This can take a few minutes."
)


def _load_sync_playwright(window: Any = None) -> Any:
    """Import Playwright, installing the runtime on first use.

    The desktop bundle does not ship the Playwright package or its browser
    build (together they would add hundreds of megabytes to the installer), so
    they are installed on demand into the application data directory.  Without
    this step a fresh installation answered a login with
    ``No module named 'playwright'`` instead of opening the window.
    """
    ensure_playwright_path()
    if browser_service.runtime_ready():
        from playwright.sync_api import sync_playwright

        return sync_playwright

    if window is not None:
        window.final_message = RUNTIME_MISSING
    log.info(
        "installing the Playwright runtime for the login window",
        extra={"extra_fields": {"project_id": getattr(window, "project_id", None)}},
    )
    ok, detail = browser_service.install_runtime()
    if not ok:
        raise RuntimeError(
            "The browser runtime could not be installed. "
            f"{detail or ''}".strip()
        )
    ensure_playwright_path()
    if window is not None:
        window.final_message = "The browser is ready. Opening the login window…"
    from playwright.sync_api import sync_playwright

    return sync_playwright


def clear_stale_profile_lock(directory: Path) -> None:
    """Remove the lock files a crashed Chrome left in our own profile."""
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        with suppress(OSError):
            (directory / name).unlink()


def launch_unflagged_chrome(
    playwright: Any,
    directory: Path,
    *,
    project_id: str | None = None,
) -> tuple[Any, subprocess.Popen[bytes]]:
    """Start the installed Chrome as a normal app and attach over CDP.

    Returns ``(context, process)``.  The caller stops ``process`` (and its
    process group) when it is done.  A missing desktop Chrome raises
    :class:`RuntimeError`; the caller may then fall back to the Playwright
    managed build, which some sites (Google) refuse.
    """
    executable = browser_service.launchable_chrome()
    if executable is None:
        raise RuntimeError("Google Chrome is not installed on this machine.")
    port = _free_port()
    clear_stale_profile_lock(directory)
    arguments = [
        executable,
        f"--user-data-dir={directory}",
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        f"--window-size={settings.login_stream_width},{settings.login_stream_height}",
        "--window-position=80,60",
        # Newer Chrome builds otherwise expose `navigator.webdriver` and tell
        # Google that a tool controls the browser.
        "--disable-blink-features=AutomationControlled",
        *ISOLATION_ARGS,
    ]
    log.info(
        "starting Chrome for the login window",
        extra={"extra_fields": {"project_id": project_id, "port": port}},
    )
    process = subprocess.Popen(  # noqa: S603 - the executable is resolved above
        arguments,
        env=browser_service.isolated_environment(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    endpoint = f"http://127.0.0.1:{port}"
    deadline = time.time() + 45
    while time.time() < deadline:
        if process.poll() is not None:
            stop_browser_process(process)
            raise RuntimeError("Chrome closed while it was starting.")
        if _debugging_port_ready(port):
            break
        time.sleep(0.25)
    else:
        stop_browser_process(process)
        raise RuntimeError("Chrome did not open its debugging port.")
    try:
        browser = playwright.chromium.connect_over_cdp(endpoint)
    except Exception:
        stop_browser_process(process)
        raise
    for _ in range(60):
        if browser.contexts:
            return browser.contexts[0], process
        time.sleep(0.1)
    return browser.new_context(), process


def stop_browser_process(process: subprocess.Popen[bytes] | None) -> None:
    """Terminate a Chrome started by :func:`launch_unflagged_chrome`."""
    if process is None:
        return
    if os.name == "posix":
        # Chrome starts helpers in the same process group; killing only the
        # parent could leave a locked profile behind.
        with suppress(Exception):
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    with suppress(Exception):
        process.terminate()
        process.wait(10)
    if process.poll() is None:
        if os.name == "posix":
            with suppress(Exception):
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        with suppress(Exception):
            process.kill()


def _free_port() -> int:
    """A free loopback port for the debugging endpoint of Chrome."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _debugging_port_ready(port: int) -> bool:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
    try:
        connection.request("GET", "/json/version")
        response = connection.getresponse()
        response.read(1024)
        return response.status == 200
    except OSError:
        return False
    finally:
        connection.close()


def _clamp(value: Any, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = low
    return max(low, min(high, number))


def _safe_url(page: Any) -> str:
    try:
        return str(page.url or "")
    except Exception:  # pragma: no cover - closed page
        return ""


def _url_host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except Exception:  # pragma: no cover - malformed URL
        return ""


def _is_google_host(url: str) -> bool:
    host = _url_host(url)
    return host == "google.com" or host.endswith(".google.com")


def _page_email(page: Any) -> str | None:
    """The signed-in address in the body of a Google page, if any."""
    try:
        text = str(page.locator("body").inner_text() or "")
    except Exception:  # pragma: no cover - Google markup changes
        return None
    match = _EMAIL.search(text)
    return match.group(0) if match else None


def login_start_url(project_id: str) -> str:
    """The page the Google window opens on."""
    del project_id
    return "https://accounts.google.com/"


def available() -> bool:
    """Whether a visible browser can be opened in this installation."""
    return settings.allow_browser_automation
