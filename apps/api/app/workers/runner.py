"""Background worker runtime.

The worker is storage agnostic: it claims tasks from the database with an
atomic conditional update, honours the concurrency limits of the project and
of the target domain, writes an append-only attempt history and publishes
live events.

It can run in three ways:
  * embedded in the API process (desktop / local mode) - ``EmbeddedWorker``
  * as a standalone process - ``python -m app.workers.runner``
  * dispatched by Celery when a broker is configured - ``app.workers.celery_app``
"""

from __future__ import annotations

import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import utcnow
from app.db.models import (
    ProjectSettings,
    Task,
    TaskAttempt,
    Website,
)
from app.db.repositories import TaskClaimRepository
from app.db.session import session_scope
from app.services import queue as queue_service
from app.services.events import record_event

log = get_logger(__name__)


@dataclass
class TaskOutcome:
    """Result of a task handler."""

    status: str
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    retryable: bool = False
    requires_human: bool = False
    requires_approval: bool = False
    message: str = ""


Handler = Callable[[Any, Task], TaskOutcome]
_HANDLERS: dict[str, Handler] = {}


def register_handler(task_type: str, handler: Handler) -> None:
    _HANDLERS[task_type] = handler


def _handle_submit(db, task: Task) -> TaskOutcome:
    from app.services.submission import execute_submission

    return execute_submission(db, task)


def _handle_verify(db, task: Task) -> TaskOutcome:
    from app.services.verification import verify_task

    return verify_task(db, task)


def _handle_discover(db, task: Task) -> TaskOutcome:
    from app.services.discovery.runner import run_discovery_task

    return run_discovery_task(db, task)


def _handle_import(db, task: Task) -> TaskOutcome:
    return TaskOutcome(status="COMPLETED", result={"message": "Imports are executed synchronously"})


def _handle_export(db, task: Task) -> TaskOutcome:
    return TaskOutcome(status="COMPLETED", result={"message": "Reports are generated on demand"})


register_handler("SUBMIT", _handle_submit)
register_handler("VERIFY", _handle_verify)
register_handler("DISCOVER", _handle_discover)
register_handler("IMPORT", _handle_import)
register_handler("EXPORT", _handle_export)


