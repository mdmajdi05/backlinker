"""Authorisation helpers.

Every read and write on project scoped data goes through these helpers so a
user can only ever see and modify the data of the projects they own (plus the
shared projects that have no owner).
"""

from __future__ import annotations

from sqlalchemy import select, true
from sqlalchemy.orm import Session

from app.db.models import (
    BacklinkRecord,
    Opportunity,
    Project,
    Task,
    TaskEvent,
    User,
)


def is_admin(user: User | None) -> bool:
    return bool(user and getattr(user, "is_admin", False))


def accessible_project_ids(db: Session, user: User | None) -> list[str] | None:
    """Return the project ids the user may access.

    ``None`` means "no restriction" (administrators).
    """
    if is_admin(user):
        return None
    if user is None:
        return []
    stmt = select(Project.id).where(
        (Project.owner_id == user.id) | (Project.owner_id.is_(None))
    )
    return list(db.execute(stmt).scalars().all())


def owns_project(db: Session, user: User | None, project_id: str | None) -> bool:
    """Check whether the user may access a single project."""
    if is_admin(user):
        return True
    if not project_id:
        return True
    project = db.get(Project, project_id)
    if project is None:
        return False
    return project.owner_id is None or (user is not None and project.owner_id == user.id)


def _scope_for(column, db: Session, user: User | None):
    """Build a filter for a project id column.

    The result is always a usable SQL expression - administrators get an
    unconditional filter instead of ``None`` so that a caller cannot
    accidentally append ``None`` to a where clause.
    """
    project_ids = accessible_project_ids(db, user)
    if project_ids is None:
        return true()
    if not project_ids:
        # The user owns nothing - only workspace level rows (no project) remain.
        return column.is_(None)
    return column.in_(project_ids)


def scope_opportunities(db: Session, user: User | None):
    """Filter expression for opportunity queries."""
    return _scope_for(Opportunity.project_id, db, user)


def scope_tasks(db: Session, user: User | None):
    """Filter expression for task queries.

    Tasks that are not bound to a project (workspace level work) stay visible;
    project tasks are restricted to the projects the user owns.
    """
    return _scope_for(Task.project_id, db, user)


def scope_events(db: Session, user: User | None):
    """Filter expression for activity event queries."""
    return _scope_for(TaskEvent.project_id, db, user)


def scope_backlinks(db: Session, user: User | None):
    """Filter expression for backlink record queries."""
    return _scope_for(BacklinkRecord.project_id, db, user)
