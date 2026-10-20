"""Scheduled work: periodic verification and discovery schedules.

The scheduler is driven by the ``schedules`` table. It is intentionally simple
and portable (no cron dependency): every schedule stores its interval and the
next run time, and the scheduler ticks from the worker loop.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import utcnow
from app.db.models import (
    BacklinkRecord,
    Project,
    Schedule,
)
from app.services import queue as queue_service
from app.services.events import record_event


def tick_schedules(db: Session) -> int:
    """Create the tasks that are due. Returns the number of created tasks."""
    now = utcnow()
    schedules = db.execute(
        select(Schedule).where(Schedule.enabled.is_(True), Schedule.next_run_at <= now)
    ).scalars().all()
    created = 0
    for schedule in schedules:
        if schedule.kind == "verification":
            created += _schedule_verification(db, schedule, now)
        elif schedule.kind == "discovery":
            created += _schedule_discovery(db, schedule, now)
        schedule.last_run_at = now
        interval = schedule.interval_seconds or 3600
        schedule.next_run_at = now + timedelta(seconds=interval)
    db.commit()
    return created


def _schedule_verification(db: Session, schedule: Schedule, now) -> int:
    stmt = select(BacklinkRecord).where(
        BacklinkRecord.verification_status.in_(("PUBLISHED_UNVERIFIED", "SUBMITTED", "VERIFIED_LIVE"))
    )
    if schedule.target_id:
        stmt = stmt.where(BacklinkRecord.project_id == schedule.target_id)
    records = db.execute(stmt.limit(settings.verification_batch_size)).scalars().all()
    created = 0
    for record in records:
        due = record.next_verification_at is None or record.next_verification_at <= now
        if not due:
            continue
        _task, was_created = queue_service.enqueue(
            db,
            task_type="VERIFY",
            project_id=record.project_id,
            opportunity_id=record.opportunity_id,
            payload={"backlink_id": record.id, "force": False},
            priority=2,
            idempotency_key=f"VERIFY:schedule:{record.id}",
        )
        if was_created:
            created += 1
    if created:
        record_event(
            db,
            "verification.scheduled",
            f"Scheduled verification for {created} backlink(s)",
            project_id=schedule.target_id,
            metadata={"count": created},
        )
    return created


def _schedule_discovery(db: Session, schedule: Schedule, now) -> int:
    project = db.get(Project, schedule.target_id) if schedule.target_id else None
    if project is None:
        return 0
    provider = (schedule.config or {}).get("provider", "manual_seed")
    query = (schedule.config or {}).get("query", "")
    limit = int((schedule.config or {}).get("limit", 25))
    from app.db.models import DiscoveryRun

    run = DiscoveryRun(
        project_id=project.id,
        provider=provider,
        status="PENDING",
        query=query,
        requested_limit=limit,
    )
    db.add(run)
    db.flush()
    _task, created = queue_service.enqueue(
        db,
        task_type="DISCOVER",
        project_id=project.id,
        payload={"run_id": run.id, "provider": provider, "criteria": {"query": query, "limit": limit}},
        priority=1,
        idempotency_key=f"DISCOVER:schedule:{project.id}:{run.id}",
    )
    return 1 if created else 0


def ensure_default_schedules(db: Session) -> None:
    """Create the default periodic verification schedule when missing."""
    existing = db.execute(
        select(Schedule).where(Schedule.kind == "verification", Schedule.name == "Periodic backlink verification")
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            Schedule(
                name="Periodic backlink verification",
                kind="verification",
                interval_seconds=3600,
                next_run_at=utcnow() + timedelta(hours=1),
                enabled=True,
                config={"batch_size": settings.verification_batch_size},
            )
        )
        db.commit()
