"""Accounts and backlink targets for every website of a project.

The flow of one project:

1. **One click** provisions every website in a single batch.  The batch opens
   the isolated profile of the project **once**, so the Google session and the
   cookies of the sites are reused and the inbox is opened **once** as well.
2. For each website the service decides the strategy from the live page:
   * a *Continue with Google* button -> the project's Google session is used,
   * otherwise the sign-up form is filled with the username and password the
     operator typed once in the details form (a blank field is generated per
     website).  Both are stored encrypted and shown on the row of the report.
3. The sign-up uses the Gmail of the project's Google login (or the address
   typed in the details form).  If the site asks for a code, it is read in the
   Gmail tab of the same browser; the row receives its **own** address alias
   (``inbox+token@gmail.com``) and only a mail addressed to that token is
   accepted.  The App Password inbox is only the fallback.  A code is claimed
   once and bound to its row.
4. A CAPTCHA is never bypassed.  The row pauses as **Needs you**, the live
   browser is one click away, and the batch continues with the next site.
5. Once the account is active the authenticated browser looks for the exact
   page that carries a link / profile field and stores it as the backlink
   target of the row.
"""

from __future__ import annotations

import re
import secrets
import string
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import decrypt, encrypt
from app.core.logging import get_logger
from app.db.base import utcnow
from app.db.models import (
    BacklinkRecord,
    Opportunity,
    Project,
    ProjectSettings,
    SiteAccount,
    Website,
)
from app.db.session import session_scope
from app.services import (
    backlink_post,
    backlink_target,
    gmail_otp,
    login_browser,
    project_login,
    site_intel,
)
from app.services import browser as browser_service

log = get_logger(__name__)

STRATEGY_GOOGLE = "GOOGLE"
STRATEGY_SIGNUP = "SIGNUP"
STRATEGY_EXISTING = "EXISTING"
#: No account at all: the site has a public form that accepts the link.
STRATEGY_DIRECT = "DIRECT"
STRATEGY_MANUAL = "MANUAL"
STRATEGY_UNKNOWN = "UNKNOWN"

STATUS_NOT_STARTED = "NOT_STARTED"
STATUS_QUEUED = "QUEUED"
STATUS_DETECTING = "DETECTING"
STATUS_CREATING = "CREATING"
STATUS_OTP_PENDING = "OTP_PENDING"
STATUS_ACTIVE = "ACTIVE"
STATUS_NEEDS_HUMAN = "NEEDS_HUMAN"
STATUS_FAILED = "FAILED"

OTP_NONE = "NONE"
OTP_WAITING = "WAITING"
OTP_RECEIVED = "RECEIVED"
OTP_USED = "USED"
OTP_EXPIRED = "EXPIRED"

ACTIVE_STATUSES = (STATUS_ACTIVE,)

#: A batch waits this long for one OTP before it pauses the row.
OTP_TIMEOUT_SECONDS = 240
#: The App Password inbox is only a fallback: wait less than the Gmail tab.
FALLBACK_OTP_SECONDS = 90
#: Human-like pause between two websites of the same batch.
PAUSE_RANGE = (2.0, 5.0)


def _pause() -> None:
    """A short, unpredictable pause between two sites of a batch."""
    low, high = PAUSE_RANGE
    time.sleep(low + secrets.randbelow(1000) / 1000.0 * (high - low))
#: How long a page may take to answer.
NAV_TIMEOUT_MS = 45_000

#: Progress of the (one) batch of a project, read by the UI.
_BATCHES: dict[str, dict[str, Any]] = {}
_THREADS: dict[str, threading.Thread] = {}
_LOCK = threading.RLock()

_SUBMIT_WORDS = (
    "create account",
    "sign up",
    "signup",
    "register",
    "create my account",
    "join",
    "continue",
    "submit",
    "get started",
)
_TERMS_WORDS = ("agree", "terms", "privacy", "accept")
_SUCCESS_WORDS = (
    "welcome",
    "account created",
    "successfully registered",
    "registration complete",
    "check your email",
    "verify your email",
    "we sent you",
    "confirm your email",
)
_LOGIN_WORDS = (
    "sign in to continue",
    "log in to continue",
    "please sign in",
    "please log in",
    "login required",
    "you must be logged in",
    "you must log in",
    "create a free account to continue",
)


# --------------------------------------------------------------------------
# Credentials and encryption
# --------------------------------------------------------------------------
def _secret() -> str:
    return settings.secret_key


def _aad(project_id: str, website_id: str) -> str:
    """Bind a stored password to its own row (no cross-row swap)."""
    return f"site-account:{project_id}:{website_id}"


def password_of(row: SiteAccount) -> str | None:
    """The decrypted password of a row (``None`` when it has none)."""
    if not row.password_encrypted:
        return None
    try:
        return decrypt(
            row.password_encrypted,
            _secret(),
            _aad(row.project_id, row.website_id),
        )
    except Exception:
        log.warning(
            "the stored site password could not be decrypted",
            extra={"extra_fields": {"website_id": row.website_id}},
        )
        return None


def set_password(row: SiteAccount, password: str) -> None:
    row.password_encrypted = encrypt(password, _secret(), _aad(row.project_id, row.website_id))


def set_otp(row: SiteAccount, code: str, message_id: str) -> None:
    row.otp_encrypted = encrypt(code, _secret(), _aad(row.project_id, row.website_id))
    row.otp_message_id = message_id
    row.otp_received_at = utcnow()
    row.otp_state = OTP_RECEIVED


def otp_of(row: SiteAccount) -> str | None:
    if not row.otp_encrypted:
        return None
    try:
        return decrypt(row.otp_encrypted, _secret(), _aad(row.project_id, row.website_id))
    except Exception:
        return None


def generate_password(length: int = 18) -> str:
    """A strong password with every character class the forms usually ask for."""
    alphabet = string.ascii_letters + string.digits + "!@#$%&*?"
    while True:
        value = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(char.islower() for char in value)
            and any(char.isupper() for char in value)
            and any(char.isdigit() for char in value)
            and any(char in "!@#$%&*?" for char in value)
        ):
            return value


def generate_username(website: Website, project: Project) -> str:
    """A readable, unique looking username derived from the site and project."""
    site = re.sub(r"[^a-z0-9]", "", (website.domain or "site").split(".")[0].lower())
    brand = re.sub(r"[^a-z0-9]", "", (project.name or project.slug or "user").lower())
    site = (site or "site")[:10]
    brand = (brand or "user")[:6]
    return f"{site}{brand}{secrets.token_hex(2)}"[:24]


# --------------------------------------------------------------------------
# Sign-up details (one answer for every website of the project)
# --------------------------------------------------------------------------
def _details_aad(project_id: str) -> str:
    return f"project-signup:{project_id}"


def _settings_row(db: Session, project_id: str) -> ProjectSettings | None:
    return db.execute(
        select(ProjectSettings).where(ProjectSettings.project_id == project_id)
    ).scalar_one_or_none()


def signup_details(
    db: Session, project_id: str, *, reveal: bool = True
) -> dict[str, Any]:
    """The username / e-mail / password the operator wants every sign-up to use."""
    row = _settings_row(db, project_id)
    data = dict((row.signup_details if row is not None else None) or {})
    password: str | None = None
    if data.get("password_encrypted"):
        try:
            password = decrypt(
                str(data["password_encrypted"]), _secret(), _details_aad(project_id)
            )
        except Exception:
            log.warning(
                "the sign-up password could not be decrypted",
                extra={"extra_fields": {"project_id": project_id}},
            )
    return {
        "username": str(data.get("username") or ""),
        "email": str(data.get("email") or ""),
        "password": password if reveal else None,
        "has_password": bool(data.get("password_encrypted")),
    }


def save_signup_details(
    db: Session,
    project: Project,
    *,
    username: str | None = None,
    password: str | None = None,
    email: str | None = None,
) -> dict[str, Any]:
    """Remember the sign-up details of the project (an empty field = generated).

    A field that is ``None`` is left unchanged; an empty string clears it, so
    the operator can go back to a generated username or password.
    """
    row = _settings_row(db, project.id)
    if row is None:
        row = ProjectSettings(project_id=project.id)
        db.add(row)
    data = dict(row.signup_details or {})
    if username is not None:
        value = username.strip()[:120]
        if value:
            data["username"] = value
        else:
            data.pop("username", None)
    if email is not None:
        value = email.strip()[:320]
        if value:
            data["email"] = value
        else:
            data.pop("email", None)
    if password is not None:
        if password:
            data["password_encrypted"] = encrypt(
                password, _secret(), _details_aad(project.id)
            )
        else:
            data.pop("password_encrypted", None)
    row.signup_details = data
    db.commit()
    return signup_details(db, project.id)


def apply_signup_details(row: SiteAccount, details: dict[str, Any]) -> None:
    """Copy the chosen username / password onto one row before it is created."""
    username = str(details.get("username") or "").strip()
    if username:
        row.username = username
    password = details.get("password") or ""
    if password:
        set_password(row, str(password))


# --------------------------------------------------------------------------
# Rows
# --------------------------------------------------------------------------
def get_account(db: Session, project_id: str, website_id: str) -> SiteAccount | None:
    return db.execute(
        select(SiteAccount).where(
            SiteAccount.project_id == project_id,
            SiteAccount.website_id == website_id,
        )
    ).scalar_one_or_none()


