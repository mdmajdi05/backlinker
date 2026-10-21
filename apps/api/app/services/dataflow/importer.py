"""Spreadsheet import engine.

The engine reads ``.xlsx`` / ``.xlsm`` / ``.csv`` workbooks, maps the columns
onto the canonical field set and produces a *plan* (exactly one action per data
row) before anything is written to the database.

The plan is derived from the **database state**, not from the spreadsheet
alone.  A row that claims a backlink is live is only skipped when the stored
:class:`~app.db.models.BacklinkRecord` agrees, so re-importing an old export
can never destroy verified work.

Action resolution table (sheet status x stored state)::

    sheet status          stored record                -> action
    ---------------------------------------------------------------------
    VERIFIED_LIVE         none                         -> CONFLICT
    VERIFIED_LIVE         status != VERIFIED_LIVE      -> CONFLICT
    VERIFIED_LIVE         VERIFIED_LIVE, next in future-> SKIP
    VERIFIED_LIVE         VERIFIED_LIVE, due/past      -> VERIFY
    SUBMITTED             VERIFIED_LIVE                -> CONFLICT
    PUBLISHED_UNVERIFIED  VERIFIED_LIVE                -> CONFLICT
    SUBMITTED             anything else                -> VERIFY
    PUBLISHED_UNVERIFIED  anything else                -> VERIFY
    FAILED                VERIFIED_LIVE                -> CONFLICT
    FAILED                retryable task               -> RETRY
    FAILED                no retryable task            -> UPDATE (with note)
    PENDING/QUEUED/blank  VERIFIED_LIVE                -> CONFLICT
    PENDING/QUEUED/blank  opportunity exists           -> UPDATE
    PENDING/QUEUED/blank  opportunity missing          -> CREATE

A blank status is *never* treated as verified.
"""

from __future__ import annotations

import csv
import io
import json
import re
import socket
import urllib.parse
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.core.net import UnsafeUrlError, assert_public_url
from app.db.base import utcnow
from app.db.models import (
    BacklinkRecord,
    ImportJob,
    ImportRow,
    Opportunity,
    OpportunityCategory,
    Project,
    Task,
    Website,
)
from app.services.dataflow.mapping import (
    REQUIRED_FIELDS,
    URL_FIELDS,
    detect_mapping,
    mapping_to_fields,
)
from app.services.opportunities import (
    create_website,
    extract_domain,
    link_to_project,
    normalize_url,
)
from app.services.queue import enqueue, retry_task

log = get_logger(__name__)

__all__ = [
    "ACTION_CONFLICT",
    "ACTION_CREATE",
    "ACTION_INVALID",
    "ACTION_RETRY",
    "ACTION_SKIP",
    "ACTION_UPDATE",
    "ACTION_VERIFY",
    "commit_import",
    "preview_import",
]

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

ACTION_CREATE = "CREATE"
ACTION_UPDATE = "UPDATE"
ACTION_SKIP = "SKIP"
ACTION_RETRY = "RETRY"
ACTION_VERIFY = "VERIFY"
ACTION_CONFLICT = "CONFLICT"
ACTION_INVALID = "INVALID"

#: Actions that mutate the database when a job is committed.
APPLYABLE_ACTIONS = (ACTION_CREATE, ACTION_UPDATE, ACTION_SKIP, ACTION_RETRY, ACTION_VERIFY)

#: Counter key (per action) used by ``ImportJob``.
COUNTER_KEYS = {
    ACTION_CREATE: "created_count",
    ACTION_UPDATE: "updated_count",
    ACTION_SKIP: "skipped_count",
    ACTION_RETRY: "retried_count",
    ACTION_VERIFY: "verify_count",
    ACTION_CONFLICT: "conflict_count",
    ACTION_INVALID: "invalid_count",
}

#: Statuses that mean "the link is confirmed live".
VERIFIED_STATUSES = frozenset({"VERIFIED_LIVE"})

#: Statuses that mean "submitted but not confirmed yet".
SUBMITTED_STATUSES = frozenset({"SUBMITTED", "PUBLISHED_UNVERIFIED"})

#: Statuses that mean "the last attempt failed".
FAILED_STATUSES = frozenset({"FAILED", "VERIFICATION_FAILED"})

#: Statuses that are handled as "pending / not started".
PENDING_STATUSES = frozenset(
    {"PENDING", "QUEUED", "NEEDS_REVIEW", "DISCOVERED", "APPROVED", "REJECTED",
     "EXCLUDED", "DUPLICATE", "IN_PROGRESS", "COMPLETED", "SKIPPED", "CANCELLED"}
)

#: Mapping of spreadsheet status -> opportunity status.
OPPORTUNITY_STATUS_BY_SHEET_STATUS = {
    "PENDING": "NEEDS_REVIEW",
    "QUEUED": "QUEUED",
    "NEEDS_REVIEW": "NEEDS_REVIEW",
    "DISCOVERED": "DISCOVERED",
    "APPROVED": "APPROVED",
    "REJECTED": "REJECTED",
    "EXCLUDED": "EXCLUDED",
    "DUPLICATE": "DUPLICATE",
    "IN_PROGRESS": "IN_PROGRESS",
    "SUBMITTED": "IN_PROGRESS",
    "PUBLISHED_UNVERIFIED": "IN_PROGRESS",
    "VERIFIED_LIVE": "COMPLETED",
    "COMPLETED": "COMPLETED",
    "FAILED": "FAILED",
    "VERIFICATION_FAILED": "FAILED",
    "SKIPPED": "NEEDS_REVIEW",
    "CANCELLED": "NEEDS_REVIEW",
}

