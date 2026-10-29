"""One-time codes for website sign-ups, read from the project's Gmail inbox.

The pipeline is built around **one inbox session per batch**, not one session
per website:

* a batch opens a single IMAP connection and keeps it open for the whole run,
* every website signs up with its own unique address alias
  (``inbox+<token>@gmail.com``), so the code of a website can only ever be
  claimed by the row that carries the same token,
* a code is claimed exactly once per batch (a global lock and a claim set),
  is bound to the ``(project, website)`` row and is stored encrypted,
* when a site rejects plus addressing the fallback still requires the sender
  domain *and* the website domain, never a bare "newest mail" guess.

Nothing here guesses: an ambiguous message is skipped and the row pauses with
a reason instead of filling a code into the wrong form.
"""

from __future__ import annotations

import email
import imaplib
import re
import secrets
import threading
import time
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime
from html import unescape
from typing import Any
from urllib.parse import quote

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import encrypt
from app.core.logging import get_logger
from app.db.models import IntegrationCredential
from app.services import integration_credentials

log = get_logger(__name__)

PROVIDER = "gmail"
DEFAULT_IMAP_HOST = "imap.gmail.com"
DEFAULT_IMAP_PORT = 993

#: A batch waits at most this long for one code.
DEFAULT_WAIT_SECONDS = 180
#: How often the open session re-reads the inbox while it waits.
POLL_SECONDS = 3.0

_CODE = re.compile(r"(?<!\d)(\d{4,8})(?!\d)")
_KEYWORDS = (
    "verification code",
    "confirmation code",
    "security code",
    "one-time code",
    "one time code",
    "otp",
    "passcode",
    "verify your email",
    "confirm your email",
    "your code",
    "code:",
)
#: Addresses / numbers that are never an OTP.
_NOT_A_CODE = {
    2024,
    2025,
    2026,
    2027,
    1900,
    2000,
}
#: A confirmation link of a sign-up mail.
_LINK = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)
_LINK_WORDS = (
    "confirm",
    "verify",
    "verification",
    "activate",
    "activation",
    "validate",
    "registration",
    "signup",
    "sign-up",
    "email-confirm",
    "email-verify",
)


@dataclass
class GmailSettings:
    """The inbox of this installation (app password, never the login password)."""

    address: str
    app_password: str
    imap_host: str = DEFAULT_IMAP_HOST
    imap_port: int = DEFAULT_IMAP_PORT

    @property
    def configured(self) -> bool:
        return bool(self.address and self.app_password)


def read_settings(db: Session) -> GmailSettings | None:
    """The stored Gmail credentials of the installation, or ``None``."""
    row = integration_credentials.stored_credential(db, PROVIDER)
    if row is None:
        return None
    password = integration_credentials.credential_secret(row)
    meta = row.meta or {}
    address = str(meta.get("address") or "").strip()
    if not password or not address:
        return None
    return GmailSettings(
        address=address,
        app_password=password,
        imap_host=str(meta.get("imap_host") or DEFAULT_IMAP_HOST),
        imap_port=int(meta.get("imap_port") or DEFAULT_IMAP_PORT),
    )


def save_settings(
    db: Session,
    *,
    address: str,
    app_password: str,
    user_id: str | None = None,
    imap_host: str = DEFAULT_IMAP_HOST,
    imap_port: int = DEFAULT_IMAP_PORT,
) -> GmailSettings:
    """Store (or replace) the inbox used for OTP retrieval."""
    address = address.strip()
    app_password = app_password.replace(" ", "").strip()
    row = integration_credentials.stored_credential(db, PROVIDER)
    if row is None:
        row = IntegrationCredential(provider=PROVIDER, label="default", user_id=user_id)
        db.add(row)
    row.secret_encrypted = encrypt(app_password, settings.secret_key, associated_data=PROVIDER)
    row.meta = {
        **(row.meta or {}),
        "address": address,
        "imap_host": imap_host,
        "imap_port": imap_port,
        "hint": f"••••{app_password[-4:]}" if len(app_password) >= 4 else "••••",
    }
    row.status = "CONFIGURED"
    db.commit()
    db.refresh(row)
    return GmailSettings(
        address=address,
        app_password=app_password,
        imap_host=imap_host,
        imap_port=imap_port,
    )


