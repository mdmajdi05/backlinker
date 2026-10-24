"""Activity log, adapters, devices, storage settings, dashboard and live events."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, Pagination
from app.core.config import settings
from app.db.base import utcnow
from app.db.models import (
    AdapterConfiguration,
    AutomationAdapter,
    BacklinkRecord,
    Device,
    Opportunity,
    Project,
    Task,
    TaskEvent,
    Website,
)
from app.db.repositories import paginate
from app.schemas import (
    ActivityEventOut,
    AdapterConfigurationOut,
    AdapterOut,
    DashboardMetricsOut,
    DeviceHeartbeatRequest,
    DeviceOut,
    DeviceRegisterRequest,
    DeviceRegisterResponse,
    DeviceTaskReport,
    PaginatedResponse,
    TaskOut,
)
from app.services import access
from app.services import queue as queue_service
from app.services.events import event_stream, record_event

activity_router = APIRouter(tags=["activity"])
adapters_router = APIRouter(prefix="/adapters", tags=["adapters"])
devices_router = APIRouter(prefix="/devices", tags=["devices"])
dashboard_router = APIRouter(prefix="/dashboard", tags=["dashboard"])
events_router = APIRouter(prefix="/events", tags=["events"])


# --------------------------------------------------------------------------
# Activity
# --------------------------------------------------------------------------

@activity_router.get("/activity", response_model=PaginatedResponse[ActivityEventOut])
def list_activity(
    db: DbSession,
    user: CurrentUser,
    page: Pagination,
    project_id: str | None = Query(default=None),
    level: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
) -> PaginatedResponse:
    stmt = select(TaskEvent)
    count_stmt = select(func.count()).select_from(TaskEvent)
    conditions = []
    scope = access.scope_events(db, user)
    if scope is not None:
        conditions.append(scope)
    if project_id:
        conditions.append(TaskEvent.project_id == project_id)
    if level:
        conditions.append(TaskEvent.level == level)
    if event_type:
        conditions.append(TaskEvent.event_type == event_type)
    if since:
        conditions.append(TaskEvent.created_at >= since)
    if until:
        conditions.append(TaskEvent.created_at <= until)
    if conditions:
        stmt = stmt.where(*conditions)
        count_stmt = count_stmt.where(*conditions)
    stmt = stmt.order_by(TaskEvent.created_at.desc())
    result = paginate(db, stmt, TaskEvent, page.page, page.page_size, count_stmt)

    project_names = {
        p.id: p.name
        for p in db.execute(select(Project)).scalars().all()
    }
    website_ids = {event.website_id for event in result.items if event.website_id}
    website_names: dict[str, str] = {}
    if website_ids:
        for website in db.execute(select(Website).where(Website.id.in_(website_ids))).scalars().all():
            website_names[website.id] = website.name or website.domain
    items = []
    for event in result.items:
        items.append(
            ActivityEventOut(
                id=event.id,
                event_type=event.event_type,
                level=event.level,
                message=event.message,
                project_id=event.project_id,
                project_name=project_names.get(event.project_id) if event.project_id else None,
                task_id=event.task_id,
                opportunity_id=event.website_id,
                website=website_names.get(event.website_id) if event.website_id else None,
                execution_environment=event.execution_environment,
                metadata=event.meta or {},
                created_at=event.created_at,
            )
        )
    return PaginatedResponse(
        items=items,
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        pages=result.pages,
    )


# --------------------------------------------------------------------------
# Adapters
# --------------------------------------------------------------------------

@adapters_router.get("", response_model=list[AdapterOut])
def list_adapters(db: DbSession, user: CurrentUser) -> list[AutomationAdapter]:
    return list(db.execute(select(AutomationAdapter).order_by(AutomationAdapter.name)).scalars().all())


@adapters_router.get("/{adapter_id}", response_model=AdapterOut)
def get_adapter(adapter_id: str, db: DbSession, user: CurrentUser) -> AutomationAdapter:
    """One adapter including its requirements and restrictions."""
    adapter = db.get(AutomationAdapter, adapter_id)
    if adapter is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Adapter not found"})
    return adapter


@adapters_router.patch("/{adapter_id}", response_model=AdapterOut)
def update_adapter(adapter_id: str, payload: dict, db: DbSession, user: CurrentUser) -> AutomationAdapter:
    adapter = db.get(AutomationAdapter, adapter_id)
    if adapter is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Adapter not found"})
    allowed = {
        "enabled",
        "name",
        "description",
        "supported_categories",
        "supported_methods",
        "required_config",
        "registration_required",
        "manual_approval_required",
        "automatable",
        "retryable_errors",
        "restrictions",
        "domains",
    }
    for key, value in payload.items():
        if key in allowed:
            setattr(adapter, key, value)
    db.commit()
    db.refresh(adapter)
    return adapter


@adapters_router.get("/{adapter_id}/configuration", response_model=list[AdapterConfigurationOut])
def adapter_configuration(
    adapter_id: str, db: DbSession, user: CurrentUser
) -> list[AdapterConfiguration]:
    rows = db.execute(
        select(AdapterConfiguration).where(AdapterConfiguration.adapter_id == adapter_id)
    ).scalars().all()
    return list(rows)


@adapters_router.put("/{adapter_id}/configuration", response_model=AdapterConfigurationOut)
def set_adapter_configuration(
    adapter_id: str, payload: dict, db: DbSession, user: CurrentUser
) -> AdapterConfiguration:
    adapter = db.get(AutomationAdapter, adapter_id)
    if adapter is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Adapter not found"})
    project_id = payload.get("project_id")
    row = db.execute(
        select(AdapterConfiguration).where(
            AdapterConfiguration.adapter_id == adapter_id,
            AdapterConfiguration.project_id == project_id,
        )
    ).scalar_one_or_none()
    if row is None:
        row = AdapterConfiguration(adapter_id=adapter_id, project_id=project_id, config={})
        db.add(row)
    row.config = payload.get("config") or {}
    db.commit()
    db.refresh(row)
    return row


# --------------------------------------------------------------------------
# Devices / local agents
# --------------------------------------------------------------------------

@devices_router.post("/register", response_model=DeviceRegisterResponse)
def register_device(payload: DeviceRegisterRequest, db: DbSession) -> DeviceRegisterResponse:
    from app.core.security import hash_password, new_api_key

    api_key = new_api_key("agent")
    device = Device(
        name=payload.name,
        platform=payload.platform,
        status="ONLINE",
        capabilities=payload.capabilities,
        version=payload.version,
        api_key_hash=hash_password(api_key),
        last_seen_at=utcnow(),
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    return DeviceRegisterResponse(
        device_id=device.id, api_key=api_key, poll_interval_seconds=settings.device_heartbeat_seconds
    )


def _device_from_key(db, api_key: str | None) -> Device:
    if not api_key:
        raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "Device key required"})
    from app.core.security import verify_password

    devices = db.execute(select(Device)).scalars().all()
    for device in devices:
        if device.api_key_hash and verify_password(api_key, device.api_key_hash):
            return device
    raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "Unknown device key"})


@devices_router.get("", response_model=list[DeviceOut])
def list_devices(db: DbSession, user: CurrentUser) -> list[Device]:
    return list(db.execute(select(Device).order_by(Device.created_at.desc())).scalars().all())


@devices_router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_device(device_id: str, db: DbSession, user: CurrentUser) -> None:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Device not found"})
    db.delete(device)
    db.commit()


@devices_router.post("/{device_id}/heartbeat")
def heartbeat(device_id: str, payload: DeviceHeartbeatRequest, db: DbSession) -> dict:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Device not found"})
    device.status = payload.status
    if payload.capabilities:
        device.capabilities = payload.capabilities
    device.last_seen_at = utcnow()
    db.commit()
    return {"ok": True, "device_id": device.id}


@devices_router.get("/tasks/claim")
def claim_device_task(
    db: DbSession,
    request: Request,
    authorization: str | None = Query(default=None),
) -> Response:
    """Claim one task that is routed to the local environment.

    Returns the task object itself, or ``204 No Content`` when there is
    nothing to do - this is the contract used by the local agent.
    """
    key = None
    header = request.headers.get("authorization")
    if header and header.lower().startswith("bearer "):
        key = header.split(" ", 1)[1]
    elif authorization:
        key = authorization
    device = _device_from_key(db, key)
    task = queue_service.claim_task(
        db, worker_id=f"device:{device.id}", types=("SUBMIT", "VERIFY"), environment="LOCAL"
    )
    if task is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    record_event(
        db,
        "task.started",
        "Task claimed by a local agent",
        task_id=task.id,
        project_id=task.project_id,
        website_id=task.website_id,
        execution_environment="LOCAL",
        metadata={"device_id": device.id},
    )
    return JSONResponse(content=TaskOut.model_validate(task).model_dump(mode="json"))


@devices_router.post("/tasks/{task_id}/report")
def report_device_task(
    task_id: str,
    payload: DeviceTaskReport,
    db: DbSession,
    request: Request,
) -> dict:
    """Receive the result of a task that was executed by a local agent.

    The attempt is recorded on the cloud side so the task history is complete
    no matter which environment executed the work.
    """
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Task not found"})

    header = request.headers.get("authorization")
    device = None
    if header and header.lower().startswith("bearer "):
        try:
            device = _device_from_key(db, header.split(" ", 1)[1])
        except HTTPException:
            device = None

    from app.db.models import TaskAttempt

    previous = db.execute(
        select(TaskAttempt.attempt_number)
        .where(TaskAttempt.task_id == task.id)
        .order_by(TaskAttempt.attempt_number.desc())
        .limit(1)
    ).scalar_one_or_none()
    attempt_number = (previous or task.attempts or 0) + 1

    attempt = TaskAttempt(
        task_id=task.id,
        attempt_number=attempt_number,
        started_at=utcnow(),
        finished_at=utcnow(),
        outcome=payload.status,
        error=payload.error,
        evidence=payload.result or {},
        worker=f"device:{device.id}" if device else "local-agent",
        execution_environment="LOCAL",
    )
    db.add(attempt)
    task.attempts = attempt_number
    task.updated_at = utcnow()

    if payload.status == "SUCCEEDED":
        task.status = payload.result.get("task_status") or "SUBMITTED"
        task.result = payload.result or {}
        task.progress = 1.0
        task.finished_at = utcnow()
        task.lease_owner = None
        task.lease_expires_at = None
        task.last_error = None
    elif payload.status == "FAILED":
        task.status = "FAILED"
        task.last_error = (payload.error or "Agent reported a failure")[:4000]
        task.finished_at = utcnow()
        task.lease_owner = None
        task.lease_expires_at = None
    else:
        task.status = payload.status
        task.lease_owner = None
        task.lease_expires_at = None
    db.commit()

    event_type = {
        "SUCCEEDED": "task.completed",
        "FAILED": "task.failed",
    }.get(payload.status, "task.reported")
    record_event(
        db,
        event_type,
        f"Local agent reported {payload.status.lower()}",
        level="SUCCESS" if payload.status == "SUCCEEDED" else "ERROR" if payload.status == "FAILED" else "INFO",
        task_id=task.id,
        project_id=task.project_id,
        website_id=task.website_id,
        execution_environment="LOCAL",
        metadata={"result": payload.result, "error": payload.error, "attempt": attempt_number},
    )
    return {"ok": True, "attempt": attempt_number, "status": task.status}


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------

@dashboard_router.get("/metrics", response_model=DashboardMetricsOut)
def dashboard_metrics(
    db: DbSession, user: CurrentUser, project_id: str | None = Query(default=None)
) -> DashboardMetricsOut:
    def count(model, *conditions) -> int:
        stmt = select(func.count()).select_from(model)
        if conditions:
            stmt = stmt.where(*conditions)
        return int(db.execute(stmt).scalar_one() or 0)

    # Every metric is scoped to the projects the user may access.
    project_ids = access.accessible_project_ids(db, user)

    def project_filter(column):
        if project_ids is None:
            return None
        if not project_ids:
            return column.is_(None)
        return column.in_(project_ids)

    def with_scope(column, *conditions):
        scoped = project_filter(column)
        if scoped is None:
            return list(conditions)
        return [scoped, *conditions]

    task_conditions = with_scope(Task.project_id)
    opp_conditions = with_scope(Opportunity.project_id)
    link_conditions = with_scope(BacklinkRecord.project_id)
    if project_id:
        task_conditions.append(Task.project_id == project_id)
        opp_conditions.append(Opportunity.project_id == project_id)
        link_conditions.append(BacklinkRecord.project_id == project_id)

    event_scope = access.scope_events(db, user)
    event_conditions: list = []
    if event_scope is not None:
        event_conditions.append(event_scope)
    if project_id:
        event_conditions.append(TaskEvent.project_id == project_id)

    by_status = {
        row[0]: int(row[1])
        for row in db.execute(
            select(Task.status, func.count())
            .where(*task_conditions)
            .group_by(Task.status)
        ).all()
    }
    by_category = [
        {"category": row[0], "count": int(row[1])}
        for row in db.execute(
            select(Website.category, func.count())
            .select_from(Website)
            .join(Opportunity, Opportunity.website_id == Website.id)
            .where(*opp_conditions)
            .group_by(Website.category)
            .order_by(func.count().desc())
        ).all()
    ]

    devices_online = count(Device, Device.status.in_(("ONLINE", "REGISTERED")))
    project_count = count(Project)
    if project_ids is not None:
        project_count = int(
            db.execute(
                select(func.count())
                .select_from(Project)
                .where(Project.id.in_(project_ids) if project_ids else Project.id.is_(None))
            ).scalar_one()
            or 0
        )
    return DashboardMetricsOut(
        projects=project_count if not project_id else 1,
        opportunities=count(Opportunity, *opp_conditions),
        approved=count(Opportunity, *(opp_conditions + [Opportunity.status == "APPROVED"])),
        queued=count(Task, *(task_conditions + [Task.status == "QUEUED"])),
        running=count(Task, *(task_conditions + [Task.status == "RUNNING"])),
        published=count(BacklinkRecord, *(link_conditions + [BacklinkRecord.verification_status.in_(("PUBLISHED_UNVERIFIED", "VERIFIED_LIVE"))])),
        verified_live=count(BacklinkRecord, *(link_conditions + [BacklinkRecord.verification_status == "VERIFIED_LIVE"])),
        pending_manual=count(Task, *(task_conditions + [Task.status == "WAITING_FOR_USER"])),
        failed=count(Task, *(task_conditions + [Task.status == "FAILED"])),
        awaiting_retry=count(Task, *(task_conditions + [Task.status == "RETRY_SCHEDULED"])),
        requiring_verification=count(BacklinkRecord, *(link_conditions + [BacklinkRecord.verification_status == "PUBLISHED_UNVERIFIED"])),
        connected_devices=devices_online,
        cloud_workers=count(Task, *(task_conditions + [Task.status == "RUNNING", Task.execution_environment == "CLOUD"])),
        running_local_jobs=count(Task, *(task_conditions + [Task.status == "RUNNING", Task.execution_environment == "LOCAL"])),
        sync_errors=0,
        by_status=by_status,
        by_category=by_category,
        generated_at=utcnow(),
    )


# --------------------------------------------------------------------------
# Live events (SSE + WebSocket)
# --------------------------------------------------------------------------

@events_router.get("/stream")
async def stream(request: Request, project_id: str | None = Query(default=None)):
    """Server-Sent Events stream.

    ``EventSource`` cannot send an ``Authorization`` header, therefore the
    token is accepted as the ``access_token`` query parameter as well.  The
    stream is authenticated either way.
    """
    from app.core.security import decode_access_token

    token = request.query_params.get("access_token")
    header = request.headers.get("authorization")
    if not token and header and header.lower().startswith("bearer "):
        token = header.split(" ", 1)[1]
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "not_authenticated", "message": "The event stream requires a token"},
        )
    try:
        decode_access_token(token)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_token", "message": "Invalid or expired token"},
        ) from exc

    async def generator():
        async for event in event_stream(project_id):
            if await request.is_disconnected():
                break
            import json

            yield f"event: {event['event']}\ndata: {json.dumps(event['data'], default=str)}\n\n"

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@events_router.get("/recent", response_model=list[ActivityEventOut])
def recent_events(db: DbSession, user: CurrentUser, limit: int = Query(default=50, le=200)) -> list[dict]:
    rows = db.execute(
        select(TaskEvent).order_by(TaskEvent.created_at.desc()).limit(limit)
    ).scalars().all()
    return [
        ActivityEventOut(
            id=row.id,
            event_type=row.event_type,
            message=row.message,
            level=row.level,
            project_id=row.project_id,
            task_id=row.task_id,
            execution_environment=row.execution_environment,
            metadata=row.meta or {},
            created_at=row.created_at,
        )
        for row in rows
    ]
