"""The visible login window of a project.

A Google login cannot be completed by an automation without the operator:
passwords, two factor codes and account choosers are human decisions.  This
module therefore opens a **real, visible Chromium window** with the isolated
profile of the project, lets the operator sign in, and exports the resulting
session as an encrypted ``storage_state``.  The same window is reused for a
single directory that asks for a login.
"""

from __future__ import annotations

import re
import threading
import time
from contextlib import suppress
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import session_scope
from app.services import project_login
from app.services.browser import ISOLATION_ARGS, ensure_playwright_path

log = get_logger(__name__)

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_WINDOWS: dict[str, LoginWindow] = {}
_LOCK = threading.Lock()


def is_open(project_id: str) -> bool:
    with _LOCK:
        window = _WINDOWS.get(project_id)
        return window is not None and window.running


def start(
    project_id: str,
    start_url: str,
    *,
    mode: str = "google",
    website_id: str | None = None,
    email_hint: str | None = None,
) -> dict[str, Any]:
    """Open the visible browser window of a project (idempotent)."""
    with _LOCK:
        existing = _WINDOWS.get(project_id)
        if existing is not None and existing.running:
            if mode == "site" and website_id and existing.website_id != website_id:
                existing.stop_event.set()
                existing.done.wait(10)
            else:
                return existing.describe()
        window = LoginWindow(
            project_id,
            start_url,
            mode=mode,
            website_id=website_id,
            email_hint=email_hint,
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
    window.done.wait(20)
    return {
        "running": window.running,
        "saved": window.saved and save,
        "resumed": window.resumed,
        "status": window.final_status,
        "mode": window.mode,
        "website_id": window.website_id,
        "message": window.final_message,
    }


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


class LoginWindow:
    """One visible Chromium window with the profile of a project."""

    def __init__(
        self,
        project_id: str,
        start_url: str,
        *,
        mode: str,
        website_id: str | None,
        email_hint: str | None,
    ) -> None:
        self.project_id = project_id
        self.start_url = start_url
        self.mode = mode
        self.website_id = website_id
        self.email_hint = (email_hint or "").strip() or None
        self.stop_event = threading.Event()
        self.done = threading.Event()
        self.running = False
        self.saved = False
        self.resumed = 0
        self.save_on_exit = True
        self.final_status = project_login.STATUS_LOGIN_OPEN
        self.final_message = "The login window is open."
        self._thread: threading.Thread | None = None
        self._last_check = 0.0
        self._connected_once = False
        self.explicit_finish = False
        # The Google cookies the profile already had when the window opened.
        # Only a *different* set proves that the operator signed in.
        self._google_fingerprint: str | None = None
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
            "website_id": self.website_id,
            "status": self.final_status,
            "message": self.final_message,
        }

    # -- browser workflow ---------------------------------------------
    def _run(self) -> None:
        context = None
        try:
            ensure_playwright_path()
            from playwright.sync_api import sync_playwright

            with session_scope() as db:
                # Do not overwrite the last real status (CONNECTED / EXPIRED):
                # the open window is derived from `is_open`, so a crash or a
                # cancel can never leave the project stuck on "window open".
                project_login.get_profile(db, self.project_id, create=True)
            directory = project_login.ensure_profile_dir(self.project_id)
            with sync_playwright() as playwright:
                launch_kwargs: dict[str, Any] = {
                    "user_data_dir": str(directory),
                    "headless": False,
                    "args": list(ISOLATION_ARGS),
                    "viewport": {"width": 1280, "height": 900},
                    "accept_downloads": False,
                }
                try:
                    # The real Google Chrome handles a Google sign-in much more
                    # reliably than Playwright's Chromium build.  It still uses
                    # the isolated profile of this project, never the personal
                    # profile of the user.
                    context = playwright.chromium.launch_persistent_context(
                        channel="chrome", **launch_kwargs
                    )
                except Exception:
                    context = playwright.chromium.launch_persistent_context(
                        **launch_kwargs
                    )
                page = context.pages[0] if context.pages else context.new_page()
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

                if self.mode == "google":
                    # Remember the cookies the profile already had.  Only a
                    # different set means the operator really signed in.
                    self._prime_google_baseline(context)

                while not self.stop_event.is_set():
                    if self._all_pages_closed(context):
                        break
                    self._inspect(context, page)
                    self.stop_event.wait(1.0)

                self._save(context)
        except Exception as exc:  # pragma: no cover - depends on the desktop
            log.exception("login window failed")
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
            with suppress(Exception):
                if context is not None:
                    context.close()
            self.running = False
            self.done.set()

    def _prime_google_baseline(self, context: Any) -> None:
        try:
            cookies = context.cookies()
        except Exception:  # pragma: no cover - navigation in progress
            return
        self._google_fingerprint = project_login.google_cookie_fingerprint(cookies)

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
            fingerprint = project_login.google_cookie_fingerprint(cookies)
            if self._google_fingerprint is None:
                # First look: this is the state the profile already had.  It
                # may be an expired session, so it is never a login by itself.
                self._google_fingerprint = fingerprint
                return
            if fingerprint == self._google_fingerprint:
                # Nothing changed since the window opened: the old cookies are
                # still there.  Do not claim a login and do not wake the queue.
                return
            email = self._detect_google_email(context) or self.email_hint
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
                    email=email,
                )
                # The login is real: queue the work that stopped at a wall
                # immediately, without waiting for the operator to close the
                # window.
                self.resumed = project_login.resume_login_paused_tasks(
                    db, self.project_id
                )
            self.saved = True
            self._connected_once = True
            self._google_fingerprint = fingerprint
            self.final_status = project_login.STATUS_CONNECTED
            self.final_message = (
                f"Google is connected. {self.resumed} paused website(s) queued again."
                if self.resumed
                else "Google is connected."
            )
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
            pages = [item for item in context.pages if not item.is_closed()]
        except Exception:  # pragma: no cover - closed page
            pages = [fallback]
        return pages[-1] if pages else fallback

    def _detect_google_email(self, context: Any) -> str | None:
        """Best effort: read the signed-in address from Google's account list."""
        page = None
        try:
            page = context.new_page()
            page.goto(
                "https://accounts.google.com/ListAccounts"
                "?gpsia=1&source=ChromiumBrowser&json=standard",
                wait_until="domcontentloaded",
                timeout=15_000,
            )
            text = str(page.locator("body").inner_text() or "")
            match = _EMAIL.search(text)
            return match.group(0) if match else None
        except Exception:  # pragma: no cover - Google markup changes
            return None
        finally:
            with suppress(Exception):
                if page is not None:
                    page.close()

    def _all_pages_closed(self, context: Any) -> bool:
        try:
            pages = context.pages
        except Exception:  # pragma: no cover - browser gone
            return True
        return bool(pages) and all(page.is_closed() for page in pages)

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
        if not project_login.google_session_present(cookies):
            if not self._connected_once:
                with session_scope() as db:
                    row = project_login.get_profile(db, self.project_id)
                    has_session = bool(row and row.storage_state_encrypted)
                    self.final_status = (
                        project_login.STATUS_EXPIRED
                        if has_session
                        else project_login.STATUS_NOT_CONNECTED
                    )
                    project_login.set_status(
                        db,
                        self.project_id,
                        self.final_status,
                        error="No Google session was found in the login window.",
                    )
            else:
                self.final_status = project_login.STATUS_CONNECTED
            self.final_message = (
                "No Google session was found. The project still needs a login."
            )
            return

        fingerprint = project_login.google_cookie_fingerprint(cookies)
        if self._connected_once:
            new_login = True
        elif self._google_fingerprint is None:
            # The baseline could not be read; only an explicit Finish may claim
            # a login in that unusual case.
            new_login = self.explicit_finish
        else:
            # A real sign-in makes Google rotate its session cookies.  Pressing
            # Finish on unchanged cookies is not a login.
            new_login = fingerprint != self._google_fingerprint
        if not new_login:
            with session_scope() as db:
                row = project_login.get_profile(db, self.project_id)
                has_session = bool(row and row.storage_state_encrypted)
                self.final_status = (
                    project_login.STATUS_EXPIRED
                    if has_session
                    else project_login.STATUS_NOT_CONNECTED
                )
                project_login.set_status(
                    db,
                    self.project_id,
                    self.final_status,
                    error="No new Google sign-in was detected.",
                )
            self.final_message = (
                "No new Google sign-in was detected. Sign in once, then press "
                "Finish again."
            )
            return

        with session_scope() as db:
            try:
                project_login.save_storage_state(db, self.project_id, state)
            except project_login.LoginStateConflict:
                db.rollback()
            email = self._detect_google_email(context) or self.email_hint
            project_login.set_status(
                db,
                self.project_id,
                project_login.STATUS_CONNECTED,
                email=email,
            )
            self.resumed = project_login.resume_login_paused_tasks(
                db, self.project_id
            )
        self.saved = True
        self._google_fingerprint = fingerprint
        self.final_status = project_login.STATUS_CONNECTED
        self.final_message = (
            f"Google is connected. {self.resumed} paused website(s) queued again."
            if self.resumed
            else "Google is connected."
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


def _safe_url(page: Any) -> str:
    try:
        return str(page.url or "")
    except Exception:  # pragma: no cover - closed page
        return ""


def login_start_url(project_id: str) -> str:
    """The page the Google window opens on."""
    del project_id
    return "https://accounts.google.com/"


def available() -> bool:
    """Whether a visible browser can be opened in this installation."""
    return settings.allow_browser_automation
