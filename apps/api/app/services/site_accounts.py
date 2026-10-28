"""Accounts and backlink targets for every website of a project.

The flow of one project:

1. **One click** provisions every website in a single batch.  The batch opens
   the isolated profile of the project **once**, so the Google session and the
   cookies of the sites are reused and the inbox is opened **once** as well.
2. For each website the service decides the strategy from the live page:
   * a *Continue with Google* button -> the project's Google session is used,
   * otherwise the sign-up form is filled with a generated username and a
     strong password (both stored encrypted and shown on the row of the
     report).
3. If the sign-up asks for a code, the row receives its **own** address alias
   (``inbox+token@gmail.com``) and only a mail addressed to that token is
   accepted.  A code is claimed once and bound to its row.
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
from app.db.models import Opportunity, Project, SiteAccount, Website
from app.db.session import session_scope
from app.services import backlink_target, gmail_otp, login_browser, project_login
from app.services import browser as browser_service

log = get_logger(__name__)

STRATEGY_GOOGLE = "GOOGLE"
STRATEGY_SIGNUP = "SIGNUP"
STRATEGY_EXISTING = "EXISTING"
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
) -> dict[str, Any]:
    """Provision the accounts of a project in one background batch."""
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


def _find_signup_url(page: Any, base: str) -> str:
    with suppress(Exception):
        marked = page.evaluate(
            """
            () => {
              const pattern = /(sign\\s*up|signup|register|create\\s+(an\\s+)?account|join)/i;
              for (const el of document.querySelectorAll('a, button, [role=button]')) {
                const text = (el.innerText || el.value || '').trim();
                if (text.length > 60 || !pattern.test(text)) continue;
                const href = el.getAttribute('href') || '';
                if (!href || href.startsWith('#') || href.startsWith('javascript')) {
                  el.setAttribute('data-abk-signup', '1');
                  return '';
                }
                el.setAttribute('data-abk-signup', '1');
                return el.href;
              }
              return '';
            }
            """
        )
    if marked:
        return str(marked)
    with suppress(Exception):
        if page.query_selector("[data-abk-signup='1']") is not None:
            with suppress(Exception):
                with page.context.expect_page(timeout=5000) as info:
                    page.click("[data-abk-signup='1']", timeout=5000)
                return info.value.url
            return page.url
    parsed = re.match(r"^(https?://[^/]+)", base or "")
    origin = parsed.group(1) if parsed else base
    return f"{origin}/signup" if origin else base


def _field_role(field: dict[str, Any]) -> str:
    raw = " ".join(
        str(field.get(key) or "")
        for key in ("name", "id", "placeholder", "label", "autocomplete")
    ).lower()
    text = re.sub(r"[_\-\[\]]+", " ", raw)
    if field.get("type") == "password":
        return "password"
    if "confirm" in text or "repeat" in text or "again" in text:
        return "confirm"
    if "email" in text or "e-mail" in text:
        return "email"
    if any(word in text for word in ("username", "user name", "login", "handle", "nickname", "screen name")):
        return "username"
    if "first name" in text or "last name" in text or text.strip() in ("name", "full name", "your name"):
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
  for (const el of document.querySelectorAll('input, textarea')) {
    if (!visible(el)) continue;
    const type = (el.getAttribute('type') || el.tagName).toLowerCase();
    if (['hidden', 'submit', 'button', 'reset', 'file', 'image'].includes(type)) continue;
    const name = el.getAttribute('name') || '';
    const id = el.id || '';
    let selector = '';
    if (id) selector = '#' + CSS.escape(id);
    else if (name) selector = el.tagName.toLowerCase() + '[name="' + CSS.escape(name) + '"]';
    if (!selector) continue;
    out.push({
      selector, name, id, type,
      placeholder: el.getAttribute('placeholder') || '',
      autocomplete: el.getAttribute('autocomplete') || '',
      label: labelFor(el),
    });
  }
  const checkboxes = Array.from(document.querySelectorAll('input[type=checkbox]'))
    .filter(visible)
    .map((el) => {
      const label = labelFor(el);
      let selector = el.id ? '#' + CSS.escape(el.id)
        : (el.getAttribute('name') ? 'input[name="' + CSS.escape(el.getAttribute('name')) + '"]' : '');
      return {selector, label, checked: el.checked};
    })
    .filter((item) => item.selector);
  return {fields: out, checkboxes, text: document.body ? document.body.innerText.slice(0, 6000) : ''};
}
"""


