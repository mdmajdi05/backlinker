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

from sqlalchemy import select
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
        db.commit()
        db.refresh(row)
    return row


def _associated_data(project_id: str) -> str:
    return f"project-login:{project_id}"


def _session_secret() -> str:
    """The local encryption key for the browser sessions.

    A per installation key file keeps the encrypted ``storage_state`` values
    useless on another machine, even when the database is copied.  If the file
    is missing (a fresh install or an upgrade) it is created with owner-only
    permissions.  An operator can override it with
    ``AUTOBL_LOGIN_SECRET`` for a managed deployment.
    """
    override = os.environ.get("AUTOBL_LOGIN_SECRET", "").strip()
    if override:
        return override
    try:
        existing = SESSION_KEY_FILE.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except OSError:
        pass
    SESSION_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(32)
    SESSION_KEY_FILE.write_text(key, encoding="utf-8")
    with suppress(OSError):
        os.chmod(SESSION_KEY_FILE, 0o600)
    return key


def save_storage_state(db: Session, project_id: str, state: dict[str, Any]) -> None:
    """Encrypt and store the Playwright storage state of a project."""
    if not isinstance(state, dict):
        return
    row = get_profile(db, project_id, create=True)
    if row is None:  # pragma: no cover - create=True always returns a row
        return
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


def clear_profile(db: Session, project_id: str, *, delete_files: bool = True) -> None:
    """Forget the stored session and remove the profile directory."""
    row = get_profile(db, project_id)
    if delete_files:
        shutil.rmtree(profile_dir(project_id), ignore_errors=True)
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


def google_session_present(cookies: list[dict[str, Any]]) -> bool:
    """Whether the cookies contain a real Google login session."""
    for cookie in cookies or []:
        domain = str(cookie.get("domain") or "")
        name = str(cookie.get("name") or "")
        if "google.com" in domain and name in _GOOGLE_COOKIES:
            return True
    return False


# --------------------------------------------------------------------------
# Resuming work after a login
# --------------------------------------------------------------------------
def pause_for_login(
    db: Session, project_id: str, website_id: str | None, message: str
) -> None:
    """Record a login wall on the project (and on the website, when known)."""
    row = get_profile(db, project_id)
    # Only a project that had a session can be "expired".  Without a stored
    # session the honest state is "not connected - log in".
    has_session = bool(row and row.storage_state_encrypted)
    set_status(
        db,
        project_id,
        STATUS_EXPIRED if has_session else STATUS_NOT_CONNECTED,
        error=message,
    )
    if website_id:
        mark_site(
            db,
            project_id,
            website_id,
            SITE_EXPIRED if has_session else SITE_LOGIN_REQUIRED,
            error=message,
        )


def count_login_paused(db: Session, project_id: str) -> int:
    return len(_login_paused_tasks(db, project_id))


def _login_paused_tasks(db: Session, project_id: str) -> list[Task]:
    return (
        db.execute(
            select(Task).where(
                Task.project_id == project_id,
                Task.status == "WAITING_FOR_USER",
                Task.last_error.like(f"{LOGIN_REQUIRED_PREFIX}%"),
            )
        )
        .scalars()
        .all()
    )


def resume_login_paused_tasks(db: Session, project_id: str) -> int:
    """Queue the tasks that stopped at a login wall again."""
    from app.services.queue import retry_task

    tasks = _login_paused_tasks(db, project_id)
    for task in tasks:
        retry_task(db, task)
        task.requires_human = False
    return len(tasks)


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
    return {
        "project_id": project_id,
        "provider": row.provider,
        "status": row.status,
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
