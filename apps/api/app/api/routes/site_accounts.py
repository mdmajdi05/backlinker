"""Accounts of a project on its backlink websites.

One endpoint family behind the campaign report:

* ``GET  /projects/{id}/accounts`` - the account of every row and the state of
  the running batch,
* ``POST /projects/{id}/accounts/provision`` - create every missing account in
  one background batch (one browser, one inbox),
* ``POST /projects/{id}/accounts/{website_id}/provision`` - retry a single row,
* ``POST /projects/{id}/accounts/{website_id}/discover`` - search the backlink
  page again with the authenticated session,
* ``GET/PUT/DELETE /accounts/gmail`` - the inbox used for one-time codes.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.db.models import Opportunity, Project, SiteAccount, Website
from app.services import access, gmail_otp, project_login, site_accounts
from app.services.browser import playwright_available
from app.services.events import record_event

router = APIRouter(tags=["site-accounts"])


class ProvisionIn(BaseModel):
    website_ids: list[str] = []
    retry: bool = False
    #: The details form: the same username / password / e-mail for every
    #: website of the project.  ``None`` keeps the saved value, ``""`` clears
    #: it (that field is generated per website then).
    username: str | None = None
    password: str | None = None
    email: str | None = None
    #: Wait on a CAPTCHA page for the operator to solve it, then continue the
    #: same row.  The challenge itself is never solved or bypassed by the app.
    captcha_wait: bool | None = None


class RetryIn(BaseModel):
    retry: bool = True


class GmailIn(BaseModel):
    address: str = ""
    app_password: str = ""
    imap_host: str = gmail_otp.DEFAULT_IMAP_HOST
    imap_port: int = gmail_otp.DEFAULT_IMAP_PORT
    save: bool = True


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
    opportunity = db.execute(
        select(Opportunity).where(
            Opportunity.project_id == project.id,
            Opportunity.website_id == website_id,
            Opportunity.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    website = db.get(Website, website_id)
    if opportunity is None or website is None or website.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "website_not_in_project",
                "message": "This website is not part of the project",
            },
        )
    return website


def _accounts_payload(db, project: Project) -> dict:
    rows = (
        db.execute(select(SiteAccount).where(SiteAccount.project_id == project.id))
        .scalars()
        .all()
    )
    return {row.website_id: site_accounts.account_payload(db, row) for row in rows}


@router.get("/projects/{project_id}/accounts")
def read_accounts(project_id: str, db: DbSession, user: CurrentUser) -> dict:
    """Every account of the project plus the live batch progress."""
    project = _project(db, project_id, user)
    settings_row = gmail_otp.read_settings(db)
    profile = project_login.get_profile(db, project_id)
    return {
        "project_id": project.id,
        "accounts": _accounts_payload(db, project),
        "batch": site_accounts.batch_state(project.id),
        "counts": site_accounts.counts_for_project(db, project.id),
        "gmail": gmail_otp.status_payload(settings_row),
        #: The details form is prefilled from here on the next visit.
        "details": site_accounts.signup_details(db, project.id),
        #: The Gmail that owns the project's Google session (the sign-up
        #: address when the operator did not type another one).
        "google_email": (profile.email if profile is not None else None),
        "google_connected": bool(
            profile is not None
            and profile.status == project_login.STATUS_CONNECTED
        ),
        "browser_ready": playwright_available(),
    }


@router.post("/projects/{project_id}/accounts/provision")
def provision_accounts(
    project_id: str, payload: ProvisionIn, db: DbSession, user: CurrentUser
) -> dict:
    """Create the accounts of the project in one batch (one browser, one inbox)."""
    project = _project(db, project_id, user)
    try:
        batch = site_accounts.start_batch(
            db,
            project,
            website_ids=payload.website_ids or None,
            retry=payload.retry,
            username=payload.username,
            password=payload.password,
            email=payload.email,
            captcha_wait=payload.captcha_wait,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "cannot_start", "message": str(exc)},
        ) from exc
    record_event(
        db,
        "accounts.batch_started",
        f"Account batch of {project.name} started",
        project_id=project.id,
        metadata={"total": batch.get("total")},
    )
    return {"batch": batch, "accounts": _accounts_payload(db, project)}


@router.post("/projects/{project_id}/accounts/stop")
def stop_accounts(project_id: str, db: DbSession, user: CurrentUser) -> dict:
    project = _project(db, project_id, user)
    stopped = site_accounts.stop_batch(project.id)
    return {
        "stopped": stopped,
        "batch": site_accounts.batch_state(project.id),
        "accounts": _accounts_payload(db, project),
    }


@router.post("/projects/{project_id}/accounts/{website_id}/provision")
def provision_one(
    project_id: str,
    website_id: str,
    payload: RetryIn,
    db: DbSession,
    user: CurrentUser,
) -> dict:
    project = _project(db, project_id, user)
    website = _website(db, project, website_id)
    row = site_accounts.ensure_account(db, project.id, website.id)
    details = site_accounts.signup_details(db, project.id)
    site_accounts.apply_signup_details(row, details)
    if not row.username:
        row.username = site_accounts.generate_username(website, project)
    if not row.password_encrypted:
        site_accounts.set_password(row, site_accounts.generate_password())
    db.commit()
    try:
        batch = site_accounts.start_batch(
            db, project, website_ids=[website.id], retry=payload.retry
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "cannot_start", "message": str(exc)},
        ) from exc
    return {
        "batch": batch,
        "account": site_accounts.account_payload(db, site_accounts.get_account(db, project.id, website.id)),
    }


@router.post("/projects/{project_id}/accounts/{website_id}/discover")
def discover_backlink_page(
    project_id: str, website_id: str, db: DbSession, user: CurrentUser
) -> dict:
    """Search the backlink page of one website with its authenticated session."""
    project = _project(db, project_id, user)
    website = _website(db, project, website_id)
    row = site_accounts.get_account(db, project.id, website.id)
    if row is None or row.status not in site_accounts.ACTIVE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "account_not_active",
                "message": "Create the account of this website first.",
            },
        )
    try:
        result = site_accounts.discover_target(db, project, website)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "discovery_failed",
                "message": f"The page search could not run: {exc}",
            },
        ) from exc
    return {
        "result": result,
        "account": site_accounts.account_payload(db, row),
    }


@router.get("/accounts/gmail")
def read_gmail(db: DbSession, user: CurrentUser) -> dict:
    del user
    return gmail_otp.status_payload(gmail_otp.read_settings(db))


@router.put("/accounts/gmail")
def save_gmail(payload: GmailIn, db: DbSession, user: CurrentUser) -> dict:
    """Store the inbox of the installation (an app password, never a login password)."""
    if not payload.address.strip() or "@" not in payload.address:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid", "message": "A full Gmail address is required."},
        )
    if len(payload.app_password.replace(" ", "").strip()) < 12:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid",
                "message": (
                    "A 16 character Google App Password is required "
                    "(Google Account -> Security -> App passwords)."
                ),
            },
        )
    settings_row = gmail_otp.GmailSettings(
        address=payload.address.strip(),
        app_password=payload.app_password.replace(" ", "").strip(),
        imap_host=payload.imap_host,
        imap_port=payload.imap_port,
    )
    ok, detail = gmail_otp.check_connection(settings_row)
    if not ok and payload.save:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "gmail_login_failed", "message": detail},
        )
    if payload.save:
        gmail_otp.save_settings(
            db,
            address=settings_row.address,
            app_password=settings_row.app_password,
            user_id=user.id,
            imap_host=settings_row.imap_host,
            imap_port=settings_row.imap_port,
        )
        record_event(
            db,
            "accounts.gmail_saved",
            "The Gmail inbox for one-time codes was saved",
        )
    return {
        "ok": ok,
        "message": detail,
        **gmail_otp.status_payload(gmail_otp.read_settings(db)),
    }


@router.post("/accounts/gmail/test")
def test_gmail(payload: GmailIn, db: DbSession, user: CurrentUser) -> dict:
    del user
    settings_row = gmail_otp.read_settings(db)
    if payload.address and payload.app_password:
        candidate = gmail_otp.GmailSettings(
            address=payload.address.strip(),
            app_password=payload.app_password.replace(" ", "").strip(),
            imap_host=payload.imap_host,
            imap_port=payload.imap_port,
        )
    elif settings_row is not None:
        candidate = settings_row
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "not_configured", "message": "Save a Gmail address first."},
        )
    ok, detail = gmail_otp.check_connection(candidate)
    return {"ok": ok, "message": detail}


@router.delete("/accounts/gmail")
def delete_gmail(db: DbSession, user: CurrentUser) -> dict:
    del user
    gmail_otp.delete_settings(db)
    return gmail_otp.status_payload(None)
