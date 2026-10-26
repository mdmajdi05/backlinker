"""The login window and login sessions of a project.

A project may have one Google account of its own.  The account is connected in
a visible browser window that only this project uses; the resulting session is
encrypted and reused by the submissions of the project.  A directory that asks
for a login can be connected in the same window, and the work that stopped at
the login wall is queued again afterwards.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.db.models import Project, Website, WebsiteLoginSession
from app.services import access, login_browser, project_login
from app.services.events import record_event

router = APIRouter(tags=["project-login"])


class GoogleLoginIn(BaseModel):
    email: str | None = None


def _project(db, project_id: str, user) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "project_not_found", "message": "Project not found"},
        )
    if not access.owns_project(db, user, project_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "forbidden", "message": "No access to this project"},
        )
    return project


def _website(db, project: Project, website_id: str) -> Website:
    from app.db.models import Opportunity

    row = db.execute(
        select(Opportunity).where(
            Opportunity.project_id == project.id,
            Opportunity.website_id == website_id,
            Opportunity.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    website = db.get(Website, website_id)
    if row is None or website is None or website.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "website_not_in_project",
                "message": "This website is not part of the project",
            },
        )
    return website


@router.get("/projects/{project_id}/login")
def read_login(project_id: str, db: DbSession, user: CurrentUser) -> dict:
    """The Google state of the project and the login state of every website."""
    project = _project(db, project_id, user)
    sessions = (
        db.execute(
            select(WebsiteLoginSession).where(
                WebsiteLoginSession.project_id == project.id
            )
        )
        .scalars()
        .all()
    )
    return {
        **project_login.describe(db, project.id),
        "sites": [
            {
                "website_id": row.website_id,
                "status": row.status,
                "method": row.method,
                "last_login_at": row.last_login_at,
                "last_checked_at": row.last_checked_at,
                "last_error": row.last_error,
            }
            for row in sessions
        ],
        "browser_available": login_browser.available(),
    }


@router.post("/projects/{project_id}/login/google")
def open_google_login(
    project_id: str, payload: GoogleLoginIn, db: DbSession, user: CurrentUser
) -> dict:
    """Open the visible Google window of this project."""
    project = _project(db, project_id, user)
    if not login_browser.available():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "browser_automation_disabled",
                "message": "Browser automation is disabled in the settings",
            },
        )
    result = login_browser.start(
        project.id,
        login_browser.login_start_url(project.id),
        mode="google",
        email_hint=payload.email,
    )
    record_event(
        db,
        "login.google_opened",
        f"Google login window opened for {project.name}",
        project_id=project.id,
    )
    return result


@router.post("/projects/{project_id}/login/finish")
def finish_login(project_id: str, db: DbSession, user: CurrentUser) -> dict:
    """Save the session of the open window and resume paused websites."""
    project = _project(db, project_id, user)
    result = login_browser.finish(project.id)
    resumed = int(result.get("resumed") or 0)
    if result.get("saved") and not resumed:
        # The window may already have saved the session earlier (the detection
        # loop does it) - resume anything that is still paused.
        resumed = project_login.resume_login_paused_tasks(db, project.id)
    record_event(
        db,
        "login.saved",
        f"Login saved for {project.name}",
        project_id=project.id,
        metadata={"saved": result.get("saved"), "resumed": resumed},
    )
    return {**result, "resumed": resumed, "login": project_login.describe(db, project.id)}


@router.post("/projects/{project_id}/login/cancel")
def cancel_login(project_id: str, db: DbSession, user: CurrentUser) -> dict:
    project = _project(db, project_id, user)
    return login_browser.cancel(project.id)


@router.delete("/projects/{project_id}/login")
def forget_login(project_id: str, db: DbSession, user: CurrentUser) -> dict:
    """Forget the Google session and delete the project's browser profile."""
    project = _project(db, project_id, user)
    login_browser.forget(project.id)
    record_event(
        db,
        "login.forgotten",
        f"Login forgotten for {project.name}",
        project_id=project.id,
    )
    return {"forgotten": True, "login": project_login.describe(db, project.id)}


@router.post("/projects/{project_id}/login/sites/{website_id}")
def open_site_login(
    project_id: str, website_id: str, db: DbSession, user: CurrentUser
) -> dict:
    """Open the login page of one website in the project's profile."""
    project = _project(db, project_id, user)
    website = _website(db, project, website_id)
    if not login_browser.available():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "browser_automation_disabled",
                "message": "Browser automation is disabled in the settings",
            },
        )
    url = project_login.login_url_for(db, project, website)
    result = login_browser.start(
        project.id,
        url,
        mode="site",
        website_id=website.id,
    )
    record_event(
        db,
        "login.site_opened",
        f"Login window opened for {website.domain}",
        project_id=project.id,
        website_id=website.id,
    )
    return {**result, "url": url}


@router.post("/projects/{project_id}/login/sites/{website_id}/finish")
def finish_site_login(
    project_id: str, website_id: str, db: DbSession, user: CurrentUser
) -> dict:
    """Save a directory login and resume the work of that website."""
    project = _project(db, project_id, user)
    website = _website(db, project, website_id)
    result = login_browser.finish(project.id)
    resumed = int(result.get("resumed") or 0)
    if result.get("saved") and not resumed:
        resumed = project_login.resume_login_paused_tasks(db, project.id)
    return {
        **result,
        "resumed": resumed,
        "site": project_login.describe_site(db, project.id, website.id),
    }


@router.post("/projects/{project_id}/login/sites/{website_id}/expired")
def mark_site_expired(
    project_id: str, website_id: str, db: DbSession, user: CurrentUser
) -> dict:
    """Mark a website login as expired (used by the campaign UI)."""
    project = _project(db, project_id, user)
    website = _website(db, project, website_id)
    project_login.mark_site(
        db,
        project.id,
        website.id,
        project_login.SITE_EXPIRED,
        error="The website login expired.",
    )
    return project_login.describe_site(db, project.id, website.id)
