"""The campaign cockpit of a project.

One screen should answer three questions:

* which websites are part of this project,
* how far is each of them,
* and what is left to do.

The module therefore adds websites by URL (one or many), starts the work with
a single call and reports the live state of every row.  It builds on the
existing services - a campaign is a view over websites, opportunities, tasks
and backlink records, not a second source of truth.
"""

from __future__ import annotations

import re
import urllib.parse
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.models import BacklinkRecord, Opportunity, Project, Task, Website
from app.services import opportunities as opportunity_service
from app.services import project_login
from app.services import queue as queue_service
from app.services import site_details as details_service
from app.services.automation_setup import automation_payload

#: The URLs of the input box are separated by a comma, a semicolon, a space
#: or a new line - people paste lists in all of these shapes.
URL_SPLIT = re.compile(r"[\s,;]+")

#: Tasks that are still on their way - the row is "in progress".
OPEN_TASK_STATUSES = (
    "QUEUED",
    "RETRY_SCHEDULED",
    "RUNNING",
    "PAUSED",
    "WAITING_FOR_APPROVAL",
    "WAITING_FOR_USER",
)

#: Verification states that mean "the link is there".
DONE_VERIFICATION = ("VERIFIED", "VERIFIED_LIVE", "LIVE")

#: Task states that mean "the submission happened".
DONE_TASK_STATUSES = ("COMPLETED", "SUBMITTED", "PUBLISHED_UNVERIFIED", "VERIFIED_LIVE")

#: Opportunities the operator removed from the campaign.
HIDDEN_OPPORTUNITY_STATUSES = ("EXCLUDED", "REJECTED", "DUPLICATE")

#: The status of one row of the campaign table.
ROW_STATUSES = (
    "NOT_STARTED",
    "NEEDS_DETAILS",
    "READY",
    "QUEUED",
    "SUBMITTING",
    "PAUSED",
    "WAITING_MANUAL",
    "LOGIN_NEEDED",
    "SUBMITTED",
    "VERIFIED",
    "FAILED",
    "VERIFICATION_FAILED",
    "EXCLUDED",
)

#: Task states the Stop button leaves behind.  They are not claimed by a
#: worker and Start turns them back into QUEUED tasks.
PAUSED_TASK_STATUSES = ("DISCOVERED", "PAUSED")


def split_urls(text: str | None) -> list[str]:
    """The single URLs of an input box, in the order the operator typed them."""
    parts = [part.strip() for part in URL_SPLIT.split(text or "") if part.strip()]
    # A pasted list often carries duplicates - adding the same site twice is
    # never useful, so the second one is reported instead of created.
    seen: set[str] = set()
    unique: list[str] = []
    for part in parts:
        key = part.lower().rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        unique.append(part)
    return unique


def _valid_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.netloc or "").split("@")[-1].split(":")[0]
    return bool(host) and ("." in host or host == "localhost")


# --------------------------------------------------------------------------
# Adding websites
# --------------------------------------------------------------------------
def add_websites(db: Session, project: Project, text: str | None) -> list[dict[str, Any]]:
    """Add the pasted URLs to the central list and to the project.

    Every URL is answered with a status - ``added`` (new website and new
    opportunity), ``linked`` (the website existed, the project is new),
    ``existing`` (already in this project), ``deleted`` (it waits in the
    recycle bin) or ``invalid``.  Nothing is dropped silently.
    """
    results: list[dict[str, Any]] = []
    for token in split_urls(text):
        normalized = opportunity_service.normalize_url(token)
        if not _valid_url(normalized):
            results.append(
                {
                    "input": token,
                    "url": normalized,
                    "status": "invalid",
                    "message": "Not a usable URL - use a domain or a full link.",
                }
            )
            continue

        website, created = opportunity_service.create_website(
            db,
            url=normalized,
            name="",
            category="BUSINESS_DIRECTORY",
            is_manual=True,
        )
        if website.deleted_at is not None:
            results.append(
                {
                    "input": token,
                    "url": normalized,
                    "status": "deleted",
                    "message": "This website waits in the recycle bin - restore it first.",
                    "website_id": website.id,
                }
            )
            continue

        if created:
            # A site the operator typed is an active part of the list, not a
            # half discovered candidate.
            website.status = "ACTIVE"

        opportunity, linked = opportunity_service.link_to_project(db, project, website)
        if created:
            status = "added"
            message = "Added to the list and to this project."
        elif linked:
            status = "linked"
            message = "Already in the list - linked to this project."
        else:
            status = "existing"
            message = "Already in this project."
        results.append(
            {
                "input": token,
                "url": website.opportunity_url,
                "status": status,
                "message": message,
                "website_id": website.id,
                "opportunity_id": opportunity.id,
            }
        )

    db.commit()
    return results