def ensure_account(db: Session, project_id: str, website_id: str) -> SiteAccount:
    row = get_account(db, project_id, website_id)
    if row is None:
        row = SiteAccount(project_id=project_id, website_id=website_id)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def account_payload(
    db: Session, row: SiteAccount | None, *, reveal: bool = True
) -> dict[str, Any] | None:
    """The account of a row as the report shows it."""
    if row is None:
        return None
    del db
    password = password_of(row) if reveal else None
    return {
        "website_id": row.website_id,
        "strategy": row.strategy,
        "status": row.status,
        "email": row.email,
        "username": row.username,
        "password": password,
        "has_password": bool(row.password_encrypted),
        "otp_state": row.otp_state,
        "otp_alias": row.otp_alias,
        "otp_received_at": row.otp_received_at,
        "login_url": row.login_url,
        "account_url": row.account_url,
        "backlink_url": row.backlink_url,
        "backlink_confidence": row.backlink_confidence,
        "backlink_form": row.backlink_form or {},
        "backlink_status": row.backlink_status,
        "backlink_published_url": row.backlink_published_url,
        "backlink_note": row.backlink_note,
        "site_intel": row.site_intel or {},
        "attempts": row.attempts,
        "last_error": row.last_error,
        "evidence": row.evidence or {},
        "updated_at": row.updated_at,
    }


# --------------------------------------------------------------------------
# Batch progress
# --------------------------------------------------------------------------
def _empty_batch(project_id: str) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "running": False,
        "stop_requested": False,
        "started_at": None,
        "finished_at": None,
        "total": 0,
        "done": 0,
        "active_website_id": None,
        "active_name": None,
        "message": None,
        "error": None,
        "items": [],
        "counts": {},
    }


def batch_state(project_id: str) -> dict[str, Any]:
    with _LOCK:
        batch = _BATCHES.get(project_id)
        if batch is None:
            return _empty_batch(project_id)
        return {
            **batch,
            "items": [dict(item) for item in batch.get("items", [])],
            "counts": dict(batch.get("counts") or {}),
        }


def _update_batch(project_id: str, **fields: Any) -> None:
    with _LOCK:
        batch = _BATCHES.setdefault(project_id, _empty_batch(project_id))
        batch.update(fields)


def _update_item(project_id: str, website_id: str, **fields: Any) -> None:
    with _LOCK:
        batch = _BATCHES.setdefault(project_id, _empty_batch(project_id))
        for item in batch.get("items", []):
            if item["website_id"] == website_id:
                item.update(fields)
                break
        counts: dict[str, int] = {}
        for item in batch.get("items", []):
            counts[str(item.get("status"))] = counts.get(str(item.get("status")), 0) + 1
        batch["counts"] = counts
        finished = [
            item
            for item in batch.get("items", [])
            if item.get("status") in (STATUS_ACTIVE, STATUS_FAILED, STATUS_NEEDS_HUMAN)
        ]
        batch["done"] = len(finished)


def stop_batch(project_id: str) -> bool:
    with _LOCK:
        batch = _BATCHES.get(project_id)
        if batch is None or not batch.get("running"):
            return False
        batch["stop_requested"] = True
        return True


def _stopped(project_id: str) -> bool:
    with _LOCK:
        batch = _BATCHES.get(project_id)
        return bool(batch and batch.get("stop_requested"))


# --------------------------------------------------------------------------
# Start a batch
# --------------------------------------------------------------------------
def _target_websites(db: Session, project: Project) -> list[Website]:
    opportunities = (
        db.execute(
            select(Opportunity).where(
                Opportunity.project_id == project.id,
                Opportunity.deleted_at.is_(None),
            )
        )
        .scalars()
        .all()
    )
    websites: list[Website] = []
    for opportunity in opportunities:
        website = db.get(Website, opportunity.website_id)
        if website is not None and website.deleted_at is None:
            websites.append(website)
    return websites


def start_batch(
    db: Session,
    project: Project,
    *,
    website_ids: list[str] | None = None,
    retry: bool = False,
    username: str | None = None,
    password: str | None = None,
    email: str | None = None,
) -> dict[str, Any]:
    """Provision the accounts of a project in one background batch.

    ``username`` / ``password`` / ``email`` are the answers of the details
    form.  They are remembered for the project and applied to every row that
    is about to be created, so the same person (the same Gmail) owns all the
    accounts.  ``None`` keeps the saved value, an empty string clears it (the
    field is generated per website then).
    """
    if not settings.allow_browser_automation:
        raise RuntimeError("Browser automation is turned off in the settings.")
    if login_browser.is_open(project.id):
        raise RuntimeError(
            "The login window of this project is open. Finish or cancel it first."
        )
    with _LOCK:
        running = _BATCHES.get(project.id)
        if running and running.get("running"):
            return batch_state(project.id)

    if username is not None or password is not None or email is not None:
        details = save_signup_details(
            db,
            project,
            username=username,
            password=password,
            email=email,
        )
    else:
        details = signup_details(db, project.id)

    websites = _target_websites(db, project)
    if website_ids:
        wanted = set(website_ids)
        websites = [website for website in websites if website.id in wanted]

    selected: list[Website] = []
    for website in websites:
        row = ensure_account(db, project.id, website.id)
        if row.status in ACTIVE_STATUSES and not retry:
            continue
        selected.append(website)
    for website in selected:
        row = ensure_account(db, project.id, website.id)
        apply_signup_details(row, details)
    if selected:
        db.commit()
    if not selected:
        raise RuntimeError("Every website already has an account.")

    gmail = gmail_otp.read_settings(db)
    items = [
        {
            "website_id": website.id,
            "name": website.name or website.domain,
            "domain": website.domain,
            "status": STATUS_QUEUED,
            "message": "Waiting for its turn…",
            "strategy": None,
        }
        for website in selected
    ]
    with _LOCK:
        _BATCHES[project.id] = {
            **_empty_batch(project.id),
            "running": True,
            "started_at": utcnow(),
            "total": len(selected),
            "message": "Opening the project browser…",
            "items": items,
            "gmail": bool(gmail),
        }
    thread = threading.Thread(
        target=_run_batch,
        args=(project.id, [website.id for website in selected]),
        name=f"site-accounts-{project.id}",
        daemon=True,
    )
    _THREADS[project.id] = thread
    thread.start()
    return batch_state(project.id)


# --------------------------------------------------------------------------
# Browser helpers
# --------------------------------------------------------------------------
def _headless() -> bool:
    """Headless when there is no display (cloud / CI) or in the test suite."""
    if settings.environment == "test":
        return True
    return not login_browser.display_available()


@dataclass
class _Browser:
    context: Any
    process: Any = None
    playwright: Any = None

    def close(self) -> None:
        with suppress(Exception):
            self.context.close()
        if self.process is not None:
            login_browser.stop_browser_process(self.process)
        if self.playwright is not None:
            with suppress(Exception):
                self.playwright.stop()


def _open_browser(project_id: str, *, headless: bool) -> _Browser:
    """Open the isolated profile of the project, once per batch."""
    from app.services.browser import ensure_playwright_path

    ensure_playwright_path()
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    directory = project_login.ensure_profile_dir(project_id)
    try:
        if not headless:
            with suppress(Exception):
                context, process = login_browser.launch_unflagged_chrome(
                    playwright, directory, project_id=project_id
                )
                return _Browser(context=context, process=process, playwright=playwright)
        context = playwright.chromium.launch_persistent_context(
            str(directory),
            headless=headless,
            args=list(browser_service.ISOLATION_ARGS),
            viewport={
                "width": settings.login_stream_width,
                "height": settings.login_stream_height,
            },
            accept_downloads=False,
        )
        return _Browser(context=context, playwright=playwright)
    except Exception:
        with suppress(Exception):
            playwright.stop()
        raise


def _page_for(context: Any) -> Any:
    return context.pages[0] if context.pages else context.new_page()


def _body_text(page: Any) -> str:
    with suppress(Exception):
        return str(page.inner_text("body")).lower()[:6000]
    return ""


def _challenge(page: Any) -> str | None:
    """The human challenge on the page, if any (never bypassed)."""
    for selector in (
        "iframe[src*='recaptcha']",
        "iframe[src*='hcaptcha']",
        "iframe[src*='turnstile']",
        ".cf-turnstile",
        "#challenge-form",
        "input[name*='captcha' i]",
        "input[id*='captcha' i]",
        "div.g-recaptcha",
        "div.h-captcha",
    ):
        with suppress(Exception):
            if page.query_selector(selector) is not None:
                return "CAPTCHA"
    text = _body_text(page)
    for marker in (
        "verify you are human",
        "verify that you are human",
        "are you a robot",
        "unusual traffic from your computer",
        "checking your browser before accessing",
        "complete the security check",
    ):
        if marker in text:
            return "CAPTCHA"
    return None


#: Controls that only exist for a signed in visitor.
_LOGOUT_SELECTORS = (
    "a[href*='logout']",
    "a[href*='log-out']",
    "a[href*='signout']",
    "a[href*='sign-out']",
    "button:has-text('Log out')",
    "a:has-text('Log out')",
    "a:has-text('Logout')",
    "a:has-text('Sign out')",
    "button:has-text('Sign out')",
)
#: Links a *logged out* visitor also sees - they cancel a weak "account" hint.
_SIGNED_OUT_SELECTORS = (
    "a[href*='login']",
    "a[href*='signin']",
    "a[href*='sign-in']",
    "a[href*='register']",
    "a[href*='signup']",
    "button:has-text('Sign in')",
    "a:has-text('Sign in')",
    "a:has-text('Log in')",
)
#: Pages that only a signed in user can open.
_PRIVATE_LINK_SELECTORS = (
    "a[href*='dashboard']",
    "a[href*='my-account']",
    "a[href*='/profile']",
    "a[href*='settings']",
)


def _logged_in(page: Any) -> bool:
    """Conservative: a real logout control and no password / sign-in field.

    A "My account" text link exists on many *logged out* pages, therefore it is
    never enough on its own.  Claiming a login this module did not observe would
    turn an unverified row into a false success.
    """
    with suppress(Exception):
        if page.query_selector("input[type='password']:visible") is not None:
            return False
    for selector in _LOGOUT_SELECTORS:
        with suppress(Exception):
            if page.query_selector(selector) is not None:
                return True
    # No logout control: only a private link *and* no obvious sign-in link.
    try:
        has_private = any(
            page.query_selector(selector) is not None
            for selector in _PRIVATE_LINK_SELECTORS
        )
        has_sign_in = any(
            page.query_selector(selector) is not None
            for selector in _SIGNED_OUT_SELECTORS
        )
    except Exception:
        return False
    return bool(has_private and not has_sign_in)