class Worker:
    """Database backed worker loop."""

    def __init__(self, worker_id: str | None = None, poll_interval: float | None = None):
        self.worker_id = worker_id or settings.worker_id
        self.poll_interval = poll_interval or settings.worker_poll_interval
        self.running = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.processed = 0
        self.failed = 0
        self._schedule_tick = 0
        self.last_heartbeat: datetime | None = None
        self.started_at: datetime | None = None

    # -- lifecycle ------------------------------------------------------
    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._stop.clear()
        self.started_at = utcnow()
        self._thread = threading.Thread(target=self.run_forever, name=f"worker-{self.worker_id}", daemon=True)
        self._thread.start()
        log.info("worker started", extra={"extra_fields": {"worker": self.worker_id}})

    def stop(self, timeout: float = 10.0) -> None:
        self.running = False
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        log.info("worker stopped", extra={"extra_fields": {"worker": self.worker_id}})

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "worker_id": self.worker_id,
            "processed": self.processed,
            "failed": self.failed,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "mode": "embedded",
        }

    # -- main loop ------------------------------------------------------
    def run_forever(self) -> None:
        last_reclaim = 0.0
        while not self._stop.is_set():
            try:
                now = time.time()
                if now - last_reclaim > 30:
                    last_reclaim = now
                    self.reclaim_expired()
                self.tick()
            except Exception:  # pragma: no cover - keep the worker alive
                log.exception("worker tick failed")
            self._stop.wait(self.poll_interval)

    def reclaim_expired(self) -> None:
        with session_scope() as db:
            repo = TaskClaimRepository(db)
            count = repo.reclaim_expired()
            if count:
                log.warning("reclaimed expired tasks", extra={"extra_fields": {"count": count}})
                record_event(
                    db,
                    "task.reclaimed",
                    f"Reclaimed {count} task(s) after a worker interruption",
                    level="WARNING",
                )

    def tick(self) -> int:
        """Claim and execute at most one task (per type) in this iteration."""
        executed = 0
        with session_scope() as db:
            repo = TaskClaimRepository(db)
            self._schedule_tick += 1
            if self._schedule_tick % 30 == 0:
                try:
                    from app.services.scheduler import tick_schedules

                    tick_schedules(db)
                except Exception:  # pragma: no cover - scheduling must not break the worker
                    log.exception("scheduler tick failed")
            for task_type in ("SUBMIT", "VERIFY", "DISCOVER", "IMPORT", "EXPORT"):
                if self._stop.is_set():
                    break
                candidates = repo.candidates([task_type])
                for candidate in candidates:
                    if self._stop.is_set():
                        break
                    if not self.within_limits(db, candidate):
                        continue
                    task = repo.try_claim(candidate.id, self.worker_id)
                    if task is None:
                        continue
                    self.execute(db, task)
                    executed += 1
                    break
        return executed

    # -- limits ---------------------------------------------------------
    def within_limits(self, db, task: Task) -> bool:
        running_total = int(
            db.execute(select(func.count()).select_from(Task).where(Task.status == "RUNNING")).scalar_one() or 0
        )
        global_limit = settings.worker_batch_size * 2
        project_settings = None
        if task.project_id:
            project_settings = db.execute(
                select(ProjectSettings).where(ProjectSettings.project_id == task.project_id)
            ).scalar_one_or_none()
            if project_settings is not None:
                global_limit = min(global_limit, project_settings.global_concurrency or global_limit)
                project_running = int(
                    db.execute(
                        select(func.count())
                        .select_from(Task)
                        .where(Task.status == "RUNNING", Task.project_id == task.project_id)
                    ).scalar_one()
                    or 0
                )
                if project_running >= (project_settings.max_concurrency or 3):
                    return False
        if running_total >= global_limit:
            return False

        if task.website_id and project_settings is not None:
            domain_limit = project_settings.per_domain_concurrency or 1
            website = db.get(Website, task.website_id)
            domain_running = int(
                db.execute(
                    select(func.count())
                    .select_from(Task)
                    .join(Website, Task.website_id == Website.id)
                    .where(Task.status == "RUNNING", Website.domain == (website.domain if website else ""))
                ).scalar_one()
                or 0
            )
            if domain_running >= domain_limit:
                return False
        return True

    # -- execution ------------------------------------------------------
    def execute(self, db, task: Task) -> None:
        handler = _HANDLERS.get(task.type)
        attempt_number = (task.attempts or 0) + 1
        attempt = TaskAttempt(
            task_id=task.id,
            attempt_number=attempt_number,
            started_at=utcnow(),
            outcome="RUNNING",
            worker=self.worker_id,
            execution_environment=task.execution_environment,
        )
        db.add(attempt)
        db.commit()
        self.processed += 1
        self.last_heartbeat = utcnow()

        record_event(
            db,
            "task.started",
            f"Task {task.type.lower()} started",
            task_id=task.id,
            project_id=task.project_id,
            website_id=task.website_id,
            execution_environment=task.execution_environment,
        )

        if handler is None:
            queue_service.fail_task(db, task, f"No handler registered for task type {task.type}")
            self.failed += 1
            return

        try:
            outcome = handler(db, task)
        except Exception as exc:  # pragma: no cover - handler bugs
            log.exception("task handler crashed", extra={"extra_fields": {"task": task.id}})
            attempt.outcome = "FAILED"
            attempt.error = f"{type(exc).__name__}: {exc}"
            attempt.finished_at = utcnow()
            attempt.evidence = {"traceback": traceback.format_exc()[-4000:]}
            db.commit()
            queue_service.fail_task(db, task, attempt.error or "Handler crashed")
            record_event(
                db,
                "task.failed",
                f"Task failed: {attempt.error}",
                level="ERROR",
                task_id=task.id,
                project_id=task.project_id,
                metadata={"error": attempt.error},
            )
            self.failed += 1
            return

        attempt.finished_at = utcnow()
        attempt.outcome = outcome.status
        attempt.error = outcome.error
        attempt.evidence = outcome.result or {}
        db.commit()

        if outcome.status in ("COMPLETED", "SUBMITTED", "PUBLISHED_UNVERIFIED", "VERIFIED_LIVE"):
            queue_service.complete_task(db, task, outcome.result, status=outcome.status)
            record_event(
                db,
                "task.completed",
                outcome.message or f"Task {outcome.status.lower()}",
                level="SUCCESS",
                task_id=task.id,
                project_id=task.project_id,
                website_id=task.website_id,
                metadata=outcome.result or {},
            )
        elif outcome.status in ("WAITING_FOR_USER", "WAITING_FOR_APPROVAL"):
            queue_service.fail_task(
                db,
                task,
                outcome.error or outcome.message or "Manual intervention required",
                requires_human=True,
                status=outcome.status,
            )
            record_event(
                db,
                "task.waiting_for_user",
                outcome.message or "Manual intervention required",
                level="WARNING",
                task_id=task.id,
                project_id=task.project_id,
                website_id=task.website_id,
                metadata=outcome.result or {},
            )
        elif outcome.status == "SKIPPED":
            task.status = "SKIPPED"
            task.skip_reason = outcome.message or outcome.error
            task.finished_at = utcnow()
            task.lease_owner = None
            task.lease_expires_at = None
            db.commit()
            record_event(
                db,
                "task.skipped",
                outcome.message or "Task skipped",
                level="WARNING",
                task_id=task.id,
                project_id=task.project_id,
                metadata=outcome.result or {},
            )
        else:
            queue_service.fail_task(
                db,
                task,
                outcome.error or "Task failed",
                retryable=outcome.retryable,
                status=None if outcome.retryable else "FAILED",
            )
            record_event(
                db,
                "task.failed",
                outcome.message or outcome.error or "Task failed",
                level="ERROR",
                task_id=task.id,
                project_id=task.project_id,
                website_id=task.website_id,
                metadata=outcome.result or {},
            )
            self.failed += 1


class EmbeddedWorker(Worker):
    """Worker that runs inside the API process (desktop / local mode)."""


def main() -> None:  # pragma: no cover - process entry point
    worker = Worker()
    worker.start()
    log.info("standalone worker running", extra={"extra_fields": {"worker": worker.worker_id}})
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        worker.stop()


if __name__ == "__main__":  # pragma: no cover
    main()