def link_imported(
    db: Session, project: Project, result: dict[str, Any]
) -> dict[str, Any]:
    """Link the rows of an imported spreadsheet to a project.

    The import itself fills the central list (``website_service``).  This adds
    the imported domains to the project of the campaign and reports how many
    opportunities were created.
    """
    domains = {
        str(row.get("domain") or "").strip().lower()
        for row in result.get("rows", [])
        if str(row.get("action") or "").upper() in ("CREATED", "UPDATED")
        and str(row.get("domain") or "").strip()
    }
    linked = 0
    if domains:
        websites = (
            db.execute(
                select(Website).where(
                    Website.domain.in_(domains), Website.deleted_at.is_(None)
                )
            )
            .scalars()
            .all()
        )
        for website in websites:
            _opportunity, created = opportunity_service.link_to_project(
                db, project, website
            )
            if created:
                linked += 1
        db.commit()
    result["linked"] = linked
    return result


# --------------------------------------------------------------------------
# Starting the work
# --------------------------------------------------------------------------
def _latest_tasks(db: Session, project_id: str) -> dict[str, Task]:
    """The newest SUBMIT task of every opportunity of the project."""
    tasks = (
        db.execute(
            select(Task)
            .where(Task.project_id == project_id, Task.type == "SUBMIT")
            .order_by(Task.created_at.asc())
        )
        .scalars()
        .all()
    )
    newest: dict[str, Task] = {}
    for task in tasks:
        if task.opportunity_id:
            newest[task.opportunity_id] = task
    return newest


def _latest_records(db: Session, project_id: str) -> dict[str, BacklinkRecord]:
    """The newest backlink record of every opportunity of the project."""
    records = (
        db.execute(
            select(BacklinkRecord)
            .where(BacklinkRecord.project_id == project_id)
            .order_by(BacklinkRecord.updated_at.asc())
        )
        .scalars()
        .all()
    )
    newest: dict[str, BacklinkRecord] = {}
    for record in records:
        if record.opportunity_id:
            newest[record.opportunity_id] = record
    return newest


def start_campaign(db: Session, project: Project) -> dict[str, Any]:
    """Fill the details and queue every ready website of the project.

    The project becomes ACTIVE - pressing start is the switch that starts the
    work.  A website whose details are still incomplete is not queued: it is
    reported as ``needs_details`` so the operator can fill the few missing
    values.  Nothing is sent half filled.
    """
    project.status = "ACTIVE"
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
    tasks = _latest_tasks(db, project.id)
    records = _latest_records(db, project.id)

    queued = 0
    already_queued = 0
    needs_details: list[dict[str, Any]] = []
    done = 0
    excluded = 0
    skipped = 0

    for opportunity in opportunities:
        website = db.get(Website, opportunity.website_id)
        if website is None or website.deleted_at is not None:
            skipped += 1
            continue
        if str(opportunity.status or "").upper() in HIDDEN_OPPORTUNITY_STATUSES:
            excluded += 1
            continue

        record = records.get(opportunity.id)
        if record is not None and record.verification_status in DONE_VERIFICATION:
            done += 1
            continue
        task = tasks.get(opportunity.id)
        # A submission that already happened is never queued twice; pressing
        # Start again reports it as done instead.
        if task is not None and task.status in DONE_TASK_STATUSES:
            done += 1
            continue

        # Fill what the business profile knows.  A fact that is not in the
        # profile stays missing - the row asks for it instead of inventing it.
        details, _generated, _source = details_service.generate_details(db, opportunity)
        probe = details_service.required_details(db, opportunity, details)
        if not probe["complete"]:
            needs_details.append(
                {
                    "opportunity_id": opportunity.id,
                    "website": website.name or website.domain,
                    "missing": [
                        probe["labels"].get(name, name) for name in probe["missing"]
                    ],
                }
            )
            continue

        if task is not None and task.status in PAUSED_TASK_STATUSES:
            # Resume the work that the Stop button paused.  The task keeps its
            # idempotency key, so pressing Start again never duplicates it.
            task.status = "QUEUED"
            task.scheduled_for = utcnow()
            task.updated_at = utcnow()
            opportunity.status = "QUEUED"
            queued += 1
            continue

        if task is not None and task.status in OPEN_TASK_STATUSES:
            already_queued += 1
            continue

        if opportunity.status not in ("APPROVED", "QUEUED", "COMPLETED"):
            opportunity.status = "APPROVED"
        _new_task, created = queue_service.enqueue(
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
                "source": "campaign",
            },
            execution_environment="LOCAL",
            idempotency_key=queue_service.build_idempotency_key(
                "SUBMIT", project.id, opportunity.id, {"opportunity": opportunity.id}
            ),
        )
        if created:
            queued += 1
            opportunity.status = "QUEUED"
        else:
            already_queued += 1

    db.commit()
    return {
        "queued": queued,
        "already_queued": already_queued,
        "needs_details": needs_details,
        "done": done,
        "excluded": excluded,
        "skipped": skipped,
        "total": len(opportunities),
    }


