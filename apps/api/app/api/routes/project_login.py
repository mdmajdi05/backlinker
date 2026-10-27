"""The login window and login sessions of a project.

A project may have one Google account of its own.  The account is connected in
a visible browser window that only this project uses; the resulting session is
encrypted and reused by the submissions of the project.  A directory that asks
for a login can be connected in the same window, and the work that stopped at
the login wall is queued again afterwards.
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import suppress
from typing import Any

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.db.models import Project, Website, WebsiteLoginSession
from app.services import access, login_browser, login_stream, project_login
from app.services.events import record_event

router = APIRouter(tags=["project-login"])


class GoogleLoginIn(BaseModel):
    email: str | None = None
    view: str | None = None


class SiteLoginIn(BaseModel):
    view: str | None = None


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
    window = login_browser.describe_window(project.id)
    return {
        **project_login.describe(db, project.id),
        # The live surface of the open window, so a reload or a second tab can
        # join the same stream (and the card knows whether to show the viewer).
        "view": window.get("view") if window.get("running") else None,
        "headless": bool(window.get("headless")),
        "warning": window.get("warning"),
        "message": window.get("message") if window.get("running") else None,
        "preparing": window.get("preparing") if window.get("running") else None,
        "stream_available": bool(window.get("stream_available")),
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
        view=payload.view,
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
    """Save the session of the open Google window and resume paused websites."""
    project = _project(db, project_id, user)
    result = login_browser.finish(project.id, expect_mode="google")
    resumed = int(result.get("resumed") or 0)
    if result.get("saved") and not resumed:
        # The window may already have saved the session earlier (the detection
        # loop does it) - resume anything that is still paused.
        resumed = project_login.resume_login_paused_tasks(db, project.id)
    if result.get("saved"):
        record_event(
            db,
            "login.saved",
            f"Login saved for {project.name}",
            project_id=project.id,
            metadata={"resumed": resumed},
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
    project_id: str,
    website_id: str,
    db: DbSession,
    user: CurrentUser,
    payload: SiteLoginIn | None = None,
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
        view=payload.view if payload else None,
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
    result = login_browser.finish(
        project.id, expect_mode="site", expect_website=website.id
    )
    resumed = int(result.get("resumed") or 0)
    site = project_login.describe_site(db, project.id, website.id)
    if site.get("status") == project_login.SITE_CONNECTED and not resumed:
        resumed = project_login.resume_login_paused_tasks(
            db, project.id, website_id=website.id
        )
    return {**result, "resumed": resumed, "site": site}


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


# ---------------------------------------------------------------------------
# Remote view of the login browser (web client / hosted backend)
# ---------------------------------------------------------------------------


@router.post("/projects/{project_id}/login/stream-ticket")
def create_stream_ticket(
    project_id: str, db: DbSession, user: CurrentUser
) -> dict[str, Any]:
    """Issue a short lived, single use ticket for the live login stream.

    The WebSocket URL only carries this ticket, never the JWT of the user, so
    the session token cannot leak into a proxy log or a browser history.
    """
    project = _project(db, project_id, user)
    info = login_browser.describe_window(project.id)
    if not info.get("running"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "login_window_closed",
                "message": "No login window is open. Open the login window first.",
            },
        )
    if info.get("view") != "remote":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "stream_not_available",
                "message": (
                    "This login window opens natively on the backend machine; "
                    "reopen it to stream it to this page."
                ),
            },
        )
    ticket = login_stream.issue_ticket(
        project.id,
        user.id,
        ttl=settings.login_stream_ticket_seconds,
    )
    return {
        **ticket,
        "view": "remote",
        "ws_path": f"{settings.api_prefix}/projects/{project.id}/login/stream",
    }


@router.websocket("/projects/{project_id}/login/stream")
async def stream_login(
    websocket: WebSocket, project_id: str, ticket: str = Query(default="")
) -> None:
    """Stream the login browser and forward pointer / keyboard events.

    The ticket was bound to this project and this user when it was issued; it
    is consumed here exactly once, so a replayed URL cannot open a second view.
    """
    if login_stream.redeem_ticket(ticket, project_id) is None:
        await websocket.close(code=4401)
        return

    view = login_browser.remote_view(project_id)
    if view is None:
        await websocket.accept()
        await websocket.send_json(
            {
                "type": "error",
                "code": "no_stream",
                "message": "The login window is not streaming. Open it again.",
            }
        )
        await websocket.close(code=4404)
        return

    await websocket.accept()
    info = login_browser.describe_window(project_id)
    await websocket.send_json(
        {
            "type": "ready",
            "view": "remote",
            "width": view.width,
            "height": view.height,
            "headless": bool(info.get("headless")),
            "warning": info.get("warning"),
        }
    )

    frame_task = asyncio.create_task(_pump_frames(websocket, view))
    input_task = asyncio.create_task(_pump_input(websocket, view))
    tasks = (frame_task, input_task)
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:  # pragma: no cover - client closed the tab
        pass
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        with suppress(Exception):
            await websocket.close(code=1000)


async def _pump_frames(websocket: WebSocket, view: login_stream.RemoteView) -> None:
    """Send the newest frame whenever it changed, plus a keep alive."""
    last_seq = -1
    last_message = time.monotonic()
    while True:
        if view.closed:
            with suppress(Exception):
                await websocket.send_json({"type": "closed"})
            return
        seq, frame = view.latest()
        if frame is not None and seq != last_seq:
            await websocket.send_json({"type": "frame", "seq": seq})
            await websocket.send_bytes(frame)
            last_seq = seq
            last_message = time.monotonic()
        elif time.monotonic() - last_message > 15:
            await websocket.send_json({"type": "ping"})
            last_message = time.monotonic()
        await asyncio.sleep(0.03)


async def _pump_input(websocket: WebSocket, view: login_stream.RemoteView) -> None:
    """Forward validated input events to the browser thread."""
    allowed = {"mouse", "key", "text", "navigate"}
    while True:
        try:
            raw = await websocket.receive_text()
        except WebSocketDisconnect:
            return
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        kind = payload.get("type")
        if kind == "ping":
            with suppress(Exception):
                await websocket.send_json({"type": "pong"})
            continue
        if kind in allowed:
            view.push_input(payload)

