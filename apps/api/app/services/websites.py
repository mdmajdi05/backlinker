"""The central list of websites.

The list is the one place where the sites the backlinks are made at live.  It
is **independent of the projects**: a website is added by hand or imported from
a spreadsheet, it can be marked as "not working" or removed, and every project
picks the sites it wants from it.

Two rules apply everywhere:

* The statistics of a website are **computed** from its tasks and
  opportunities - they are never stored, therefore they can never go stale.
* Removing a website is a **soft delete**: the status becomes ``DELETED`` and
  the opportunities, the tasks and the submissions stay untouched, so the
  reports remain truthful.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.models import Opportunity, Project, Task, Website
from app.services.dataflow.importer import (
    check_url_syntax,
    detect_header_row,
    normalise_value,
    read_workbook,
)
from app.services.dataflow.mapping import detect_mapping, mapping_to_fields
from app.services.opportunities import (
    extract_domain,
    link_to_project,
    normalize_url,
)
from app.services.queue import build_idempotency_key, enqueue

__all__ = [
    "WEBSITE_STATUSES",
    "choose_for_project",
    "create_entry",
    "delete_entry",
    "import_entries",
    "list_entries",
    "stats_rows",
    "update_entry",
]

#: The states a website of the central list can be in.
WEBSITE_STATUSES: tuple[str, ...] = (
    "DISCOVERED",
    "NEEDS_REVIEW",
    "APPROVED",
    "ACTIVE",
    "NOT_WORKING",
    "DELETED",
    "EXCLUDED",
    "REJECTED",
    "DUPLICATE",
)

#: The status a website of the central list gets when it is added by hand.
DEFAULT_STATUS = "ACTIVE"

#: The status a removed website carries (the rows stay, the history stays).
DELETED_STATUS = "DELETED"
ACTIVE_STATUS = "ACTIVE"

#: The category a website gets when nothing else is known.
DEFAULT_CATEGORY = "BUSINESS_DIRECTORY"

# -- task states ----------------------------------------------------------
#: A task of one of these states means "the site was submitted to".
SUBMITTED_TASK_STATUSES: tuple[str, ...] = ("SUBMITTED", "PUBLISHED_UNVERIFIED", "VERIFIED_LIVE")
#: A task of one of these states means "the link is confirmed live".
VERIFIED_TASK_STATUSES: tuple[str, ...] = ("VERIFIED_LIVE",)
#: A task of one of these states means "the last attempt failed".
FAILED_TASK_STATUSES: tuple[str, ...] = ("FAILED",)
#: A task of one of these states means "the work is still open".
PENDING_TASK_STATUSES: tuple[str, ...] = ("QUEUED", "RUNNING", "RETRY_SCHEDULED")
#: A task of one of these states waits for the details of a human.
WAITING_TASK_STATUSES: tuple[str, ...] = ("WAITING_FOR_USER",)

#: The sortable columns of the list.
SORT_COLUMNS = {
    "name": Website.name,
    "domain": Website.domain,
    "category": Website.category,
    "niche": Website.niche,
    "status": Website.status,
    "score": Website.score,
    "created_at": Website.created_at,
    "updated_at": Website.updated_at,
}


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def normalize_category(value: str | None) -> str:
    """Normalise a category key (``"business directory"`` -> ``BUSINESS_DIRECTORY``)."""
    text = str(value or "").strip().upper().replace(" ", "_").replace("-", "_")
    return text or DEFAULT_CATEGORY


def normalize_niche(value: str | None) -> str:
    """Normalise a free text niche."""
    return str(value or "").strip()


def find_entry(db: Session, opportunity_url: str) -> Website | None:
    """Find a website of the list by its opportunity URL."""
    normalized = normalize_url(opportunity_url)
    if not normalized:
        return None
    domain = extract_domain(normalized)
    return db.execute(
        select(Website).where(
            Website.domain == domain, Website.opportunity_url == normalized
        )
    ).scalar_one_or_none()


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------
def _project_ids(db: Session, website_ids: Sequence[str]) -> dict[str, list[str]]:
    """The projects that use every website of the list."""
    if not website_ids:
        return {}
    rows = db.execute(
        select(Opportunity.website_id, Opportunity.project_id).where(
            Opportunity.website_id.in_(list(website_ids)),
            Opportunity.project_id.is_not(None),
        )
    ).all()
    mapping: dict[str, list[str]] = {}
    for website_id, project_id in rows:
        projects = mapping.setdefault(website_id, [])
        if project_id not in projects:
            projects.append(project_id)
    return mapping


def compute_stats(
    db: Session, website_ids: Sequence[str], project_id: str | None = None
) -> dict[str, dict[str, Any]]:
    """Compute the statistics of the given websites.

    The numbers are derived from the tasks and the opportunities of the
    website - they are never stored.  When ``project_id`` is given only the
    work of that project is counted.
    """
    ids = list(dict.fromkeys(website_ids))
    if not ids:
        return {}

    stats: dict[str, dict[str, Any]] = {
        website_id: {
            "opportunities": 0,
            "submitted": 0,
            "verified": 0,
            "failed": 0,
            "pending": 0,
            "waiting_for_details": 0,
            "last_attempt_at": None,
        }
        for website_id in ids
    }

    opportunity_stmt = select(
        Opportunity.website_id, func.count()
    ).where(Opportunity.website_id.in_(ids))
    if project_id:
        opportunity_stmt = opportunity_stmt.where(Opportunity.project_id == project_id)
    for website_id, count in db.execute(
        opportunity_stmt.group_by(Opportunity.website_id)
    ).all():
        stats[website_id]["opportunities"] = int(count)

    task_stmt = select(Task.website_id, Task.status, func.count()).where(
        Task.website_id.in_(ids)
    )
    if project_id:
        task_stmt = task_stmt.where(Task.project_id == project_id)
    for website_id, status, count in db.execute(
        task_stmt.group_by(Task.website_id, Task.status)
    ).all():
        bucket = stats.get(website_id)
        if bucket is None:
            continue
        status = str(status or "").upper()
        if status in SUBMITTED_TASK_STATUSES:
            bucket["submitted"] += int(count)
        if status in VERIFIED_TASK_STATUSES:
            bucket["verified"] += int(count)
        if status in FAILED_TASK_STATUSES:
            bucket["failed"] += int(count)
        if status in PENDING_TASK_STATUSES:
            bucket["pending"] += int(count)
        if status in WAITING_TASK_STATUSES:
            bucket["waiting_for_details"] += int(count)

    last_stmt = select(
        Task.website_id,
        func.max(func.coalesce(Task.finished_at, Task.started_at, Task.created_at)),
    ).where(Task.website_id.in_(ids))
    if project_id:
        last_stmt = last_stmt.where(Task.project_id == project_id)
    for website_id, last_attempt in db.execute(last_stmt.group_by(Task.website_id)).all():
        if website_id in stats:
            stats[website_id]["last_attempt_at"] = last_attempt
    return stats


def _automation_payload(website: Website) -> dict[str, Any] | None:
    """The client friendly view of the per website adapter configuration."""
    from app.services.automation_setup import automation_payload

    return automation_payload(website)


def item_payload(
    db: Session, websites: Sequence[Website], project_id: str | None = None
) -> list[dict[str, Any]]:
    """The API payload of the given websites."""
    ids = [website.id for website in websites]
    projects = _project_ids(db, ids)
    stats = compute_stats(db, ids, project_id)
    payloads: list[dict[str, Any]] = []
    for website in websites:
        bucket = stats.get(website.id, {})
        project_ids = projects.get(website.id, [])
        payloads.append(
            {
                "id": website.id,
                "name": website.name,
                "domain": website.domain,
                "opportunity_url": website.opportunity_url,
                "signup_url": website.signup_url,
                "post_url": website.post_url,
                "recipe": website.recipe if isinstance(website.recipe, dict) else None,
                "registration_required": website.registration_required,
                "category": website.category,
                "niche": website.niche or "",
                "status": website.status,
                "submission_method": website.submission_method,
                "score": float(website.score or 0.0),
                "notes": website.notes,
                "excluded_until": website.excluded_until,
                "adapter_id": website.adapter_id,
                "adapter_key": website.adapter.key if website.adapter else None,
                "adapter_config": _automation_payload(website),
                "project_ids": project_ids,
                "project_count": len(project_ids),
                "stats": {
                    "opportunities": int(bucket.get("opportunities", 0)),
                    "submitted": int(bucket.get("submitted", 0)),
                    "verified": int(bucket.get("verified", 0)),
                    "failed": int(bucket.get("failed", 0)),
                    "pending": int(bucket.get("pending", 0)),
                    "waiting_for_details": int(bucket.get("waiting_for_details", 0)),
                    "last_attempt_at": bucket.get("last_attempt_at"),
                },
                "created_at": website.created_at,
                "updated_at": website.updated_at,
            }
        )
    return payloads


def list_entries(
    db: Session,
    *,
    search: str | None = None,
    category: str | None = None,
    niche: str | None = None,
    status: str | None = None,
    project_id: str | None = None,
    page: int = 1,
    page_size: int = 25,
    sort: str | None = None,
    order: str = "desc",
) -> tuple[list[dict[str, Any]], int]:
    """The (filtered) rows of the central list.

    Removed websites (``status = DELETED``) are not part of the list - they
    stay in the database, but the operator asked for them to be gone.  They
    can still be read with ``status=DELETED``.
    """
    conditions: list[Any] = []
    if status:
        conditions.append(Website.status == status.strip().upper())
    else:
        conditions.append(Website.status != DELETED_STATUS)
    if category:
        conditions.append(func.lower(Website.category) == category.strip().lower())
    if niche:
        conditions.append(func.lower(Website.niche).contains(niche.strip().lower()))
    if search:
        pattern = f"%{search.strip().lower()}%"
        conditions.append(
            or_(
                Website.name.ilike(pattern),
                Website.domain.ilike(pattern),
                Website.opportunity_url.ilike(pattern),
                Website.niche.ilike(pattern),
            )
        )
    if project_id:
        conditions.append(
            Website.id.in_(
                select(Opportunity.website_id).where(Opportunity.project_id == project_id)
            )
        )

    stmt = select(Website).where(*conditions)
    count_stmt = select(func.count()).select_from(Website).where(*conditions)
    column = SORT_COLUMNS.get((sort or "").strip().lower(), Website.created_at)
    stmt = stmt.order_by(column.desc() if order == "desc" else column.asc())

    total = int(db.execute(count_stmt).scalar_one() or 0)
    page = max(1, int(page))
    page_size = max(1, min(500, int(page_size)))
    rows = list(db.execute(stmt.limit(page_size).offset((page - 1) * page_size)).scalars().all())
    return item_payload(db, rows, project_id), total


def stats_rows(db: Session, project_id: str | None = None) -> list[dict[str, Any]]:
    """The per website statistics (one row per website of the list)."""
    conditions: list[Any] = [Website.status != DELETED_STATUS]
    if project_id:
        conditions.append(
            Website.id.in_(
                select(Opportunity.website_id).where(Opportunity.project_id == project_id)
            )
        )
    websites = list(
        db.execute(
            select(Website).where(*conditions).order_by(Website.domain.asc(), Website.name.asc())
        ).scalars().all()
    )
    stats = compute_stats(db, [website.id for website in websites], project_id)
    rows: list[dict[str, Any]] = []
    for website in websites:
        bucket = stats.get(website.id, {})
        rows.append(
            {
                "domain": website.domain,
                "name": website.name,
                "category": website.category,
                "status": website.status,
                "opportunities": int(bucket.get("opportunities", 0)),
                "submitted": int(bucket.get("submitted", 0)),
                "verified": int(bucket.get("verified", 0)),
                "failed": int(bucket.get("failed", 0)),
                "pending": int(bucket.get("pending", 0)),
                "waiting_for_details": int(bucket.get("waiting_for_details", 0)),
                "last_attempt_at": bucket.get("last_attempt_at"),
                "notes": website.notes,
            }
        )
    return rows


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------
def create_entry(
    db: Session,
    *,
    opportunity_url: str,
    name: str = "",
    category: str = DEFAULT_CATEGORY,
    niche: str = "",
    notes: str | None = None,
    submission_method: str = "UNKNOWN",
    status: str = DEFAULT_STATUS,
    signup_url: str | None = None,
    post_url: str | None = None,
) -> Website:
    """Add a website to the central list."""
    normalized = normalize_url(opportunity_url)
    domain = extract_domain(normalized)
    website = Website(
        name=(name or "").strip() or domain,
        domain=domain,
        opportunity_url=normalized,
        signup_url=(signup_url or "").strip() or None,
        post_url=(post_url or "").strip() or None,
        category=normalize_category(category),
        niche=normalize_niche(niche),
        discovery_source="manual",
        submission_method=str(submission_method or "UNKNOWN").strip().upper(),
        notes=notes,
        status=str(status or DEFAULT_STATUS).strip().upper(),
        is_manual=True,
    )
    db.add(website)
    db.commit()
    db.refresh(website)
    return website


def update_entry(db: Session, website: Website, changes: dict[str, Any]) -> Website:
    """Apply the given changes to a website of the list.

    Only the fields that are part of ``changes`` are written - a field that
    is not sent keeps its value.  The niche, the notes and the exclusion can
    be cleared (an empty value), the name, the category and the status can
    not.
    """
    if "name" in changes and changes["name"] is not None:
        name = str(changes["name"]).strip()
        if name:
            website.name = name
    if "category" in changes and changes["category"] is not None:
        website.category = normalize_category(changes["category"])
    if "niche" in changes:
        website.niche = normalize_niche(changes["niche"])
    if "notes" in changes:
        notes = changes["notes"]
        website.notes = str(notes).strip() if notes else None
    if "status" in changes and changes["status"] is not None:
        website.status = str(changes["status"]).strip().upper()
    if "excluded_until" in changes:
        website.excluded_until = changes["excluded_until"]
    if "signup_url" in changes:
        website.signup_url = (str(changes["signup_url"]).strip() or None) if changes["signup_url"] else None
    if "post_url" in changes:
        website.post_url = (str(changes["post_url"]).strip() or None) if changes["post_url"] else None
    website.version += 1
    website.updated_at = utcnow()
    db.commit()
    db.refresh(website)
    return website


def delete_entry(db: Session, website: Website) -> Website:
    """Remove a website from the list (soft delete).

    The opportunities, the tasks and the submissions of the website stay in the
    database - only the status of the website changes.
    """
    website.status = DELETED_STATUS
    website.deleted_at = utcnow()
    website.version += 1
    website.updated_at = utcnow()
    db.commit()
    db.refresh(website)
    return website


def restore_entry(db: Session, website: Website) -> Website:
    """Bring a removed website back into the list."""
    website.status = ACTIVE_STATUS
    website.deleted_at = None
    website.version += 1
    website.updated_at = utcnow()
    db.commit()
    db.refresh(website)
    return website


def purge_entry(db: Session, website: Website) -> int:
    """Delete a website forever - including its opportunities and tasks.

    Returns the number of opportunities that were removed with it.
    """
    opportunities = list(
        db.execute(select(Opportunity).where(Opportunity.website_id == website.id)).scalars().all()
    )
    for opportunity in opportunities:
        db.execute(delete(Task).where(Task.opportunity_id == opportunity.id))
        db.delete(opportunity)
    db.delete(website)
    db.commit()
    return len(opportunities)


# --------------------------------------------------------------------------
# Import
# --------------------------------------------------------------------------
def _looks_like_url(value: str) -> bool:
    """Does the value look like a URL (and not like a name)?"""
    text = str(value or "").strip()
    if not text:
        return False
    if text.startswith(("http://", "https://")):
        return True
    return " " not in text and "." in text and "/" not in text


def _niche_column(headers: Sequence[str], fields: dict[str, str]) -> str | None:
    """The column that carries the niche (the registry has no alias for it)."""
    for header in headers or []:
        source = str(header or "").strip().lower()
        if source in {"niche", "niches", "vertical"} and fields.get(str(header)):
            return str(header)
    return None


def _row_values(
    headers: Sequence[str], mapping: list[dict], cells: dict[str, Any]
) -> dict[str, Any]:
    """The canonical values of a spreadsheet row."""
    fields = mapping_to_fields(mapping)
    values: dict[str, Any] = {}
    for source, target in fields.items():
        values[target] = normalise_value(target, cells.get(source))
    niche_column = _niche_column(headers, fields)
    if niche_column:
        values["niche"] = normalise_value("niche", cells.get(niche_column))
    return values


def _is_blank_row(cells: Iterable[Any]) -> bool:
    for cell in cells:
        if cell is None:
            continue
        if str(cell).strip():
            return False
    return True


def import_entries(
    db: Session,
    path: Path,
    *,
    category: str | None = None,
    niche: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Import a spreadsheet into the central list.

    The column names are the ones of the campaign import (``Website``,
    ``Opportunity URL``, ``Category``, ``Anchor Text``, ``Target URL``,
    ``Description``, ``Email``, ``Notes``).  A row without a usable URL is
    reported as ``invalid`` with a reason - it is never dropped silently.
    """
    default_category = normalize_category(category) if category else ""
    default_niche = normalize_niche(niche)
    default_status = str(status or "").strip().upper()

    rows: list[dict[str, Any]] = []
    created = updated = skipped = invalid = 0
    usable_sheets = 0

    for sheet in read_workbook(path):
        header_index, headers = detect_header_row(sheet.rows)
        mapping = detect_mapping(headers)
        if not any(entry.get("target_field") for entry in mapping):
            # A sheet without a single known column is not a data sheet.
            continue
        usable_sheets += 1
        for offset, cells in enumerate(sheet.rows[header_index + 1 :]):
            if _is_blank_row(cells):
                continue
            row_number = header_index + 2 + offset
            row_cells = {
                headers[index] if index < len(headers) else f"column_{index + 1}": cell
                for index, cell in enumerate(cells)
            }
            outcome = _import_row(
                db,
                headers,
                mapping,
                row_cells,
                row_number,
                default_category=default_category,
                default_niche=default_niche,
                default_status=default_status,
            )
            action = outcome["action"]
            if action == "created":
                created += 1
            elif action == "updated":
                updated += 1
            elif action == "skipped":
                skipped += 1
            else:
                invalid += 1
            rows.append(outcome)

    if not usable_sheets:
        raise ValueError(
            "The file does not contain a known column "
            "('Opportunity URL' or 'Website' with a URL)"
        )

    db.commit()
    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "invalid": invalid,
        "rows": rows,
    }