def _fill_signup(page: Any, row: SiteAccount, project: Project) -> tuple[bool, str | None]:
    with suppress(Exception):
        data = page.evaluate(_COLLECT_FIELDS_JS)
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
    filled = 0
    for role, value in (
        ("email", email),
        ("username", username),
        ("name", username),
        ("password", password),
        ("confirm", password),
    ):
        if not value:
            continue
        for index, field in enumerate(roles.get(role, [])):
            if role == "password" and index > 0:
                continue
            with suppress(Exception):
                page.fill(field["selector"], value, timeout=6000)
                filled += 1
            if role == "email" and index == 0:
                _use_dot_alias_if_rejected(page, field["selector"], row)
    if filled == 0:
        return False, "No email, username or password field was recognised."

    # Terms checkbox: only check the ones that mention terms / privacy.
    for checkbox in data.get("checkboxes") or []:
        label = str(checkbox.get("label") or "").lower()
        if any(word in label for word in _TERMS_WORDS):
            with suppress(Exception):
                page.check(checkbox["selector"], timeout=4000)
            break

    clicked = _click_submit(page)
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
    inbox: gmail_otp.OtpInbox | None,
    gmail_address: str | None,
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

    # Already signed in (a previous run or the operator did it).
    if _logged_in(page):
        row.strategy = STRATEGY_EXISTING
        row.account_url = page.url
        row.login_url = page.url
        _remember_login(db, context, project.id, website.id)
        _set_row(db, row, STATUS_ACTIVE, message="Already signed in.", strategy=STRATEGY_EXISTING)
        _store_target(db, context, project, website, row)
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
    if not row.username:
        row.username = generate_username(website, project)
    if not row.password_encrypted:
        set_password(row, generate_password())
    if gmail_address:
        token = gmail_otp.alias_token(project.id, website.id)
        row.otp_alias = gmail_otp.alias_for(gmail_address, token)
        if not row.email or "@" not in row.email:
            row.email = row.otp_alias
    db.commit()
    _update_item(
        project.id,
        website.id,
        strategy=STRATEGY_SIGNUP,
        message="Signing up with a generated username and password…",
    )

    signup_url = _find_signup_url(page, website.opportunity_url)
    if signup_url and signup_url != page.url:
        with suppress(Exception):
            page.goto(signup_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            page.wait_for_timeout(1200)
    row.login_url = page.url

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

    filled, reason = _fill_signup(page, row, project)
    if not filled:
        _set_row(
            db,
            row,
            STATUS_NEEDS_HUMAN,
            error=reason or "No sign-up form was found on this website.",
            message="No sign-up form was found - open the site and check it once.",
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

    # --- OTP -------------------------------------------------------------
    if _needs_otp(page):
        _set_row(db, row, STATUS_OTP_PENDING, message="Waiting for the e-mail code…")
        if inbox is None or not row.otp_alias:
            _set_row(
                db,
                row,
                STATUS_NEEDS_HUMAN,
                error="The site asks for an e-mail code, but Gmail is not configured or this row has no alias.",
                message="E-mail code needed - configure Gmail in the account dialog.",
            )
            return
        code, otp_reason = inbox.wait_for_code(
            alias=row.otp_alias,
            since=started_at,
            site_domain=website.domain,
            timeout=OTP_TIMEOUT_SECONDS,
        )
        if code is None:
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
        set_otp(row, code.code, code.message_id)
        db.commit()
        _update_item(project.id, website.id, message=f"Code received ({code.matched_by}).")
        filled_code = False
        with suppress(Exception):
            selector = page.query_selector(_OTP_SELECTOR)
            if selector is not None:
                selector.fill(code.code, timeout=6000)
                filled_code = True
        if not filled_code:
            # Some sites show the six boxes of a code separately.
            with suppress(Exception):
                boxes = page.query_selector_all(
                    "input[inputmode='numeric'], input[maxlength='1']"
                )
                if len(boxes) >= 4:
                    for box, digit in zip(boxes, code.code, strict=False):
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

    if not _success(page, row.login_url or website.opportunity_url):
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


# --------------------------------------------------------------------------
# The batch thread
# --------------------------------------------------------------------------
def _run_batch(project_id: str, website_ids: list[str]) -> None:
    db = session_scope()
    browser: _Browser | None = None
    inbox: gmail_otp.OtpInbox | None = None
    try:
        project = db.get(Project, project_id)
        if project is None:
            return
        gmail = gmail_otp.read_settings(db)
        if gmail is not None:
            try:
                inbox = gmail_otp.OtpInbox(gmail)
                inbox.open()
            except Exception as exc:
                gmail = None
                inbox = None
                log.warning(
                    "the Gmail session could not be opened",
                    extra={"extra_fields": {"error": str(exc)}},
                )
                _update_batch(
                    project_id,
                    message=(
                        "Gmail could not be opened - sites that need an e-mail "
                        "code will pause. Check the App Password."
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
                    inbox,
                    gmail.address if gmail is not None else None,
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