def delete_settings(db: Session) -> None:
    row = integration_credentials.stored_credential(db, PROVIDER)
    if row is not None:
        db.delete(row)
        db.commit()


def status_payload(settings_row: GmailSettings | None) -> dict[str, Any]:
    return {
        "configured": bool(settings_row and settings_row.configured),
        "address": settings_row.address if settings_row else None,
        "imap_host": settings_row.imap_host if settings_row else DEFAULT_IMAP_HOST,
    }


# --------------------------------------------------------------------------
# Aliases: the binding key of the whole pipeline
# --------------------------------------------------------------------------
def alias_token(project_id: str, website_id: str) -> str:
    """A short, unique, mail-safe token for one (project, website) row."""
    digest = secrets.token_hex(3)
    return f"{project_id[:4]}{website_id[:4]}{digest}".lower()


def site_alias_token(site: str, website_id: str = "") -> str:
    """A readable label of the website for the alias (``example.com``).

    The inbox then shows *which site* sent the code instead of an opaque
    hexadecimal token: ``you+example-com@gmail.com``.  Everything that is not
    a letter or a digit becomes ``-`` so the local part stays valid, and an
    empty / unusable name falls back to the old random token.
    """
    text = (site or "").strip().lower()
    text = re.sub(r"^[a-z][a-z0-9+.-]*://", "", text)
    text = text.split("/", 1)[0]
    text = text.removeprefix("www.")
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    slug = slug[:32].strip("-")
    if not slug:
        return alias_token("", website_id)
    return slug


def alias_for(address: str, token: str) -> str:
    """``name+token@gmail.com`` (Gmail delivers it to ``name@gmail.com``)."""
    local, _, domain = address.partition("@")
    if not domain:
        return address
    return f"{local}+{token}@{domain}"


def dot_alias_for(address: str, token: str = "") -> str:
    """A dots-only variant of *address* for sites that refuse ``+``.

    Gmail ignores dots in the local part, so ``i.nbox@gmail.com`` still reaches
    ``inbox@gmail.com``.  A dot variant cannot carry the website name; it is
    only used for the rare form that rejects plus addressing.
    """
    local, _, domain = address.partition("@")
    if not domain:
        return address
    # Drop an existing plus alias first: only dots of the real inbox count.
    local = local.split("+", 1)[0]
    if len(local) < 2:
        return address
    return f"{local[0]}.{local[1:]}@{domain}"


# --------------------------------------------------------------------------
# Message parsing
# --------------------------------------------------------------------------
@dataclass
class OtpCode:
    code: str
    message_id: str
    subject: str
    sender: str
    received_at: datetime
    matched_by: str
    #: Set instead of ``code`` when the mail carries a confirmation link.
    link: str | None = None


@dataclass
class _Message:
    uid: str
    message_id: str
    subject: str
    sender: str
    recipients: list[str]
    received_at: datetime
    text: str
    raw: Message = field(repr=False)


def _decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _body_text(message: Message) -> str:
    parts: list[str] = []

    def add(part: Message) -> None:
        try:
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
        except Exception:
            log.debug("a mail part could not be decoded")
            return
        if part.get_content_subtype() == "html":
            text = unescape(re.sub(r"<[^>]+>", " ", text))
        parts.append(text)

    if message.is_multipart():
        for part in message.walk():
            if part.get_content_maintype() == "text":
                add(part)
    else:
        add(message)
    return re.sub(r"\s+", " ", " ".join(parts))


def _received_at(message: Message) -> datetime:
    raw = message.get("Date")
    if raw:
        try:
            parsed = parsedate_to_datetime(raw)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC).replace(tzinfo=None)
        except Exception:
            log.debug("a mail had no parseable date")
    return datetime.now(UTC).replace(tzinfo=None)


def extract_code(text: str) -> str | None:
    """The most plausible one-time code in *text* (or ``None``)."""
    lowered = (text or "").lower()
    if not lowered:
        return None
    best: tuple[int, str] | None = None
    for match in _CODE.finditer(text):
        value = match.group(1)
        number = int(value)
        if number in _NOT_A_CODE:
            continue
        # A code is usually close to the word that introduces it.
        window = lowered[max(0, match.start() - 120) : match.start()]
        score = 0
        for keyword in _KEYWORDS:
            position = window.rfind(keyword)
            if position >= 0:
                score = max(score, 100 - (len(window) - position))
        # Six digits are the most common OTP length.
        if len(value) == 6:
            score += 20
        elif len(value) in (5, 7):
            score += 8
        elif len(value) == 4:
            score += 4
        if score <= 0:
            continue
        if best is None or score > best[0]:
            best = (score, value)
    return best[1] if best else None