def _has_password_form(page: Any) -> bool:
    """Whether the page shows a visible password field."""
    with suppress(Exception):
        return page.query_selector("input[type='password']:visible") is not None
    return False


_EMPTY_REQUIRED_JS = """
() => {
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    const box = el.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden'
      && box.width > 1 && box.height > 1;
  };
  return Array.from(document.querySelectorAll(
    'input[required], textarea[required], select[required]'
  )).filter(visible).some((el) => {
    if (el.type === 'checkbox' || el.type === 'radio') return !el.checked;
    return !String(el.value || '').trim();
  });
}
"""


_MISSING_REQUIRED_JS = """
() => {
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    const box = el.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden'
      && box.width > 1 && box.height > 1;
  };
  const nameOf = (el) => {
    let label = '';
    if (el.id) {
      const node = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (node) label = (node.innerText || '').trim();
    }
    if (!label && el.closest('label')) {
      label = (el.closest('label').innerText || '').trim();
    }
    return (
      label
      || el.getAttribute('aria-label')
      || el.getAttribute('placeholder')
      || el.getAttribute('name')
      || el.id
      || el.tagName.toLowerCase()
    ).slice(0, 60);
  };
  const out = [];
  for (const el of document.querySelectorAll(
    'input[required], textarea[required], select[required]'
  )) {
    if (!visible(el)) continue;
    if (el.type === 'checkbox' || el.type === 'radio') {
      if (el.checked) continue;
    } else if (String(el.value || '').trim()) {
      continue;
    }
    const label = nameOf(el);
    if (!out.includes(label)) out.push(label);
  }
  return out;
}
"""


def _missing_required(page: Any) -> list[str]:
    """Labels of visible required fields that are still empty."""
    with suppress(Exception):
        found = page.evaluate(_MISSING_REQUIRED_JS)
        if isinstance(found, list):
            return [str(item) for item in found if str(item).strip()]
    return []


def _has_empty_required(page: Any) -> bool:
    """A required field of the current form is still empty (next step)."""
    for root in _form_roots(page):
        with suppress(Exception):
            if root.evaluate(_EMPTY_REQUIRED_JS):
                return True
    return False


def _click_google(page: Any, context: Any) -> tuple[Any, bool]:
    """Click the *Continue with Google* control (returns the page to drive)."""
    marked = page.evaluate(
        """
        () => {
          const pattern = /(continue|sign\\s*in|sign\\s*up|log\\s*in|register).{0,25}google|google.{0,25}(continue|sign\\s*in|sign\\s*up|log\\s*in)/i;
          const oauth = /accounts\\.google\\.com|\\/auth\\/google|oauth\\/google|google-login/i;
          for (const el of document.querySelectorAll('a, button, [role=button]')) {
            const text = (el.innerText || el.value || '').trim();
            const href = el.getAttribute('href') || '';
            if (text.length > 90) continue;
            if (pattern.test(text) || oauth.test(href)) {
              el.setAttribute('data-abk-google', '1');
              return true;
            }
          }
          return false;
        }
        """
    )
    if not marked:
        return page, False
    try:
        with context.expect_page(timeout=7000) as info:
            page.click("[data-abk-google='1']", timeout=8000)
        return info.value, True
    except Exception:
        return page, True


def _google_session_ready(db: Session, project_id: str) -> str | None:
    state = project_login.load_storage_state(db, project_id)
    if state is None:
        return None
    if not project_login.google_session_present(list(state.get("cookies") or [])):
        return None
    profile = project_login.get_profile(db, project_id)
    return (profile.email if profile is not None and profile.email else "") or ""


def _finish_google(
    page: Any, context: Any, *, email: str, timeout: float = 75.0
) -> tuple[str, str | None]:
    """Complete the Google consent/account chooser without typing a password.

    Returns ``("ok" | "human" | "failed", message)``.
    """
    deadline = time.monotonic() + timeout
    picked = False
    while time.monotonic() < deadline:
        pages = list(context.pages)
        target = page
        for candidate in pages:
            with suppress(Exception):
                if "accounts.google.com" in candidate.url:
                    target = candidate
                    break
        try:
            url = target.url
        except Exception:
            return "failed", "The Google window was closed."
        if "accounts.google.com" not in url:
            # Back on the website: the login happened.
            return "ok", None
        with suppress(Exception):
            if target.query_selector("input[type='password']:visible") is not None:
                return (
                    "human",
                    "Google asked for the account password. Sign in once in the "
                    "login view, then create the accounts again.",
                )
        with suppress(Exception):
            if target.query_selector("iframe[src*='accounts.google.com/gsi']") is not None:
                # One Tap: try to click the account tile inside the frame.
                for frame in target.frames:
                    with suppress(Exception):
                        if "accounts.google.com" not in frame.url:
                            continue
                        if email:
                            frame.get_by_text(email, exact=False).first.click(timeout=4000)
                            picked = True
                            break
        if not picked:
            with suppress(Exception):
                marked = target.evaluate(
                    """
                    (email) => {
                      const wanted = (email || '').toLowerCase();
                      const nodes = Array.from(document.querySelectorAll(
                        '[data-email], div[role=link], li, div[role=button], a'
                      ));
                      let fallback = null;
                      for (const node of nodes) {
                        const text = (node.innerText || '').toLowerCase();
                        if (!text || text.length > 300) continue;
                        const value = (node.getAttribute('data-email') || '').toLowerCase();
                        if (wanted && (value === wanted || text.includes(wanted))) {
                          node.setAttribute('data-abk-account', '1');
                          return 'match';
                        }
                        if (!fallback && /@/.test(text)) {
                          node.setAttribute('data-abk-account', '1');
                          fallback = 'fallback';
                        }
                      }
                      return fallback || '';
                    }
                    """,
                    email,
                )
            if marked:
                with suppress(Exception):
                    target.click("[data-abk-account='1']", timeout=5000)
                picked = True
        time.sleep(1.0)
    return (
        "human",
        "The Google sign-in did not come back to the website. Finish it in the "
        "login view and try this row again.",
    )


#: Mark every element that opens a sign-up form (link, tab, modal button).
_FIND_SIGNUP_JS = r"""
() => {
  const pattern = /(sign\s*up|signup|register|registration|create\s+(an\s+|a\s+)?(new\s+)?account|join|become\s+a\s+member|get\s+started|registr|anmeld|inscri|cadastr|criar\s+conta|crear\s+cuenta|s'inscrire|créer\s+un\s+compte|konto\s+erstellen|注册|登録)/i;
  const hrefPattern = /(signup|sign-up|register|registration|join|create-account|create_account|registr|anmeld|inscri|cadastr)/i;
  const out = [];
  let markedButton = false;
  for (const el of document.querySelectorAll('a, button, [role=button], [role=link]')) {
    const text = (el.innerText || el.value || '').trim();
    const href = el.getAttribute('href') || '';
    const byHref = hrefPattern.test(href);
    if ((!text && !byHref) || text.length > 80) continue;
    if (!byHref && !pattern.test(text)) continue;
    // A newsletter or a coupon "join" is not an account.
    if (/(newsletter|subscribe|coupon|deal|follow us|mailing list)/i.test(text)) continue;
    if (!href || href.startsWith('#') || href.startsWith('javascript')) {
      if (markedButton) continue;
      markedButton = true;
      el.setAttribute('data-abk-signup', '1');
      out.push('');
      continue;
    }
    out.push(el.href);
  }
  return out;
}
"""


def _signup_entry_points(page: Any) -> tuple[list[str], list[Any]]:
    """Every link / button that opens a sign-up form, frames included.

    Returns the hrefs to open and the roots (page or iframe) that carry a
    button which opens the form without navigating (a modal).
    """
    links: list[str] = []
    clickables: list[Any] = []
    for root in _form_roots(page):
        with suppress(Exception):
            found = root.evaluate(_FIND_SIGNUP_JS) or []
        for href in found or []:
            href = str(href or "").strip()
            if href:
                if href not in links:
                    links.append(href)
            elif root not in clickables:
                clickables.append(root)
    return links, clickables


def _click_signup_entry(page: Any, root: Any) -> str:
    """Press the marked sign-up button of ``root`` (a modal or a new tab)."""
    with suppress(Exception):
        with page.context.expect_page(timeout=4000) as info:
            root.click("[data-abk-signup='1']", timeout=5000)
        return str(info.value.url or page.url)
    with suppress(Exception):
        root.click("[data-abk-signup='1']", timeout=5000)
    return str(page.url or "")


def _signup_candidates(base: str) -> list[str]:
    """The usual sign-up paths, tried when the page has no visible link."""
    parsed = re.match(r"^(https?://[^/]+)", base or "")
    origin = parsed.group(1) if parsed else base.rstrip("/")
    if not origin:
        return []
    return [
        f"{origin}{path}"
        for path in (
            "/signup",
            "/sign-up",
            "/signup.php",
            "/register",
            "/register.php",
            "/register.html",
            "/join",
            "/join-now",
            "/create-account",
            "/account/register",
            "/account/signup",
            "/account/create",
            "/user/register",
            "/users/sign_up",
            "/members/register",
            "/member/register",
            "/wp-login.php?action=register",
            "/?register=1",
            "/index.php?action=register",
        )
    ]


def _form_roots(page: Any) -> list[Any]:
    """The page itself and every child frame a form may live in."""
    roots: list[Any] = [page]
    with suppress(Exception):
        roots.extend(frame for frame in page.frames if frame is not page.main_frame)
    return roots


