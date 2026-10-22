"""Auto pilot: keep submitting without a manual queueing step.

When a project enables the auto pilot, every **approved** opportunity is
queued for submission automatically.  The operator stays in control of *what*
is submitted (only approved opportunities are) and the system takes care of
*when* it happens.

The module is deliberately free of side effects beyond the database: the
worker calls :func:`sweep` on every tick, the registry calls
:func:`queue_approved` after an approval.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.models import Opportunity, Project, ProjectSettings, Task, Website
from app.services import queue as queue_service
from app.services.events import record_event

#: Task states that mean "this opportunity is already being worked on".
OPEN_TASK_STATUSES = (
    "QUEUED",
    "RUNNING",
    "RETRY_SCHEDULED",
    "WAITING_FOR_USER",
    "WAITING_FOR_APPROVAL",
)

#: Task states that mean "the submission happened".
SUBMITTED_TASK_STATUSES = (
    "SUBMITTED",
    "PUBLISHED_UNVERIFIED",
    "VERIFIED_LIVE",
    "COMPLETED",
)


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------
def get_settings(db: Session, project_id: str) -> ProjectSettings | None:
    """The settings row of a project (``None`` when there is none)."""
    return db.execute(
        select(ProjectSettings).where(ProjectSettings.project_id == project_id)
    ).scalar_one_or_none()


def auto_submit_enabled(db: Session, project_id: str) -> bool:
    """Is the auto pilot enabled for this project?"""
    row = get_settings(db, project_id)
    return bool(row and row.auto_submit)


def categories_of(row: ProjectSettings | None) -> list[str]:
    """The categories the auto pilot is limited to (empty = every category)."""
    if row is None:
        return []
    return [str(item).strip().upper() for item in (row.auto_submit_categories or []) if str(item).strip()]


def set_auto_submit(
    db: Session,
    project_id: str,
    enabled: bool,
    categories: list[str] | None = None,
) -> ProjectSettings:
    """Enable or disable the auto pilot of a project."""
    row = get_settings(db, project_id)
    if row is None:
        row = ProjectSettings(project_id=project_id)
        db.add(row)
    row.auto_submit = bool(enabled)
    if categories is not None:
        row.auto_submit_categories = [
            str(item).strip().upper() for item in categories if str(item).strip()
        ]
    db.commit()
    db.refresh(row)
    return row


def category_allowed(category: str, allowed: list[str]) -> bool:
    """Is a category part of the auto pilot? An empty list allows everything."""
    if not allowed:
        return True
    return (category or "").strip().upper() in allowed


# --------------------------------------------------------------------------
# Queueing
# --------------------------------------------------------------------------
def _open_task_ids(db: Session, project_id: str) -> set[str]:
    """The opportunities that already have an open submission task."""
    rows = db.execute(
        select(Task.opportunity_id).where(
            Task.project_id == project_id,
            Task.type == "SUBMIT",
            Task.status.in_(OPEN_TASK_STATUSES),
            Task.opportunity_id.is_not(None),
        )
    ).scalars().all()
    return {row for row in rows if row}


def queue_approved(db: Session, project_id: str) -> list[Task]:
    """Queue every approved opportunity of the project that is not queued yet.

    The auto pilot has to be enabled for the project, otherwise nothing
    happens.  The idempotency key of the queue makes sure that an opportunity
    is never submitted twice.
    """
    row = get_settings(db, project_id)
    if row is None or not row.auto_submit:
        return []

    # One state decides whether a project is worked on: its status.  A paused
    # or archived project never gets new tasks, even with the auto pilot on.
    project = db.get(Project, project_id)
    if project is None or project.deleted_at is not None or project.status != "ACTIVE":
        return []

    allowed = categories_of(row)
    opportunities = db.execute(
        select(Opportunity, Website)
        .join(Website, Opportunity.website_id == Website.id)
        .where(
            Opportunity.project_id == project_id,
            Opportunity.status == "APPROVED",
            Opportunity.deleted_at.is_(None),
        )
    ).all()
    if not opportunities:
        return []

    busy = _open_task_ids(db, project_id)
    created: list[Task] = []
    for opportunity, website in opportunities:
        if opportunity.id in busy:
            continue
        if not category_allowed(website.category, allowed):
            continue
        if website.excluded_until is not None and website.excluded_until > utcnow():
            continue
        task, was_created = queue_service.enqueue(
            db,
            task_type="SUBMIT",
            project_id=project_id,
            opportunity_id=opportunity.id,
            website_id=website.id,
            adapter_id=website.adapter_id,
            payload={
                "opportunity_id": opportunity.id,
                "website_id": website.id,
                "landing_page": opportunity.target_landing_page,
                "anchor_text": website.anchor_text,
                "source": "autopilot",
            },
            idempotency_key=queue_service.build_idempotency_key(
                "SUBMIT", project_id, opportunity.id, {"opportunity": opportunity.id}
            ),
        )
        if not was_created:
            continue
        opportunity.status = "QUEUED"
        created.append(task)
        record_event(
            db,
            "task.queued",
            f"Auto pilot queued {website.domain}",
            task_id=task.id,
            project_id=project_id,
            website_id=website.id,
            metadata={"type": "SUBMIT", "source": "autopilot"},
        )
    if created:
        db.commit()
    return created


def sweep(db: Session) -> dict[str, int]:
    """Queue the approved opportunities of every project with the auto pilot on.

    This is the function the worker calls on every tick.  Projects without
    the setting are never touched.
    """
    rows = db.execute(
        select(ProjectSettings)
        .join(Project, Project.id == ProjectSettings.project_id)
        .where(
            ProjectSettings.auto_submit.is_(True),
            Project.status == "ACTIVE",
            Project.deleted_at.is_(None),
        )
    ).scalars().all()
    queued = 0
    for row in rows:
        queued += len(queue_approved(db, row.project_id))
    return {"projects": len(rows), "queued": queued}


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------
def _approved_opportunities(db: Session, project_id: str, allowed: list[str]) -> list[Opportunity]:
    rows = db.execute(
        select(Opportunity, Website)
        .join(Website, Opportunity.website_id == Website.id)
        .where(
            Opportunity.project_id == project_id,
            Opportunity.status == "APPROVED",
            Opportunity.deleted_at.is_(None),
        )
    ).all()
    return [
        opportunity
        for opportunity, website in rows
        if category_allowed(website.category, allowed)
    ]


def pending_count(db: Session, project_id: str) -> int:
    """The approved opportunities that are not queued yet."""
    row = get_settings(db, project_id)
    allowed = categories_of(row)
    opportunities = _approved_opportunities(db, project_id, allowed)
    if not opportunities:
        return 0
    busy = _open_task_ids(db, project_id)
    return len([item for item in opportunities if item.id not in busy])


def queued_count(db: Session, project_id: str) -> int:
    """The open submission tasks of the project."""
    return int(
        db.execute(
            select(func.count())
            .select_from(Task)
            .where(
                Task.project_id == project_id,
                Task.type == "SUBMIT",
                Task.status.in_(OPEN_TASK_STATUSES),
            )
        ).scalar_one()
        or 0
    )


def submitted_count(db: Session, project_id: str) -> int:
    """The opportunities the worker submitted for this project."""
    return int(
        db.execute(
            select(func.count())
            .select_from(Task)
            .where(
                Task.project_id == project_id,
                Task.type == "SUBMIT",
                Task.status.in_(SUBMITTED_TASK_STATUSES),
            )
        ).scalar_one()
        or 0
    )


def approved_count(db: Session, project_id: str) -> int:
    """The approved opportunities of the project."""
    row = get_settings(db, project_id)
    return len(_approved_opportunities(db, project_id, categories_of(row)))


def describe(db: Session, project_id: str) -> dict[str, object]:
    """The state of the auto pilot of a project."""
    row = get_settings(db, project_id)
    enabled = bool(row and row.auto_submit)
    waiting = pending_count(db, project_id)
    return {
        "project_id": project_id,
        "enabled": enabled,
        "categories": categories_of(row),
        "waiting": waiting,
        "submitted": submitted_count(db, project_id),
        "pending": waiting,
        "queued": queued_count(db, project_id),
    }