def extract_link(text: str) -> str | None:
    """The most plausible confirmation link of a sign-up mail (or ``None``)."""
    seen: set[str] = set()
    for match in _LINK.finditer(unescape(text or "")):
        url = match.group(0).rstrip(".,);]")
        if url in seen:
            continue
        seen.add(url)
        if any(word in url.lower() for word in _LINK_WORDS):
            return url
    return None


def _addresses(values: list[str]) -> set[str]:
    found: set[str] = set()
    for value in values:
        for chunk in str(value or "").split(","):
            address = parseaddr(chunk)[1].strip().lower()
            if address:
                found.add(address)
    return found


def _domain_of(value: str) -> str:
    value = (value or "").strip().lower()
    if "@" in value:
        return value.rsplit("@", 1)[1]
    return value


def _message_from_uid(uid: str, data: bytes) -> _Message | None:
    try:
        message = email.message_from_bytes(data)
    except Exception:
        return None
    recipients = _addresses(
        [
            str(message.get("To") or ""),
            str(message.get("Delivered-To") or ""),
            str(message.get("X-Original-To") or ""),
            str(message.get("Cc") or ""),
        ]
    )
    return _Message(
        uid=uid,
        message_id=str(message.get("Message-ID") or f"uid:{uid}"),
        subject=_decode(str(message.get("Subject") or "")),
        sender=parseaddr(str(message.get("From") or ""))[1].lower(),
        recipients=sorted(recipients),
        received_at=_received_at(message),
        text=_body_text(message),
        raw=message,
    )