def _frame_with_form(page: Any) -> Any | None:
    """The page or iframe that really shows a sign-up form."""
    for root in _form_roots(page):
        with suppress(Exception):
            data = root.evaluate(_COLLECT_FIELDS_JS) or {}
        roles = {_field_role(field) for field in data.get("fields") or []}
        if "password" in roles and roles & {"email", "username"}:
            return root
        # Passwordless sign-up: an e-mail field and a continue / create button.
        # The mail carries the link, the inbox reads it (same pipeline).
        if "email" in roles and not (roles & {"password", "confirm"}):
            buttons = " ".join(
                str(button.get("text") or "").lower()
                for button in data.get("buttons") or []
            )
            if any(
                word in buttons
                for word in (
                    "sign up",
                    "signup",
                    "register",
                    "create",
                    "join",
                    "continue",
                    "next",
                    "start",
                )
            ):
                return root
    return None


_DISMISS_OVERLAYS_JS = """
() => {
  const containers = document.querySelectorAll(
    '[id*="cookie" i], [class*="cookie" i], [id*="consent" i], [class*="consent" i], '
    + '[id*="gdpr" i], [class*="gdpr" i], #onetrust-banner-sdk, .cc-window'
  );
  for (const box of containers) {
    const text = (box.innerText || '').toLowerCase();
    if (!/(cookie|consent|privacy|gdpr)/.test(text)) continue;
    for (const el of box.querySelectorAll('button, a, [role="button"]')) {
      const label = (el.innerText || el.value || '').trim();
      if (!label || label.length > 40) continue;
      if (!/(accept|agree|allow all|got it|understood|allow)/i.test(label)) continue;
      if (/(reject|decline|settings|manage|only necessary|essential)/i.test(label)) continue;
      el.click();
      return label;
    }
  }
  return '';
}
"""


def _dismiss_overlays(page: Any) -> bool:
    """Close the cookie / consent banner that hides a form (best effort)."""
    for root in _form_roots(page):
        with suppress(Exception):
            label = root.evaluate(_DISMISS_OVERLAYS_JS)
            if label:
                page.wait_for_timeout(600)
                return True
    return False


_CHECK_RADIOS_JS = """
() => {
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    const box = el.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden'
      && box.width > 1 && box.height > 1;
  };
  const nameOf = (el) => {
    if (el.id) {
      const node = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (node) return (node.innerText || '').toLowerCase();
    }
    const parent = el.closest('label');
    return parent ? (parent.innerText || '').toLowerCase() : '';
  };
  const groups = {};
  for (const el of document.querySelectorAll('input[type="radio"]')) {
    if (!visible(el) || !el.name) continue;
    (groups[el.name] = groups[el.name] || []).push(el);
  }
  let clicked = 0;
  for (const name of Object.keys(groups)) {
    const group = groups[name];
    if (group.some((el) => el.checked)) continue;
    if (!group.some((el) => el.required || el.getAttribute('aria-required') === 'true')) continue;
    const preferred = group.find((el) =>
      /(business|company|organis|organization|professional|yes|agree)/i.test(nameOf(el))
    );
    const choice = preferred || group[0];
    choice.click();
    clicked += 1;
  }
  return clicked;
}
"""


def _check_radios(root: Any) -> int:
    """Pick a sensible option in every empty required radio group."""
    with suppress(Exception):
        return int(root.evaluate(_CHECK_RADIOS_JS) or 0)
    return 0


def _field_role(field: dict[str, Any]) -> str:
    """What a form field asks for, guessed from every hint the browser gives."""
    raw = " ".join(
        str(field.get(key) or "")
        for key in ("name", "id", "placeholder", "label", "autocomplete", "aria", "title")
    ).lower()
    text = re.sub(r"[_\-\[\]]+", " ", raw)
    text = re.sub(r"\s+", " ", text).strip()
    kind = str(field.get("type") or "").lower()

    if kind == "password" or "password" in text or "passwd" in text:
        if any(word in text for word in ("confirm", "repeat", "again", "retype", "verify")):
            return "confirm"
        return "password"
    if kind == "email" or "email" in text or "e-mail" in text:
        return "email"
    if kind == "tel" or any(
        word in text
        for word in ("phone", "mobile", "telephone", "contact number", "whatsapp")
    ):
        return "phone"
    if kind == "url" or any(
        word in text
        for word in ("website", "web site", "homepage", "home page", "your url", "site url")
    ):
        return "website"
    if any(word in text for word in ("user name", "username", "login name", "handle", "nickname", "screen name", "user id")):
        return "username"
    if "first name" in text or "firstname" in text or "given name" in text or "fname" in text:
        return "first"
    if "last name" in text or "lastname" in text or "surname" in text or "family name" in text or "lname" in text:
        return "last"
    if any(word in text for word in ("company", "business name", "organization", "organisation", "brand name")):
        return "company"
    if any(word in text for word in ("address", "street")):
        return "address"
    if any(word in text for word in ("zip", "postal", "postcode")):
        return "zip"
    if any(word in text for word in ("city", "town")):
        return "city"
    if "country" in text:
        return "country"
    if any(word in text for word in ("full name", "your name", "display name", "name")):
        return "name"
    return ""


_COLLECT_FIELDS_JS = """
() => {
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    const box = el.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden'
      && box.width > 1 && box.height > 1;
  };
  const labelFor = (el) => {
    const parts = [];
    if (el.labels) for (const label of el.labels) parts.push(label.innerText || '');
    return parts.join(' ').replace(/\\s+/g, ' ').trim();
  };
  const out = [];
  for (const el of document.querySelectorAll('input, textarea, [contenteditable="true"]')) {
    if (!visible(el)) continue;
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || (tag === 'input' ? 'text' : tag)).toLowerCase();
    if (['hidden', 'submit', 'button', 'reset', 'file', 'image'].includes(type)) continue;
    const name = el.getAttribute('name') || '';
    const id = el.id || '';
    let selector = '';
    if (id) selector = '#' + CSS.escape(id);
    else if (name) selector = el.tagName.toLowerCase() + '[name="' + CSS.escape(name) + '"]';
    if (!selector) continue;
    out.push({
      selector, name, id, tag, type,
      placeholder: el.getAttribute('placeholder') || '',
      autocomplete: el.getAttribute('autocomplete') || '',
      aria: el.getAttribute('aria-label') || '',
      title: el.getAttribute('title') || '',
      label: labelFor(el),
      required: el.required === true || el.getAttribute('aria-required') === 'true',
    });
  }
  const selects = [];
  for (const el of document.querySelectorAll('select')) {
    if (!visible(el)) continue;
    const name = el.getAttribute('name') || '';
    const id = el.id || '';
    let selector = '';
    if (id) selector = '#' + CSS.escape(id);
    else if (name) selector = 'select[name="' + CSS.escape(name) + '"]';
    if (!selector) continue;
    selects.push({
      selector, name, id,
      aria: el.getAttribute('aria-label') || '',
      label: labelFor(el),
    });
  }
  const combos = [];
  for (const el of document.querySelectorAll('[role="combobox"]')) {
    if (!visible(el)) continue;
    const id = el.id || '';
    let selector = id ? '#' + CSS.escape(id) : '';
    if (!selector) {
      const parent = el.parentElement;
      if (parent && parent.id) selector = '#' + CSS.escape(parent.id);
    }
    if (!selector) continue;
    combos.push({
      selector,
      aria: el.getAttribute('aria-label') || '',
      label: labelFor(el) || (el.innerText || '').trim(),
    });
  }
  const checkboxes = Array.from(document.querySelectorAll('input[type=checkbox]'))
    .filter(visible)
    .map((el) => {
      const label = labelFor(el);
      let selector = el.id ? '#' + CSS.escape(el.id)
        : (el.getAttribute('name') ? 'input[name="' + CSS.escape(el.getAttribute('name')) + '"]' : '');
      return {selector, label, checked: el.checked, required: el.required === true};
    })
    .filter((item) => item.selector);
  return {fields: out, selects, combos, checkboxes, text: document.body ? document.body.innerText.slice(0, 6000) : ''};
}
"""


def _profile_values(project: Project) -> dict[str, str]:
    """The business values a sign-up form may ask for (best effort)."""
    profile = getattr(project, "business_profile", None)
    name = (getattr(profile, "name", "") or project.name or "").strip()
    website = (
        getattr(profile, "primary_website", "") or project.target_website or ""
    ).strip()
    phone = (getattr(profile, "contact_phone", "") or "").strip()
    countries = getattr(profile, "target_countries", None) or []
    country = str(countries[0]).strip() if countries else ""
    return {
        "company": name,
        "name": name,
        "website": website,
        "phone": phone,
        "country": country,
    }


def _wait_for_signup_form(page: Any, timeout: float = 6.0) -> Any | None:
    """Wait briefly for a JavaScript-rendered form (or for its iframe)."""
    deadline = time.monotonic() + timeout
    while True:
        root = _frame_with_form(page)
        if root is not None:
            return root
        if time.monotonic() >= deadline:
            return None
        with suppress(Exception):
            page.wait_for_timeout(500)


