"""Auto pilot endpoints: switch the automatic submission of a project on/off.

The auto pilot is what turns "approve" into "the system keeps submitting":
when it is enabled, every approved opportunity of the project is queued for
submission without any further action.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser, DbSession
from app.db.models import Project
from app.schemas import AutopilotStateIn, AutopilotStateOut
from app.services import autopilot as autopilot_service
from app.services.audit import record_audit

router = APIRouter(prefix="/projects", tags=["autopilot"])


def _project(db, project_id: str, user) -> Project:
    """Load a project the user may access."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Project not found"})
    if project.owner_id and project.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Access denied"})
    return project


def _state(db, project_id: str) -> AutopilotStateOut:
    data = autopilot_service.describe(db, project_id)
    return AutopilotStateOut(**data)  # type: ignore[arg-type]


@router.get("/{project_id}/autopilot", response_model=AutopilotStateOut)
def get_autopilot(project_id: str, db: DbSession, user: CurrentUser) -> AutopilotStateOut:
    """The state of the auto pilot and how many opportunities are waiting."""
    project = _project(db, project_id, user)
    return _state(db, project.id)


@router.post("/{project_id}/autopilot", response_model=AutopilotStateOut)
def update_autopilot(
    project_id: str, payload: AutopilotStateIn, db: DbSession, user: CurrentUser
) -> AutopilotStateOut:
    """Enable or disable the auto pilot of a project.

    Enabling it queues the opportunities that are already approved.
    """
    project = _project(db, project_id, user)
    autopilot_service.set_auto_submit(db, project.id, payload.enabled, payload.categories)
    record_audit(
        db,
        "update",
        "project_settings",
        project.id,
        actor_id=user.id,
        after={"auto_submit": payload.enabled, "auto_submit_categories": payload.categories},
    )
    if payload.enabled:
        autopilot_service.queue_approved(db, project.id)
    return _state(db, project.id)