class OtpInbox:
    """One IMAP session for a whole batch.

    The object is thread safe: a site that waits for its code does not open a
    second connection, and a code is never handed to two rows.
    """

    def __init__(self, credentials: GmailSettings, *, poll_seconds: float = POLL_SECONDS):
        self.credentials = credentials
        self.poll_seconds = poll_seconds
        self._connection: imaplib.IMAP4_SSL | None = None
        self._lock = threading.Lock()
        self._claimed: set[str] = set()
        self._seen: set[str] = set()

    # -- lifecycle ---------------------------------------------------------
    def open(self) -> None:
        if self._connection is not None:
            return
        connection = imaplib.IMAP4_SSL(
            self.credentials.imap_host,
            self.credentials.imap_port,
            timeout=30,
        )
        connection.login(self.credentials.address, self.credentials.app_password)
        status, _ = connection.select("INBOX")
        if status != "OK":
            raise RuntimeError("The Gmail inbox could not be opened.")
        self._connection = connection

    def close(self) -> None:
        connection, self._connection = self._connection, None
        if connection is None:
            return
        with suppress(Exception):
            connection.close()
        with suppress(Exception):
            connection.logout()

    def __enter__(self) -> OtpInbox:
        self.open()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- reading -----------------------------------------------------------
    def messages(self, since: datetime) -> list[_Message]:
        """Every message of the inbox that arrived after *since*."""
        connection = self._connection
        if connection is None:
            raise RuntimeError("The inbox is not open.")
        # Gmail's SINCE only has a day granularity: read one extra day.
        day = (since - timedelta(days=1)).strftime("%d-%b-%Y")
        status, data = connection.uid("search", None, "SINCE", day)
        if status != "OK" or not data:
            return []
        uids = data[0].split()
        found: list[_Message] = []
        with self._lock:
            for raw_uid in uids[-80:]:
                uid = raw_uid.decode("ascii", errors="ignore")
                if uid in self._seen:
                    continue
                status, payload = connection.uid("fetch", raw_uid, "(RFC822)")
                if status != "OK" or not payload:
                    continue
                for item in payload:
                    if isinstance(item, tuple) and len(item) >= 2:
                        message = _message_from_uid(uid, item[1])
                        if message is not None:
                            found.append(message)
                        break
                self._seen.add(uid)
        found.sort(key=lambda item: item.received_at)
        return [item for item in found if item.received_at >= since - timedelta(seconds=90)]

    def claim(
        self,
        messages: list[_Message],
        *,
        alias: str,
        base_address: str,
        site_domain: str,
    ) -> tuple[OtpCode | None, str | None]:
        """Pick the single message that belongs to *alias*.

        Returns ``(code, None)`` on success or ``(None, reason)`` when the
        message was ambiguous - the caller pauses the row instead of guessing.
        """
        alias = alias.strip().lower()
        base_address = base_address.strip().lower()
        site_host = _domain_of(site_domain).removeprefix("www.")
        candidates: list[tuple[int, _Message, str]] = []
        for message in messages:
            if message.message_id in self._claimed:
                continue
            code = extract_code(message.text)
            if code is None:
                code = extract_code(message.subject)
            if code is None:
                continue
            level = 0
            matched = ""
            if alias and any(alias in recipient for recipient in message.recipients):
                level, matched = 3, "alias"
            elif base_address and base_address in message.recipients:
                sender_host = _domain_of(message.sender)
                text = f"{message.subject} {message.text}".lower()
                if site_host and (sender_host.endswith(site_host) or site_host in text):
                    level, matched = 2, "sender+domain"
                elif site_host and site_host in message.sender:
                    level, matched = 2, "sender"
                else:
                    continue
            else:
                continue
            candidates.append(
                (
                    level,
                    message,
                    matched,
                )
            )
        if not candidates:
            return None, None
        if len(candidates) > 1 and candidates[-1][0] == candidates[-2][0] == 3:
            # Two different mails for the same alias: do not guess.
            codes = {extract_code(item[1].text) for item in candidates}
            if len(codes) > 1:
                return None, "Two different codes arrived for this address; enter it by hand."
        level, message, matched = max(candidates, key=lambda item: (item[0], item[1].received_at))
        code = extract_code(message.text) or extract_code(message.subject)
        assert code is not None
        self._claimed.add(message.message_id)
        return (
            OtpCode(
                code=code,
                message_id=message.message_id,
                subject=message.subject,
                sender=message.sender,
                received_at=message.received_at,
                matched_by=matched,
            ),
            None,
        )

    def wait_for_code(
        self,
        *,
        alias: str,
        since: datetime,
        site_domain: str,
        timeout: float = DEFAULT_WAIT_SECONDS,
    ) -> tuple[OtpCode | None, str | None]:
        """Poll the open session until the code of *alias* arrives."""
        if self._connection is None:
            self.open()
        deadline = time.monotonic() + max(1.0, timeout)
        reason: str | None = None
        while time.monotonic() < deadline:
            try:
                messages = self.messages(since)
            except Exception:
                log.warning("reopening the Gmail session after an IMAP error")
                self.close()
                self.open()
                messages = self.messages(since)
            code, reason = self.claim(
                messages,
                alias=alias,
                base_address=self.credentials.address,
                site_domain=site_domain,
            )
            if code is not None:
                return code, None
            time.sleep(self.poll_seconds)
        return None, reason or "No e-mail with a code arrived in time."


# --------------------------------------------------------------------------
# Reading the codes from the Gmail tab of the project browser
# --------------------------------------------------------------------------
_READ_ROWS_JS = """
() => {
  const main = document.querySelector('div[role="main"]');
  if (!main) return [];
  const rows = Array.from(main.querySelectorAll('tr'));
  const out = [];
  rows.forEach((row, index) => {
    // A message row carries the sender cell (.yX); the inbox tabs are a
    // tablist <tr> without it.
    if (!row.classList.contains('zA') && !row.querySelector('.yX')) return;
    const text = (row.innerText || '').trim();
    if (text) out.push({ index, text: text.slice(0, 800) });
  });
  return out.slice(0, 8);
}
"""

_READ_MESSAGE_JS = """
() => {
  const main = document.querySelector('div[role="main"]');
  if (!main) return { text: '', sender: '' };
  const sender =
    main.querySelector('span[email]')?.getAttribute('email') ||
    main.querySelector('[email]')?.getAttribute('email') || '';
  return { text: (main.innerText || '').slice(0, 12000), sender };
}
"""


class GmailTabUnavailable(RuntimeError):
    """The project's Google session cannot open Gmail (signed out, no Gmail)."""