def _import_row(
    db: Session,
    headers: Sequence[str],
    mapping: list[dict],
    cells: dict[str, Any],
    row_number: int,
    *,
    default_category: str,
    default_niche: str,
    default_status: str,
) -> dict[str, Any]:
    """Import a single row of a spreadsheet into the central list."""
    values = _row_values(headers, mapping, cells)

    raw_url = str(values.get("opportunity_url") or "").strip()
    name = str(values.get("website_name") or "").strip()
    if not raw_url and _looks_like_url(name):
        # The "Website" column carries the URL of the site.
        raw_url = name
        name = ""

    if not raw_url:
        return {
            "row": row_number,
            "action": "invalid",
            "reason": (
                "no opportunity URL in the row "
                "(neither an 'Opportunity URL' nor a 'Website' column with a URL)"
            ),
            "domain": "",
        }

    problem = check_url_syntax(raw_url)
    if problem:
        return {
            "row": row_number,
            "action": "invalid",
            "reason": f"opportunity_url: {problem}",
            "domain": "",
        }

    normalized = normalize_url(raw_url)
    domain = extract_domain(normalized)
    row_category = normalize_category(values.get("category")) if values.get("category") else ""
    row_niche = normalize_niche(values.get("niche"))
    row_status = str(values.get("status") or "").strip().upper()
    if row_status and row_status not in WEBSITE_STATUSES:
        # Campaign sheets carry the state of a *backlink* ("VERIFIED_LIVE",
        # "PENDING", ...), not the state of a website.
        row_status = ""

    existing = db.execute(
        select(Website).where(
            Website.domain == domain, Website.opportunity_url == normalized
        )
    ).scalar_one_or_none()

    if existing is not None:
        if existing.status == DELETED_STATUS:
            return {
                "row": row_number,
                "action": "skipped",
                "reason": "the website was removed from the list (status DELETED)",
                "domain": domain,
            }
        changes: dict[str, Any] = {}
        if name:
            changes["name"] = name
        if row_category:
            changes["category"] = row_category
        if row_niche:
            changes["niche"] = row_niche
        if values.get("notes"):
            changes["notes"] = values["notes"]
        if values.get("description"):
            existing.description = values["description"]
        if values.get("email"):
            existing.contact_email = values["email"]
        if values.get("anchor_text"):
            existing.anchor_text = values["anchor_text"]
        if row_status:
            existing.status = row_status
        if changes:
            update_entry(db, existing, changes)
        else:
            existing.updated_at = utcnow()
            db.commit()
        return {
            "row": row_number,
            "action": "updated",
            "reason": "the website is already in the list; its fields were refreshed",
            "domain": domain,
        }

    website = Website(
        name=name or domain,
        domain=domain,
        opportunity_url=normalized,
        category=row_category or default_category or DEFAULT_CATEGORY,
        niche=row_niche or default_niche,
        discovery_source="import",
        submission_method="UNKNOWN",
        description=values.get("description"),
        contact_email=values.get("email"),
        anchor_text=values.get("anchor_text"),
        notes=values.get("notes"),
        status=row_status or default_status or DEFAULT_STATUS,
        is_manual=True,
    )
    db.add(website)
    db.commit()
    db.refresh(website)
    return {
        "row": row_number,
        "action": "created",
        "reason": "the website was added to the list",
        "domain": domain,
    }


