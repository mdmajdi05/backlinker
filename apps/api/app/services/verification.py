"""Backlink verification engine.

The engine re-fetches the published page and looks for the expected link.

Status transitions:

``SUBMITTED``
    -> ``PUBLISHED_UNVERIFIED`` - the page is live, the link was not found yet
    -> ``VERIFIED_LIVE`` - the page links to the expected destination
``PUBLISHED_UNVERIFIED``
    -> ``VERIFIED_LIVE`` / ``VERIFICATION_FAILED`` / ``REMOVED``
    -> ``TEMPORARILY_UNAVAILABLE`` - the page could not be fetched

Nothing is ever assumed: a backlink is only reported as live when the link
was really observed in the fetched HTML. A page that renders its content
with JavaScript is reported as ``UNKNOWN`` instead of being treated as a
failure - and it is never reported as a success either.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.net import extract_links, safe_get
from app.db.base import utcnow
from app.db.models import BacklinkRecord, ProjectSettings, Task, VerificationRun
from app.workers.runner import TaskOutcome

STATUS_SUBMITTED = "SUBMITTED"
STATUS_PUBLISHED_UNVERIFIED = "PUBLISHED_UNVERIFIED"
STATUS_VERIFIED_LIVE = "VERIFIED_LIVE"
STATUS_VERIFICATION_FAILED = "VERIFICATION_FAILED"
STATUS_TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
STATUS_REMOVED = "REMOVED"
STATUS_UNKNOWN = "UNKNOWN"
STATUS_SKIPPED = "SKIPPED"

# Markers of a page that needs JavaScript (or that shows an anti bot wall).
_JS_MARKERS = (
    "enable javascript",
    "javascript is required",
    "requires javascript",
    "please enable js",
    "enable-javascript",
    "just a moment",
    "checking your browser",
    "attention required",
)

# Markers of a client side rendered application shell.
_JS_ROOTS = (
    'id="root"',
    "id='root'",
    'id="app"',
    "id='app'",
    'id="__next"',
    "id='__nuxt'",
    "ng-version",
    "data-reactroot",
    "data-v-app",
)


@dataclass
class LinkMatch:
    """The outcome of the link lookup on a page."""

    exact: dict[str, Any] | None = None
    domain_level: dict[str, Any] | None = None

    @property
    def found(self) -> dict[str, Any] | None:
        """The link that points to the expected destination."""
        return self.exact or self.domain_level


def verify_backlink_record(
    db: Session, record: BacklinkRecord, force: bool = False
) -> VerificationRun:
    """Check a backlink record and store the result as a verification run."""
    now = utcnow()
    if not force and record.next_verification_at is not None and record.next_verification_at > now:
        return _append(
            db,
            record,
            status=STATUS_SKIPPED,
            error=None,
            evidence={
                "reason": "not_due",
                "next_verification_at": record.next_verification_at.isoformat(),
            },
        )

    url = _target_url(record)
    if not url:
        return _append(
            db,
            record,
            status=STATUS_VERIFICATION_FAILED,
            error="The record does not contain a URL that could be verified.",
            evidence={},
        )

    response = safe_get(url, allow_robots=settings.respect_robots)
    evidence: dict[str, Any] = {
        "requested_url": url,
        "final_url": response.final_url,
        "http_status": response.status_code,
        "elapsed_ms": response.elapsed_ms,
        "redirects": response.redirects,
        "truncated": response.truncated,
        "expected_destination": record.expected_destination_url,
        "expected_normalized": normalize_destination(record.expected_destination_url),
    }

    if response.error and "robots.txt" in response.error:
        return _append(
            db,
            record,
            status=STATUS_UNKNOWN,
            error=response.error,
            evidence=evidence,
        )
    if response.error:
        return _append(
            db,
            record,
            status=STATUS_TEMPORARILY_UNAVAILABLE,
            error=response.error,
            evidence=evidence,
        )
    if response.status_code in (404, 410):
        return _append(
            db,
            record,
            status=STATUS_REMOVED,
            error=f"The published page answered with HTTP {response.status_code}.",
            evidence=evidence,
            http_status=response.status_code,
        )
    if response.status_code >= 500 or response.status_code in (403, 408, 429):
        return _append(
            db,
            record,
            status=STATUS_TEMPORARILY_UNAVAILABLE,
            error=f"The published page answered with HTTP {response.status_code}.",
            evidence=evidence,
            http_status=response.status_code,
        )
    if response.status_code >= 400:
        return _append(
            db,
            record,
            status=STATUS_VERIFICATION_FAILED,
            error=f"The published page answered with HTTP {response.status_code}.",
            evidence=evidence,
            http_status=response.status_code,
        )

    links = extract_links(response.content, response.final_url)
    evidence["links_scanned"] = len(links)
    match = match_link(links, record.expected_destination_url)

    if match.exact is not None:
        link = match.exact
        return _append(
            db,
            record,
            status=STATUS_VERIFIED_LIVE,
            error=None,
            evidence=evidence,
            link_present=True,
            destination_matched=True,
            http_status=response.status_code,
            observed_anchor_text=str(link.get("text") or "") or None,
            observed_destination_url=str(link.get("href") or "") or None,
            link_attribute_value=link_attribute(link.get("rel")),
        )

    link_present = match.domain_level is not None
    if link_present and match.domain_level is not None:
        evidence["domain_level_link"] = match.domain_level.get("href")

    if _looks_javascript_rendered(response.content, links):
        return _append(
            db,
            record,
            status=STATUS_UNKNOWN,
            error=(
                "The published page renders its content with JavaScript, so the link could not "
                "be confirmed."
            ),
            evidence=evidence,
            link_present=link_present,
            destination_matched=False,
            http_status=response.status_code,
        )

    if record.verification_status in (STATUS_SUBMITTED, "PENDING", "", None):
        return _append(
            db,
            record,
            status=STATUS_PUBLISHED_UNVERIFIED,
            error=None,
            evidence=evidence,
            link_present=link_present,
            destination_matched=False,
            http_status=response.status_code,
        )

    return _append(
        db,
        record,
        status=STATUS_VERIFICATION_FAILED,
        error="The published page is live but the expected link was not found.",
        evidence=evidence,
        link_present=link_present,
        destination_matched=False,
        http_status=response.status_code,
    )


def verify_task(db: Session, task: Task) -> TaskOutcome:
    """Execute a verification task and translate the result into an outcome."""
    payload: dict[str, Any] = task.payload or {}
    backlink_id = payload.get("backlink_id")
    record = db.get(BacklinkRecord, str(backlink_id)) if backlink_id else None
    if record is None:
        message = "The backlink record of this task no longer exists."
        return TaskOutcome(status="FAILED", error=message, message=message, retryable=False)

    force = bool(payload.get("force", False))
    run = verify_backlink_record(db, record, force=force)
    result: dict[str, Any] = {
        "backlink_id": record.id,
        "verification_run_id": run.id,
        "verification_status": run.status,
        "link_present": run.link_present,
        "destination_matched": run.destination_matched,
        "http_status": run.http_status,
        "observed_anchor_text": run.observed_anchor_text,
        "observed_destination_url": run.observed_destination_url,
        "link_attribute": run.link_attribute,
        "error": run.error,
        "next_verification_at": record.next_verification_at.isoformat()
        if record.next_verification_at
        else None,
    }

    if run.status == STATUS_VERIFIED_LIVE:
        return TaskOutcome(
            status=STATUS_VERIFIED_LIVE,
            result=result,
            message="The backlink is live and points to the expected destination.",
        )
    if run.status == STATUS_TEMPORARILY_UNAVAILABLE:
        return TaskOutcome(
            status=STATUS_TEMPORARILY_UNAVAILABLE,
            result=result,
            error=run.error,
            message=run.error or "The published page could not be fetched.",
            retryable=True,
        )
    if run.status == STATUS_UNKNOWN:
        return TaskOutcome(
            status=STATUS_UNKNOWN,
            result=result,
            error=run.error,
            message=run.error or "The published page could not be checked reliably.",
            retryable=True,
        )
    return TaskOutcome(
        status="COMPLETED",
        result=result,
        message=f"Verification finished: {run.status}.",
        error=run.error,
    )


# -- helpers --------------------------------------------------------------


def normalize_destination(url: str) -> str:
    """Normalise a URL for the comparison (scheme, ``www.`` and trailing slash)."""
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urllib.parse.urlparse(raw)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    port = f":{parsed.port}" if parsed.port else ""
    path = parsed.path.rstrip("/") or "/"
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{host}{port}{path}{query}"


def match_link(links: list[dict[str, Any]], expected: str) -> LinkMatch:
    """Find the link that points to the expected destination."""
    target = normalize_destination(expected)
    match = LinkMatch()
    if not target:
        return match
    target_host = target.split("/")[0]
    for link in links:
        normalized = normalize_destination(str(link.get("href") or ""))
        if not normalized:
            continue
        if normalized == target:
            if match.exact is None:
                match.exact = link
        elif normalized.split("/")[0] == target_host and match.domain_level is None:
            match.domain_level = link
    return match


def link_attribute(rel: Any) -> str:
    """Derive the link attribute (``follow`` / ``nofollow`` / ...) from ``rel``."""
    if isinstance(rel, list):
        values = {str(item).lower() for item in rel}
    else:
        values = {item for item in str(rel or "").lower().replace(",", " ").split() if item}
    if "sponsored" in values:
        return "sponsored"
    if "ugc" in values:
        return "ugc"
    if "nofollow" in values:
        return "nofollow"
    return "follow"


def _looks_javascript_rendered(html: str, links: list[dict[str, Any]]) -> bool:
    """Does the page need JavaScript to show its content?"""
    lowered = (html or "").lower()
    if links:
        return any(marker in lowered for marker in ("just a moment", "checking your browser", "attention required"))
    if any(marker in lowered for marker in _JS_MARKERS):
        return True
    return any(root in lowered for root in _JS_ROOTS)


def _target_url(record: BacklinkRecord) -> str:
    """The URL that has to be fetched to verify a record."""
    return record.published_page_url or record.expected_link_url or record.target_website


def _append(
    db: Session,
    record: BacklinkRecord,
    *,
    status: str,
    error: str | None,
    evidence: dict[str, Any],
    link_present: bool | None = None,
    destination_matched: bool | None = None,
    http_status: int | None = None,
    observed_anchor_text: str | None = None,
    observed_destination_url: str | None = None,
    link_attribute_value: str | None = None,
) -> VerificationRun:
    """Store a verification run and update the backlink record."""
    run = VerificationRun(
        backlink_id=record.id,
        status=status,
        link_present=link_present,
        destination_matched=destination_matched,
        http_status=http_status,
        observed_anchor_text=observed_anchor_text,
        observed_destination_url=observed_destination_url,
        link_attribute=link_attribute_value,
        error=error,
        evidence=evidence or {},
        verified_at=utcnow(),
    )
    db.add(run)

    if status != STATUS_SKIPPED:
        record.verification_status = status
        record.error = error
        if link_present is not None:
            record.link_present = link_present
        if destination_matched is not None:
            record.destination_matched = destination_matched
        if http_status is not None:
            record.http_status = http_status
        if observed_anchor_text is not None:
            record.observed_anchor_text = observed_anchor_text
        if observed_destination_url is not None:
            record.observed_destination_url = observed_destination_url
        if link_attribute_value is not None:
            record.link_attribute = link_attribute_value
        if status == STATUS_VERIFIED_LIVE:
            record.is_live = True
            record.verified_at = utcnow()
            record.last_success_at = utcnow()
        elif status in (STATUS_VERIFICATION_FAILED, STATUS_REMOVED):
            record.is_live = False
        record.next_verification_at = _next_verification_at(db, record, status)
    db.commit()
    db.refresh(run)
    return run


def _next_verification_at(db: Session, record: BacklinkRecord, status: str) -> Any:
    """When the record has to be checked again."""
    interval = _project_hours(db, record, "verify_interval_hours", settings.verification_interval_hours)
    if status in (STATUS_TEMPORARILY_UNAVAILABLE, STATUS_UNKNOWN):
        hours = _project_hours(db, record, "verify_backoff_hours", 24)
    else:
        hours = interval
    return utcnow() + timedelta(hours=max(1, hours))


def _project_hours(db: Session, record: BacklinkRecord, attribute: str, fallback: int) -> int:
    """Read a duration from the project settings of a record."""
    if not record.project_id:
        return int(fallback)
    from sqlalchemy import select

    row = db.execute(
        select(ProjectSettings).where(ProjectSettings.project_id == record.project_id)
    ).scalars().first()
    if row is not None:
        value = getattr(row, attribute, None)
        if value:
            return int(value)
    return int(fallback)
