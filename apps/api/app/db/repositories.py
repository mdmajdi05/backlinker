"""Storage abstraction layer.

All business logic goes through these repositories so the application never
depends on a concrete database implementation. The repositories are written
with portable SQLAlchemy constructs only (no PostgreSQL specific syntax),
therefore the exact same code paths serve SQLite (local / desktop mode) and
PostgreSQL (cloud mode).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import timedelta
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.db.base import Base, utcnow
from app.db.models import Task

ModelT = TypeVar("ModelT", bound=Base)


class Repository(Generic[ModelT]):
    """Generic CRUD repository."""

    model: type[ModelT]

    def __init__(self, db: Session):
        self.db = db

    def get(self, entity_id: str) -> ModelT | None:
        return self.db.get(self.model, entity_id)

    def list(self, limit: int = 50, offset: int = 0, order_by: Any = None) -> list[ModelT]:
        stmt = select(self.model)
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        stmt = stmt.limit(limit).offset(offset)
        return list(self.db.execute(stmt).scalars().all())

    def count(self, *conditions: Any) -> int:
        stmt = select(func.count()).select_from(self.model)
        if conditions:
            stmt = stmt.where(*conditions)
        return int(self.db.execute(stmt).scalar_one())

    def add(self, entity: ModelT) -> ModelT:
        self.db.add(entity)
        self.db.flush()
        return entity

    def bulk_add(self, entities: Iterable[ModelT]) -> list[ModelT]:
        entities = list(entities)
        self.db.add_all(entities)
        self.db.flush()
        return entities

    def update_fields(self, entity_id: str, **values: Any) -> ModelT | None:
        entity = self.get(entity_id)
        if entity is None:
            return None
        for key, value in values.items():
            setattr(entity, key, value)
        self.db.flush()
        return entity

    def delete(self, entity_id: str) -> bool:
        entity = self.get(entity_id)
        if entity is None:
            return False
        self.db.delete(entity)
        self.db.flush()
        return True

    def delete_where(self, *conditions: Any) -> int:
        stmt = delete(self.model).where(*conditions)
        result = self.db.execute(stmt)
        self.db.flush()
        return int(result.rowcount or 0)


class PaginatedResult(Generic[ModelT]):
    def __init__(self, items: Sequence[ModelT], total: int, page: int, page_size: int):
        self.items = list(items)
        self.total = total
        self.page = page
        self.page_size = page_size

    @property
    def pages(self) -> int:
        if self.page_size <= 0:
            return 0
        return max(1, (self.total + self.page_size - 1) // self.page_size)


def paginate(
    db: Session,
    stmt: Select,
    model: type[ModelT],
    page: int = 1,
    page_size: int = 25,
    count_stmt: Select | None = None,
) -> PaginatedResult[ModelT]:
    """Portable pagination helper (works on SQLite and PostgreSQL)."""
    page = max(1, int(page))
    page_size = max(1, min(500, int(page_size)))
    if count_stmt is None:
        count_stmt = select(func.count()).select_from(model)
    total = int(db.execute(count_stmt).scalar_one() or 0)
    items = list(db.execute(stmt.limit(page_size).offset((page - 1) * page_size)).scalars().all())
    return PaginatedResult(items, total, page, page_size)


def like(value: str) -> str:
    """Case-insensitive contains filter (portable across dialects)."""
    return f"%{value.strip().lower()}%"


def build_search(model: Any, fields: Sequence[str], term: str | None) -> Any:
    if not term:
        return None
    pattern = like(term)
    return or_(*[getattr(model, field).ilike(pattern) for field in fields])


class TaskClaimRepository:
    """Atomic task claiming that works on SQLite and PostgreSQL.

    A claim uses a conditional UPDATE, so two workers can never own the same
    task: only the UPDATE that matches the expected status/lease wins.
    """

    def __init__(self, db: Session):
        self.db = db

    def claimable_types(self) -> tuple[str, ...]:
        return ("SUBMIT", "VERIFY", "DISCOVER", "IMPORT", "EXPORT")

    def candidates(
        self,
        types: Sequence[str],
        environment: str | None = None,
        limit: int = 25,
    ) -> list[Task]:
        """Return claimable tasks without claiming them (limit checks happen first)."""
        now = utcnow()
        stmt = (
            select(Task)
            .where(
                Task.type.in_(tuple(types)),
                Task.status.in_(("QUEUED", "RETRY_SCHEDULED")),
                or_(Task.scheduled_for.is_(None), Task.scheduled_for <= now),
                or_(Task.lease_expires_at.is_(None), Task.lease_expires_at < now),
                or_(Task.lease_owner.is_(None), Task.lease_owner == ""),
            )
            .order_by(Task.priority.desc(), Task.created_at.asc())
            .limit(limit)
        )
        if environment:
            stmt = stmt.where(Task.execution_environment == environment)
        return list(self.db.execute(stmt).scalars().all())

    def try_claim(
        self,
        task_id: str,
        worker_id: str,
        lease_seconds: int = 300,
    ) -> Task | None:
        """Atomically claim one task; returns None when another worker won."""
        now = utcnow()
        result = self.db.execute(
            update(Task)
            .where(
                Task.id == task_id,
                Task.status.in_(("QUEUED", "RETRY_SCHEDULED")),
                or_(Task.lease_expires_at.is_(None), Task.lease_expires_at < now),
                or_(Task.lease_owner.is_(None), Task.lease_owner == ""),
            )
            .values(
                status="RUNNING",
                lease_owner=worker_id,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                started_at=func.coalesce(Task.started_at, now),
                updated_at=now,
            )
        )
        if result.rowcount != 1:
            self.db.rollback()
            return None
        self.db.commit()
        return self.db.get(Task, task_id)

    def claim_next(
        self,
        worker_id: str,
        types: Sequence[str],
        lease_seconds: int = 300,
        environment: str | None = None,
    ):
        now = utcnow()
        stmt = (
            select(Task.id)
            .where(
                Task.type.in_(tuple(types)),
                Task.status.in_(("QUEUED", "RETRY_SCHEDULED")),
                or_(Task.scheduled_for.is_(None), Task.scheduled_for <= now),
                or_(Task.lease_expires_at.is_(None), Task.lease_expires_at < now),
                or_(Task.lease_owner.is_(None), Task.lease_owner == ""),
            )
            .order_by(Task.priority.desc(), Task.created_at.asc())
            .limit(25)
        )
        if environment:
            stmt = stmt.where(Task.execution_environment == environment)
        candidates = list(self.db.execute(stmt).scalars().all())
        for task_id in candidates:
            update_stmt = (
                update(Task)
                .where(
                    Task.id == task_id,
                    Task.status.in_(("QUEUED", "RETRY_SCHEDULED")),
                    or_(Task.lease_expires_at.is_(None), Task.lease_expires_at < now),
                    or_(Task.lease_owner.is_(None), Task.lease_owner == ""),
                )
                .values(
                    status="RUNNING",
                    lease_owner=worker_id,
                    lease_expires_at=now + timedelta(seconds=lease_seconds),
                    started_at=func.coalesce(Task.started_at, now),
                    updated_at=now,
                )
            )
            result = self.db.execute(update_stmt)
            if result.rowcount == 1:
                self.db.commit()
                return self.db.get(Task, task_id)
        return None

    def release(self, task_id: str, worker_id: str) -> None:
        self.db.execute(
            update(Task)
            .where(Task.id == task_id, Task.lease_owner == worker_id)
            .values(lease_owner=None, lease_expires_at=None, updated_at=utcnow())
        )
        self.db.commit()

    def reclaim_expired(self) -> int:
        """Return abandoned RUNNING tasks to the queue after a worker crash."""
        now = utcnow()
        stmt = (
            update(Task)
            .where(
                Task.status == "RUNNING",
                Task.requires_human.is_(False),
                Task.lease_expires_at.is_not(None),
                Task.lease_expires_at < now,
            )
            .values(
                status="RETRY_SCHEDULED",
                lease_owner=None,
                lease_expires_at=None,
                next_retry_at=now,
                last_error="Worker lease expired - task returned to queue",
                updated_at=now,
            )
        )
        result = self.db.execute(stmt)
        self.db.commit()
        return int(result.rowcount or 0)
