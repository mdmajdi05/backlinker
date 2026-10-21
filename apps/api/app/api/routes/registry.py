"""Website registry endpoints (list, edit, bulk actions, exclusions)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUser, DbSession, Pagination
from app.db.models import Opportunity, Project, Website
from app.schemas import (
    BulkActionRequest,
    OpportunityIn,
    OpportunityOut,
    OpportunityUpdate,
    PaginatedResponse,
)
from app.services import access
from app.services.audit import record_audit
from app.services.events import record_event
from app.services.opportunities import (
    create_website,
    link_to_project,
    normalize_url,
    opportunity_to_dict,
)

router = APIRouter(tags=["registry"])


def _load(db, opportunity_id: str, user) -> tuple[Opportunity, Website]:
    opportunity = db.get(Opportunity, opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Opportunity not found"})
    if not access.owns_project(db, user, opportunity.project_id):
        raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Access denied"})
    website = db.get(Website, opportunity.website_id)
    if website is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Website not found"})
    return opportunity, website


def _owned_project(db, project_id: str, user) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Project not found"})
    if project.owner_id and project.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Access denied"})
    return project


@router.get("/opportunities", response_model=PaginatedResponse[OpportunityOut])
def list_opportunities(
    db: DbSession,
    user: CurrentUser,
    page: Pagination,
    project_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    category: str | None = Query(default=None),
    domain: str | None = Query(default=None),
    source: str | None = Query(default=None),
    backlink_status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    min_score: float | None = Query(default=None),
    execution_environment: str | None = Query(default=None),
) -> PaginatedResponse:
    stmt = select(Opportunity, Website).join(Website, Opportunity.website_id == Website.id)
    count_stmt = (
        select(func.count())
        .select_from(Opportunity)
        .join(Website, Opportunity.website_id == Website.id)
    )
    conditions = []
    scope = access.scope_opportunities(db, user)
    if scope is not None:
        conditions.append(scope)
    if project_id:
        conditions.append(Opportunity.project_id == project_id)
    if status_filter:
        conditions.append(Opportunity.status == status_filter)
    if category:
        conditions.append(Website.category == category)
    if domain:
        conditions.append(Website.domain.ilike(f"%{domain.lower()}%"))
    if source:
        conditions.append(Website.discovery_source == source)
    if backlink_status:
        conditions.append(Website.backlink_status == backlink_status)
    if min_score is not None:
        conditions.append(Website.score >= min_score)
    if search:
        pattern = f"%{search.lower()}%"
        conditions.append(
            or_(
                Website.name.ilike(pattern),
                Website.domain.ilike(pattern),
                Website.opportunity_url.ilike(pattern),
            )
        )
    if conditions:
        stmt = stmt.where(*conditions)
        count_stmt = count_stmt.where(*conditions)

    sort_column = {
        "score": Website.score,
        "name": Website.name,
        "domain": Website.domain,
        "created_at": Website.created_at,
        "updated_at": Website.updated_at,
    }.get(page.sort or "created_at", Website.created_at)
    stmt = stmt.order_by(sort_column.desc() if page.order == "desc" else sort_column.asc())

    rows = db.execute(stmt).all()
    items = [opportunity_to_dict(opportunity, website) for opportunity, website in rows]
    total = int(db.execute(count_stmt).scalar_one() or 0)
    start = (page.page - 1) * page.page_size
    window = items[start : start + page.page_size]
    pages = max(1, (total + page.page_size - 1) // page.page_size)
    return PaginatedResponse(items=window, total=total, page=page.page, page_size=page.page_size, pages=pages)


@router.post("/opportunities", response_model=OpportunityOut, status_code=status.HTTP_201_CREATED)
def create_opportunity(payload: OpportunityIn, db: DbSession, user: CurrentUser) -> dict:
    normalized = normalize_url(payload.opportunity_url)
    website, _ = create_website(
        db,
        url=normalized,
        name=payload.name or "",
        category=payload.category,
        discovery_source=payload.discovery_source,
        description=payload.description,
        submission_method=payload.submission_method,
        registration_required=payload.registration_required,
        requires_approval=payload.requires_approval,
        adapter_id=payload.adapter_id,
        anchor_text=payload.anchor_text,
        contact_email=payload.contact_email,
        notes=payload.notes,
        is_manual=True,
    )
    # Link the website to the requested project, or to every project the user
    # owns when no project was specified.
    projects = []
    if payload.project_id:
        projects = [_owned_project(db, payload.project_id, user)]
    else:
        projects = db.execute(
            select(Project).where((Project.owner_id == user.id) | (Project.owner_id.is_(None)))
        ).scalars().all()
    opportunities = []
    for project in projects:
        opportunity, _created = link_to_project(
            db,
            project,
            website,
            target_landing_page=payload.target_landing_page,
        )
        opportunities.append(opportunity)
    db.commit()
    record_event(
        db,
        "website.added",
        f"Manually added {website.domain}",
        project_id=opportunities[0].project_id if opportunities else None,
        website_id=website.id,
        metadata={"url": website.opportunity_url},
    )
    record_audit(db, "create", "website", website.id, actor_id=user.id, after={"url": website.opportunity_url})
    first = opportunities[0] if opportunities else None
    if first is None:
        raise HTTPException(status_code=400, detail={"code": "no_project", "message": "Create a project first"})
    db.refresh(first)
    return opportunity_to_dict(first, website)


@router.get("/opportunities/{opportunity_id}", response_model=OpportunityOut)
def get_opportunity(opportunity_id: str, db: DbSession, user: CurrentUser) -> dict:
    opportunity, website = _load(db, opportunity_id, user)
    return opportunity_to_dict(opportunity, website)


@router.patch("/opportunities/{opportunity_id}", response_model=OpportunityOut)
def update_opportunity(
    opportunity_id: str, payload: OpportunityUpdate, db: DbSession, user: CurrentUser
) -> dict:
    opportunity, website = _load(db, opportunity_id, user)
    data = payload.model_dump(exclude_unset=True)
    for field in ("notes", "target_landing_page"):
        if field in data:
            setattr(opportunity, field, data.pop(field))
    for field, value in data.items():
        if value is not None:
            setattr(website, field, value)
    website.version += 1
    opportunity.version += 1
    db.commit()
    db.refresh(opportunity)
    record_audit(db, "update", "website", website.id, actor_id=user.id)
    return opportunity_to_dict(opportunity, website)


@router.post("/opportunities/bulk")
def bulk_action(payload: BulkActionRequest, db: DbSession, user: CurrentUser) -> dict:
    action = payload.action.lower()
    scope = access.scope_opportunities(db, user)
    stmt = select(Opportunity).where(Opportunity.id.in_(payload.opportunity_ids))
    if scope is not None:
        stmt = stmt.where(scope)
    opportunities = db.execute(stmt).scalars().all()
    if not opportunities:
        return {"affected": 0}

    project = None
    if payload.project_id:
        project = _owned_project(db, payload.project_id, user)

    affected = 0
    for opportunity in opportunities:
        website = db.get(Website, opportunity.website_id)
        if website is None:
            continue
        if action == "approve":
            opportunity.status = "APPROVED"
            website.status = "APPROVED"
            record_event(
                db,
                "website.approved",
                f"Approved {website.domain}",
                project_id=opportunity.project_id,
                website_id=website.id,
            )
            affected += 1
        elif action == "reject":
            opportunity.status = "REJECTED"
            website.status = "REJECTED"
            record_event(
                db,
                "website.rejected",
                f"Rejected {website.domain}",
                project_id=opportunity.project_id,
                website_id=website.id,
                metadata={"reason": payload.reason},
            )
            affected += 1
        elif action == "exclude":
            website.excluded_until = payload.excluded_until or None
            website.excluded_reason = payload.reason
            opportunity.status = "EXCLUDED"
            record_event(
                db,
                "website.excluded",
                f"Excluded {website.domain}",
                project_id=opportunity.project_id,
                website_id=website.id,
                metadata={"until": str(payload.excluded_until), "reason": payload.reason},
            )
            affected += 1
        elif action == "add_to_project" and project is not None:
            _opportunity, created = link_to_project(
                db, project, website, target_landing_page=opportunity.target_landing_page
            )
            if created:
                affected += 1
        elif action == "delete":
            db.delete(opportunity)
            db.flush()
            if not db.execute(
                select(Opportunity).where(Opportunity.website_id == website.id)
            ).scalars().first():
                db.delete(website)
            record_event(
                db,
                "website.deleted",
                f"Deleted {website.domain}",
                project_id=opportunity.project_id,
                metadata={"reason": payload.reason},
            )
            affected += 1
    db.commit()
    record_audit(
        db,
        f"bulk.{action}",
        "opportunity",
        None,
        actor_id=user.id,
        after={"count": affected, "ids": payload.opportunity_ids},
    )
    return {"affected": affected}


@router.post("/registry/exclusions")
def exclude_domain(payload: dict, db: DbSession, user: CurrentUser) -> dict:
    domain = (payload.get("domain") or "").lower().strip().removeprefix("www.")
    if not domain:
        raise HTTPException(status_code=400, detail={"code": "invalid", "message": "domain is required"})
    until = payload.get("until")
    parsed_until = None
    if until:
        try:
            parsed_until = datetime.fromisoformat(str(until).replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            parsed_until = None
    websites = db.execute(select(Website).where(Website.domain == domain)).scalars().all()
    for website in websites:
        website.excluded_until = parsed_until
        website.excluded_reason = payload.get("reason")
        for opportunity in db.execute(
            select(Opportunity).where(Opportunity.website_id == website.id)
        ).scalars().all():
            opportunity.status = "EXCLUDED"
    db.commit()
    record_event(
        db,
        "domain.excluded",
        f"Domain {domain} excluded",
        metadata={"until": str(parsed_until), "reason": payload.get("reason")},
    )
    return {"domain": domain, "affected": len(websites), "until": parsed_until}


@router.post("/registry/merge")
def merge_duplicates(payload: dict, db: DbSession, user: CurrentUser) -> dict:
    """Merge duplicate website records into a primary record."""
    primary_id = payload.get("primary_id")
    duplicate_ids = payload.get("duplicate_ids") or []
    primary = db.get(Website, primary_id)
    if primary is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Primary website not found"})
    moved = 0
    for duplicate_id in duplicate_ids:
        duplicate = db.get(Website, duplicate_id)
        if duplicate is None or duplicate.id == primary.id:
            continue
        for opportunity in db.execute(
            select(Opportunity).where(Opportunity.website_id == duplicate.id)
        ).scalars().all():
            existing = db.execute(
                select(Opportunity).where(
                    Opportunity.project_id == opportunity.project_id,
                    Opportunity.website_id == primary.id,
                )
            ).scalar_one_or_none()
            if existing is None:
                opportunity.website_id = primary.id
                moved += 1
            else:
                db.delete(opportunity)
        duplicate.duplicate_of = primary.id
        duplicate.status = "DUPLICATE"
        moved += 1
    db.commit()
    record_audit(db, "merge", "website", primary.id, actor_id=user.id, after={"merged": duplicate_ids})
    return {"primary_id": primary.id, "merged": moved}
