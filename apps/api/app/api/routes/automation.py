"""Automation control endpoints.

They cover the browser runtime (isolated, headless by default), the resource
aware scheduler and the global execution control (pause / resume / stop).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.db.models import Task, Website
from app.services import browser as browser_service
from app.services import execution as execution_service
from app.services import resources as resource_service

router = APIRouter(tags=["automation"])


@router.get("/browser/status")
def browser_status(db: DbSession, user: CurrentUser) -> dict:
    """Is the isolated browser runtime ready?"""
    return browser_service.runtime_status().as_dict()


@router.post("/browser/install")
def browser_install(db: DbSession, user: CurrentUser) -> dict:
    """Download the browser runtime into the directory of this installation.

    The download needs an internet connection once.  Everything else of the
    application works without the browser.
    """
    ok, message = browser_service.install_runtime()
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "install_failed", "message": message[:2000]},
        )
    return {"ok": True, "message": message, "status": browser_service.runtime_status().as_dict()}


@router.get("/worker/status")
def worker_status(db: DbSession, user: CurrentUser) -> dict:
    """The execution control state, the running jobs and the machine load."""
    settings_row = execution_service.get_settings(db)
    running = int(
        db.execute(
            select(func.count()).select_from(Task).where(Task.status == "RUNNING")
        ).scalar_one()
        or 0
    )
    browser_running = 0
    for website_id in db.execute(
        select(Task.website_id).where(Task.status == "RUNNING", Task.type == "SUBMIT")
    ).scalars().all():
        if not website_id:
            continue
        website = db.get(Website, website_id)
        if website and website.adapter_id:
            from app.db.models import AutomationAdapter

            row = db.get(AutomationAdapter, website.adapter_id)
            if row is not None and row.key == "playwright_form":
                browser_running += 1

    load = resource_service.governor.status(
        settings_row.max_browser_jobs, settings_row.resource_preference
    )
    return {
        "execution": execution_service.describe(db),
        "running_jobs": running,
        "running_browser_jobs": browser_running,
        "resources": load,
        "browser": browser_service.runtime_status().as_dict(),
        "queue": _queue_counts(db),
    }


def _queue_counts(db) -> dict:
    rows = db.execute(select(Task.status, func.count()).group_by(Task.status)).all()
    return {status_value: int(count) for status_value, count in rows}


@router.put("/worker/settings")
def update_worker_settings(payload: dict, db: DbSession, user: CurrentUser) -> dict:
    """Change the concurrency, the resource preference or the browser mode."""
    allowed = {
        "max_browser_jobs",
        "resource_preference",
        "headless",
        "per_domain_limit",
        "per_domain_requests_per_minute",
        "task_timeout_seconds",
        "page_timeout_seconds",
    }
    changes = {key: value for key, value in payload.items() if key in allowed}
    if "resource_preference" in changes and changes["resource_preference"] not in (
        "max_speed",
        "balanced",
        "save_resources",
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid",
                "message": "resource_preference must be max_speed, balanced or save_resources",
            },
        )
    if "max_browser_jobs" in changes:
        try:
            changes["max_browser_jobs"] = max(1, min(16, int(changes["max_browser_jobs"])))
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "invalid", "message": "max_browser_jobs must be a number"},
            )
    settings_row = execution_service.update_settings(db, changes)
    return {"execution": settings_row.as_dict()}


@router.post("/worker/pause")
def pause_workers(db: DbSession, user: CurrentUser) -> dict:
    """Stop claiming new jobs - running jobs finish."""
    return {"execution": execution_service.pause(db).as_dict()}


@router.post("/worker/resume")
def resume_workers(db: DbSession, user: CurrentUser) -> dict:
    """Claim jobs again."""
    return {"execution": execution_service.resume(db).as_dict()}


@router.post("/worker/stop")
def stop_workers(db: DbSession, user: CurrentUser) -> dict:
    """Stop claiming new jobs and cancel the running ones."""
    from app.db.models import Task as TaskModel

    running = db.execute(
        select(TaskModel).where(TaskModel.status == "RUNNING")
    ).scalars().all()
    for task in running:
        task.cancel_requested = True
    db.commit()
    return {"execution": execution_service.stop(db).as_dict(), "cancelled": len(running)}


@router.get("/resources")
def resources(db: DbSession, user: CurrentUser) -> dict:
    """The current machine load."""
    settings_row = execution_service.get_settings(db)
    return resource_service.governor.status(
        settings_row.max_browser_jobs, settings_row.resource_preference
    )