def _fill_signup(page: Any, row: SiteAccount, project: Project) -> tuple[bool, str | None]:
    root = _frame_with_form(page) or page
    with suppress(Exception):
        data = root.evaluate(_COLLECT_FIELDS_JS)
    if not data:
        return False, "The sign-up form could not be read."
    fields = data.get("fields") or []
    roles: dict[str, list[dict[str, Any]]] = {}
    for field in fields:
        role = _field_role(field)
        if role:
            roles.setdefault(role, []).append(field)

    password = password_of(row) or ""
    email = row.email or ""
    username = row.username or ""
    business = _profile_values(project)
    first = re.split(r"[._\-\s]+", username)[0] if username else ""
    values: dict[str, str] = {
        "email": email,
        "username": username,
        "first": first,
        "last": username[len(first) :].strip("._- ") if first else "",
        "name": business.get("name") or username,
        "company": business.get("company") or "",
        "phone": business.get("phone") or "",
        "website": business.get("website") or "",
        "address": "",
        "city": "",
        "zip": "",
        "password": password,
        "confirm": password,
    }

    filled = 0
    for role in (
        "email",
        "username",
        "first",
        "last",
        "name",
        "company",
        "phone",
        "website",
        "address",
        "city",
        "zip",
        "password",
        "confirm",
    ):
        value = values.get(role) or ""
        if not value:
            continue
        for index, field in enumerate(roles.get(role, [])):
            kind = str(field.get("type") or "").lower()
            if kind in ("checkbox", "radio", "file", "hidden"):
                continue
            with suppress(Exception):
                root.fill(field["selector"], value, timeout=6000)
                filled += 1
            if role == "email" and index == 0:
                _use_dot_alias_if_rejected(root, field["selector"], row)

    # A country is usually a <select> and the profile knows the target one.
    country = business.get("country") or ""
    for select_field in data.get("selects") or []:
        label = " ".join(
            str(select_field.get(key) or "") for key in ("label", "name", "id", "aria")
        ).lower()
        if "country" not in label and "nation" not in label:
            continue
        options: list[dict[str, str]] = []
        with suppress(Exception):
            options = root.evaluate(
                "(sel) => Array.from(document.querySelectorAll(sel + ' option'))"
                ".map((o) => ({value: o.value, text: (o.innerText || '').trim()}))",
                select_field["selector"],
            ) or []
        chosen = None
        wanted = country.lower()
        if wanted:
            chosen = next(
                (
                    option
                    for option in options
                    if wanted in option["text"].lower()
                    or option["text"].lower() in wanted
                ),
                None,
            )
        if chosen is None:
            chosen = next(
                (
                    option
                    for option in options
                    if option["value"]
                    and not re.search(r"select|choose|please|^-+$", option["text"], re.I)
                ),
                None,
            )
        if chosen is not None:
            with suppress(Exception):
                root.select_option(select_field["selector"], value=chosen["value"])
                filled += 1

    # A custom country widget (React select and friends): click, type, Enter.
    for combo in data.get("combos") or []:
        label = " ".join(
            str(combo.get(key) or "") for key in ("label", "aria")
        ).lower()
        if "country" not in label and "nation" not in label:
            continue
        if not country:
            continue
        with suppress(Exception):
            root.click(combo["selector"], timeout=4000)
            page.keyboard.type(country, delay=40)
            page.wait_for_timeout(700)
            page.keyboard.press("Enter")
            filled += 1

    if filled == 0:
        return False, "No email, username or password field was recognised."

    # Terms and required consent checkboxes: only check them, never marketing.
    for checkbox in data.get("checkboxes") or []:
        label = str(checkbox.get("label") or "").lower()
        terms = any(word in label for word in _TERMS_WORDS)
        required = bool(checkbox.get("required"))
        marketing = any(
            word in label
            for word in ("newsletter", "marketing", "offers", "promotions", "updates")
        )
        if (terms or required) and not marketing:
            with suppress(Exception):
                root.check(checkbox["selector"], timeout=4000)

    # Required radio groups (Business / Individual ...): pick a real option.
    _check_radios(root)

    # A form can ask for something the profile has no value for (a custom
    # required field).  Submitting would only bounce: stop here and tell the
    # operator exactly which field to type by hand.
    missing = _missing_required(root)
    if missing:
        return False, "These required fields could not be filled by the app: " + (
            ", ".join(missing[:6])
        )

    clicked = _click_submit(root)
    if not clicked:
        with suppress(Exception):
            page.keyboard.press("Enter")
    return True, None


#: The browser's own message for an input whose value it refuses.
_VALIDATION_JS = (
    "(sel) => { const el = document.querySelector(sel);"
    " return el ? (el.validationMessage || '') : ''; }"
)


def _use_dot_alias_if_rejected(page: Any, selector: str, row: SiteAccount) -> None:
    """Some forms refuse the ``+`` of the alias; Gmail ignores dots instead.

    The address that is finally typed becomes ``row.email`` / ``row.otp_alias``,
    so the code waiting still claims only mail addressed to *this* row.
    """
    value = row.email or ""
    if "+" not in value or "@" not in value:
        return
    local, _, domain = value.partition("@")
    fallback = f"{local.replace('+', '.')}@{domain}"
    switched = False
    with suppress(Exception):
        feedback = page.evaluate(_VALIDATION_JS, selector)
        if str(feedback or "").strip():
            page.fill(selector, fallback, timeout=6000)
            still = page.evaluate(_VALIDATION_JS, selector)
            switched = not str(still or "").strip()
    if switched:
        row.email = fallback
        row.otp_alias = fallback


def _click_submit(page: Any) -> bool:
    pattern = "|".join(re.escape(word) for word in _SUBMIT_WORDS)
    with suppress(Exception):
        locator = page.get_by_role(
            "button", name=re.compile(pattern, re.IGNORECASE)
        ).first
        if locator.count() > 0:
            locator.click(timeout=6000)
            return True
    for selector in ("button[type='submit']", "input[type='submit']"):
        with suppress(Exception):
            if page.query_selector(selector) is not None:
                page.click(selector, timeout=6000)
                return True
    return False


_OTP_SELECTOR = (
    "input[autocomplete='one-time-code'], "
    "input[name*='otp' i], input[id*='otp' i], "
    "input[name*='code' i], input[id*='code' i], "
    "input[name*='verification' i]"
)


def _needs_otp(page: Any) -> bool:
    with suppress(Exception):
        if page.query_selector(_OTP_SELECTOR) is not None:
            return True
    text = _body_text(page)
    return any(
        marker in text
        for marker in (
            "verification code",
            "verify your email",
            "check your email",
            "we sent you a code",
            "we sent a code",
            "confirm your email",
            "enter the code",
        )
    )


def _find_login_url(page: Any, base: str) -> str:
    """The sign-in page of the site (or a sensible guess)."""
    with suppress(Exception):
        marked = page.evaluate(
            """
            () => {
              const words = /(log\\s*in|sign\\s*in|login|signin|my\\s*account|account)/i;
              for (const el of document.querySelectorAll('a[href], button')) {
                const text = (el.innerText || el.value || '').trim();
                if (!text || text.length > 50) continue;
                if (/(log\\s*out|sign\\s*out|register|sign\\s*up)/i.test(text)) continue;
                const href = el.getAttribute('href') || '';
                if (!words.test(text) && !/(login|signin|sign-in|log-in)/i.test(href)) continue;
                if (href && !href.startsWith('#') && !href.startsWith('javascript')) {
                  return el.href;
                }
                el.setAttribute('data-abk-login', '1');
                return '';
              }
              return '';
            }
            """
        )
    if marked:
        return str(marked)
    with suppress(Exception):
        if page.query_selector("[data-abk-login='1']") is not None:
            with page.context.expect_page(timeout=5000) as info:
                page.click("[data-abk-login='1']", timeout=5000)
            return info.value.url
    parsed = re.match(r"^(https?://[^/]+)", base or "")
    origin = parsed.group(1) if parsed else base
    return f"{origin}/login" if origin else base


