"""Audit trail helper."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AuditLog


def record_audit(
    db: Session,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    *,
    actor_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip_address: str | None = None,
    commit: bool = True,
) -> AuditLog:
    entry = AuditLog(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        before=before or {},
        after=after or {},
        ip_address=ip_address,
    )
    db.add(entry)
    if commit:
        db.commit()
    else:
        db.flush()
    return entry
