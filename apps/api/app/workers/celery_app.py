"""Optional Celery dispatcher.

Celery is only used when a broker is configured (``AUTOBL_USE_CELERY=true``
and ``AUTOBL_CELERY_BROKER_URL``). The task handlers are identical to the
embedded worker, so cloud deployments can scale workers horizontally without
changing any business logic.

Without a broker the embedded database worker (app.workers.runner) executes
the very same tasks, which keeps local / desktop mode dependency free.
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

try:  # pragma: no cover - celery is an optional dependency
    from celery import Celery

    CELERY_AVAILABLE = True
except Exception:  # pragma: no cover
    Celery = None  # type: ignore[assignment]
    CELERY_AVAILABLE = False


def create_celery_app() -> Any:
    if not CELERY_AVAILABLE:
        raise RuntimeError("Celery is not installed")
    broker = settings.celery_broker_url or "memory://"
    backend = settings.celery_result_backend or broker
    app = Celery("autobacklinker", broker=broker, backend=backend)
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        task_track_started=True,
        task_default_queue="autobacklinker",
    )
    return app


celery_app = None
if CELERY_AVAILABLE and settings.use_celery:  # pragma: no cover - requires a broker
    celery_app = create_celery_app()


def register_celery_tasks(app: Any) -> None:  # pragma: no cover - requires a broker
    """Expose the task handlers as Celery tasks."""

    @app.task(name="autobacklinker.execute_task", bind=True, max_retries=0)
    def execute_task(self, task_id: str) -> dict:
        from app.db.models import Task
        from app.db.session import session_scope
        from app.workers.runner import Worker

        worker = Worker(worker_id=f"celery:{self.request.id}")
        with session_scope() as db:
            task = db.get(Task, task_id)
            if task is None:
                return {"status": "unknown_task", "task_id": task_id}
            if task.lease_owner and task.lease_owner != worker.worker_id:
                return {"status": "already_claimed", "task_id": task_id}
            worker.execute(db, task)
            db.refresh(task)
            return {"status": task.status, "task_id": task_id}