# --------------------------------------------------------------------------
# Choosing websites for a project
# --------------------------------------------------------------------------
def choose_for_project(
    db: Session,
    project: Project,
    *,
    website_ids: Sequence[str],
    category: str | None = None,
    niche: str | None = None,
    anchor_text: str | None = None,
    target_landing_page: str | None = None,
) -> dict[str, Any]:
    """Add websites of the central list to a project.

    Every website that is linked creates an opportunity and a submission task.
    Websites that are filtered out (by category or niche), that are already
    linked or that were removed from the list are skipped - a second run
    therefore never duplicates the work.
    """
    linked = skipped = tasks_created = 0
    task_ids: list[str] = []

    wanted_category = (category or "").strip().upper()
    wanted_niche = (niche or "").strip().lower()

    for website_id in website_ids or []:
        website = db.get(Website, website_id)
        if website is None:
            skipped += 1
            continue
        if website.status == DELETED_STATUS:
            skipped += 1
            continue
        if wanted_category and (website.category or "").strip().upper() != wanted_category:
            skipped += 1
            continue
        if wanted_niche and (website.niche or "").strip().lower() != wanted_niche:
            skipped += 1
            continue

        opportunity, created = link_to_project(
            db,
            project,
            website,
            target_landing_page=target_landing_page,
        )
        if not created:
            # The site is already part of the project - nothing is duplicated.
            skipped += 1
            continue

        linked += 1
        if anchor_text:
            website.anchor_text = anchor_text
        opportunity.status = "QUEUED"
        website.updated_at = utcnow()

        task, was_created = enqueue(
            db,
            task_type="SUBMIT",
            project_id=project.id,
            opportunity_id=opportunity.id,
            website_id=website.id,
            adapter_id=website.adapter_id,
            payload={
                "opportunity_id": opportunity.id,
                "website_id": website.id,
                "landing_page": opportunity.target_landing_page,
                "anchor_text": website.anchor_text,
                "source": "website_list",
            },
            idempotency_key=build_idempotency_key(
                "SUBMIT", project.id, opportunity.id, {"opportunity": opportunity.id}
            ),
        )
        if was_created:
            tasks_created += 1
            task_ids.append(task.id)

    db.commit()
    return {
        "linked": linked,
        "skipped": skipped,
        "tasks_created": tasks_created,
        "task_ids": task_ids,
    }
