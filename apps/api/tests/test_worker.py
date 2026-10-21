"""Worker tests: execution, attempt history, retries, recovery and limits."""

from __future__ import annotations

import time
from datetime import timedelta

from app.db.base import utcnow
from app.db.models import Task, TaskAttempt
from app.db.repositories import TaskClaimRepository
from app.db.session import get_session_factory
from app.services import queue as queue_service
from app.workers.runner import TaskOutcome, Worker, register_handler


def _read_task(task_id: str) -> Task | None:
    """Read a task with a fresh session (the worker uses its own session)."""
    session = get_session_factory()()
    try:
        return session.get(Task, task_id)
    finally:
        session.close()


def _claim(task_id: str, worker_id: str = "test-worker") -> None:
    """Claim a task so it is in the RUNNING state."""
    session = get_session_factory()()
    try:
        assert TaskClaimRepository(session).try_claim(task_id, worker_id) is not None
    finally:
        session.close()


def test_worker_executes_the_handler_and_writes_an_attempt(db_session) -> None:
    register_handler("TEST_OK", lambda db, task: TaskOutcome(status="COMPLETED", result={"ok": True}))
    task, _created = queue_service.enqueue(
        db_session, task_type="TEST_OK", idempotency_key="worker-ok"
    )
    _claim(task.id)

    worker = Worker(worker_id="test-worker")
    worker.execute(db_session, db_session.get(Task, task.id))

    db_session.rollback()
    attempts = db_session.query(TaskAttempt).filter_by(task_id=task.id).all()
    assert len(attempts) == 1
    assert attempts[0].attempt_number == 1
    assert attempts[0].outcome == "COMPLETED"
    assert attempts[0].error is None
    assert attempts[0].evidence == {"ok": True}
    assert attempts[0].worker == "test-worker"
    assert attempts[0].finished_at is not None


def test_worker_moves_the_task_to_a_terminal_status(db_session) -> None:
    register_handler("TEST_DONE", lambda db, task: TaskOutcome(status="COMPLETED"))
    task, _created = queue_service.enqueue(
        db_session, task_type="TEST_DONE", idempotency_key="worker-done"
    )
    _claim(task.id)

    worker = Worker(worker_id="test-worker")
    worker.execute(db_session, db_session.get(Task, task.id))

    db_session.rollback()
    stored = db_session.get(Task, task.id)
    assert stored.status in ("COMPLETED", "SUBMITTED")
    assert stored.finished_at is not None
    assert stored.progress == 1.0


def test_failing_handler_schedules_a_retry_with_backoff(db_session) -> None:
    def failing(db, task):
        return TaskOutcome(status="FAILED", error="boom", message="boom", retryable=True)

    register_handler("TEST_FAIL", failing)
    task, _created = queue_service.enqueue(
        db_session, task_type="TEST_FAIL", idempotency_key="worker-fail"
    )
    _claim(task.id)
    before = utcnow()

    worker = Worker(worker_id="test-worker")
    worker.execute(db_session, db_session.get(Task, task.id))

    db_session.rollback()
    stored = db_session.get(Task, task.id)
    assert stored.status == "RETRY_SCHEDULED"
    assert stored.attempts == 1
    assert stored.last_error == "boom"
    assert stored.next_retry_at is not None
    assert stored.next_retry_at > before
    assert stored.next_retry_at > utcnow()
    assert stored.lease_owner is None
    assert stored.lease_expires_at is None

    attempts = db_session.query(TaskAttempt).filter_by(task_id=task.id).all()
    assert len(attempts) == 1
    assert attempts[0].outcome == "FAILED"
    assert attempts[0].error == "boom"


def test_failing_handler_without_retry_marks_the_task_failed(db_session) -> None:
    register_handler(
        "TEST_FATAL",
        lambda db, task: TaskOutcome(status="FAILED", error="fatal", retryable=False),
    )
    task, _created = queue_service.enqueue(
        db_session, task_type="TEST_FATAL", idempotency_key="worker-fatal"
    )
    _claim(task.id)

    worker = Worker(worker_id="test-worker")
    worker.execute(db_session, db_session.get(Task, task.id))

    db_session.rollback()
    stored = db_session.get(Task, task.id)
    assert stored.status == "FAILED"
    assert stored.next_retry_at is None


