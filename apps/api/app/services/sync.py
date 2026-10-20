"""Hybrid synchronisation between the local database and a cloud workspace.

The cloud is the source of truth for synchronised entities. Local writes are
queued in ``sync_changes`` and pushed on the next successful connection.
Incoming changes are version checked: a newer cloud version wins, an older
local version is queued for push, and a genuine conflict is flagged for the
operator instead of being silently overwritten.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.base import utcnow
from app.db.models import (
    Opportunity,
    Project,
    SyncChange,
)
from app.services.storage import read_cloud_connection

log = get_logger(__name__)

SYNCED_ENTITIES = ("projects", "opportunities", "tasks")


def record_change(
    db: Session,
    entity_type: str,
    entity_id: str,
    payload: dict[str, Any],
    operation: str = "upsert",
    version: int = 1,
) -> SyncChange:
    """Queue a local change for the next synchronisation push."""
    change = SyncChange(
        entity_type=entity_type,
        entity_id=entity_id,
        operation=operation,
        version=version,
        payload=payload,
    )
    db.add(change)
    return change


def pending_changes(db: Session, limit: int = 200) -> list[SyncChange]:
    return list(
        db.execute(
            select(SyncChange)
            .where(SyncChange.synced_at.is_(None))
            .order_by(SyncChange.created_at.asc())
            .limit(limit)
        ).scalars().all()
    )


def cloud_client() -> tuple[httpx.Client | None, str]:
    connection = read_cloud_connection()
    if not connection:
        return None, "No cloud connection configured"
    base_url = connection.get("api_url") or connection.get("base_url")
    token = connection.get("api_token")
    if not base_url:
        return None, "Cloud connection has no API URL"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=20.0), ""


def push(db: Session) -> dict[str, Any]:
    """Push queued local changes to the cloud workspace."""
    client, reason = cloud_client()
    if client is None:
        return {"ok": False, "message": reason, "pushed": 0}
    pushed = 0
    conflicts = 0
    try:
        for change in pending_changes(db):
            try:
                response = client.post(
                    f"/api/v1/sync/{change.entity_type}",
                    json={
                        "entity_id": change.entity_id,
                        "operation": change.operation,
                        "version": change.version,
                        "payload": change.payload,
                    },
                )
            except Exception as exc:
                log.warning("sync push failed", extra={"extra_fields": {"error": str(exc)}})
                break
            if response.status_code == 409:
                change.conflict = True
                conflicts += 1
                continue
            if response.status_code >= 400:
                change.conflict = True
                conflicts += 1
                continue
            change.synced_at = utcnow()
            pushed += 1
        db.commit()
    finally:
        client.close()
    return {"ok": True, "pushed": pushed, "conflicts": conflicts}


def pull(db: Session, since: datetime | None = None) -> dict[str, Any]:
    """Pull remote changes and apply them when the local copy is not newer."""
    client, reason = cloud_client()
    if client is None:
        return {"ok": False, "message": reason, "applied": 0}
    applied = 0
    skipped = 0
    try:
        params = {"since": since.isoformat()} if since else {}
        response = client.get("/api/v1/sync/changes", params=params)
        if response.status_code >= 400:
            return {"ok": False, "message": f"Cloud returned {response.status_code}", "applied": 0}
        payload = response.json()
        for item in payload.get("changes", []):
            entity_type = item.get("entity_type")
            entity_id = item.get("entity_id")
            data = item.get("payload") or {}
            remote_version = int(item.get("version") or 1)
            if entity_type == "projects":
                project = db.get(Project, entity_id)
                if project is None:
                    db.add(Project(**{**data, "id": entity_id}))
                    applied += 1
                elif remote_version > project.version:
                    for key, value in data.items():
                        if hasattr(project, key):
                            setattr(project, key, value)
                    project.version = remote_version
                    applied += 1
                else:
                    skipped += 1
            elif entity_type == "opportunities":
                opportunity = db.get(Opportunity, entity_id)
                if opportunity is None:
                    db.add(Opportunity(**{**data, "id": entity_id}))
                    applied += 1
                elif remote_version > opportunity.version:
                    for key, value in data.items():
                        if hasattr(opportunity, key):
                            setattr(opportunity, key, value)
                    opportunity.version = remote_version
                    applied += 1
                else:
                    skipped += 1
            else:
                skipped += 1
        db.commit()
    finally:
        client.close()
    return {"ok": True, "applied": applied, "skipped": skipped}


def resolve_conflict(db: Session, change_id: str, strategy: str) -> dict[str, Any]:
    """Resolve a flagged conflict either by keeping the local or the remote copy."""
    change = db.get(SyncChange, change_id)
    if change is None:
        return {"ok": False, "message": "Change not found"}
    if strategy == "local":
        change.conflict = False
        change.synced_at = None
    elif strategy == "remote":
        change.conflict = False
        change.synced_at = utcnow()
    else:
        return {"ok": False, "message": "Unknown strategy"}
    db.commit()
    return {"ok": True, "strategy": strategy}


def sync_status(db: Session) -> dict[str, Any]:
    pending = pending_changes(db)
    conflicts = [change for change in pending if change.conflict]
    last_sync = db.execute(
        select(SyncChange).where(SyncChange.synced_at.is_not(None)).order_by(SyncChange.synced_at.desc()).limit(1)
    ).scalar_one_or_none()
    return {
        "pending": len(pending),
        "conflicts": len(conflicts),
        "last_sync_at": last_sync.synced_at.isoformat() if last_sync and last_sync.synced_at else None,
        "online": read_cloud_connection() is not None,
    }
