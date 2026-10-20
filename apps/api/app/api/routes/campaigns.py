"""Campaign and schedule endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.db.base import utcnow
from app.db.models import Campaign, Project, Schedule
from app.services.audit import record_audit
from app.services.events import record_event

router = APIRouter(tags=["campaigns"])


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    name: str
    description: str | None
    status: str
    goal_type: str | None
    target_value: int | None
    created_at: datetime
    updated_at: datetime


class ScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    kind: str
    target_id: str | None
    interval_seconds: int | None
    cron: str | None
    next_run_at: datetime | None
    last_run_at: datetime | None
    enabled: bool
    config: dict


def _project(db, project_id: str, user) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Project not found"})
    if project.owner_id and project.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Access denied"})
    return project


@router.get("/projects/{project_id}/campaigns", response_model=list[CampaignOut])
def list_campaigns(project_id: str, db: DbSession, user: CurrentUser) -> list[Campaign]:
    _project(db, project_id, user)
    return list(
        db.execute(select(Campaign).where(Campaign.project_id == project_id)).scalars().all()
    )


@router.post("/projects/{project_id}/campaigns", response_model=CampaignOut, status_code=status.HTTP_201_CREATED)
def create_campaign(project_id: str, payload: dict, db: DbSession, user: CurrentUser) -> Campaign:
    _project(db, project_id, user)
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid", "message": "Campaign name is required"},
        )
    campaign = Campaign(
        project_id=project_id,
        name=name,
        description=payload.get("description"),
        status=payload.get("status", "ACTIVE"),
        goal_type=payload.get("goal_type"),
        target_value=payload.get("target_value"),
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    record_audit(db, "create", "campaign", campaign.id, actor_id=user.id, after={"name": name})
    return campaign


@router.delete("/campaigns/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_campaign(campaign_id: str, db: DbSession, user: CurrentUser) -> None:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Campaign not found"})
    db.delete(campaign)
    db.commit()


@router.get("/schedules", response_model=list[ScheduleOut])
def list_schedules(db: DbSession, user: CurrentUser) -> list[Schedule]:
    return list(db.execute(select(Schedule).order_by(Schedule.name)).scalars().all())


@router.post("/schedules", response_model=ScheduleOut, status_code=status.HTTP_201_CREATED)
def create_schedule(payload: dict, db: DbSession, user: CurrentUser) -> Schedule:
    kind = payload.get("kind")
    if kind not in ("discovery", "verification"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid", "message": "kind must be 'discovery' or 'verification'"},
        )
    name = (payload.get("name") or kind).strip()
    interval = int(payload.get("interval_seconds") or 3600)
    schedule = Schedule(
        name=name,
        kind=kind,
        target_id=payload.get("target_id"),
        interval_seconds=interval,
        cron=payload.get("cron"),
        next_run_at=utcnow(),
        enabled=bool(payload.get("enabled", True)),
        config=payload.get("config") or {},
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    record_event(
        db,
        "schedule.created",
        f"Schedule '{name}' created",
        metadata={"kind": kind, "interval_seconds": interval},
    )
    return schedule


@router.patch("/schedules/{schedule_id}", response_model=ScheduleOut)
def update_schedule(schedule_id: str, payload: dict, db: DbSession, user: CurrentUser) -> Schedule:
    schedule = db.get(Schedule, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Schedule not found"})
    for field in ("name", "enabled", "interval_seconds", "cron", "target_id", "config", "next_run_at"):
        if field in payload:
            setattr(schedule, field, payload[field])
    db.commit()
    db.refresh(schedule)
    return schedule


@router.delete("/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_schedule(schedule_id: str, db: DbSession, user: CurrentUser) -> None:
    schedule = db.get(Schedule, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Schedule not found"})
    db.delete(schedule)
    db.commit()
