"""Project CRUD + project settings."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select, update

from app.api.deps import CurrentUser, DbSession, Pagination
from app.db.base import utcnow
from app.db.models import (
    BusinessProfile,
    Opportunity,
    Project,
    ProjectSettings,
    TargetWebsite,
    Task,
)
from app.db.repositories import paginate
from app.schemas import (
    BacklinkDetailsIn,
    BacklinkDetailsOut,
    PaginatedResponse,
    ProjectDetailOut,
    ProjectIn,
    ProjectOut,
    ProjectPatch,
    ProjectSettingsIn,
    ProjectSettingsOut,
    TargetWebsiteOut,
)
from app.services import backlink_details
from app.services.audit import record_audit
from app.services.queue import OPEN_TASK_STATUSES

router = APIRouter(prefix="/projects", tags=["projects"])


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "project"


def _get_project(db, project_id: str, user) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.deleted_at is not None:
        # A project that waits in the recycle bin is gone for every reader.
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Project not found"})
    if project.owner_id and user and project.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Access denied"})
    return project


def _counts(db, project_id: str) -> dict[str, int]:
    opp_status = dict(
        db.execute(
            select(Opportunity.status, func.count())
            .where(Opportunity.project_id == project_id)
            .group_by(Opportunity.status)
        ).all()
    )
    task_status = dict(
        db.execute(
            select(Task.status, func.count())
            .where(Task.project_id == project_id)
            .group_by(Task.status)
        ).all()
    )
    return {
        "opportunities": sum(opp_status.values()),
        "approved": int(opp_status.get("APPROVED", 0)),
        "queued": int(task_status.get("QUEUED", 0)),
        "running": int(task_status.get("RUNNING", 0)),
        "completed": int(task_status.get("COMPLETED", 0)) + int(task_status.get("SUBMITTED", 0)),
        "failed": int(task_status.get("FAILED", 0)),
        "verified_live": int(task_status.get("VERIFIED_LIVE", 0)),
        "pending_manual": int(task_status.get("WAITING_FOR_USER", 0)),
    }


@router.get("", response_model=PaginatedResponse[ProjectOut])
def list_projects(db: DbSession, user: CurrentUser, page: Pagination) -> PaginatedResponse:
    stmt = select(Project)
    count_stmt = select(func.count()).select_from(Project)
    if not user.is_admin:
        stmt = stmt.where((Project.owner_id == user.id) | (Project.owner_id.is_(None)))
        count_stmt = count_stmt.where((Project.owner_id == user.id) | (Project.owner_id.is_(None)))
    stmt = stmt.where(Project.deleted_at.is_(None))
    count_stmt = count_stmt.where(Project.deleted_at.is_(None))
    stmt = stmt.order_by(Project.created_at.desc())
    result = paginate(db, stmt, Project, page.page, page.page_size, count_stmt)
    return PaginatedResponse(
        items=[ProjectOut.model_validate(p) for p in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        pages=result.pages,
    )


@router.post("", response_model=ProjectDetailOut, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectIn, db: DbSession, user: CurrentUser) -> ProjectDetailOut:
    if payload.business_profile_id:
        profile = db.get(BusinessProfile, payload.business_profile_id)
        if profile is None:
            raise HTTPException(status_code=400, detail={"code": "invalid_profile", "message": "Business profile not found"})

    base_slug = slugify(payload.name)
    slug = base_slug
    counter = 1
    while db.execute(select(Project).where(Project.slug == slug)).scalar_one_or_none() is not None:
        counter += 1
        slug = f"{base_slug}-{counter}"

    project = Project(
        name=payload.name,
        slug=slug,
        description=payload.description,
        target_website=payload.target_website,
        business_profile_id=payload.business_profile_id,
        owner_id=user.id,
        status="ACTIVE",
    )
    settings_payload = (payload.settings or ProjectSettingsIn()).model_dump()
    project.settings = ProjectSettings(**settings_payload)
    db.add(project)
    db.flush()

    for landing in payload.landing_pages:
        url = landing.url.strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        db.add(
            TargetWebsite(
                project_id=project.id,
                name=landing.name,
                url=url.rstrip("/"),
                domain=url.split("//", 1)[-1].split("/", 1)[0].lower(),
                kind=landing.kind,
            )
        )
    db.commit()
    db.refresh(project)
    if payload.details is not None:
        backlink_details.write(
            db, project, user, payload.details.model_dump(exclude_unset=True)
        )
    record_audit(db, "create", "project", project.id, actor_id=user.id, after={"name": project.name})
    _queue_sync(db, project)
    return ProjectDetailOut(
        **ProjectOut.model_validate(project).model_dump(),
        settings=ProjectSettingsOut.model_validate(project.settings) if project.settings else None,
        counts=_counts(db, project.id),
    )


@router.get("/{project_id}", response_model=ProjectDetailOut)
def get_project(project_id: str, db: DbSession, user: CurrentUser) -> ProjectDetailOut:
    project = _get_project(db, project_id, user)
    return ProjectDetailOut(
        **ProjectOut.model_validate(project).model_dump(),
        settings=ProjectSettingsOut.model_validate(project.settings) if project.settings else None,
        counts=_counts(db, project.id),
    )


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(project_id: str, payload: ProjectPatch, db: DbSession, user: CurrentUser) -> ProjectOut:
    project = _get_project(db, project_id, user)
    data = payload.model_dump(exclude_unset=True)
    landing_pages = data.pop("landing_pages", None)
    details = data.pop("details", None)
    for field, value in data.items():
        if value is None:
            if field == "business_profile_id":
                # An empty profile detaches the project from the profile.
                project.business_profile_id = None
            continue
        setattr(project, field, value)
    if landing_pages is not None:
        _replace_landing_pages(db, project, landing_pages)
    if details is not None:
        backlink_details.write(db, project, user, details)
    project.version += 1
    project.updated_at = utcnow()
    db.commit()
    db.refresh(project)
    record_audit(db, "update", "project", project.id, actor_id=user.id)
    _queue_sync(db, project)
    return ProjectOut.model_validate(project)


def _replace_landing_pages(db: DbSession, project: Project, pages: list[dict]) -> None:
    """Replace the landing pages of a project with the given list."""
    from app.db.models import TargetWebsite

    for existing in list(
        db.execute(select(TargetWebsite).where(TargetWebsite.project_id == project.id)).scalars().all()
    ):
        db.delete(existing)
    db.flush()
    for page in pages:
        url = str(page.get("url") or "").strip()
        if not url:
            continue
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        url = url.rstrip("/")
        db.add(
            TargetWebsite(
                project_id=project.id,
                name=str(page.get("name") or url),
                url=url,
                domain=url.split("//", 1)[-1].split("/", 1)[0].lower(),
                kind=str(page.get("kind") or "LANDING"),
            )
        )
    db.flush()


@router.get("/{project_id}/backlink-details", response_model=BacklinkDetailsOut)
def get_backlink_details(project_id: str, db: DbSession, user: CurrentUser) -> BacklinkDetailsOut:
    """The details a submission needs, and how complete they are."""
    project = _get_project(db, project_id, user)
    return BacklinkDetailsOut(**backlink_details.read(db, project))


@router.put("/{project_id}/backlink-details", response_model=BacklinkDetailsOut)
def put_backlink_details(
    project_id: str, payload: BacklinkDetailsIn, db: DbSession, user: CurrentUser
) -> BacklinkDetailsOut:
    """Store the details of the project in its business profile.

    This is the one place where the company facts live: a second project that
    uses the same profile sees the same values, so nothing is duplicated.
    """
    project = _get_project(db, project_id, user)
    stored = backlink_details.write(db, project, user, payload.model_dump(exclude_unset=True))
    record_audit(db, "update", "project", project.id, actor_id=user.id, after={"details": True})
    return BacklinkDetailsOut(**stored)


def _queue_sync(db, project: Project) -> None:
    """Queue the project for the next hybrid synchronisation push."""
    from app.services.sync import record_change

    record_change(
        db,
        "projects",
        project.id,
        {
            "id": project.id,
            "name": project.name,
            "slug": project.slug,
            "description": project.description,
            "target_website": project.target_website,
            "business_profile_id": project.business_profile_id,
            "status": project.status,
            "version": project.version,
        },
        version=project.version,
    )
    db.commit()


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: str, db: DbSession, user: CurrentUser) -> None:
    """Move the project into the recycle bin.

    The project disappears from the lists, but its opportunities, tasks and
    verification records stay so the reports keep telling the truth.  It waits
    in the recycle bin until it is restored or deleted forever.
    """
    project = _get_project(db, project_id, user)
    project.deleted_at = utcnow()
    project.version += 1
    project.updated_at = utcnow()
    # Nothing may be submitted for a project that left the lists.
    db.execute(
        update(Task)
        .where(
            Task.project_id == project.id,
            Task.status.in_(OPEN_TASK_STATUSES),
        )
        .values(status="CANCELLED", finished_at=utcnow(), lease_owner=None, lease_expires_at=None)
    )
    db.commit()
    record_audit(db, "delete", "project", project_id, actor_id=user.id)


@router.get("/{project_id}/settings", response_model=ProjectSettingsOut)
def get_settings(project_id: str, db: DbSession, user: CurrentUser) -> ProjectSettings:
    project = _get_project(db, project_id, user)
    if project.settings is None:
        project.settings = ProjectSettings(project_id=project.id)
        db.commit()
        db.refresh(project)
    return project.settings


@router.get("/{project_id}/websites", response_model=PaginatedResponse[TargetWebsiteOut])
def list_target_websites(
    project_id: str,
    db: DbSession,
    user: CurrentUser,
    page: Pagination,
    kind: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
) -> PaginatedResponse:
    """The landing pages of a project (the targets a backlink may point to)."""
    _get_project(db, project_id, user)
    conditions = [TargetWebsite.project_id == project_id]
    if kind:
        conditions.append(TargetWebsite.kind == kind)
    if is_active is not None:
        conditions.append(TargetWebsite.is_active.is_(is_active))
    stmt = select(TargetWebsite).where(*conditions)
    count_stmt = select(func.count()).select_from(TargetWebsite).where(*conditions)
    stmt = stmt.order_by(TargetWebsite.created_at.desc())
    result = paginate(db, stmt, TargetWebsite, page.page, page.page_size, count_stmt)
    return PaginatedResponse(
        items=[TargetWebsiteOut.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        pages=result.pages,
    )


@router.put("/{project_id}/settings", response_model=ProjectSettingsOut)
def update_settings(
    project_id: str, payload: ProjectSettingsIn, db: DbSession, user: CurrentUser
) -> ProjectSettings:
    project = _get_project(db, project_id, user)
    if project.settings is None:
        project.settings = ProjectSettings(project_id=project.id)
        db.flush()
    for field, value in payload.model_dump().items():
        setattr(project.settings, field, value)
    db.commit()
    db.refresh(project)
    return project.settings