#: Mapping of spreadsheet status -> verification status of the website.
VERIFICATION_STATUS_BY_SHEET_STATUS = {
    "PENDING": "PENDING",
    "QUEUED": "PENDING",
    "NEEDS_REVIEW": "PENDING",
    "DISCOVERED": "PENDING",
    "APPROVED": "PENDING",
    "SUBMITTED": "SUBMITTED",
    "PUBLISHED_UNVERIFIED": "PUBLISHED_UNVERIFIED",
    "VERIFIED_LIVE": "VERIFIED_LIVE",
    "COMPLETED": "VERIFIED_LIVE",
    "FAILED": "VERIFICATION_FAILED",
    "VERIFICATION_FAILED": "VERIFICATION_FAILED",
}

#: Verification statuses ordered by strength (used to never downgrade).
VERIFICATION_RANK = {
    "PENDING": 0,
    "SUBMITTED": 1,
    "PUBLISHED_UNVERIFIED": 2,
    "VERIFIED_LIVE": 3,
}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")
CATEGORY_RE = re.compile(r"^[A-Z0-9_]{2,64}$")

SUPPORTED_SUFFIXES = {".xlsx", ".xlsm", ".csv"}
HEADER_SEARCH_LIMIT = 25
DNS_TIMEOUT_SECONDS = 3.0

#: Maximum number of DNS lookups performed by a single import (per host).
SAFETY_CHECK_LIMIT = 512

#: Cache of the SSRF check results (host -> error message or ``None``).
_SAFETY_CACHE: dict[str, str | None] = {}


# --------------------------------------------------------------------------
# Data holders
# --------------------------------------------------------------------------


@dataclass
class SheetData:
    """A single worksheet (or the single sheet of a CSV file)."""

    name: str
    rows: list[list[Any]] = field(default_factory=list)


@dataclass
class RowPlan:
    """The computed action for a single spreadsheet row."""

    row_number: int
    sheet: str
    action: str
    reason: str
    values: dict[str, Any]
    errors: list[str]
    raw: dict[str, Any]
    opportunity_id: str | None = None
    task_id: str | None = None
    website_id: str | None = None
    project_id: str | None = None
    record_id: str | None = None

    def to_payload(self) -> dict[str, Any]:
        """Return the DTO payload (mirrors ``ImportRowPlan``)."""
        return {
            "row_number": self.row_number,
            "action": self.action,
            "reason": self.reason,
            "opportunity_id": self.opportunity_id,
            "task_id": self.task_id,
            "values": dict(self.values),
            "errors": list(self.errors),
        }


# --------------------------------------------------------------------------
# File readers
# --------------------------------------------------------------------------


def read_workbook(path: Path) -> list[SheetData]:
    """Read every sheet of a workbook.

    Raises :class:`ValueError` with a human readable message when the file
    cannot be read (unsupported or legacy ``.xls`` files, corrupt archives).
    """
    target = Path(path)
    if not target.exists():
        raise ValueError(f"Import file not found: {target.name}")
    suffix = target.suffix.lower()
    if suffix == ".xls":
        raise ValueError(
            "Legacy .xls workbooks are not supported. "
            "Please re-save the file as .xlsx (or .csv) and import it again."
        )
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Unsupported file type: {suffix or '(none)'}")
    if suffix == ".csv":
        return [_read_csv(target)]
    return _read_xlsx(target)


def _read_xlsx(path: Path) -> list[SheetData]:
    """Read an ``.xlsx`` / ``.xlsm`` workbook with openpyxl."""
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:  # pragma: no cover - depends on a broken file
        raise ValueError(f"Could not read the workbook: {exc}") from exc
    sheets: list[SheetData] = []
    try:
        for worksheet in workbook.worksheets:
            rows = [list(row) for row in worksheet.iter_rows(values_only=True)]
            sheets.append(SheetData(name=worksheet.title, rows=rows))
    finally:
        workbook.close()
    if not sheets:
        raise ValueError("The workbook does not contain any sheet")
    return sheets


def _read_csv(path: Path) -> SheetData:
    """Read a CSV file, sniffing the delimiter."""
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    sample = text[:8192]
    delimiter = ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [list(row) for row in reader]
    return SheetData(name=path.stem or "Sheet1", rows=rows)


# --------------------------------------------------------------------------
# Header detection
# --------------------------------------------------------------------------


def _header_labels(row: Sequence[Any]) -> list[str]:
    """Turn a spreadsheet row into header labels."""
    labels: list[str] = []
    for index, cell in enumerate(row):
        text = "" if cell is None else str(cell).strip()
        labels.append(text or f"column_{index + 1}")
    return labels


def detect_header_row(rows: list[list[Any]]) -> tuple[int, list[str]]:
    """Find the header row of a sheet.

    The header row is the first row that maps onto at least one known column.
    When no row matches, row 1 is used.
    """
    if not rows:
        return 0, []
    for index in range(min(len(rows), HEADER_SEARCH_LIMIT)):
        labels = _header_labels(rows[index])
        mapping = detect_mapping(labels)
        if any(entry["target_field"] for entry in mapping):
            return index, labels
    return 0, _header_labels(rows[0])


# --------------------------------------------------------------------------
# Value normalisation and validation
# --------------------------------------------------------------------------


def _parse_bool(value: str) -> bool | None:
    text = str(value or "").strip().lower()
    if text in {"true", "yes", "y", "1", "verified", "live"}:
        return True
    if text in {"false", "no", "n", "0", "not verified"}:
        return False
    return None