def stop_campaign(db: Session, project: Project) -> dict[str, Any]:
    """Pause the work of a project without losing it.

    Queued tasks are put back into a paused state Start can resume.  A task
    that is already running cannot be killed halfway through a form - it gets
    the stop request and ends at the next checkpoint.  The answer says exactly
    which of both happened.
    """
    project.status = "PAUSED"
    paused = 0
    stopping = 0
    tasks = (
        db.execute(
            select(Task).where(
                Task.project_id == project.id,
                Task.type == "SUBMIT",
                Task.status.in_(OPEN_TASK_STATUSES),
            )
        )
        .scalars()
        .all()
    )
    for task in tasks:
        if task.status == "RUNNING":
            task.cancel_requested = True
            task.updated_at = utcnow()
            stopping += 1
        elif task.status in ("QUEUED", "RETRY_SCHEDULED"):
            queue_service.pause_task(db, task)
            paused += 1
    db.commit()
    return {
        "project_status": project.status,
        "paused": paused,
        "stopping": stopping,
        "message": (
            f"{paused} website(s) paused"
            + (f", {stopping} running task(s) stop at the next step" if stopping else "")
        ),
    }


def unassign(
    db: Session, project: Project, opportunity: Opportunity
) -> dict[str, Any]:
    """Remove one website from a project - the website itself stays.

    Open work of the row is cancelled first, so a removed website cannot be
    submitted in the background.  The website remains in the central list and
    can be added to this project again later.
    """
    task = (
        db.execute(
            select(Task)
            .where(Task.opportunity_id == opportunity.id, Task.type == "SUBMIT")
            .order_by(Task.created_at.desc())
        )
        .scalars()
        .first()
    )
    if task is not None and task.status in OPEN_TASK_STATUSES:
        if task.status == "RUNNING":
            task.cancel_requested = True
        queue_service.cancel_task(db, task, "Website removed from the project")

    opportunity.status = "EXCLUDED"
    opportunity.deleted_at = utcnow()
    opportunity.updated_at = utcnow()
    db.commit()
    return {"removed": True, "opportunity_id": opportunity.id}


def restart_failed(db: Session, project: Project) -> dict[str, Any]:
    """Queue every failed submission and failed verification again."""
    tasks = _latest_tasks(db, project.id)
    records = _latest_records(db, project.id)
    retried = 0
    verifications = 0

    for task in tasks.values():
        if task.status != "FAILED":
            continue
        queue_service.retry_task(db, task, reset_attempts=True)
        retried += 1

    for record in records.values():
        if record.verification_status not in ("VERIFICATION_FAILED", "REMOVED"):
            continue
        opportunity = db.get(Opportunity, record.opportunity_id) if record.opportunity_id else None
        if opportunity is None or opportunity.deleted_at is not None:
            continue
        queue_service.enqueue(
            db,
            task_type="VERIFY",
            project_id=project.id,
            opportunity_id=opportunity.id,
            website_id=opportunity.website_id,
            payload={"backlink_id": record.id, "force": True},
            priority=3,
            idempotency_key=(
                f"VERIFY:{record.id}:restart:{int(utcnow().timestamp())}"
            ),
        )
        verifications += 1

    if retried or verifications:
        project.status = "ACTIVE"
        db.commit()
    return {
        "retried": retried,
        "verifications": verifications,
        "project_status": project.status,
    }


