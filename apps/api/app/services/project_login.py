"""Per project browser profiles and website login sessions.

The operator connects one Google account per project.  That login is kept in
the isolated profile directory of the project and exported as an encrypted
Playwright ``storage_state``.  Workers load the state for the submissions of
the project, so a directory that accepts "Continue with Google" can be entered
without typing a password again.

Nothing in this module claims a login it did not observe: a state is only
marked ``CONNECTED`` when the browser really carries a Google session (or the
operator finished a site login), and a session is marked ``EXPIRED`` when a
submission page answers with a login wall.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
from contextlib import suppress
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import decrypt, encrypt
from app.db.base import utcnow
from app.db.models import (
    Project,
    ProjectLoginProfile,
    Task,
    Website,
    WebsiteLoginSession,
)

PROFILE_ROOT = settings.managed_files_dir / "profiles"

#: The encryption key of the browser sessions of this installation.  It is a
#: local key file (owner only), so the encrypted sessions are useless when the
#: database is copied to another machine.
SESSION_KEY_FILE = settings.managed_files_dir / "login-profile.key"

STATUS_NOT_CONNECTED = "NOT_CONNECTED"
STATUS_LOGIN_OPEN = "LOGIN_OPEN"
STATUS_CONNECTED = "CONNECTED"
STATUS_EXPIRED = "EXPIRED"
STATUS_ERROR = "ERROR"

SITE_UNKNOWN = "UNKNOWN"
SITE_CONNECTED = "CONNECTED"
SITE_LOGIN_REQUIRED = "LOGIN_REQUIRED"
SITE_EXPIRED = "EXPIRED"

#: Task errors that carry this prefix are resumed after a fresh login.
LOGIN_REQUIRED_PREFIX = "LOGIN_REQUIRED:"

_GOOGLE_COOKIES = {
    "SID",
    "HSID",
    "SSID",
    "APISID",
    "SAPISID",
    "__Secure-1PSID",
    "__Secure-3PSID",
}

_LOGIN_TEXT = (
    "sign in to continue",
    "log in to continue",
    "please sign in",
    "please log in",
    "you must sign in",
    "you must be logged in",
    "login required",
    "log in required",
    "sign in required",
    "authentication required",
    "session expired",
    "create a free account to continue",
)

_LOGIN_PATH = re.compile(
    r"/(log-?in|sign-?in|signin|auth|authenticate|session|account/login)(/|$)",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------
# Profile rows
# --------------------------------------------------------------------------
def profile_dir(project_id: str) -> Path:
    """The isolated browser profile directory of one project."""
    return PROFILE_ROOT / project_id


def ensure_profile_dir(project_id: str) -> Path:
    """Create the profile directory with owner-only permissions."""
    directory = profile_dir(project_id)
    directory.mkdir(parents=True, exist_ok=True)
    with suppress(OSError):
        # Owner-only access is best effort on exotic filesystems.
        os.chmod(directory, 0o700)
    return directory


def get_profile(
    db: Session, project_id: str, *, create: bool = False
) -> ProjectLoginProfile | None:
    row = db.execute(
        select(ProjectLoginProfile).where(ProjectLoginProfile.project_id == project_id)
    ).scalar_one_or_none()
    if row is None and create:
        row = ProjectLoginProfile(
            project_id=project_id,
            provider="google",
            status=STATUS_NOT_CONNECTED,
            profile_dir=str(profile_dir(project_id)),
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            # Another process created the row between the SELECT and the
            # INSERT (the API and the worker can both inspect a login).  The
            # existing row is the truth - never fail the login because of it.
            db.rollback()
            row = db.execute(
                select(ProjectLoginProfile).where(
                    ProjectLoginProfile.project_id == project_id
                )
            ).scalar_one_or_none()
        else:
            db.refresh(row)
    return row


def profile_version(db: Session, project_id: str) -> int | None:
    """The version a caller read, so a stale save can be rejected."""
    row = get_profile(db, project_id)
    return row.version if row is not None else None


class LoginStateConflict(RuntimeError):
    """A newer login session was stored after this caller read its state."""


def profile_path_for(db: Session, project_id: str) -> Path:
    """The profile directory recorded for the project, or the default path."""
    row = get_profile(db, project_id)
    stored = str(row.profile_dir or "").strip() if row is not None else ""
    if stored:
        return Path(stored)
    return profile_dir(project_id)


def _associated_data(project_id: str) -> str:
    return f"project-login:{project_id}"


def _session_secret() -> str:
    """The local encryption key for the browser sessions.

    A per installation key file keeps the encrypted ``storage_state`` values
    useless on another machine, even when the database is copied.  If the file
    is missing (a fresh install or an upgrade) it is created atomically with
    owner-only permissions.  An operator can override it with
    ``AUTOBL_LOGIN_SECRET`` for a managed deployment.
    """
    override = os.environ.get("AUTOBL_LOGIN_SECRET", "").strip()
    if override:
        return override
    try:
        # Deliberately not guarded by ``except OSError``: a file that exists
        # but cannot be read must fail loudly instead of being replaced
        # (replacing it would destroy every stored session).
        return _read_key_file()
    except FileNotFoundError:
        pass

    SESSION_KEY_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = secrets.token_hex(32)
    try:
        # O_EXCL makes the create atomic: two processes that start at the same
        # time cannot both write a different key.
        descriptor = os.open(
            SESSION_KEY_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
        )
    except FileExistsError:
        return _read_key_file()
    try:
        os.write(descriptor, key.encode("utf-8"))
    finally:
        os.close(descriptor)
    return key


def _read_key_file() -> str:
    key = SESSION_KEY_FILE.read_text(encoding="utf-8").strip()
    if not key:
        raise RuntimeError(
            f"The login key file {SESSION_KEY_FILE} is empty. Restore it or remove "
            "it (the stored browser sessions would have to be connected again)."
        )
    return key


def save_storage_state(
    db: Session,
    project_id: str,
    state: dict[str, Any],
    *,
    expected_version: int | None = None,
) -> None:
    """Encrypt and store the Playwright storage state of a project.

    ``expected_version`` is the profile version the caller read together with
    its state.  When a newer session was stored in the meantime (a fresh login
    while a long submission was still running) the stale write is rejected
    instead of destroying the newer cookies.
    """
    if not isinstance(state, dict):
        return
    row = get_profile(db, project_id, create=True)
    if row is None:  # pragma: no cover - create=True always returns a row
        return
    if expected_version is not None and row.version != expected_version:
        raise LoginStateConflict(
            f"The project login changed while the browser was open "
            f"(expected version {expected_version}, stored {row.version})."
        )
    row.storage_state_encrypted = encrypt(
        json.dumps(state, separators=(",", ":")),
        _session_secret(),
        _associated_data(project_id),
    )
    row.last_checked_at = utcnow()
    row.version += 1
    db.commit()


def load_storage_state(db: Session, project_id: str) -> dict[str, Any] | None:
    """Decrypt the storage state of a project, or ``None`` when unusable."""
    row = get_profile(db, project_id)
    if row is None or not row.storage_state_encrypted:
        return None
    try:
        raw = decrypt(
            row.storage_state_encrypted,
            _session_secret(),
            _associated_data(project_id),
        )
        state = json.loads(raw)
    except Exception:
        row.status = STATUS_ERROR
        row.last_error = (
            "The stored browser session could not be decrypted. Connect Google again."
        )
        db.commit()
        return None
    return state if isinstance(state, dict) else None


def set_status(
    db: Session,
    project_id: str,
    status: str,
    *,
    email: str | None = None,
    error: str | None = None,
) -> ProjectLoginProfile:
    row = get_profile(db, project_id, create=True)
    assert row is not None
    row.status = status
    if email is not None:
        row.email = email.strip() or row.email
    row.last_error = error
    row.last_checked_at = utcnow()
    if status == STATUS_CONNECTED:
        row.last_login_at = utcnow()
        row.last_error = None
    row.version += 1
    db.commit()
    db.refresh(row)
    return row


def remove_profile_files(db: Session, project_id: str) -> None:
    """Delete every profile directory recorded for the project."""
    paths = {profile_path_for(db, project_id), profile_dir(project_id)}
    for path in paths:
        with suppress(OSError):
            shutil.rmtree(path, ignore_errors=True)


def clear_profile(db: Session, project_id: str, *, delete_files: bool = True) -> None:
    """Forget the stored session and remove the profile directory."""
    row = get_profile(db, project_id)
    paths = {profile_dir(project_id)}
    if row is not None and str(row.profile_dir or "").strip():
        paths.add(Path(str(row.profile_dir).strip()))
    if delete_files:
        for path in paths:
            with suppress(OSError):
                shutil.rmtree(path, ignore_errors=True)
    if row is not None:
        row.storage_state_encrypted = None
        row.status = STATUS_NOT_CONNECTED
        row.email = None
        row.last_error = None
        row.last_login_at = None
        row.version += 1
        db.commit()


# --------------------------------------------------------------------------
# Website sessions
# --------------------------------------------------------------------------
def get_site_session(
    db: Session, project_id: str, website_id: str
) -> WebsiteLoginSession | None:
    return db.execute(
        select(WebsiteLoginSession).where(
            WebsiteLoginSession.project_id == project_id,
            WebsiteLoginSession.website_id == website_id,
        )
    ).scalar_one_or_none()


def mark_site(
    db: Session,
    project_id: str,
    website_id: str,
    status: str,
    *,
    method: str | None = None,
    error: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> WebsiteLoginSession:
    row = get_site_session(db, project_id, website_id)
    if row is None:
        row = WebsiteLoginSession(
            project_id=project_id,
            website_id=website_id,
            status=status,
            method=method or "UNKNOWN",
            evidence={},
        )
        db.add(row)
    row.status = status
    if method:
        row.method = method
    if evidence:
        row.evidence = {**(row.evidence or {}), **evidence}
    row.last_checked_at = utcnow()
    row.last_error = error
    if status == SITE_CONNECTED:
        row.last_login_at = utcnow()
        row.last_error = None
    db.commit()
    db.refresh(row)
    return row


def describe_site(db: Session, project_id: str, website_id: str) -> dict[str, Any]:
    row = get_site_session(db, project_id, website_id)
    if row is None:
        return {
            "website_id": website_id,
            "status": SITE_UNKNOWN,
            "method": "UNKNOWN",
            "last_login_at": None,
            "last_checked_at": None,
            "last_error": None,
        }
    return {
        "website_id": website_id,
        "status": row.status,
        "method": row.method,
        "last_login_at": row.last_login_at,
        "last_checked_at": row.last_checked_at,
        "last_error": row.last_error,
    }


# --------------------------------------------------------------------------
# Login wall detection (works with a real Playwright page)
# --------------------------------------------------------------------------
def page_requires_login(page: Any) -> bool:
    """Does this browser page show a login wall?

    The check is deliberately conservative: a header that merely contains a
    "Sign in" link is not a wall.  A wall is a login URL, a Google accounts
    page, explicit "sign in to continue" text, or a password form without the
    submission fields the adapter is about to fill.
    """
    try:
        url = str(page.url or "")
    except Exception:  # pragma: no cover - closed page
        url = ""
    if "accounts.google.com" in url:
        return True
    if _LOGIN_PATH.search(url):
        return True
    try:
        body = str(page.evaluate("() => (document.body ? document.body.innerText : '')") or "")
    except Exception:  # pragma: no cover - navigation in progress
        body = ""
    lowered = body.lower()
    if any(marker in lowered for marker in _LOGIN_TEXT):
        return True
    try:
        password_inputs = page.locator("input[type=password]").count()
    except Exception:  # pragma: no cover - closed page
        password_inputs = 0
    if password_inputs > 0:
        # A password field alone is not enough: some public forms ask for a
        # password to create an account on the same page.  A wall has no
        # normal submission controls.
        try:
            textareas = page.locator("textarea").count()
            text_inputs = page.locator("input[type=text], input[type=email]").count()
        except Exception:  # pragma: no cover - closed page
            textareas = 0
            text_inputs = 0
        if textareas == 0 and text_inputs <= 2:
            return True
    return False


def _is_google_domain(domain: str) -> bool:
    host = str(domain or "").strip().lstrip(".").lower()
    return host == "google.com" or host.endswith(".google.com")


def google_session_present(cookies: list[dict[str, Any]]) -> bool:
    """Whether the cookies contain a real Google login session."""
    for cookie in cookies or []:
        if _is_google_domain(str(cookie.get("domain") or "")) and str(
            cookie.get("name") or ""
        ) in _GOOGLE_COOKIES:
            return True
    return False


# --------------------------------------------------------------------------
# Resuming work after a login
# --------------------------------------------------------------------------
def pause_for_login(
    db: Session,
    project_id: str,
    website_id: str | None,
    message: str,
    *,
    google: bool = True,
) -> None:
    """Record a login wall on the project (and on the website, when known).

    A wall on a website that simply wants its own account is a *site* login and
    must not claim that the project's Google session expired - that would send
    the operator to the wrong login window.
    """
    row = get_profile(db, project_id)
    # Only a project that had a session can be "expired".  Without a stored
    # session the honest state is "not connected - log in".
    has_session = bool(row and row.storage_state_encrypted)
    if website_id:
        mark_site(
            db,
            project_id,
            website_id,
            SITE_EXPIRED if has_session else SITE_LOGIN_REQUIRED,
            error=message,
        )
    if google:
        # A decryption failure is actionable ("connect Google again") and must
        # not be replaced by a generic wall state.
        if row is not None and row.status == STATUS_ERROR:
            return
        set_status(
            db,
            project_id,
            STATUS_EXPIRED if has_session else STATUS_NOT_CONNECTED,
            error=message,
        )


def count_login_paused(db: Session, project_id: str) -> int:
    return len(_login_paused_tasks(db, project_id))


def _login_paused_tasks(
    db: Session, project_id: str, website_id: str | None = None
) -> list[Task]:
    query = select(Task).where(
        Task.project_id == project_id,
        Task.status == "WAITING_FOR_USER",
        Task.last_error.like(f"{LOGIN_REQUIRED_PREFIX}%"),
    )
    if website_id:
        query = query.where(Task.website_id == website_id)
    return db.execute(query).scalars().all()


def resume_login_paused_tasks(
    db: Session, project_id: str, *, website_id: str | None = None
) -> int:
    """Queue the tasks that stopped at a login wall again.

    A login for one website only requeues that website (a Google login requeues
    everything).  The update is conditional: a task that the operator finished
    meanwhile is never resurrected.
    """
    tasks = _login_paused_tasks(db, project_id, website_id)
    ids = [task.id for task in tasks]
    if not ids:
        return 0
    now = utcnow()
    result = db.execute(
        update(Task)
        .where(
            Task.id.in_(ids),
            Task.status == "WAITING_FOR_USER",
            Task.last_error.like(f"{LOGIN_REQUIRED_PREFIX}%"),
        )
        .values(
            status="QUEUED",
            scheduled_for=now,
            next_retry_at=now,
            last_error=None,
            requires_human=False,
            lease_owner=None,
            lease_expires_at=None,
            finished_at=None,
            updated_at=now,
        )
    )
    db.commit()
    return int(result.rowcount or 0)


# --------------------------------------------------------------------------
# The API payload
# --------------------------------------------------------------------------
def describe(db: Session, project_id: str) -> dict[str, Any]:
    row = get_profile(db, project_id)
    running = False
    browser_available = settings.allow_browser_automation
    try:
        from app.services.login_browser import available, is_open

        running = is_open(project_id)
        browser_available = available()
    except Exception:  # pragma: no cover - the manager is optional
        running = False
    if row is None:
        return {
            "project_id": project_id,
            "provider": "google",
            "status": STATUS_NOT_CONNECTED,
            "email": None,
            "last_login_at": None,
            "last_checked_at": None,
            "last_error": None,
            "login_open": running,
            "browser_available": browser_available,
            "paused_tasks": count_login_paused(db, project_id),
        }
    status = row.status
    if running:
        status = STATUS_LOGIN_OPEN
    elif status == STATUS_LOGIN_OPEN:
        # A row written by an older version may still carry the transient
        # status.  The window is gone, so report the real session state.
        status = STATUS_CONNECTED if row.storage_state_encrypted else STATUS_NOT_CONNECTED
    return {
        "project_id": project_id,
        "provider": row.provider,
        "status": status,
        "email": row.email,
        "last_login_at": row.last_login_at,
        "last_checked_at": row.last_checked_at,
        "last_error": row.last_error,
        "login_open": running,
        "browser_available": browser_available,
        "paused_tasks": count_login_paused(db, project_id),
    }


def login_url_for(db: Session, project: Project, website: Website) -> str:
    """The best URL to open when a website asks for a login."""
    config = website.adapter_config if isinstance(website.adapter_config, dict) else {}
    form_url = str(config.get("form_url") or "").strip()
    return form_url or website.opportunity_url or project.target_website


def cleanup_project(db: Session, project_id: str) -> None:
    """Remove the profile of a project that is deleted forever."""
    clear_profile(db, project_id, delete_files=True)
