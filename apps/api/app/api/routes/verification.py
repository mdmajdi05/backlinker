"""Backlink verification endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, Pagination
from app.db.models import BacklinkRecord, VerificationRun
from app.db.repositories import paginate
from app.schemas import (
    BacklinkRecordOut,
    PaginatedResponse,
    VerificationRunOut,
    VerifyRequest,
)
from app.services import queue as queue_service
from app.services.events import record_event

router = APIRouter(prefix="/verification", tags=["verification"])


@router.get("/records", response_model=PaginatedResponse[BacklinkRecordOut])
def list_records(
    db: DbSession,
    user: CurrentUser,
    page: Pagination,
    project_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None),
) -> PaginatedResponse:
    stmt = select(BacklinkRecord)
    count_stmt = select(func.count()).select_from(BacklinkRecord)
    conditions = []
    if project_id:
        conditions.append(BacklinkRecord.project_id == project_id)
    if status_filter:
        conditions.append(BacklinkRecord.verification_status == status_filter)
    if search:
        pattern = f"%{search.lower()}%"
        conditions.append(
            (BacklinkRecord.expected_link_url.ilike(pattern))
            | (BacklinkRecord.expected_destination_url.ilike(pattern))
            | (BacklinkRecord.target_website.ilike(pattern))
        )
    if conditions:
        stmt = stmt.where(*conditions)
        count_stmt = count_stmt.where(*conditions)
    stmt = stmt.order_by(BacklinkRecord.updated_at.desc())
    result = paginate(db, stmt, BacklinkRecord, page.page, page.page_size, count_stmt)
    return PaginatedResponse(
        items=[BacklinkRecordOut.model_validate(r) for r in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        pages=result.pages,
    )


@router.post("/run")
def run_verification(payload: VerifyRequest, db: DbSession, user: CurrentUser) -> dict:
    """Schedule verification work for the given records (or a whole project)."""
    stmt = select(BacklinkRecord)
    if payload.backlink_ids:
        stmt = stmt.where(BacklinkRecord.id.in_(payload.backlink_ids))
    elif payload.project_id:
        stmt = stmt.where(BacklinkRecord.project_id == payload.project_id)
    else:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_request", "message": "Provide backlink_ids or project_id"},
        )
    records = db.execute(stmt).scalars().all()
    created_ids: list[str] = []
    for record in records:
        task, created = queue_service.enqueue(
            db,
            task_type="VERIFY",
            project_id=record.project_id,
            opportunity_id=record.opportunity_id,
            website_id=None,
            payload={"backlink_id": record.id, "force": payload.force},
            priority=3,
            idempotency_key=f"VERIFY:{record.id}:{'force' if payload.force else 'scheduled'}",
        )
        if created:
            created_ids.append(task.id)
    db.commit()
    record_event(
        db,
        "verification.scheduled",
        f"Verification scheduled for {len(created_ids)} backlinks",
        project_id=payload.project_id,
        metadata={"tasks": len(created_ids)},
    )
    return {"scheduled": len(created_ids), "task_ids": created_ids}


@router.get("/records/{record_id}", response_model=BacklinkRecordOut)
def get_record(record_id: str, db: DbSession, user: CurrentUser) -> BacklinkRecord:
    record = db.get(BacklinkRecord, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Record not found"})
    return record


@router.get("/records/{record_id}/history", response_model=list[VerificationRunOut])
def record_history(record_id: str, db: DbSession, user: CurrentUser) -> list[VerificationRun]:
    record = db.get(BacklinkRecord, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Record not found"})
    return list(
        db.execute(
            select(VerificationRun)
            .where(VerificationRun.backlink_id == record_id)
            .order_by(VerificationRun.verified_at.desc())
        ).scalars().all()
    )
