"""Queue and task control endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, Pagination
from app.db.models import Opportunity, Project, Task, Website
from app.db.repositories import paginate
from app.schemas import (
    PaginatedResponse,
    QueueCreateRequest,
    ReorderRequest,
    TaskAttemptOut,
    TaskControlRequest,
    TaskEventOut,
    TaskOut,
)
from app.services import access
from app.services import queue as queue_service
from app.services.events import record_event

router = APIRouter(tags=["queue"])


def _get_task(db, task_id: str, user) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Task not found"})
    if task.project_id:
        project = db.get(Project, task.project_id)
        if project and project.owner_id and project.owner_id != user.id and not user.is_admin:
            raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Access denied"})
    return task


@router.get("/queue", response_model=PaginatedResponse[TaskOut])
def list_queue(
    db: DbSession,
    user: CurrentUser,
    page: Pagination,
    project_id: str | None = Query(default=None),
    type_filter: str | None = Query(default=None, alias="type"),
    status_filter: str | None = Query(default=None, alias="status"),
    environment: str | None = Query(default=None),
    search: str | None = Query(default=None),
) -> PaginatedResponse:
    stmt = select(Task)
    count_stmt = select(func.count()).select_from(Task)
    conditions = []
    scope = access.scope_tasks(db, user)
    if scope is not True:
        conditions.append(scope)
    if project_id:
        conditions.append(Task.project_id == project_id)
    if type_filter:
        conditions.append(Task.type == type_filter)
    if status_filter:
        conditions.append(Task.status == status_filter)
    if environment:
        conditions.append(Task.execution_environment == environment)
    if search:
        pattern = f"%{search.lower()}%"
        conditions.append(Task.idempotency_key.ilike(pattern))
    if conditions:
        stmt = stmt.where(*conditions)
        count_stmt = count_stmt.where(*conditions)
    stmt = stmt.order_by(Task.priority.desc(), Task.created_at.desc())
    result = paginate(db, stmt, Task, page.page, page.page_size, count_stmt)
    return PaginatedResponse(
        items=[TaskOut.model_validate(t) for t in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        pages=result.pages,
    )


@router.get("/queue/stats")
def queue_stats(db: DbSession, user: CurrentUser, project_id: str | None = Query(default=None)) -> dict:
    return queue_service.queue_stats(db, project_id)


@router.post("/queue")
def create_queue_tasks(payload: QueueCreateRequest, db: DbSession, user: CurrentUser) -> dict:
    created_ids: list[str] = []
    skipped = 0

    if payload.opportunity_ids:
        opportunities = db.execute(
            select(Opportunity).where(Opportunity.id.in_(payload.opportunity_ids))
        ).scalars().all()
        for opportunity in opportunities:
            website = db.get(Website, opportunity.website_id)
            if website is None:
                continue
            if website.excluded_until is not None:
                skipped += 1
                continue
            task, created = queue_service.enqueue(
                db,
                task_type=payload.type,
                project_id=opportunity.project_id,
                opportunity_id=opportunity.id,
                website_id=website.id,
                adapter_id=payload.adapter_id or website.adapter_id,
                payload={
                    "opportunity_id": opportunity.id,
                    "website_id": website.id,
                    "landing_page": opportunity.target_landing_page,
                    "anchor_text": website.anchor_text,
                },
                priority=payload.priority,
                scheduled_for=payload.scheduled_for,
                execution_environment=payload.execution_environment,
                idempotency_key=queue_service.build_idempotency_key(
                    payload.type, opportunity.project_id, opportunity.id, {"opportunity": opportunity.id}
                ),
            )
            if created:
                created_ids.append(task.id)
                opportunity.status = "QUEUED"
                record_event(
                    db,
                    "task.queued",
                    f"Task queued for {website.domain}",
                    task_id=task.id,
                    project_id=opportunity.project_id,
                    website_id=website.id,
                    metadata={"type": payload.type},
                )
            else:
                skipped += 1
    elif payload.project_ids:
        for project_id in payload.project_ids:
            project = db.get(Project, project_id)
            if project is None:
                continue
            task, created = queue_service.enqueue(
                db,
                task_type=payload.type,
                project_id=project.id,
                payload={"project_id": project.id},
                priority=payload.priority,
                scheduled_for=payload.scheduled_for,
                execution_environment=payload.execution_environment,
                idempotency_key=queue_service.build_idempotency_key(
                    payload.type, project.id, None, {"project": project.id}
                ),
            )
            if created:
                created_ids.append(task.id)
    db.commit()
    return {"created": len(created_ids), "task_ids": created_ids, "skipped": skipped}


@router.post("/queue/reorder")
def reorder_queue(payload: ReorderRequest, db: DbSession, user: CurrentUser) -> dict:
    updated = queue_service.reorder_tasks(db, payload.task_ids)
    return {"updated": updated}


@router.post("/queue/bulk-control")
def bulk_control(payload: TaskControlRequest, db: DbSession, user: CurrentUser) -> dict:
    affected = 0
    for task_id in payload.task_ids:
        task = db.get(Task, task_id)
        if task is None:
            continue
        _apply_control(db, task, payload)
        affected += 1
    return {"affected": affected}


@router.post("/queue/{task_id}/control", response_model=TaskOut)
def control_task(task_id: str, payload: TaskControlRequest, db: DbSession, user: CurrentUser) -> Task:
    task = _get_task(db, task_id, user)
    _apply_control(db, task, payload)
    db.refresh(task)
    return task


def _apply_control(db, task: Task, payload: TaskControlRequest) -> None:
    action = payload.action.lower()
    if action == "pause":
        queue_service.pause_task(db, task)
        record_event(db, "task.paused", "Task paused", task_id=task.id, project_id=task.project_id)
    elif action == "resume":
        queue_service.resume_task(db, task)
        record_event(db, "task.resumed", "Task resumed", task_id=task.id, project_id=task.project_id)
    elif action == "cancel":
        queue_service.cancel_task(db, task, payload.reason or "Cancelled by operator")
        record_event(
            db,
            "task.cancelled",
            "Task cancelled",
            task_id=task.id,
            project_id=task.project_id,
            level="WARNING",
        )
    elif action == "retry":
        queue_service.retry_task(db, task)
        record_event(db, "task.retry", "Task requeued for retry", task_id=task.id, project_id=task.project_id)
    elif action == "requeue":
        queue_service.retry_task(db, task, reset_attempts=True)
        record_event(db, "task.requeued", "Task requeued", task_id=task.id, project_id=task.project_id)
    else:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_action", "message": f"Unknown action: {payload.action}"},
        )


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: str, db: DbSession, user: CurrentUser) -> Task:
    return _get_task(db, task_id, user)


@router.get("/tasks/{task_id}/attempts", response_model=list[TaskAttemptOut])
def task_attempts(task_id: str, db: DbSession, user: CurrentUser) -> list:
    from app.db.models import TaskAttempt

    task = _get_task(db, task_id, user)
    return list(
        db.execute(
            select(TaskAttempt)
            .where(TaskAttempt.task_id == task.id)
            .order_by(TaskAttempt.attempt_number.desc())
        ).scalars().all()
    )


@router.get("/tasks/{task_id}/events", response_model=list[TaskEventOut])
def task_events(task_id: str, db: DbSession, user: CurrentUser) -> list:
    from app.db.models import TaskEvent

    task = _get_task(db, task_id, user)
    return list(
        db.execute(
            select(TaskEvent)
            .where(TaskEvent.task_id == task.id)
            .order_by(TaskEvent.created_at.desc())
            .limit(200)
        ).scalars().all()
    )


@router.post("/tasks/{task_id}/cancel", response_model=TaskOut)
def cancel_task(task_id: str, db: DbSession, user: CurrentUser) -> Task:
    task = _get_task(db, task_id, user)
    queue_service.cancel_task(db, task)
    record_event(db, "task.cancelled", "Task cancelled", task_id=task.id, project_id=task.project_id)
    db.refresh(task)
    return task


@router.post("/tasks/{task_id}/retry", response_model=TaskOut)
def retry_task(task_id: str, db: DbSession, user: CurrentUser) -> Task:
    task = _get_task(db, task_id, user)
    queue_service.retry_task(db, task)
    record_event(db, "task.retry", "Task queued for retry", task_id=task.id, project_id=task.project_id)
    db.refresh(task)
    return task