def _login_existing(page: Any, row: SiteAccount, website: Website) -> bool:
    """Log in with the stored credentials (after sign-up or a session loss)."""
    email = (row.email or "").strip()
    username = (row.username or "").strip()
    password = password_of(row) or ""
    if not password or not (email or username):
        return False
    login_url = "" if _has_password_form(page) else _find_login_url(page, website.opportunity_url)
    if login_url and login_url.rstrip("/") != (page.url or "").rstrip("/"):
        with suppress(Exception):
            page.goto(login_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            page.wait_for_timeout(1200)
    with suppress(Exception):
        if page.query_selector("input[type='password']:visible") is None:
            return False
    with suppress(Exception):
        data = page.evaluate(_COLLECT_FIELDS_JS) or {}
    roles: dict[str, list[dict[str, Any]]] = {}
    for field in data.get("fields") or []:
        role = _field_role(field)
        if role:
            roles.setdefault(role, []).append(field)
    password_field = next(
        (field for field in roles.get("password", []) if field.get("type") == "password"),
        None,
    )
    login_field = next(
        (
            field
            for role in ("email", "username", "name")
            for field in roles.get(role, [])
        ),
        None,
    )
    if password_field is None or login_field is None:
        return False
    with suppress(Exception):
        page.fill(login_field["selector"], email or username, timeout=6000)
        page.fill(password_field["selector"], password, timeout=6000)
        _click_submit(page)
        page.wait_for_timeout(4500)
    return _logged_in(page)


def _success(page: Any, before_url: str) -> bool:
    if _logged_in(page):
        return True
    text = _body_text(page)
    if any(word in text for word in _SUCCESS_WORDS):
        return True
    with suppress(Exception):
        url = page.url
        if url != before_url and not re.search(r"(signup|sign-up|register|create-account)", url, re.I):
            return True
    return False


def _screenshot(page: Any, project_id: str, website_id: str) -> str | None:
    directory = settings.managed_files_dir / "accounts"
    with suppress(OSError):
        directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{project_id}-{website_id}-{int(time.time())}.png"
    try:
        page.screenshot(path=str(path), full_page=False)
    except Exception:
        return None
    return str(path)


def _remember_login(db: Session, context: Any, project_id: str, website_id: str) -> None:
    """Export the session of the whole batch into the project profile."""
    with suppress(Exception):
        state = context.storage_state()
        project_login.save_storage_state(db, project_id, state)
    project_login.mark_site(
        db,
        project_id,
        website_id,
        project_login.SITE_CONNECTED,
        method="ACCOUNT",
        evidence={"created_by": "site_accounts"},
    )


# --------------------------------------------------------------------------
# One website
# --------------------------------------------------------------------------
def _set_row(
    db: Session,
    row: SiteAccount,
    status: str,
    *,
    message: str | None = None,
    error: str | None = None,
    strategy: str | None = None,
) -> None:
    row.status = status
    if strategy:
        row.strategy = strategy
    row.last_error = error
    db.commit()
    _update_item(
        row.project_id,
        row.website_id,
        status=status,
        message=message or error or status.replace("_", " ").title(),
        strategy=row.strategy,
    )


def _provision_site(
    db: Session,
    context: Any,
    project: Project,
    website: Website,
    row: SiteAccount,
    inbox: Any | None,
    gmail_address: str | None,
    *,
    details: dict[str, Any] | None = None,
    fallback_inbox: Any | None = None,
) -> None:
    page = _page_for(context)
    started_at = utcnow()
    row.attempts += 1
    _set_row(db, row, STATUS_DETECTING, message="Opening the website…")

    try:
        page.goto(website.opportunity_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        page.wait_for_timeout(1200)
    except Exception as exc:
        _set_row(
            db,
            row,
            STATUS_FAILED,
            error=f"The website could not be opened: {exc}",
            message="The website could not be opened.",
        )
        return

    challenge = _challenge(page)
    if challenge == "CAPTCHA":
        _set_row(
            db,
            row,
            STATUS_NEEDS_HUMAN,
            error="A CAPTCHA asked for a human. Solve it once in the live browser, then retry this row.",
            message="CAPTCHA - solve it once in the live browser.",
        )
        return

    # Read the site's own code before guessing any route: what it is, where
    # its sign-up lives and whether a public form already accepts a link.
    intel = site_intel.inspect(page)
    if intel.get("url"):
        row.site_intel = site_intel.brief(intel)
        db.commit()
        if intel.get("platform") and intel.get("platform") != "unknown":
            _update_item(
                project.id,
                website.id,
                message=(
                    f"Read the site: {site_intel.label(intel)} - looking for "
                    "its sign-up or public form…"
                ),
            )

    # Already signed in (a previous run or the operator did it).
    if _logged_in(page):
        row.strategy = STRATEGY_EXISTING
        row.account_url = page.url
        row.login_url = page.url
        _remember_login(db, context, project.id, website.id)
        _set_row(db, row, STATUS_ACTIVE, message="Already signed in.", strategy=STRATEGY_EXISTING)
        _store_target(db, context, project, website, row)
        _post_backlink(db, context, project, website, row)
        return

    # No account exists on this site, but its own form accepts a link.
    if intel.get("plan") == "DIRECT":
        _direct_post(db, context, project, website, row, intel)
        return

    # --- Continue with Google -------------------------------------------
    oauth_page, clicked = _click_google(page, context)
    if clicked:
        row.strategy = STRATEGY_GOOGLE
        _update_item(project.id, website.id, strategy=STRATEGY_GOOGLE, message="Signing in with Google…")
        email = gmail_address or ""
        project_email = ""
        with suppress(Exception):
            profile = project_login.get_profile(db, project.id)
            project_email = (profile.email if profile is not None else "") or ""
        outcome, message = _finish_google(
            oauth_page, context, email=project_email or email
        )
        if outcome == "ok":
            page = _page_for(context)
            page.wait_for_timeout(1500)
            row.login_url = page.url
            if not _confirm_login(page, website.opportunity_url):
                path = _screenshot(page, project.id, website.id)
                row.evidence = {**(row.evidence or {}), "screenshot": path}
                db.commit()
                _set_row(
                    db,
                    row,
                    STATUS_NEEDS_HUMAN,
                    error=(
                        "Google returned to the website but no signed in state "
                        "appeared. Open the site once, finish the last step, then "
                        "press Retry."
                    ),
                    message="Google returned - confirm the account once.",
                    strategy=STRATEGY_GOOGLE,
                )
                return
            row.account_url = page.url
            _remember_login(db, context, project.id, website.id)
            _set_row(
                db,
                row,
                STATUS_ACTIVE,
                message="Account created with Google.",
                strategy=STRATEGY_GOOGLE,
            )
            _store_target(db, context, project, website, row)
            _post_backlink(db, context, project, website, row)
            return
        if outcome == "human":
            _set_row(
                db,
                row,
                STATUS_NEEDS_HUMAN,
                error=message,
                message=message,
                strategy=STRATEGY_GOOGLE,
            )
            return
        _set_row(
            db,
            row,
            STATUS_FAILED,
            error=message or "The Google sign-in failed.",
            message="The Google sign-in failed.",
            strategy=STRATEGY_GOOGLE,
        )
        return

    # --- Sign-up form ----------------------------------------------------
    row.strategy = STRATEGY_SIGNUP
    details = details or {}
    chosen_username = str(details.get("username") or "").strip()
    chosen_password = str(details.get("password") or "")
    if chosen_username:
        row.username = chosen_username
    if not row.username:
        row.username = generate_username(website, project)
    if chosen_password:
        set_password(row, chosen_password)
    if not row.password_encrypted:
        set_password(row, generate_password())
    base_email = str(details.get("email") or "").strip() or (gmail_address or "").strip()
    if base_email:
        token = gmail_otp.alias_token(project.id, website.id)
        current = (row.email or "").strip()
        base_local = base_email.split("@", 1)[0].lower()
        current_local = current.split("@", 1)[0].lower() if "@" in current else ""
        # A Gmail address gets a per-website plus alias so a code can never
        # land in another row.  Any other address is used exactly as typed.
        if "@gmail.com" in base_email.lower() or "@googlemail.com" in base_email.lower():
            alias = gmail_otp.alias_for(base_email, token)
            if current_local.startswith(base_local) and len(current_local) > len(base_local):
                row.otp_alias = current
            else:
                row.email = alias
                row.otp_alias = alias
        else:
            if not current_local:
                row.email = base_email
            row.otp_alias = row.email or base_email
    db.commit()
    _update_item(
        project.id,
        website.id,
        strategy=STRATEGY_SIGNUP,
        message="Signing up with your username and password…",
    )

    links, clickables = _signup_entry_points(page)
    fallback_url = page.url
    seen_urls: set[str] = set()
    opened = False
    intel_links = [str(url) for url in intel.get("signup_urls") or [] if url]
    for candidate in [
        *intel_links,
        *links,
        *_signup_candidates(website.opportunity_url),
    ]:
        if not candidate or candidate in seen_urls:
            continue
        seen_urls.add(candidate)
        if candidate != page.url:
            with suppress(Exception):
                page.goto(candidate, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                page.wait_for_timeout(1200)
        _dismiss_overlays(page)
        if _wait_for_signup_form(page):
            opened = True
            break

    if not opened and clickables:
        # The form lives behind a modal / tab, so a link alone is not enough.
        if fallback_url and page.url != fallback_url:
            with suppress(Exception):
                page.goto(fallback_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                page.wait_for_timeout(1200)
        for root in clickables:
            opened_url = ""
            with suppress(Exception):
                opened_url = _click_signup_entry(page, root)
            page.wait_for_timeout(1500)
            _dismiss_overlays(page)
            if opened_url and opened_url != page.url:
                with suppress(Exception):
                    page.goto(opened_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                    page.wait_for_timeout(1200)
            if _wait_for_signup_form(page):
                opened = True
                break
            if fallback_url and page.url != fallback_url:
                with suppress(Exception):
                    page.goto(fallback_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                    page.wait_for_timeout(1200)

    if not opened and fallback_url and page.url != fallback_url:
        # No guess showed a real form: return to the page we started from and
        # let the normal "no sign-up form" report explain it.
        with suppress(Exception):
            page.goto(fallback_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            page.wait_for_timeout(1200)
    row.login_url = page.url

    if not opened and intel.get("direct"):
        # No sign-up at all, but the site's own form already takes a link.
        _direct_post(db, context, project, website, row, intel)
        return

    challenge = _challenge(page)
    if challenge == "CAPTCHA":
        _set_row(
            db,
            row,
            STATUS_NEEDS_HUMAN,
            error="A CAPTCHA asked for a human on the sign-up form. Solve it once in the live browser, then retry this row.",
            message="CAPTCHA - solve it once in the live browser.",
        )
        return

    _dismiss_overlays(page)
    filled, reason = _fill_signup(page, row, project)
    if not filled:
        found = site_intel.explain(intel) if not opened else ""
        _set_row(
            db,
            row,
            STATUS_NEEDS_HUMAN,
            error=(
                f"{reason or 'No sign-up form was found on this website.'} "
                f"{found} ".strip()
                + " Open the site from this row, type the username, password and "
                "e-mail shown here yourself, then press Retry."
            ),
            message="Sign-up form not filled - open the site and finish it by hand.",
        )
        return

    _set_row(db, row, STATUS_CREATING, message="Submitting the sign-up form…")
    page.wait_for_timeout(4500)

    if _challenge(page) == "CAPTCHA":
        _set_row(
            db,
            row,
            STATUS_NEEDS_HUMAN,
            error="A CAPTCHA appeared after submitting the form. Solve it once in the live browser, then retry this row.",
            message="CAPTCHA after submit - solve it once.",
        )
        return

    # A sign-up is often two or three steps (account, then a profile detail).
    # Fill whatever the next step asks for with the same values, but never
    # submit the same form forever: at most three extra steps.
    for step in range(3):
        if _needs_otp(page):
            break
        if not _has_empty_required(page):
            break
        _update_item(
            project.id,
            website.id,
            message=f"Filling step {step + 2} of the sign-up form…",
        )
        _dismiss_overlays(page)
        with suppress(Exception):
            if not _fill_signup(page, row, project)[0]:
                break
            page.wait_for_timeout(4000)

    # --- OTP / confirmation link -----------------------------------------
    if _needs_otp(page):
        _set_row(db, row, STATUS_OTP_PENDING, message="Waiting for the e-mail…")
        readers = [reader for reader in (inbox, fallback_inbox) if reader is not None]
        if not readers or not row.otp_alias:
            _set_row(
                db,
                row,
                STATUS_NEEDS_HUMAN,
                error=(
                    "The site asks for an e-mail code, but the project's Gmail is "
                    "not signed in and no App Password inbox is configured for "
                    "this row."
                ),
                message="E-mail code needed - connect Google or add a Gmail App Password.",
            )
            return
        has_field = False
        with suppress(Exception):
            has_field = page.query_selector(_OTP_SELECTOR) is not None
        found: gmail_otp.OtpCode | None = None
        otp_reason: str | None = None
        for position, reader in enumerate(readers):
            # The Gmail tab of the session is the first choice; the App
            # Password inbox is only a shorter fallback.
            wait = OTP_TIMEOUT_SECONDS if position == 0 else FALLBACK_OTP_SECONDS
            if not has_field and isinstance(reader, gmail_otp.BrowserInbox):
                # The page says "check your email" but shows no field: the mail
                # may carry either a code or a confirmation link.
                found, otp_reason = reader.wait_for_code_or_link(
                    alias=row.otp_alias,
                    since=started_at,
                    site_domain=website.domain,
                    timeout=wait,
                )
            else:
                found, otp_reason = reader.wait_for_code(
                    alias=row.otp_alias,
                    since=started_at,
                    site_domain=website.domain,
                    timeout=wait,
                )
            if found is not None:
                break
        if found is None:
            row.otp_state = OTP_EXPIRED
            db.commit()
            _set_row(
                db,
                row,
                STATUS_NEEDS_HUMAN,
                error=otp_reason or "No code arrived for this address.",
                message=otp_reason or "No code arrived - enter it by hand.",
            )
            return
        if found.link:
            _update_item(
                project.id,
                website.id,
                message="Opening the confirmation link from the e-mail…",
            )
            link_page = None
            try:
                link_page = context.new_page()
                link_page.goto(
                    found.link,
                    wait_until="domcontentloaded",
                    timeout=NAV_TIMEOUT_MS,
                )
                link_page.wait_for_timeout(2500)
            except Exception as exc:
                _set_row(
                    db,
                    row,
                    STATUS_NEEDS_HUMAN,
                    error=f"The confirmation link could not be opened: {exc}",
                    message="Confirmation link - open the mail once.",
                )
                return
            finally:
                if link_page is not None:
                    with suppress(Exception):
                        link_page.close()
            # Reload the site in the same session: the account is confirmed
            # now, and the signed-in check below is the real proof.
            with suppress(Exception):
                page.goto(
                    row.login_url or website.opportunity_url,
                    wait_until="domcontentloaded",
                    timeout=NAV_TIMEOUT_MS,
                )
                page.wait_for_timeout(1500)
            row.otp_state = OTP_USED
            row.otp_used_at = utcnow()
            db.commit()
        else:
            set_otp(row, found.code, found.message_id)
            db.commit()
            _update_item(
                project.id, website.id, message=f"Code received ({found.matched_by})."
            )
            filled_code = False
            with suppress(Exception):
                selector = page.query_selector(_OTP_SELECTOR)
                if selector is not None:
                    selector.fill(found.code, timeout=6000)
                    filled_code = True
            if not filled_code:
                # Some sites show the six boxes of a code separately.
                with suppress(Exception):
                    boxes = page.query_selector_all(
                        "input[inputmode='numeric'], input[maxlength='1']"
                    )
                    if len(boxes) >= 4:
                        for box, digit in zip(boxes, found.code, strict=False):
                            box.fill(digit, timeout=3000)
                        filled_code = True
            if not filled_code:
                _set_row(
                    db,
                    row,
                    STATUS_NEEDS_HUMAN,
                    error="The code arrived but the page has no code field. Enter it in the live browser.",
                    message="Code arrived - the field is not recognised.",
                )
                return
            _click_submit(page)
            page.wait_for_timeout(4500)
            row.otp_state = OTP_USED
            row.otp_used_at = utcnow()
            db.commit()

    # --- Result ----------------------------------------------------------
    if _challenge(page) == "CAPTCHA":
        _set_row(
            db,
            row,
            STATUS_NEEDS_HUMAN,
            error="A CAPTCHA appeared after the code. Solve it once in the live browser, then retry this row.",
            message="CAPTCHA after the code - solve it once.",
        )
        return

    success_seen = _success(page, row.login_url or website.opportunity_url)
    signed_in = _logged_in(page)
    if not signed_in and (success_seen or _has_password_form(page)):
        # The account exists but the site did not keep the session: sign in
        # with exactly the credentials shown on the row.
        _update_item(
            project.id, website.id, message="Signing in with the created account…"
        )
        with suppress(Exception):
            signed_in = _login_existing(page, row, website)

    if not success_seen and not signed_in:
        path = _screenshot(page, project.id, website.id)
        row.evidence = {**(row.evidence or {}), "screenshot": path}
        db.commit()
        _set_row(
            db,
            row,
            STATUS_NEEDS_HUMAN,
            error=(
                "The form was submitted but no success signal appeared. "
                "Open the site once and finish the last step (it may ask for a "
                "confirmation or a profile detail)."
            ),
            message="Submitted - the site did not confirm the account yet.",
        )
        return

    # A real login check: reload the site and look for a signed-in control.
    # Only then is the row called "active" - a welcome page alone is not proof.
    confirmed = _confirm_login(page, website.opportunity_url)
    if not confirmed:
        path = _screenshot(page, project.id, website.id)
        row.evidence = {**(row.evidence or {}), "screenshot": path}
        db.commit()
        _set_row(
            db,
            row,
            STATUS_NEEDS_HUMAN,
            error=(
                "The sign-up went through but the site did not show a signed in "
                "state. Open the site once - it may still need an e-mail "
                "confirmation or a first profile step - then press Retry."
            ),
            message="Account may exist - confirm it once in the live browser.",
        )
        return

    row.account_url = page.url
    _remember_login(db, context, project.id, website.id)
    _set_row(
        db,
        row,
        STATUS_ACTIVE,
        message="Account created with username and password.",
        strategy=STRATEGY_SIGNUP,
    )
    _store_target(db, context, project, website, row)
    _post_backlink(db, context, project, website, row)


def _confirm_login(page: Any, base_url: str) -> bool:
    """Reload the site and require a real signed-in control.

    Google sign-in and the sign-up path both end here, so "the account was
    created" is never reported from a success banner alone.
    """
    if _logged_in(page):
        return True
    parsed = re.match(r"^(https?://[^/]+)", base_url or "")
    origin = parsed.group(1) if parsed else base_url
    if not origin:
        return False
    try:
        page.goto(origin, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        page.wait_for_timeout(1200)
    except Exception:
        return False
    return _logged_in(page)


def _store_target(
    db: Session, context: Any, project: Project, website: Website, row: SiteAccount
) -> None:
    """Find and store the page where the backlink can be placed."""
    _update_item(project.id, website.id, message="Looking for the backlink page…")
    try:
        result = backlink_target.discover(
            context, website, start_url=row.account_url or website.opportunity_url
        )
    except Exception as exc:  # pragma: no cover - browser dependent
        log.warning("backlink discovery failed", extra={"extra_fields": {"error": str(exc)}})
        return
    if not result.get("found"):
        _update_item(
            project.id,
            website.id,
            message="Account ready - backlink page not found yet.",
        )
        return
    row.backlink_url = result.get("url")
    row.backlink_form = {
        "fields": result.get("fields") or [],
        "buttons": result.get("buttons") or [],
        "reasons": result.get("reasons") or [],
    }
    row.backlink_confidence = int(result.get("confidence") or 0)
    row.backlink_found_at = utcnow()
    db.commit()
    _update_item(
        project.id,
        website.id,
        message=f"Account ready - backlink page found ({row.backlink_confidence}%).",
    )


def _record_backlink(
    db: Session,
    project: Project,
    row: SiteAccount,
    *,
    published_url: str,
    landing: str,
) -> None:
    """Queue the posted link for the normal verification engine."""
    existing = db.execute(
        select(BacklinkRecord).where(
            BacklinkRecord.project_id == project.id,
            BacklinkRecord.published_page_url == published_url,
            BacklinkRecord.expected_destination_url == landing,
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            BacklinkRecord(
                project_id=project.id,
                target_website=published_url[:500],
                expected_link_url=published_url,
                published_page_url=published_url,
                expected_destination_url=landing,
                verification_status="PUBLISHED_UNVERIFIED",
                next_verification_at=utcnow(),
                evidence={
                    "source": "site_account",
                    "account_id": row.id,
                    "account_url": row.account_url,
                    "reasons": (row.backlink_form or {}).get("reasons") or [],
                },
            )
        )
    else:
        existing.next_verification_at = utcnow()


def _direct_post(
    db: Session,
    context: Any,
    project: Project,
    website: Website,
    row: SiteAccount,
    intel: dict[str, Any],
) -> None:
    """Post on a site that has no account: its own form already takes a link.

    The inspection found a page with a URL field that works for a visitor
    (a guest comment form, a public submission form).  Nothing is created, so
    the row is reported with the ``DIRECT`` strategy and the honest state of
    the post.
    """
    direct = intel.get("direct") or {}
    target = str(direct.get("url") or row.account_url or website.opportunity_url)
    row.strategy = STRATEGY_DIRECT
    row.account_url = target
    row.backlink_url = target
    row.backlink_form = {
        "fields": [
            {"name": str(name), "type": "text"} for name in direct.get("fields") or []
        ],
        "buttons": [],
        "reasons": [str(direct.get("kind") or "anonymous form")],
    }
    row.backlink_confidence = 70
    row.backlink_found_at = utcnow()
    row.backlink_status = backlink_post.STATUS_NONE
    row.backlink_note = None
    _remember_login(db, context, project.id, website.id)
    _set_row(
        db,
        row,
        STATUS_ACTIVE,
        message=f"No account needed - posting through the site's {direct.get('kind') or 'public form'}.",
        strategy=STRATEGY_DIRECT,
    )
    _post_backlink(db, context, project, website, row)


def _post_backlink(
    db: Session,
    context: Any,
    project: Project,
    website: Website,
    row: SiteAccount,
) -> str:
    """Post the link from the fresh account, honestly.

    A successful sign-up is not the same as a posted backlink: this step only
    reports ``POSTED``/``VERIFIED`` when the live page proves it.  A CAPTCHA or
    an unknown required field leaves the account active and marks the post as
    ``NEEDS_HUMAN`` with the exact reason, so one row never blocks the batch.
    """
    if row.backlink_status == backlink_post.STATUS_VERIFIED:
        return row.backlink_status
    if (
        row.backlink_status == backlink_post.STATUS_POSTED
        and row.backlink_published_url
    ):
        return row.backlink_status
    if not row.backlink_url:
        row.backlink_status = backlink_post.STATUS_NEEDS_HUMAN
        row.backlink_note = (
            "No page with a link field was found while logged in. Open the "
            "account once and use its profile / listing editor, then retry."
        )
        db.commit()
        _update_item(
            project.id,
            website.id,
            message="Account ready - no link form was found; open the site once.",
        )
        return row.backlink_status
    target = row.backlink_url
    values = backlink_post.build_values(
        project,
        website,
        row,
        landing_url=str(getattr(project, "target_website", "") or ""),
    )
    if not values.get("link"):
        row.backlink_status = backlink_post.STATUS_NEEDS_HUMAN
        row.backlink_note = (
            "The project has no target website, so there is no link to place. "
            "Add the website in the project details."
        )
        db.commit()
        return row.backlink_status
    _update_item(project.id, website.id, message="Posting the backlink…")
    page = None
    try:
        page = context.new_page()
        result = backlink_post.post(
            page,
            target_url=target,
            values=values,
            challenge=lambda: _challenge(page),
        )
    except Exception as exc:  # pragma: no cover - browser dependent
        log.warning(
            "posting the backlink failed",
            extra={"extra_fields": {"project_id": project.id, "website_id": website.id}},
        )
        row.backlink_status = backlink_post.STATUS_NEEDS_HUMAN
        row.backlink_note = f"The backlink page could not be used: {exc}"
        db.commit()
        return row.backlink_status
    finally:
        if page is not None:
            with suppress(Exception):
                page.close()

    status = str(result.get("status") or backlink_post.STATUS_NEEDS_HUMAN)
    row.backlink_status = status
    row.backlink_note = result.get("message")
    published = str(result.get("published_url") or "")
    if status in (backlink_post.STATUS_POSTED, backlink_post.STATUS_VERIFIED):
        # Only a real post gets a tracking link; a page that merely stopped
        # must never look like a published backlink.
        row.backlink_published_url = published or target
    else:
        row.backlink_published_url = None
    if status in (backlink_post.STATUS_POSTED, backlink_post.STATUS_VERIFIED):
        row.evidence = {
            **(row.evidence or {}),
            "backlink": {
                "status": status,
                "published_url": published,
                "reasons": result.get("reasons") or [],
            },
        }
        _record_backlink(
            db,
            project,
            row,
            published_url=published or target,
            landing=values["link"],
        )
    db.commit()
    if status == backlink_post.STATUS_VERIFIED:
        _update_item(
            project.id, website.id, message="Backlink posted and verified on the live page."
        )
    elif status == backlink_post.STATUS_POSTED:
        _update_item(
            project.id, website.id, message="Backlink posted - waiting for the site to publish it."
        )
    else:
        _update_item(
            project.id,
            website.id,
            message="Account ready - the backlink needs you: open the site and finish it once.",
        )
    return status


# --------------------------------------------------------------------------
# The batch thread
# --------------------------------------------------------------------------
def _run_batch(project_id: str, website_ids: list[str]) -> None:
    db = session_scope()
    browser: _Browser | None = None
    inbox: gmail_otp.OtpInbox | None = None
    web_inbox: gmail_otp.BrowserInbox | None = None
    try:
        project = db.get(Project, project_id)
        if project is None:
            return
        details = signup_details(db, project_id)
        gmail = gmail_otp.read_settings(db)
        if gmail is not None:
            try:
                inbox = gmail_otp.OtpInbox(gmail)
                inbox.open()
            except Exception as exc:
                inbox = None
                log.warning(
                    "the Gmail session could not be opened",
                    extra={"extra_fields": {"error": str(exc)}},
                )
                _update_batch(
                    project_id,
                    message=(
                        "The App Password inbox could not be opened - codes will "
                        "be read from the Gmail tab of the browser."
                    ),
                )

        headless = _headless()
        try:
            browser = _open_browser(project_id, headless=headless)
        except Exception as exc:
            _update_batch(
                project_id,
                running=False,
                finished_at=utcnow(),
                error=f"The browser could not be opened: {exc}",
                message="The browser could not be opened.",
            )
            for website_id in website_ids:
                _update_item(
                    project_id,
                    website_id,
                    status=STATUS_FAILED,
                    message="The browser could not be opened.",
                )
            return

        _update_batch(project_id, message="Browser ready - working through the websites.")

        # The sign-ups must use the Gmail of the project's Google login.  The
        # address is read once from the account page (the same session the
        # sites see) and remembered when the profile had none.
        google_email = login_browser.detect_google_email(browser.context) or ""
        profile = project_login.get_profile(db, project_id)
        if google_email and profile is not None and not (profile.email or "").strip():
            profile.email = google_email
            db.commit()
        if not google_email and profile is not None:
            google_email = (profile.email or "").strip()
        signup_email = str(details.get("email") or "").strip() or google_email
        connected = bool(profile is not None and profile.status == project_login.STATUS_CONNECTED)
        if connected:
            web_inbox = gmail_otp.BrowserInbox(
                browser.context,
                signup_email or (gmail.address if gmail is not None else ""),
            )
        if not signup_email and gmail is not None:
            signup_email = gmail.address

        for index, website_id in enumerate(website_ids):
            if _stopped(project_id):
                _update_batch(project_id, message="Stopped by the operator.")
                break
            website = db.get(Website, website_id)
            row = get_account(db, project_id, website_id)
            if website is None or row is None:
                continue
            _update_batch(
                project_id,
                active_website_id=website.id,
                active_name=website.name or website.domain,
                message=f"{website.name or website.domain}: opening…",
            )
            try:
                _provision_site(
                    db,
                    browser.context,
                    project,
                    website,
                    row,
                    web_inbox if web_inbox is not None else inbox,
                    signup_email,
                    details=details,
                    fallback_inbox=inbox if web_inbox is not None else None,
                )
            except Exception as exc:  # pragma: no cover - defensive
                db.rollback()
                log.exception("provisioning a website failed")
                row = get_account(db, project_id, website_id) or row
                _set_row(
                    db,
                    row,
                    STATUS_FAILED,
                    error=f"The account could not be created: {exc}",
                    message="The account could not be created.",
                )
            if index < len(website_ids) - 1:
                _pause()
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("the account batch failed")
        _update_batch(
            project_id,
            running=False,
            finished_at=utcnow(),
            error=str(exc),
            message="The batch stopped unexpectedly.",
        )
        return
    finally:
        if web_inbox is not None:
            with suppress(Exception):
                web_inbox.close()
        if inbox is not None:
            with suppress(Exception):
                inbox.close()
        if browser is not None:
            with suppress(Exception):
                state = browser.context.storage_state()
                project_login.save_storage_state(db, project_id, state)
        if browser is not None:
            browser.close()
        with _LOCK:
            batch = _BATCHES.get(project_id)
            if batch is not None:
                batch["running"] = False
                batch["finished_at"] = utcnow()
                batch["active_website_id"] = None
                batch["active_name"] = None
                if not batch.get("error"):
                    batch["message"] = "Batch finished."
        db.close()


# --------------------------------------------------------------------------
# Single actions
# --------------------------------------------------------------------------
def discover_target(db: Session, project: Project, website: Website) -> dict[str, Any]:
    """Re-run the backlink target search for one website (authenticated)."""
    from app.services.browser import ensure_playwright_path

    ensure_playwright_path()
    from playwright.sync_api import sync_playwright

    if batch_state(project.id)["running"]:
        raise RuntimeError(
            "The account batch is still running. Wait until it finishes (or press "
            "Stop accounts) before searching a page again."
        )
    if login_browser.is_open(project.id):
        raise RuntimeError(
            "The login window of this project is open. Close it before searching a page."
        )
    row = ensure_account(db, project.id, website.id)
    state = project_login.load_storage_state(db, project.id)
    directory = project_login.ensure_profile_dir(project.id)
    login_browser.clear_stale_profile_lock(directory)
    with sync_playwright() as playwright:
        headless = _headless()
        context = playwright.chromium.launch_persistent_context(
            str(directory),
            headless=headless,
            storage_state=state,
            args=list(browser_service.ISOLATION_ARGS),
            viewport={
                "width": settings.login_stream_width,
                "height": settings.login_stream_height,
            },
        )
        try:
            result = backlink_target.discover(
                context, website, start_url=row.account_url or website.opportunity_url
            )
        finally:
            with suppress(Exception):
                context.close()

    if result.get("found"):
        row.backlink_url = result.get("url")
        row.backlink_form = {
            "fields": result.get("fields") or [],
            "buttons": result.get("buttons") or [],
            "reasons": result.get("reasons") or [],
        }
        row.backlink_confidence = int(result.get("confidence") or 0)
        row.backlink_found_at = utcnow()
    db.commit()
    return result


def counts_for_project(db: Session, project_id: str) -> dict[str, int]:
    rows = (
        db.execute(select(SiteAccount).where(SiteAccount.project_id == project_id))
        .scalars()
        .all()
    )
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    return counts


__all__ = [
    "ACTIVE_STATUSES",
    "STATUS_ACTIVE",
    "STATUS_FAILED",
    "STATUS_NEEDS_HUMAN",
    "account_payload",
    "batch_state",
    "counts_for_project",
    "discover_target",
    "ensure_account",
    "generate_password",
    "generate_username",
    "get_account",
    "password_of",
    "set_password",
    "start_batch",
    "stop_batch",
]
