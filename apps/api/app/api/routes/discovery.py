"""Discovery endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, Pagination
from app.db.models import BusinessProfile, DiscoveryRun, DiscoverySource, Project
from app.db.repositories import paginate
from app.schemas import (
    DiscoveryProviderOut,
    DiscoveryRequest,
    DiscoveryRunOut,
    PaginatedResponse,
)
from app.services import queue as queue_service
from app.services.discovery.base import all_providers, get_provider
from app.services.events import record_event

router = APIRouter(prefix="/discovery", tags=["discovery"])


@router.get("/providers", response_model=list[DiscoveryProviderOut])
def list_providers(db: DbSession, user: CurrentUser) -> list[dict]:
    """Available discovery providers and their credential requirements."""
    from app.services.discovery import load_providers

    load_providers()
    rows = db.execute(select(DiscoverySource)).scalars().all()
    registry = {source.key: source for source in rows}
    out: list[dict] = []
    for provider in all_providers():
        source = registry.get(provider.key)
        available, reason = provider.available({})
        out.append(
            {
                "key": provider.key,
                "name": provider.name,
                "description": provider.description,
                "requires_credentials": provider.requires_credentials,
                "categories": list(provider.categories),
                "enabled": source.enabled if source else True,
                "available": available,
                "reason": reason,
            }
        )
    return out


@router.post("/runs", response_model=DiscoveryRunOut, status_code=status.HTTP_202_ACCEPTED)
def start_discovery(payload: DiscoveryRequest, db: DbSession, user: CurrentUser) -> DiscoveryRun:
    from app.services.discovery import load_providers

    load_providers()
    project = db.get(Project, payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Project not found"})
    if project.owner_id and project.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Access denied"})

    provider = get_provider(payload.provider)
    if provider is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "unknown_provider", "message": f"Unknown discovery provider: {payload.provider}"},
        )
    available, reason = provider.available(payload.config)
    if not available:
        raise HTTPException(
            status_code=400,
            detail={"code": "provider_unavailable", "message": reason or "Provider is not configured"},
        )

    run = DiscoveryRun(
        project_id=project.id,
        provider=payload.provider,
        status="PENDING",
        query=payload.query,
        keywords=payload.keywords,
        config=payload.config,
        requested_limit=payload.limit,
    )
    db.add(run)
    db.flush()

    profile = (
        db.get(BusinessProfile, project.business_profile_id) if project.business_profile_id else None
    )
    # The task payload is stored as JSON, therefore it may only contain plain
    # values.  The worker reloads the business profile from the database, so
    # only the search criteria travel with the task.
    criteria = {
        "query": payload.query or "",
        "keywords": list(payload.keywords or []),
        "countries": list(payload.countries or []),
        "language": payload.language,
        "category": payload.category,
        "limit": payload.limit,
        "seeds": list(payload.seeds or []),
        "config": dict(payload.config or {}),
        "project_id": project.id,
        "excluded_domains": list(profile.excluded_domains) if profile else [],
    }
    task, _created = queue_service.enqueue(
        db,
        task_type="DISCOVER",
        project_id=project.id,
        payload={"run_id": run.id, "provider": payload.provider, "criteria": criteria},
        priority=5,
        idempotency_key=f"DISCOVER:{project.id}:{run.id}",
    )
    db.commit()
    db.refresh(run)
    record_event(
        db,
        "discovery.started",
        f"Discovery started with {payload.provider}",
        task_id=task.id,
        project_id=project.id,
        metadata={"provider": payload.provider, "limit": payload.limit},
    )
    return run


@router.get("/runs", response_model=PaginatedResponse[DiscoveryRunOut])
def list_runs(
    db: DbSession,
    user: CurrentUser,
    page: Pagination,
    project_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    provider: str | None = Query(default=None),
) -> PaginatedResponse:
    stmt = select(DiscoveryRun)
    count_stmt = select(func.count()).select_from(DiscoveryRun)
    conditions = []
    if project_id:
        conditions.append(DiscoveryRun.project_id == project_id)
    if status_filter:
        conditions.append(DiscoveryRun.status == status_filter)
    if provider:
        conditions.append(DiscoveryRun.provider == provider)
    if conditions:
        stmt = stmt.where(*conditions)
        count_stmt = count_stmt.where(*conditions)
    stmt = stmt.order_by(DiscoveryRun.created_at.desc())
    result = paginate(db, stmt, DiscoveryRun, page.page, page.page_size, count_stmt)
    return PaginatedResponse(
        items=[DiscoveryRunOut.model_validate(r) for r in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        pages=result.pages,
    )


@router.get("/runs/{run_id}", response_model=DiscoveryRunOut)
def get_run(run_id: str, db: DbSession, user: CurrentUser) -> DiscoveryRun:
    run = db.get(DiscoveryRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Run not found"})
    return run
