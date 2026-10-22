"""Durable task queue.

The queue is stored in the database so it survives restarts, works offline in
local mode and can be processed by cloud workers, the embedded desktop worker
or a registered local agent. Claiming is atomic (conditional UPDATE) so the
same task can never be processed twice at the same time.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import utcnow
from app.db.models import Task
from app.db.repositories import TaskClaimRepository

log = get_logger(__name__)

QUEUE_STATUSES = ("QUEUED", "RETRY_SCHEDULED")

#: The statuses that still may turn into a submission.  When a project or an
#: opportunity leaves the lists, its open tasks are cancelled so the worker
#: cannot submit work for something that was deleted.
OPEN_TASK_STATUSES = (
    "QUEUED",
    "RETRY_SCHEDULED",
    "WAITING_FOR_APPROVAL",
    "WAITING_FOR_USER",
)


class DuplicateTask(Exception):
    """Raised when a task with the same idempotency key already exists."""

    def __init__(self, task: Task):
        super().__init__(f"Duplicate task {task.id} for key {task.idempotency_key}")
        self.task = task


def build_idempotency_key(
    task_type: str,
    project_id: str | None,
    opportunity_id: str | None,
    config: dict[str, Any] | None = None,
) -> str:
    """Stable identity: type + project + opportunity + relevant configuration."""
    payload = json.dumps(config or {}, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    parts = [task_type, project_id or "-", opportunity_id or "-", digest]
    return ":".join(parts)


def enqueue(
    db: Session,
    *,
    task_type: str,
    project_id: str | None = None,
    opportunity_id: str | None = None,
    website_id: str | None = None,
    campaign_id: str | None = None,
    adapter_id: str | None = None,
    payload: dict[str, Any] | None = None,
    priority: int = 0,
    scheduled_for: datetime | None = None,
    execution_environment: str = "CLOUD",
    max_attempts: int = 3,
    idempotency_key: str | None = None,
    status: str = "QUEUED",
) -> tuple[Task, bool]:
    """Create a task. Returns ``(task, created)``.

    ``created`` is False when an existing task with the same idempotency key
    was reused (this is how re-imported reports avoid duplicated work).
    """
    key = idempotency_key or build_idempotency_key(task_type, project_id, opportunity_id, payload)
    existing = db.execute(select(Task).where(Task.idempotency_key == key)).scalar_one_or_none()
    if existing is not None:
        return existing, False

    # The payload is stored as JSON - fail early with a clear message instead
    # of letting the database driver raise a serialization error.
    try:
        json.dumps(payload or {})
    except (TypeError, ValueError) as exc:
        raise ValueError(f"The task payload is not JSON serialisable: {exc}") from exc

    task = Task(
        project_id=project_id,
        opportunity_id=opportunity_id,
        website_id=website_id,
        campaign_id=campaign_id,
        type=task_type,
        status=status,
        priority=priority,
        execution_environment=execution_environment,
        adapter_id=adapter_id,
        idempotency_key=key,
        payload=payload or {},
        max_attempts=max_attempts,
        scheduled_for=scheduled_for,
    )
    db.add(task)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.execute(select(Task).where(Task.idempotency_key == key)).scalar_one_or_none()
        if existing is None:
            raise
        return existing, False
    return task, True


def claim_task(
    db: Session,
    worker_id: str,
    types: Sequence[str] = ("SUBMIT", "VERIFY", "DISCOVER", "IMPORT", "EXPORT"),
    environment: str | None = None,
) -> Task | None:
    repo = TaskClaimRepository(db)
    return repo.claim_next(worker_id, types, lease_seconds=settings.task_lease_seconds, environment=environment)


def complete_task(
    db: Session,
    task: Task,
    result: dict[str, Any] | None = None,
    status: str | None = None,
) -> Task:
    now = utcnow()
    task.status = status or ("SUBMITTED" if task.type == "SUBMIT" else "COMPLETED")
    task.result = result or {}
    task.progress = 1.0
    task.finished_at = now
    task.lease_owner = None
    task.lease_expires_at = None
    task.last_error = None
    task.updated_at = now
    db.commit()
    return task


def fail_task(
    db: Session,
    task: Task,
    error: str,
    *,
    retryable: bool = True,
    requires_human: bool = False,
    status: str | None = None,
) -> Task:
    now = utcnow()
    task.attempts = (task.attempts or 0) + 1
    task.last_error = error[:4000]
    task.updated_at = now

    if status:
        task.status = status
        if status in ("WAITING_FOR_USER", "WAITING_FOR_APPROVAL", "SKIPPED", "CANCELLED", "FAILED"):
            # These states are held by a human - the lease must be released so
            # the recovery sweep does not silently re-queue them.
            task.lease_owner = None
            task.lease_expires_at = None
            task.finished_at = now
    elif requires_human:
        task.status = "WAITING_FOR_USER"
        task.requires_human = True
    elif retryable and task.attempts < task.max_attempts:
        delay = _backoff_seconds(db, task)
        task.status = "RETRY_SCHEDULED"
        task.next_retry_at = now + timedelta(seconds=delay)
        task.scheduled_for = now + timedelta(seconds=delay)
        task.finished_at = now
        task.lease_owner = None
        task.lease_expires_at = None
    else:
        task.status = "FAILED"
        task.finished_at = now
        task.lease_owner = None
        task.lease_expires_at = None
    db.commit()
    return task


def _backoff_seconds(db: Session, task: Task) -> int:
    """Exponential backoff with jitter, honouring project settings."""
    base = 30
    jitter = 15
    if task.project_id:
        from app.db.models import ProjectSettings

        row = db.execute(
            select(ProjectSettings).where(ProjectSettings.project_id == task.project_id)
        ).scalar_one_or_none()
        if row is not None:
            base = row.backoff_base_seconds or base
            jitter = row.jitter_seconds if row.jitter_seconds is not None else jitter
    return base * (2 ** max(0, task.attempts - 1)) + secrets.randbelow(max(1, jitter) + 1)


def retry_task(db: Session, task: Task, *, reset_attempts: bool = False) -> Task:
    now = utcnow()
    if reset_attempts:
        task.attempts = 0
    task.status = "QUEUED"
    task.scheduled_for = now
    task.next_retry_at = now
    task.last_error = None
    task.requires_human = False
    task.lease_owner = None
    task.lease_expires_at = None
    task.finished_at = None
    task.updated_at = now
    db.commit()
    return task


def cancel_task(db: Session, task: Task, reason: str = "Cancelled by user") -> Task:
    task.status = "CANCELLED"
    task.skip_reason = reason
    task.finished_at = utcnow()
    task.lease_owner = None
    task.lease_expires_at = None
    task.updated_at = utcnow()
    db.commit()
    return task


def pause_task(db: Session, task: Task) -> Task:
    if task.status in ("QUEUED", "RETRY_SCHEDULED"):
        task.status = "DISCOVERED"
        task.updated_at = utcnow()
        db.commit()
    return task


def resume_task(db: Session, task: Task) -> Task:
    if task.status == "DISCOVERED":
        task.status = "QUEUED"
        task.scheduled_for = utcnow()
        task.updated_at = utcnow()
        db.commit()
    return task


def reorder_tasks(db: Session, task_ids: Sequence[str]) -> int:
    """Assign descending priorities following the given order (drag & drop)."""
    total = len(task_ids)
    updated = 0
    for index, task_id in enumerate(task_ids):
        task = db.get(Task, task_id)
        if task is None:
            continue
        task.priority = total - index
        task.updated_at = utcnow()
        updated += 1
    db.commit()
    return updated


def queue_stats(db: Session, project_id: str | None = None) -> dict[str, int]:
    stmt = select(Task.status, func.count()).group_by(Task.status)
    if project_id:
        stmt = stmt.where(Task.project_id == project_id)
    stats = dict.fromkeys(("QUEUED", "RUNNING", "RETRY_SCHEDULED", "WAITING_FOR_USER", "WAITING_FOR_APPROVAL", "FAILED", "SKIPPED", "CANCELLED", "SUBMITTED", "PUBLISHED_UNVERIFIED", "VERIFIED_LIVE"), 0)
    for status, count in db.execute(stmt).all():
        stats[status] = int(count)
    stats["TOTAL"] = sum(v for k, v in stats.items() if k != "TOTAL")
    return stats


def running_counts(db: Session) -> dict[str, int]:
    """Concurrency accounting used to enforce per project / domain limits."""
    rows = db.execute(
        select(Task.project_id, Task.website_id, Task.type, func.count())
        .where(Task.status == "RUNNING")
        .group_by(Task.project_id, Task.website_id, Task.type)
    ).all()
    by_project: dict[str, int] = {}
    by_domain: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for project_id, website_id, task_type, count in rows:
        if project_id:
            by_project[project_id] = by_project.get(project_id, 0) + int(count)
        if website_id:
            by_domain[website_id] = by_domain.get(website_id, 0) + int(count)
        by_type[task_type] = by_type.get(task_type, 0) + int(count)
    return {"by_project": by_project, "by_domain": by_domain, "by_type": by_type}