def mark_submitted(
    db: Session,
    project: Project,
    opportunity: Opportunity,
    *,
    published_url: str | None = None,
    anchor_text: str | None = None,
    verify: bool = True,
) -> dict[str, Any]:
    """Record a submission the operator made by hand.

    Many directories have no automation - the operator fills the form and
    tells the app that it happened.  The task is completed (so it no longer
    waits), a backlink record is written and the verification is queued.  The
    record is *not* marked verified - only a real check may do that.
    """
    website = db.get(Website, opportunity.website_id)
    if website is None:
        raise ValueError("The opportunity has no website")

    landing = opportunity.target_landing_page or project.target_website or ""
    published = opportunity_service.normalize_url(published_url or "") or website.opportunity_url

    record = db.execute(
        select(BacklinkRecord)
        .where(BacklinkRecord.opportunity_id == opportunity.id)
        .order_by(BacklinkRecord.updated_at.desc())
    ).scalars().first()
    if record is None:
        record = BacklinkRecord(
            project_id=project.id,
            opportunity_id=opportunity.id,
            target_website=published,
            expected_link_url=published,
            published_page_url=published,
            expected_destination_url=landing,
            verification_status="SUBMITTED",
            evidence={"manual": True},
        )
        db.add(record)
    else:
        record.published_page_url = published
        record.target_website = published
        record.expected_link_url = published
        record.expected_destination_url = landing or record.expected_destination_url
        record.verification_status = "SUBMITTED"
        record.error = None
        record.version += 1
    if anchor_text:
        record.observed_anchor_text = anchor_text.strip()
    elif website.anchor_text:
        record.observed_anchor_text = website.anchor_text

    task = db.execute(
        select(Task)
        .where(Task.opportunity_id == opportunity.id, Task.type == "SUBMIT")
        .order_by(Task.created_at.desc())
    ).scalars().first()
    if task is not None and task.status in OPEN_TASK_STATUSES:
        queue_service.complete_task(
            db,
            task,
            {"manual": True, "published_page_url": published},
            status="SUBMITTED",
        )

    opportunity.status = "COMPLETED"
    db.flush()

    verify_task_id = None
    if verify:
        verify_task, _created = queue_service.enqueue(
            db,
            task_type="VERIFY",
            project_id=project.id,
            opportunity_id=opportunity.id,
            website_id=website.id,
            payload={"backlink_id": record.id, "force": True},
            priority=3,
            idempotency_key=f"VERIFY:{record.id}:manual:{int(utcnow().timestamp())}",
        )
        verify_task_id = verify_task.id

    db.commit()
    db.refresh(record)
    return {
        "backlink_id": record.id,
        "published_page_url": record.published_page_url,
        "verification_status": record.verification_status,
        "verify_task_id": verify_task_id,
        "opportunity_id": opportunity.id,
    }


# --------------------------------------------------------------------------
# Reading the live state
# --------------------------------------------------------------------------
def _row_status(
    opportunity: Opportunity,
    details_complete: bool,
    task: Task | None,
    record: BacklinkRecord | None,
    login_status: str | None = None,
) -> str:
    if str(opportunity.status or "").upper() in HIDDEN_OPPORTUNITY_STATUSES:
        return "EXCLUDED"
    if record is not None and record.verification_status in DONE_VERIFICATION:
        return "VERIFIED"
    if record is not None and record.verification_status in (
        "VERIFICATION_FAILED",
        "REMOVED",
    ):
        return "VERIFICATION_FAILED"
    if record is not None and record.verification_status in (
        "SUBMITTED",
        "PUBLISHED_UNVERIFIED",
    ):
        return "SUBMITTED"
    if task is not None:
        if task.status in PAUSED_TASK_STATUSES:
            return "PAUSED"
        if task.status == "RUNNING":
            return "SUBMITTING"
        if task.status in ("QUEUED", "RETRY_SCHEDULED", "PAUSED"):
            return "QUEUED"
        if task.status in ("WAITING_FOR_USER", "WAITING_FOR_APPROVAL"):
            if str(task.last_error or "").startswith(project_login.LOGIN_REQUIRED_PREFIX):
                return "LOGIN_NEEDED"
            return "WAITING_MANUAL" if details_complete else "NEEDS_DETAILS"
        if task.status == "FAILED":
            return "FAILED"
        if task.status in DONE_TASK_STATUSES:
            return "SUBMITTED"
    if login_status in ("EXPIRED", "LOGIN_REQUIRED"):
        # The site refused the last visit with a login wall.  Starting it again
        # without a fresh login would only pause it again, so the row says what
        # it needs instead of pretending to be ready.
        return "NEEDS_DETAILS" if not details_complete else "LOGIN_NEEDED"
    if details_complete:
        return "READY"
    return "NEEDS_DETAILS"


def _percent(filled: int, total: int) -> int:
    if total <= 0:
        return 100
    return max(0, min(100, round(filled * 100 / total)))