def test_a_crashing_handler_is_recorded_as_a_failed_attempt(db_session) -> None:
    def crashing(db, task):
        raise RuntimeError("handler exploded")

    register_handler("TEST_CRASH", crashing)
    task, _created = queue_service.enqueue(
        db_session, task_type="TEST_CRASH", idempotency_key="worker-crash"
    )
    _claim(task.id)

    worker = Worker(worker_id="test-worker")
    worker.execute(db_session, db_session.get(Task, task.id))

    db_session.rollback()
    stored = db_session.get(Task, task.id)
    assert stored.status == "RETRY_SCHEDULED"
    assert "handler exploded" in (stored.last_error or "")

    attempts = db_session.query(TaskAttempt).filter_by(task_id=task.id).all()
    assert len(attempts) == 1
    assert attempts[0].outcome == "FAILED"
    assert "handler exploded" in (attempts[0].error or "")


def test_reclaim_expired_returns_an_abandoned_task_to_the_queue(db_session) -> None:
    task, _created = queue_service.enqueue(
        db_session, task_type="SUBMIT", idempotency_key="worker-reclaim"
    )
    _claim(task.id)

    db_session.rollback()
    stored = db_session.get(Task, task.id)
    assert stored.status == "RUNNING"
    stored.lease_expires_at = utcnow() - timedelta(minutes=5)
    db_session.commit()

    worker = Worker(worker_id="test-worker")
    worker.reclaim_expired()

    db_session.rollback()
    reclaimed = db_session.get(Task, task.id)
    assert reclaimed.status == "RETRY_SCHEDULED"
    assert reclaimed.lease_owner is None
    assert reclaimed.lease_expires_at is None
    assert "lease expired" in (reclaimed.last_error or "").lower()


def test_within_limits_blocks_when_the_project_limit_is_reached(
    authenticated_client, db_session
) -> None:
    project = authenticated_client.post(
        "/api/v1/projects",
        json={
            "name": "Limited Campaign",
            "target_website": "https://limited.example",
            "settings": {"max_concurrency": 1, "global_concurrency": 8},
        },
    ).json()

    running, _created = queue_service.enqueue(
        db_session, task_type="SUBMIT", project_id=project["id"], idempotency_key="limit-1"
    )
    waiting, _created = queue_service.enqueue(
        db_session, task_type="SUBMIT", project_id=project["id"], idempotency_key="limit-2"
    )
    _claim(running.id)

    worker = Worker(worker_id="test-worker")
    db_session.rollback()
    assert worker.within_limits(db_session, db_session.get(Task, running.id)) is False
    assert worker.within_limits(db_session, db_session.get(Task, waiting.id)) is False


def test_within_limits_allows_a_task_below_the_limit(db_session) -> None:
    task, _created = queue_service.enqueue(
        db_session, task_type="SUBMIT", idempotency_key="limit-free"
    )

    worker = Worker(worker_id="test-worker")
    assert worker.within_limits(db_session, db_session.get(Task, task.id)) is True


def test_embedded_worker_picks_up_a_queued_task(worker_client, db_session) -> None:
    # The global execution state is shared by every test - make sure the
    # worker is allowed to claim before the test starts.
    from app.services.execution import resume

    resume(db_session)

    task, _created = queue_service.enqueue(
        db_session, task_type="IMPORT", idempotency_key="embedded-worker"
    )

    deadline = time.monotonic() + 10.0
    attempt = None
    while time.monotonic() < deadline:
        db_session.rollback()
        attempt = (
            db_session.query(TaskAttempt).filter_by(task_id=task.id).first()
        )
        if attempt is not None:
            break
        time.sleep(0.05)

    assert attempt is not None, "the embedded worker did not execute the task"
    assert attempt.outcome == "COMPLETED"


def test_embedded_worker_finalises_the_task(worker_client, db_session) -> None:
    from app.services.execution import resume

    resume(db_session)

    task, _created = queue_service.enqueue(
        db_session, task_type="IMPORT", idempotency_key="embedded-worker-final"
    )

    deadline = time.monotonic() + 10.0
    stored = None
    while time.monotonic() < deadline:
        stored = _read_task(task.id)
        if stored is not None and stored.status in ("COMPLETED", "SUBMITTED"):
            break
        time.sleep(0.05)

    assert stored is not None
    assert stored.status in ("COMPLETED", "SUBMITTED")
    assert stored.finished_at is not None