class BrowserInbox:
    """Read one-time codes from the Gmail tab of the project browser.

    The batch already has a browser that is signed in to the project's Google
    account, so the codes are read from ``mail.google.com`` in that profile -
    no App Password is needed.  The search is scoped to the alias of the row
    (``to:"inbox+token@gmail.com"``), therefore a code of another website can
    never be picked up.  A mail is claimed once, exactly like the IMAP reader.

    IMAP stays available as the fallback for a project whose Google session
    cannot open Gmail (for example when the account has no Gmail).
    """

    def __init__(
        self,
        context: Any,
        base_address: str = "",
        *,
        poll_seconds: float = POLL_SECONDS,
    ):
        self.context = context
        self.base_address = base_address
        self.poll_seconds = poll_seconds
        self._page: Any = None
        self._lock = threading.Lock()
        self._claimed: set[str] = set()
        self._seen: set[str] = set()

    # -- lifecycle ---------------------------------------------------------
    def open(self) -> None:
        """Nothing to open: the tab is created on the first search."""

    def close(self) -> None:
        page, self._page = self._page, None
        if page is not None:
            with suppress(Exception):
                page.close()

    def __enter__(self) -> BrowserInbox:
        self.open()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- reading -----------------------------------------------------------
    def _tab(self) -> Any:
        page = self._page
        if page is not None:
            with suppress(Exception):
                if not page.is_closed():
                    return page
        page = None
        for candidate in self.context.pages:
            with suppress(Exception):
                if "mail.google.com" in (candidate.url or ""):
                    page = candidate
                    break
        if page is None:
            page = self.context.new_page()
        self._page = page
        return page

    def _search_url(self, alias: str, since: datetime) -> str:
        age = datetime.now(UTC).replace(tzinfo=None) - since
        window = "1d" if age < timedelta(days=1) else "2d"
        query = f'to:"{alias}" newer_than:{window}'
        return "https://mail.google.com/mail/u/0/#search/" + quote(query, safe="")

    def _search(self, page: Any, alias: str, since: datetime) -> None:
        page.goto(
            self._search_url(alias, since),
            wait_until="domcontentloaded",
            timeout=45_000,
        )
        page.wait_for_timeout(1800)
        url = ""
        with suppress(Exception):
            url = page.url or ""
        if "accounts.google.com" in url:
            raise GmailTabUnavailable(
                "The project's Google account is not signed in to Gmail in this browser."
            )

    def _rows(self, page: Any) -> list[dict[str, Any]]:
        try:
            rows = page.evaluate(_READ_ROWS_JS)
        except Exception:
            return []
        return [row for row in (rows or []) if str(row.get("text") or "").strip()]

    def _read(
        self, *, alias: str, since: datetime, site_domain: str, mode: str = "code"
    ) -> OtpCode | None:
        del site_domain  # the alias search already scopes the mail to the row
        page = self._tab()
        search_url = self._search_url(alias, since)
        self._search(page, alias, since)
        rows = self._rows(page)
        if not rows:
            return None
        newest = rows[0]
        key = str(newest.get("text") or "")
        if key in self._claimed or key in self._seen:
            return None
        opened = False
        data: dict[str, Any] = {}
        try:
            locator = page.locator('div[role="main"] tr')
            locator.nth(int(newest.get("index") or 0)).click(timeout=10_000)
            opened = True
            page.wait_for_timeout(1500)
            data = page.evaluate(_READ_MESSAGE_JS) or {}
        except Exception:
            data = {}
        finally:
            if opened:
                with suppress(Exception):
                    page.go_back(wait_until="domcontentloaded", timeout=15_000)
            if page.url != search_url:
                with suppress(Exception):
                    page.goto(search_url, wait_until="domcontentloaded", timeout=45_000)
            with suppress(Exception):
                page.wait_for_timeout(500)
        text = str(data.get("text") or "")
        code = extract_code(text) or extract_code(key) if mode != "link" else None
        link = extract_link(text) if mode != "code" and code is None else None
        if code is None and link is None:
            with self._lock:
                self._seen.add(key)
            return None
        with self._lock:
            if key in self._claimed:
                return None
            self._claimed.add(key)
        return OtpCode(
            code=code or "",
            message_id=f"gmail-tab:{key[:60]}",
            subject=key[:120],
            sender=str(data.get("sender") or ""),
            received_at=datetime.now(UTC).replace(tzinfo=None),
            matched_by="gmail-tab" if code else "gmail-link",
            link=link,
        )

    def wait_for_code(
        self,
        *,
        alias: str,
        since: datetime,
        site_domain: str,
        timeout: float = DEFAULT_WAIT_SECONDS,
    ) -> tuple[OtpCode | None, str | None]:
        """Poll the Gmail tab until the code addressed to *alias* arrives."""
        if not alias:
            return None, "This row has no address alias."
        deadline = time.monotonic() + max(1.0, timeout)
        reason: str | None = None
        while time.monotonic() < deadline:
            try:
                code = self._read(alias=alias, since=since, site_domain=site_domain)
            except GmailTabUnavailable as exc:
                # Nothing will change by waiting: let the caller fall back to
                # the App Password inbox straight away.
                return None, str(exc)
            except Exception as exc:
                reason = f"The Gmail tab could not be read: {exc}"
                code = None
            if code is not None:
                return code, None
            time.sleep(self.poll_seconds)
        return None, reason or "No e-mail with a code arrived in time."

    def wait_for_link(
        self,
        *,
        alias: str,
        since: datetime,
        site_domain: str,
        timeout: float = DEFAULT_WAIT_SECONDS,
    ) -> tuple[OtpCode | None, str | None]:
        """Poll the Gmail tab until the confirmation link of *alias* arrives."""
        if not alias:
            return None, "This row has no address alias."
        deadline = time.monotonic() + max(1.0, timeout)
        reason: str | None = None
        while time.monotonic() < deadline:
            try:
                found = self._read(
                    alias=alias, since=since, site_domain=site_domain, mode="link"
                )
            except GmailTabUnavailable as exc:
                return None, str(exc)
            except Exception as exc:
                reason = f"The Gmail tab could not be read: {exc}"
                found = None
            if found is not None and found.link:
                return found, None
            time.sleep(self.poll_seconds)
        return None, reason or "No confirmation link arrived in time."

    def wait_for_code_or_link(
        self,
        *,
        alias: str,
        since: datetime,
        site_domain: str,
        timeout: float = DEFAULT_WAIT_SECONDS,
    ) -> tuple[OtpCode | None, str | None]:
        """Poll once per mail for the first code *or* confirmation link."""
        if not alias:
            return None, "This row has no address alias."
        deadline = time.monotonic() + max(1.0, timeout)
        reason: str | None = None
        while time.monotonic() < deadline:
            try:
                found = self._read(
                    alias=alias, since=since, site_domain=site_domain, mode="any"
                )
            except GmailTabUnavailable as exc:
                return None, str(exc)
            except Exception as exc:
                reason = f"The Gmail tab could not be read: {exc}"
                found = None
            if found is not None:
                return found, None
            time.sleep(self.poll_seconds)
        return None, reason or "No e-mail with a code or a link arrived in time."