def campaign_payload(db: Session, project: Project) -> dict[str, Any]:
    """Every row of the campaign plus the counters above the table."""
    opportunities = (
        db.execute(
            select(Opportunity)
            .where(
                Opportunity.project_id == project.id,
                Opportunity.deleted_at.is_(None),
            )
            .order_by(Opportunity.created_at.asc())
        )
        .scalars()
        .all()
    )
    tasks = _latest_tasks(db, project.id)
    records = _latest_records(db, project.id)
    from app.db.models import WebsiteLoginSession

    login_rows = (
        db.execute(
            select(WebsiteLoginSession).where(
                WebsiteLoginSession.project_id == project.id
            )
        )
        .scalars()
        .all()
    )
    logins = {row.website_id: row for row in login_rows}

    rows: list[dict[str, Any]] = []
    counters = {
        "total": 0,
        "done": 0,
        "verified": 0,
        "submitted": 0,
        "in_progress": 0,
        "waiting_manual": 0,
        "login_needed": 0,
        "needs_details": 0,
        "not_started": 0,
        "paused": 0,
        "failed": 0,
        "excluded": 0,
        "remaining": 0,
    }

    for opportunity in opportunities:
        website = db.get(Website, opportunity.website_id)
        if website is None:
            continue
        task = tasks.get(opportunity.id)
        record = records.get(opportunity.id)
        # The gap report separates three groups: values that are stored, values
        # the business profile can supply on Start, and values nobody can
        # supply.  Only the last group blocks the row - a row that Start can
        # complete is "ready", not "needs details".
        gap = details_service.gap_report(db, opportunity)
        required = gap["required"]
        derivable = gap["derivable"]
        blocked = gap["not_derivable"]
        details_percent = _percent(
            len(gap["filled"]) + len(derivable), len(required)
        )
        login_row = logins.get(website.id)
        login_status = login_row.status if login_row is not None else None
        status = _row_status(
            opportunity, not blocked, task, record, login_status
        )

        last_update = max(
            [
                value
                for value in (
                    opportunity.updated_at,
                    website.updated_at,
                    task.updated_at if task else None,
                    record.updated_at if record else None,
                )
                if isinstance(value, datetime)
            ],
            default=None,
        )

        counters["total"] += 1
        if status == "VERIFIED":
            counters["verified"] += 1
            counters["done"] += 1
        elif status == "SUBMITTED":
            counters["submitted"] += 1
            counters["done"] += 1
        elif status in ("QUEUED", "SUBMITTING"):
            counters["in_progress"] += 1
        elif status == "WAITING_MANUAL":
            counters["waiting_manual"] += 1
        elif status == "LOGIN_NEEDED":
            counters["login_needed"] += 1
        elif status == "NEEDS_DETAILS":
            counters["needs_details"] += 1
        elif status == "PAUSED":
            counters["paused"] += 1
        elif status in ("FAILED", "VERIFICATION_FAILED"):
            counters["failed"] += 1
        elif status == "EXCLUDED":
            counters["excluded"] += 1
        elif status == "READY":
            counters["not_started"] += 1
        else:
            counters["not_started"] += 1

        rows.append(
            {
                "opportunity_id": opportunity.id,
                "website_id": website.id,
                "name": website.name or website.domain,
                "domain": website.domain,
                "url": website.opportunity_url,
                "category": website.category,
                "status": status,
                "details_percent": details_percent,
                "details_complete": not blocked,
                "missing": [item["label"] for item in blocked],
                "task_id": task.id if task else None,
                "task_status": task.status if task else None,
                "backlink_id": record.id if record else None,
                "verification_status": record.verification_status if record else None,
                "published_page_url": record.published_page_url if record else None,
                "observed_anchor_text": record.observed_anchor_text if record else None,
                "adapter_key": website.adapter.key if website.adapter else None,
                "adapter_config": automation_payload(website),
                "login_status": login_status,
                "login_error": login_row.last_error if login_row is not None else None,
                "last_update": last_update,
            }
        )

    counters["remaining"] = max(
        0, counters["total"] - counters["done"] - counters["excluded"]
    )
    workable = max(0, counters["total"] - counters["excluded"])
    counters["percent"] = _percent(counters["done"], workable) if workable else 0
    return {
        "project_id": project.id,
        "project_status": project.status,
        "generated_at": utcnow(),
        "rows": rows,
        "summary": counters,
    }


def campaign_row(db: Session, project_id: str, opportunity_id: str) -> Opportunity | None:
    """The opportunity of the project (``None`` when it is not part of it)."""
    return db.execute(
        select(Opportunity).where(
            Opportunity.id == opportunity_id,
            Opportunity.project_id == project_id,
            Opportunity.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
