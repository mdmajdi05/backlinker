"""The recycle bin: everything that was deleted waits here.

Deleting a project, a business profile, a website or an opportunity no longer
throws the row away.  It gets a ``deleted_at`` timestamp, disappears from the
normal endpoints and shows up in this module - until it is restored or deleted
forever.

Keeping the row is what makes the old reports truthful: the submissions, the
attempts and the verification records of a removed website still exist, they
are only out of sight.  "Delete forever" is the explicit, irreversible way out.
"""

from __future__ import annotations

from contextlib import suppress
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.models import BusinessProfile, Opportunity, Project, Task, User, Website
from app.services import access, project_login
from app.services import websites as website_service

#: The kinds of rows that can wait in the recycle bin.
KINDS = ("project", "website", "profile", "opportunity")

KIND_LABELS = {
    "project": "Project",
    "website": "Website",
    "profile": "Business profile",
    "opportunity": "Opportunity",
}


class RecycleBinError(Exception):
    """Raised when a recycle bin action cannot be done."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _check_kind(kind: str) -> str:
    if kind not in KINDS:
        raise RecycleBinError(404, f"Unknown kind '{kind}'")
    return kind


# --------------------------------------------------------------------------
# Listing
# --------------------------------------------------------------------------
def _project_ids_of(db: Session, user: User | None) -> list[str] | None:
    """The projects whose removed opportunities the user may see."""
    if access.is_admin(user):
        return None
    if user is None:
        return []
    stmt = select(Project.id).where((Project.owner_id == user.id) | (Project.owner_id.is_(None)))
    return list(db.execute(stmt).scalars().all())


def _count(db: Session, model, condition, user: User | None) -> int:
    stmt = select(func.count()).select_from(model).where(condition)
    if (model is Project or model is BusinessProfile) and not access.is_admin(user):
        if user is None:
            return 0
        stmt = stmt.where((model.owner_id == user.id) | (model.owner_id.is_(None)))
    if model is Opportunity:
        ids = _project_ids_of(db, user)
        if ids is not None:
            if not ids:
                return 0
            stmt = stmt.where(Opportunity.project_id.in_(ids))
    return int(db.execute(stmt).scalar_one())


def counts(db: Session, user: User | None) -> dict[str, int]:
    """How many rows of every kind wait in the recycle bin."""
    result: dict[str, int] = {}
    result["project"] = _count(db, Project, Project.deleted_at.is_not(None), user)
    result["website"] = _count(db, Website, Website.deleted_at.is_not(None), user)
    result["profile"] = _count(db, BusinessProfile, BusinessProfile.deleted_at.is_not(None), user)
    result["opportunity"] = _count(db, Opportunity, Opportunity.deleted_at.is_not(None), user)
    return result


def _project_item(db: Session, project: Project) -> dict[str, Any]:
    return {
        "kind": "project",
        "id": project.id,
        "title": project.name,
        "subtitle": project.target_website,
        "deleted_at": project.deleted_at,
        "meta": {"status": project.status},
    }


def _website_item(website: Website) -> dict[str, Any]:
    return {
        "kind": "website",
        "id": website.id,
        "title": website.domain,
        "subtitle": website.name or website.opportunity_url,
        "deleted_at": website.deleted_at,
        "meta": {"category": website.category, "niche": website.niche},
    }


def _profile_item(profile: BusinessProfile) -> dict[str, Any]:
    return {
        "kind": "profile",
        "id": profile.id,
        "title": profile.name,
        "subtitle": profile.primary_website,
        "deleted_at": profile.deleted_at,
        "meta": {"industry": profile.industry},
    }


def _opportunity_item(db: Session, opportunity: Opportunity) -> dict[str, Any]:
    website = db.get(Website, opportunity.website_id)
    project = db.get(Project, opportunity.project_id)
    return {
        "kind": "opportunity",
        "id": opportunity.id,
        "title": website.domain if website else "Unknown website",
        "subtitle": project.name if project else None,
        "deleted_at": opportunity.deleted_at,
        "meta": {
            "project_id": opportunity.project_id,
            "website_id": opportunity.website_id,
        },
    }


def list_items(
    db: Session,
    user: User | None,
    kind: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """The removed rows - newest first, optionally limited to one kind."""
    if kind:
        _check_kind(kind)
    per_kind = counts(db, user)
    total = per_kind[kind] if kind else sum(per_kind.values())
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    pages = max(1, (total + page_size - 1) // page_size)
    offset = (page - 1) * page_size

    # The kinds are merged by their deletion time.  A page is assembled from
    # the rows of every selected kind, so the order stays stable across kinds.
    rows: list[dict[str, Any]] = []

    if kind in (None, "project"):
        condition = Project.deleted_at.is_not(None)
        if kind is None:
            # Every row is needed for the global ordering; the page is cut
            # after the merge.  The kinds are small by nature (a recycle bin).
            limit = 200
        else:
            limit = offset + page_size
        stmt = select(Project).where(condition).order_by(Project.deleted_at.desc()).limit(limit)
        if not access.is_admin(user):
            if user is None:
                stmt = stmt.where(Project.owner_id.is_(None))
            else:
                stmt = stmt.where((Project.owner_id == user.id) | (Project.owner_id.is_(None)))
        rows.extend(_project_item(db, project) for project in db.execute(stmt).scalars().all())

    if kind in (None, "website"):
        limit = 200 if kind is None else offset + page_size
        stmt = (
            select(Website)
            .where(Website.deleted_at.is_not(None))
            .order_by(Website.deleted_at.desc())
            .limit(limit)
        )
        rows.extend(_website_item(website) for website in db.execute(stmt).scalars().all())

    if kind in (None, "profile"):
        limit = 200 if kind is None else offset + page_size
        stmt = (
            select(BusinessProfile)
            .where(BusinessProfile.deleted_at.is_not(None))
            .order_by(BusinessProfile.deleted_at.desc())
            .limit(limit)
        )
        if not access.is_admin(user):
            if user is None:
                stmt = stmt.where(BusinessProfile.owner_id.is_(None))
            else:
                stmt = stmt.where(
                    (BusinessProfile.owner_id == user.id) | (BusinessProfile.owner_id.is_(None))
                )
        rows.extend(_profile_item(profile) for profile in db.execute(stmt).scalars().all())

    if kind in (None, "opportunity"):
        limit = 200 if kind is None else offset + page_size
        stmt = (
            select(Opportunity)
            .where(Opportunity.deleted_at.is_not(None))
            .order_by(Opportunity.deleted_at.desc())
            .limit(limit)
        )
        project_ids = _project_ids_of(db, user)
        if project_ids is not None:
            if project_ids:
                stmt = stmt.where(Opportunity.project_id.in_(project_ids))
            else:
                stmt = stmt.where(Opportunity.id.is_(None))
        rows.extend(
            _opportunity_item(db, opportunity)
            for opportunity in db.execute(stmt).scalars().all()
        )

    rows.sort(
        key=lambda item: item["deleted_at"] or datetime.min,
        reverse=True,
    )
    window = rows[offset : offset + page_size]

    return {
        "items": window,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
        "counts": per_kind,
    }


# --------------------------------------------------------------------------
# Restore
# --------------------------------------------------------------------------
def _load(db: Session, user: User | None, kind: str, item_id: str):
    _check_kind(kind)
    model = {
        "project": Project,
        "website": Website,
        "profile": BusinessProfile,
        "opportunity": Opportunity,
    }[kind]
    row = db.get(model, item_id)
    if row is None or row.deleted_at is None:
        raise RecycleBinError(404, f"{KIND_LABELS[kind]} is not in the recycle bin")
    if isinstance(row, (Project, BusinessProfile)):
        owned_by_other = (
            row.owner_id
            and user is not None
            and row.owner_id != user.id
            and not access.is_admin(user)
        )
        if owned_by_other:
            raise RecycleBinError(403, "Access denied")
    if isinstance(row, Opportunity) and not access.owns_project(db, user, row.project_id):
        raise RecycleBinError(403, "Access denied")
    return row


def restore_item(db: Session, user: User | None, kind: str, item_id: str) -> dict[str, Any]:
    """Bring a removed row back into the normal lists."""
    row = _load(db, user, kind, item_id)
    if isinstance(row, Website):
        website_service.restore_entry(db, row)
        return _website_item(row)
    if isinstance(row, Project):
        row.deleted_at = None
        row.version += 1
        row.updated_at = utcnow()
        db.commit()
        db.refresh(row)
        return _project_item(db, row)
    if isinstance(row, BusinessProfile):
        row.deleted_at = None
        db.commit()
        db.refresh(row)
        return _profile_item(row)
    row.deleted_at = None
    row.version += 1
    row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    return _opportunity_item(db, row)


# --------------------------------------------------------------------------
# Delete forever
# --------------------------------------------------------------------------
def purge_item(db: Session, user: User | None, kind: str, item_id: str) -> dict[str, int]:
    """Remove a row from the recycle bin forever.

    Everything that depends on the row goes with it - this is the explicit,
    irreversible action.
    """
    row = _load(db, user, kind, item_id)
    removed = {"opportunities": 0, "tasks": 0}

    if isinstance(row, Website):
        removed["opportunities"] = website_service.purge_entry(db, row)
        return removed

    if isinstance(row, Project):
        # Close a visible login window *before* any write transaction is
        # opened: its save path writes to the same SQLite database, and waiting
        # for it inside a write lock would deadlock both sides.
        with suppress(Exception):
            from app.services import login_browser

            login_browser.close(row.id)
        profile_path = project_login.profile_path_for(db, row.id)
        opportunity_ids = list(
            db.execute(select(Opportunity.id).where(Opportunity.project_id == row.id))
            .scalars()
            .all()
        )
        removed["opportunities"] = len(opportunity_ids)
        task_count = db.execute(
            select(func.count()).select_from(Task).where(Task.project_id == row.id)
        ).scalar_one()
        removed["tasks"] = int(task_count)
        db.execute(update(Task).where(Task.project_id == row.id).values(opportunity_id=None))
        # The browser profile and its encrypted session belong to the project
        # and must not outlive it on the disk.  The files are removed after the
        # commit, when no browser can recreate them any more.
        project_login.clear_profile(db, row.id, delete_files=False)
        db.delete(row)
        db.commit()
        with suppress(Exception):
            import shutil

            shutil.rmtree(profile_path, ignore_errors=True)
            default_path = project_login.profile_dir(item_id)
            if default_path != profile_path:
                shutil.rmtree(default_path, ignore_errors=True)
        return removed

    if isinstance(row, Opportunity):
        task_count = db.execute(
            select(func.count()).select_from(Task).where(Task.opportunity_id == row.id)
        ).scalar_one()
        removed["tasks"] = int(task_count)
        db.execute(
            update(Task).where(Task.opportunity_id == row.id).values(opportunity_id=None)
        )
        db.delete(row)
        db.commit()
        return removed

    # A business profile: the projects keep working without it.
    db.execute(
        update(Project)
        .where(Project.business_profile_id == row.id)
        .values(business_profile_id=None)
    )
    db.delete(row)
    db.commit()
    return removed