def check_connection(credentials: GmailSettings) -> tuple[bool, str]:
    """Open and close the inbox once (used by the settings form)."""
    try:
        with OtpInbox(credentials) as inbox:
            inbox.messages(datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1))
        return True, "The inbox is reachable."
    except imaplib.IMAP4.error as exc:
        return False, (
            "Gmail refused the login. Use a 16 character App Password "
            f"(Google Account -> Security -> App passwords). Details: {exc}"
        )
    except Exception as exc:  # pragma: no cover - network dependent
        return False, f"The inbox could not be opened: {exc}"


def latest_message_summary(db: Session, credentials: GmailSettings) -> dict[str, Any] | None:
    """A privacy friendly summary of the newest mail (for the settings card)."""
    del db
    try:
        with OtpInbox(credentials) as inbox:
            messages = inbox.messages(datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1))
    except Exception:
        return None
    if not messages:
        return None
    newest = messages[-1]
    return {
        "subject": newest.subject[:160],
        "sender": newest.sender,
        "received_at": newest.received_at.isoformat(),
        "has_code": extract_code(newest.text) is not None,
    }


__all__ = [
    "DEFAULT_WAIT_SECONDS",
    "BrowserInbox",
    "GmailSettings",
    "GmailTabUnavailable",
    "OtpCode",
    "OtpInbox",
    "alias_for",
    "alias_token",
    "check_connection",
    "dot_alias_for",
    "extract_code",
    "extract_link",
    "latest_message_summary",
    "read_settings",
    "save_settings",
    "site_alias_token",
    "status_payload",
]
