"""Hybrid synchronisation endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.api.deps import CurrentUser, DbSession
from app.services import sync as sync_service

router = APIRouter(prefix="/sync", tags=["sync"])


@router.get("/status")
def sync_status(db: DbSession, user: CurrentUser) -> dict:
    return sync_service.sync_status(db)


@router.post("/push")
def push(db: DbSession, user: CurrentUser) -> dict:
    return sync_service.push(db)


@router.post("/pull")
def pull(db: DbSession, user: CurrentUser, since: datetime | None = Query(default=None)) -> dict:
    return sync_service.pull(db, since)


@router.post("/conflicts/{change_id}/resolve")
def resolve_conflict(change_id: str, payload: dict, db: DbSession, user: CurrentUser) -> dict:
    strategy = payload.get("strategy")
    if strategy not in ("local", "remote"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_strategy", "message": "strategy must be 'local' or 'remote'"},
        )
    return sync_service.resolve_conflict(db, change_id, strategy)


# --------------------------------------------------------------------------
# Cloud side of the protocol (a cloud workspace serves these endpoints)
# --------------------------------------------------------------------------

@router.post("/{entity_type}")
def receive_change(entity_type: str, payload: dict, db: DbSession, user: CurrentUser) -> dict:
    """Accept a change pushed by a local workspace."""
    from app.db.models import Opportunity, Project

    entity_id = payload.get("entity_id")
    data = payload.get("payload") or {}
    version = int(payload.get("version") or 1)
    if not entity_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_payload", "message": "entity_id is required"},
        )
    model = {"projects": Project, "opportunities": Opportunity}.get(entity_type)
    if model is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "unsupported_entity", "message": f"Unknown entity type: {entity_type}"},
        )
    existing = db.get(model, entity_id)
    if existing is not None and getattr(existing, "version", 0) > version:
        return JSONResponse(
            status_code=409,
            content={"error": {"code": "conflict", "message": "A newer version exists in the cloud"}},
        )
    if existing is None:
        db.add(model(**{**data, "id": entity_id}))
    else:
        for key, value in data.items():
            if hasattr(existing, key):
                setattr(existing, key, value)
        if hasattr(existing, "version"):
            existing.version = version
    db.commit()
    sync_service.record_change(db, entity_type, entity_id, data, version=version)
    db.commit()
    return {"ok": True, "entity_type": entity_type, "entity_id": entity_id, "version": version}


@router.get("/changes")
def list_changes(
    db: DbSession,
    user: CurrentUser,
    since: datetime | None = Query(default=None),
    limit: int = Query(default=200, le=1000),
) -> dict:
    """Serve the changes a local workspace should pull."""
    from sqlalchemy import select

    from app.db.models import SyncChange

    stmt = select(SyncChange).where(SyncChange.conflict.is_(False))
    if since:
        stmt = stmt.where(SyncChange.created_at >= since)
    stmt = stmt.order_by(SyncChange.created_at.asc()).limit(limit)
    changes = db.execute(stmt).scalars().all()
    return {
        "changes": [
            {
                "entity_type": change.entity_type,
                "entity_id": change.entity_id,
                "operation": change.operation,
                "version": change.version,
                "payload": change.payload,
                "created_at": change.created_at.isoformat() if change.created_at else None,
            }
            for change in changes
        ]
    }