def normalise_value(field: str, raw: Any) -> Any:
    """Normalise a single cell for a canonical field."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        raw = "true" if raw else "false"
    if isinstance(raw, datetime):
        raw = raw.isoformat(sep=" ")
    text = str(raw).strip()
    if not text:
        return None
    if field in URL_FIELDS:
        return normalize_url(text)
    if field == "email":
        return text.lower()
    if field in {"status", "category", "adapter"}:
        return text.upper().replace(" ", "_").replace("-", "_")
    if field == "verified":
        return _parse_bool(text)
    if field == "score":
        try:
            return float(text)
        except ValueError:
            return text
    return text


def check_url_syntax(url: str) -> str | None:
    """Return an error message when the URL is syntactically invalid."""
    if not url or " " in url:
        return "URL is empty or contains spaces"
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        return f"unsupported URL scheme '{parsed.scheme or '(missing)'}'"
    if not parsed.hostname:
        return "URL is missing a hostname"
    if "." not in parsed.hostname and parsed.hostname.lower() != "localhost":
        return f"'{parsed.hostname}' does not look like a hostname"
    if parsed.username or parsed.password:
        return "URLs with embedded credentials are not allowed"
    return None


def _is_ip_literal(host: str) -> bool:
    try:
        socket.inet_pton(socket.AF_INET, host)
        return True
    except OSError:
        pass
    try:
        socket.inet_pton(socket.AF_INET6, host)
        return True
    except OSError:
        return False


def _call_with_timeout(func, *args, timeout: float = DNS_TIMEOUT_SECONDS):
    """Call ``func`` with a timeout.

    Returns the result, the raised exception or ``None`` when the call timed
    out (the worker thread is then abandoned).
    """
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(func, *args)
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            future.cancel()
            return None
        except Exception as exc:
            # The caller inspects the exception (see ``check_url_safety``).
            return exc
    finally:
        pool.shutdown(wait=False)


def check_url_safety(url: str, timeout: float = DNS_TIMEOUT_SECONDS) -> str | None:
    """Return an error message when a URL must never be fetched.

    The check uses :func:`app.core.net.assert_public_url` - the same SSRF
    guard the HTTP layer uses - so an imported spreadsheet can never point the
    platform at an internal address.  A host that simply does not resolve is
    *not* an error: the row is unknown, not dangerous.

    The result is cached per host (the check needs a DNS round trip) and the
    number of lookups per import is bounded by :data:`SAFETY_CHECK_LIMIT`.
    """
    host = urllib.parse.urlparse(url).hostname or ""
    if not host:
        return None
    if host in _SAFETY_CACHE:
        return _SAFETY_CACHE[host]
    if len(_SAFETY_CACHE) >= SAFETY_CHECK_LIMIT:
        # The budget is exhausted: the HTTP layer still refuses private
        # destinations when the URL is actually fetched.
        return None
    if _is_ip_literal(host):
        try:
            assert_public_url(url)
        except UnsafeUrlError as exc:
            _SAFETY_CACHE[host] = str(exc)
            return _SAFETY_CACHE[host]
        _SAFETY_CACHE[host] = None
        return None
    outcome = _call_with_timeout(assert_public_url, url, timeout=timeout)
    if outcome is None:
        # DNS timed out - we cannot prove the host is unsafe.
        _SAFETY_CACHE[host] = None
        return None
    if isinstance(outcome, UnsafeUrlError):
        message = str(outcome)
        if "Cannot resolve host" in message:
            _SAFETY_CACHE[host] = None
            return None
        _SAFETY_CACHE[host] = message
        return message
    if isinstance(outcome, Exception):
        _SAFETY_CACHE[host] = str(outcome)
        return _SAFETY_CACHE[host]
    _SAFETY_CACHE[host] = None
    return None


def validate_values(
    values: dict[str, Any], known_categories: set[str] | None = None
) -> list[str]:
    """Validate a normalised record and return the list of problems."""
    errors: list[str] = []
    for name in sorted(REQUIRED_FIELDS):
        if not values.get(name):
            errors.append(f"Missing required value: {name}")
    for name in sorted(URL_FIELDS):
        value = values.get(name)
        if not value:
            continue
        problem = check_url_syntax(str(value))
        if problem:
            errors.append(f"{name}: {problem}")
            continue
        blocked = check_url_safety(str(value))
        if blocked:
            errors.append(f"{name}: {blocked}")
    email = values.get("email")
    if email and not EMAIL_RE.match(str(email)):
        errors.append(f"email: '{email}' is not a valid email address")
    category = values.get("category")
    if category:
        if not CATEGORY_RE.match(str(category)):
            errors.append(f"category: '{category}' is not a valid category key")
        elif known_categories and str(category) not in known_categories:
            errors.append(f"category: unknown category '{category}'")
    score = values.get("score")
    if score is not None and not isinstance(score, (int, float)):
        errors.append(f"score: '{score}' is not a number")
    elif isinstance(score, (int, float)) and not 0 <= float(score) <= 100:
        errors.append(f"score: {score} is outside the 0-100 range")
    return errors


# --------------------------------------------------------------------------
# Database lookups
# --------------------------------------------------------------------------


def _known_categories(db: Session) -> set[str]:
    rows = db.execute(select(OpportunityCategory.key)).scalars().all()
    return {str(row) for row in rows}


def _find_project_by_name(
    db: Session, name: str, cache: dict[str, Project | None] | None = None
) -> Project | None:
    text = str(name or "").strip()
    if not text:
        return None
    if cache is not None and text in cache:
        return cache[text]
    project = db.execute(
        select(Project).where(Project.name == text)
    ).scalars().first()
    if project is None:
        lowered = text.lower()
        for candidate in db.execute(select(Project)).scalars().all():
            if candidate.name.lower() == lowered or candidate.slug.lower() == lowered:
                project = candidate
                break
    if cache is not None:
        cache[text] = project
    return project


def _resolve_project(
    db: Session,
    job_project_id: str | None,
    values: dict[str, Any],
    cache: dict[str, Project | None] | None = None,
) -> tuple[Project | None, str | None, str | None]:
    """Resolve the project a row belongs to.

    Returns ``(project, error, conflict)``.  ``error`` marks the row as
    unusable, ``conflict`` marks it as contradicting the import target.
    """
    named = values.get("project") or values.get("project_name")
    if job_project_id:
        project = db.get(Project, job_project_id)
        if project is None:
            return None, f"Target project {job_project_id} does not exist", None
        if named:
            other = _find_project_by_name(db, str(named), cache)
            if other is not None and other.id != project.id:
                return None, None, (
                    f"row targets project '{other.name}' but this import targets "
                    f"'{project.name}'"
                )
        return project, None, None
    if not named:
        return None, "No project specified for this row", None
    project = _find_project_by_name(db, str(named), cache)
    if project is None:
        return None, f"Project '{named}' not found", None
    return project, None, None


def _find_website(db: Session, opportunity_url: str) -> Website | None:
    """Find a website by its normalised opportunity URL (exact match only)."""
    normalized = normalize_url(opportunity_url)
    if not normalized:
        return None
    domain = extract_domain(normalized)
    return db.execute(
        select(Website).where(
            Website.domain == domain, Website.opportunity_url == normalized
        )
    ).scalars().first()


def _find_opportunity(
    db: Session, project_id: str, website: Website | None
) -> Opportunity | None:
    if website is None:
        return None
    return db.execute(
        select(Opportunity).where(
            Opportunity.project_id == project_id, Opportunity.website_id == website.id
        )
    ).scalars().first()


def _find_record(
    db: Session, project_id: str, opportunity: Opportunity | None, opportunity_url: str
) -> BacklinkRecord | None:
    """Find the backlink record of an opportunity (most recent first)."""
    if opportunity is not None:
        record = db.execute(
            select(BacklinkRecord)
            .where(BacklinkRecord.opportunity_id == opportunity.id)
            .order_by(BacklinkRecord.updated_at.desc())
        ).scalars().first()
        if record is not None:
            return record
    normalized = normalize_url(opportunity_url)
    if not normalized:
        return None
    return db.execute(
        select(BacklinkRecord)
        .where(
            BacklinkRecord.project_id == project_id,
            or_(
                BacklinkRecord.expected_link_url == normalized,
                BacklinkRecord.published_page_url == normalized,
            ),
        )
        .order_by(BacklinkRecord.updated_at.desc())
    ).scalars().first()


def _find_tasks(
    db: Session, project_id: str, opportunity: Opportunity | None, website: Website | None
) -> list[Task]:
    """Return the tasks of an opportunity (newest first)."""
    tasks: list[Task] = []
    if opportunity is not None:
        tasks = list(
            db.execute(
                select(Task)
                .where(Task.opportunity_id == opportunity.id)
                .order_by(Task.created_at.desc())
            ).scalars().all()
        )
    if not tasks and website is not None:
        tasks = list(
            db.execute(
                select(Task)
                .where(Task.website_id == website.id, Task.project_id == project_id)
                .order_by(Task.created_at.desc())
            ).scalars().all()
        )
    return tasks


def _latest_task(tasks: list[Task]) -> Task | None:
    return tasks[0] if tasks else None


def _failed_task(tasks: list[Task]) -> Task | None:
    for task in tasks:
        if task.status == "FAILED":
            return task
    return None


def _retry_eligible(task: Task | None) -> bool:
    """A task can be retried when it failed and still has attempts left."""
    if task is None or task.status != "FAILED":
        return False
    return (task.attempts or 0) < (task.max_attempts or 0)


# --------------------------------------------------------------------------
# Decision logic
# --------------------------------------------------------------------------


def decide_action(
    values: dict[str, Any],
    record: BacklinkRecord | None,
    tasks: Sequence[Task],
    exists: bool,
) -> tuple[str, str]:
    """Decide the action of a row from the sheet status and the database state.

    Returns ``(action, reason)``.  A blank status is never treated as
    verified.
    """
    now = utcnow()
    sheet_status = str(values.get("status") or "").strip().upper()

    if sheet_status == "VERIFIED_LIVE":
        if record is None:
            return (
                ACTION_CONFLICT,
                "sheet reports VERIFIED_LIVE but no backlink record exists in the database",
            )
        stored = str(record.verification_status or "").upper()
        if stored != "VERIFIED_LIVE":
            return (
                ACTION_CONFLICT,
                f"sheet reports VERIFIED_LIVE but the stored verification status is {stored or 'UNKNOWN'}",
            )
        next_at = record.next_verification_at
        if next_at is not None and next_at > now:
            return ACTION_SKIP, f"verified live until {next_at.isoformat(sep=' ')}"
        return ACTION_VERIFY, "re-verification due"

    if sheet_status in SUBMITTED_STATUSES:
        if record is not None and str(record.verification_status or "").upper() == "VERIFIED_LIVE":
            return (
                ACTION_CONFLICT,
                f"sheet reports {sheet_status} but the stored verification status is VERIFIED_LIVE",
            )
        return ACTION_VERIFY, f"verification due for {sheet_status.lower()} submission"

    if sheet_status in FAILED_STATUSES:
        if record is not None and str(record.verification_status or "").upper() == "VERIFIED_LIVE":
            return (
                ACTION_CONFLICT,
                f"sheet reports {sheet_status} but the stored verification status is VERIFIED_LIVE",
            )
        failed = _failed_task(list(tasks))
        if failed is not None and _retry_eligible(failed):
            return (
                ACTION_RETRY,
                f"task {failed.id} failed with {failed.attempts}/{failed.max_attempts} attempts; retry eligible",
            )
        return ACTION_UPDATE, _retry_note(_latest_task(list(tasks)), sheet_status)

    # PENDING / QUEUED / blank / unknown
    if (
        sheet_status
        and record is not None
        and str(record.verification_status or "").upper() == "VERIFIED_LIVE"
    ):
        return (
            ACTION_CONFLICT,
            f"sheet reports {sheet_status} but the stored verification status is VERIFIED_LIVE",
        )
    if exists:
        return ACTION_UPDATE, "existing opportunity; refreshing its fields"
    return ACTION_CREATE, "new opportunity"


def _retry_note(task: Task | None, sheet_status: str) -> str:
    """Explain why a failed row cannot be retried."""
    if task is None:
        return (
            f"sheet reports {sheet_status} but no task exists for this opportunity; "
            "applied as an update instead"
        )
    if task.status != "FAILED":
        return (
            f"sheet reports {sheet_status} but the stored task status is {task.status}; "
            "retry not eligible, applied as an update instead"
        )
    return (
        f"sheet reports {sheet_status} but task {task.id} already used "
        f"{task.attempts}/{task.max_attempts} attempts; retry not eligible, "
        "applied as an update instead"
    )


def _opportunity_status(values: dict[str, Any], current: str | None = None) -> str:
    """Map a sheet status onto an opportunity status."""
    sheet_status = str(values.get("status") or "").strip().upper()
    if not sheet_status:
        return current or "NEEDS_REVIEW"
    return OPPORTUNITY_STATUS_BY_SHEET_STATUS.get(sheet_status, current or "NEEDS_REVIEW")


def _verification_status(values: dict[str, Any]) -> str | None:
    sheet_status = str(values.get("status") or "").strip().upper()
    return VERIFICATION_STATUS_BY_SHEET_STATUS.get(sheet_status)


def _apply_verification_status(website: Website, values: dict[str, Any]) -> None:
    """Update the verification state without ever downgrading a live link."""
    target = _verification_status(values)
    if not target:
        return
    current = str(website.backlink_status or "").upper()
    if current == "VERIFIED_LIVE" and target != "VERIFIED_LIVE":
        return
    if VERIFICATION_RANK.get(target, 0) >= VERIFICATION_RANK.get(current, 0):
        website.backlink_status = target


# --------------------------------------------------------------------------
# Row plan construction
# --------------------------------------------------------------------------


def _row_values(mapping: list[dict], cells: dict[str, Any]) -> dict[str, Any]:
    """Map the raw cells onto the canonical fields."""
    fields = mapping_to_fields(mapping)
    values: dict[str, Any] = {}
    for source, target in fields.items():
        values[target] = normalise_value(target, cells.get(source))
    return values


def _build_plan(
    db: Session,
    job: ImportJob,
    sheet_name: str,
    row_number: int,
    headers: list[str],
    cells: dict[str, Any],
    mapping: list[dict],
    known_categories: set[str],
    project_cache: dict[str, Project | None] | None = None,
) -> RowPlan:
    """Build the plan of a single data row."""
    values = _row_values(mapping, cells)
    errors = validate_values(values, known_categories)
    raw = {
        "sheet": sheet_name,
        "row": row_number,
        "cells": {key: ("" if value is None else str(value)) for key, value in cells.items()},
        "values": values,
    }

    project, project_error, project_conflict = _resolve_project(
        db, job.project_id, values, project_cache
    )
    if project_error:
        errors.append(project_error)
    # Remember the resolved project so the commit uses exactly the same target.
    raw["project_id"] = project.id if project else None

    opportunity_url = str(values.get("opportunity_url") or "")
    website = _find_website(db, opportunity_url) if opportunity_url else None
    opportunity = _find_opportunity(db, project.id, website) if project else None
    record = (
        _find_record(db, project.id, opportunity, opportunity_url)
        if project
        else None
    )
    tasks = _find_tasks(db, project.id, opportunity, website) if project else []
    task = _latest_task(tasks)

    if errors:
        return RowPlan(
            row_number=row_number,
            sheet=sheet_name,
            action=ACTION_INVALID,
            reason="; ".join(errors),
            values=values,
            errors=errors,
            raw=raw,
            opportunity_id=opportunity.id if opportunity else None,
            task_id=task.id if task else None,
            website_id=website.id if website else None,
            project_id=project.id if project else None,
            record_id=record.id if record else None,
        )

    if project_conflict:
        return RowPlan(
            row_number=row_number,
            sheet=sheet_name,
            action=ACTION_CONFLICT,
            reason=project_conflict,
            values=values,
            errors=[],
            raw=raw,
            opportunity_id=opportunity.id if opportunity else None,
            task_id=task.id if task else None,
            website_id=website.id if website else None,
            project_id=project.id if project else None,
            record_id=record.id if record else None,
        )

    action, reason = decide_action(values, record, tasks, opportunity is not None)
    return RowPlan(
        row_number=row_number,
        sheet=sheet_name,
        action=action,
        reason=reason,
        values=values,
        errors=[],
        raw=raw,
        opportunity_id=opportunity.id if opportunity else None,
        task_id=task.id if task else None,
        website_id=website.id if website else None,
        project_id=project.id if project else None,
        record_id=record.id if record else None,
    )


def _is_blank_row(cells: Sequence[Any]) -> bool:
    for cell in cells:
        if cell is None:
            continue
        if str(cell).strip():
            return False
    return True


# --------------------------------------------------------------------------
# Preview
# --------------------------------------------------------------------------


def preview_import(
    db: Session,
    path: Path,
    original_filename: str,
    project_id: str | None,
    user_id: str,
) -> dict:
    """Analyse a workbook and build (and persist) an import plan.

    Nothing is written to the domain tables: the job is stored with the
    status ``PREVIEWED`` so the UI can show the plan and the user can decide
    which actions to commit.
    """
    target = Path(path)
    file_name = str(original_filename or target.name)
    job = ImportJob(
        project_id=project_id,
        user_id=user_id,
        file_name=file_name,
        file_path=str(target),
        status="PENDING",
        dry_run=True,
        sheet_names=[],
    )
    db.add(job)
    db.flush()

    try:
        sheets = read_workbook(target)
    except ValueError as exc:
        job.status = "FAILED"
        job.error = str(exc)
        db.commit()
        raise

    job.sheet_names = [sheet.name for sheet in sheets]
    known_categories = _known_categories(db)

    best_mapping: list[dict] = []
    plans: list[RowPlan] = []
    project_cache: dict[str, Project | None] = {}
    for sheet in sheets:
        header_index, headers = detect_header_row(sheet.rows)
        mapping = detect_mapping(headers)
        if _mapping_score(mapping) > _mapping_score(best_mapping):
            best_mapping = mapping
        # A sheet whose header does not look like a data sheet (for example a
        # "Column guide" sheet next to the data) is skipped instead of being
        # reported as hundreds of invalid rows.
        if _mapping_score(mapping) < 2:
            continue
        for offset, cells in enumerate(sheet.rows[header_index + 1 :]):
            if _is_blank_row(cells):
                continue
            row_number = header_index + 2 + offset
            row_cells = {
                headers[index] if index < len(headers) else f"column_{index + 1}": cell
                for index, cell in enumerate(cells)
            }
            plans.append(
                _build_plan(
                    db,
                    job,
                    sheet.name,
                    row_number,
                    headers,
                    row_cells,
                    mapping,
                    known_categories,
                    project_cache,
                )
            )

    counts = _count_actions(plans)
    job.detected_mapping = best_mapping
    job.total_rows = len(plans)
    job.created_count = counts["create"]
    job.updated_count = counts["update"]
    job.skipped_count = counts["skip"]
    job.retried_count = counts["retry"]
    job.verify_count = counts["verify"]
    job.conflict_count = counts["conflict"]
    job.invalid_count = counts["invalid"]
    job.status = "PREVIEWED"
    job.dry_run = True

    for plan in plans:
        db.add(
            ImportRow(
                import_job_id=job.id,
                row_number=plan.row_number,
                action=plan.action,
                reason=plan.reason,
                raw=plan.raw,
                errors=json.dumps(plan.errors) if plan.errors else None,
                website_id=plan.website_id,
                task_id=plan.task_id,
            )
        )
    db.commit()
    db.refresh(job)

    log.info(
        "import previewed",
        extra={
            "extra_fields": {
                "job": job.id,
                "file": file_name,
                "rows": len(plans),
                "counts": counts,
            }
        },
    )

    return {
        "import_job_id": job.id,
        "file_name": file_name,
        "sheets": list(job.sheet_names),
        "detected_mapping": list(job.detected_mapping or []),
        "rows": [plan.to_payload() for plan in plans],
        "counts": counts,
    }


def _mapping_score(mapping: list[dict]) -> int:
    return sum(1 for entry in mapping or [] if entry.get("target_field"))


def _count_actions(plans: Iterable[RowPlan]) -> dict[str, int]:
    """Count the planned actions (the shape used by ``ImportPreview.counts``)."""
    counts = {
        "total": 0,
        "create": 0,
        "update": 0,
        "skip": 0,
        "retry": 0,
        "verify": 0,
        "conflict": 0,
        "invalid": 0,
    }
    keys = {
        ACTION_CREATE: "create",
        ACTION_UPDATE: "update",
        ACTION_SKIP: "skip",
        ACTION_RETRY: "retry",
        ACTION_VERIFY: "verify",
        ACTION_CONFLICT: "conflict",
        ACTION_INVALID: "invalid",
    }
    for plan in plans:
        counts["total"] += 1
        key = keys.get(plan.action)
        if key:
            counts[key] += 1
    return counts


# --------------------------------------------------------------------------
# Commit
# --------------------------------------------------------------------------


def commit_import(
    db: Session,
    job: ImportJob,
    apply_actions: list[str] | None = None,
    dry_run: bool = False,
) -> None:
    """Apply the plan of an import job.

    Only the rows whose action is part of ``apply_actions`` are applied (all
    actions when ``apply_actions`` is ``None``).  ``INVALID`` and ``CONFLICT``
    rows are never applied automatically; they stay in the error report.
    """
    rows = db.execute(
        select(ImportRow)
        .where(ImportRow.import_job_id == job.id)
        .order_by(ImportRow.row_number)
    ).scalars().all()
    wanted = (
        {str(action).upper() for action in apply_actions}
        if apply_actions is not None
        else None
    )

    counters = {
        "created_count": 0,
        "updated_count": 0,
        "skipped_count": 0,
        "retried_count": 0,
        "verify_count": 0,
        "conflict_count": 0,
        "invalid_count": 0,
    }
    not_applied: list[ImportRow] = []

    for row in rows:
        action = str(row.action or "").upper()
        if action == ACTION_INVALID:
            counters["invalid_count"] += 1
            not_applied.append(row)
            continue
        if action == ACTION_CONFLICT:
            counters["conflict_count"] += 1
            not_applied.append(row)
            continue
        if wanted is not None and action not in wanted:
            not_applied.append(row)
            continue
        if dry_run:
            not_applied.append(row)
            continue
        if not _apply_row(db, job, row, action):
            not_applied.append(row)
            continue
        counters[COUNTER_KEYS.get(action, "updated_count")] += 1

    report_path = write_error_report(job, not_applied)
    job.error_report_path = str(report_path)

    if dry_run:
        # A dry run applies nothing: the counters keep describing the plan
        # that was computed by the preview.
        job.dry_run = True
    else:
        job.created_count = counters["created_count"]
        job.updated_count = counters["updated_count"]
        job.skipped_count = counters["skipped_count"]
        job.retried_count = counters["retried_count"]
        job.verify_count = counters["verify_count"]
        job.conflict_count = counters["conflict_count"]
        job.invalid_count = counters["invalid_count"]
        job.dry_run = False
        job.status = "COMMITTED"
        job.committed_at = utcnow()
    db.commit()
    db.refresh(job)

    log.info(
        "import committed",
        extra={
            "extra_fields": {
                "job": job.id,
                "dry_run": dry_run,
                "counters": counters,
                "not_applied": len(not_applied),
            }
        },
    )


def _row_values_from_row(row: ImportRow) -> dict[str, Any]:
    raw = row.raw or {}
    values = raw.get("values") if isinstance(raw, dict) else None
    return dict(values) if isinstance(values, dict) else {}


def _apply_row(db: Session, job: ImportJob, row: ImportRow, action: str) -> bool:
    """Apply a single row.  Returns ``False`` when the row could not be applied."""
    values = _row_values_from_row(row)
    try:
        if action == ACTION_CREATE:
            return _apply_create(db, job, row, values)
        if action == ACTION_UPDATE:
            return _apply_update(db, job, row, values)
        if action == ACTION_RETRY:
            return _apply_retry(db, job, row, values)
        if action == ACTION_VERIFY:
            return _apply_verify(db, job, row, values)
        if action == ACTION_SKIP:
            return _apply_skip(db, job, row, values)
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("import row failed")
        row.reason = f"{row.reason or ''} | {type(exc).__name__}: {exc}".strip(" |")
        db.commit()
        return False
    return False


def _target_project(
    db: Session, job: ImportJob, row: ImportRow, values: dict[str, Any]
) -> Project | None:
    """Resolve the project a row belongs to at commit time."""
    raw = row.raw or {}
    stored = raw.get("project_id") if isinstance(raw, dict) else None
    if stored:
        project = db.get(Project, stored)
        if project is not None:
            return project
    project, error, _conflict = _resolve_project(db, job.project_id, values)
    if error:
        return None
    return project


def _apply_create(
    db: Session, job: ImportJob, row: ImportRow, values: dict[str, Any]
) -> bool:
    """Create the website and the opportunity of a row."""
    project = _target_project(db, job, row, values)
    if project is None:
        row.reason = f"{row.reason or ''} | no target project could be resolved".strip(" |")
        db.commit()
        return False
    opportunity_url = str(values.get("opportunity_url") or "")
    if not opportunity_url:
        row.reason = f"{row.reason or ''} | missing opportunity url".strip(" |")
        db.commit()
        return False

    website, _created = create_website(
        db,
        url=opportunity_url,
        name=str(values.get("website_name") or ""),
        category=str(values.get("category") or "CUSTOM"),
        discovery_source="import",
        description=values.get("description"),
        language=values.get("language"),
        region=values.get("region"),
        anchor_text=values.get("anchor_text"),
        contact_email=values.get("email"),
        score=float(values["score"]) if isinstance(values.get("score"), (int, float)) else 0.0,
        notes=values.get("notes"),
        is_manual=True,
    )
    opportunity, _linked = link_to_project(
        db,
        project,
        website,
        target_landing_page=values.get("target_url"),
        status_value=_opportunity_status(values, "NEEDS_REVIEW"),
    )
    if values.get("notes"):
        opportunity.notes = values["notes"]
    _apply_verification_status(website, values)
    website.updated_at = utcnow()
    row.website_id = website.id
    db.commit()
    return True


def _apply_update(
    db: Session, job: ImportJob, row: ImportRow, values: dict[str, Any]
) -> bool:
    """Update the editable fields of an existing opportunity."""
    project = _target_project(db, job, row, values)
    if project is None:
        row.reason = f"{row.reason or ''} | no target project could be resolved".strip(" |")
        db.commit()
        return False
    website = _find_website(db, str(values.get("opportunity_url") or ""))
    if website is None:
        row.reason = (
            f"{row.reason or ''} | the opportunity no longer exists; "
            "the row was not applied"
        ).strip(" |")
        db.commit()
        return False
    opportunity = _find_opportunity(db, project.id, website)
    if opportunity is None:
        row.reason = (
            f"{row.reason or ''} | the opportunity is no longer linked to the project; "
            "the row was not applied"
        ).strip(" |")
        db.commit()
        return False

    if values.get("anchor_text"):
        website.anchor_text = values["anchor_text"]
    if values.get("description"):
        website.description = values["description"]
    if values.get("email"):
        website.contact_email = values["email"]
    if values.get("notes"):
        website.notes = values["notes"]
        opportunity.notes = values["notes"]
    if values.get("category"):
        website.category = values["category"]
    if values.get("language"):
        website.language = values["language"]
    if values.get("region"):
        website.region = values["region"]
    if isinstance(values.get("score"), (int, float)):
        website.score = float(values["score"])
    if values.get("target_url"):
        opportunity.target_landing_page = values["target_url"]
    opportunity.status = _opportunity_status(values, opportunity.status)
    _apply_verification_status(website, values)
    website.updated_at = utcnow()
    row.website_id = website.id
    db.commit()
    return True


def _apply_retry(
    db: Session, job: ImportJob, row: ImportRow, values: dict[str, Any]
) -> bool:
    """Requeue a failed task (the attempt history is preserved)."""
    project = _target_project(db, job, row, values)
    if project is None:
        row.reason = f"{row.reason or ''} | no target project could be resolved".strip(" |")
        db.commit()
        return False
    website = _find_website(db, str(values.get("opportunity_url") or ""))
    opportunity = _find_opportunity(db, project.id, website)
    tasks = _find_tasks(db, project.id, opportunity, website)
    failed = _failed_task(tasks)
    if failed is None or not _retry_eligible(failed):
        row.reason = (
            f"{row.reason or ''} | {_retry_note(failed, str(values.get('status') or 'FAILED'))}"
        ).strip(" |")
        db.commit()
        return False
    last_error = failed.last_error
    retry_task(db, failed)
    row.task_id = failed.id
    if last_error:
        row.reason = f"{row.reason or ''} | previous error: {last_error}".strip(" |")
    db.commit()
    return True


def _apply_verify(
    db: Session, job: ImportJob, row: ImportRow, values: dict[str, Any]
) -> bool:
    """Schedule a verification for the backlink record of a row."""
    project = _target_project(db, job, row, values)
    if project is None:
        row.reason = f"{row.reason or ''} | no target project could be resolved".strip(" |")
        db.commit()
        return False
    website = _find_website(db, str(values.get("opportunity_url") or ""))
    opportunity = _find_opportunity(db, project.id, website)
    record = _find_record(
        db, project.id, opportunity, str(values.get("opportunity_url") or "")
    )
    if record is None:
        record = _create_record_from_sheet(db, project, opportunity, website, values)
    if record is None:
        row.reason = (
            f"{row.reason or ''} | no backlink record to verify; the row was not applied"
        ).strip(" |")
        db.commit()
        return False
    task, _created = enqueue(
        db,
        task_type="VERIFY",
        project_id=project.id,
        opportunity_id=opportunity.id if opportunity else None,
        website_id=website.id if website else None,
        payload={"backlink_id": record.id, "force": False, "source": "reimport"},
        priority=3,
        idempotency_key=f"VERIFY:{record.id}:reimport",
    )
    row.task_id = task.id
    db.commit()
    return True


def _create_record_from_sheet(
    db: Session,
    project: Project,
    opportunity: Opportunity | None,
    website: Website | None,
    values: dict[str, Any],
) -> BacklinkRecord | None:
    """Create a backlink record from the imported row.

    Only sheet data is used (published URL, target URL, status); the record
    starts *unverified* so the verification engine decides whether the link is
    really live.
    """
    published = values.get("published_url") or values.get("opportunity_url")
    destination = values.get("target_url")
    if not published or not destination or opportunity is None:
        return None
    sheet_status = str(values.get("status") or "").strip().upper()
    status = (
        "PUBLISHED_UNVERIFIED"
        if sheet_status in {"PUBLISHED_UNVERIFIED", "VERIFIED_LIVE"}
        else "SUBMITTED"
    )
    record = BacklinkRecord(
        project_id=project.id,
        opportunity_id=opportunity.id,
        target_website=str(published),
        expected_link_url=str(published),
        published_page_url=str(published),
        expected_destination_url=str(destination),
        verification_status=status,
        evidence={"source": "import"},
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _apply_skip(
    db: Session, job: ImportJob, row: ImportRow, values: dict[str, Any]
) -> bool:
    """Record a skipped row without touching the verified work."""
    project = _target_project(db, job, row, values)
    if project is None:
        row.reason = f"{row.reason or ''} | no target project could be resolved".strip(" |")
        db.commit()
        return False
    website = _find_website(db, str(values.get("opportunity_url") or ""))
    opportunity = _find_opportunity(db, project.id, website)
    tasks = _find_tasks(db, project.id, opportunity, website)
    task = _latest_task(tasks)
    if task is not None and task.status != "VERIFIED_LIVE":
        task.status = "SKIPPED"
        task.skip_reason = row.reason or "skipped by import"
        task.finished_at = utcnow()
        task.lease_owner = None
        task.lease_expires_at = None
        task.updated_at = utcnow()
        row.task_id = task.id
        db.commit()
    return True


# --------------------------------------------------------------------------
# Error report
# --------------------------------------------------------------------------


def write_error_report(job: ImportJob, rows: list[ImportRow]) -> Path:
    """Write the error report of an import job into the managed files folder."""
    directory = settings.managed_files_dir
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"import-errors-{job.id}.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["row_number", "sheet", "action", "reason", "errors", "raw"]
        )
        for row in rows:
            raw = row.raw or {}
            sheet = raw.get("sheet", "") if isinstance(raw, dict) else ""
            writer.writerow(
                [
                    row.row_number,
                    sheet,
                    row.action,
                    row.reason or "",
                    row.errors or "",
                    json.dumps(raw, default=str, ensure_ascii=False),
                ]
            )
    return path
