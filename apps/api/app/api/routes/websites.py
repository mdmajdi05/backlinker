"""The central website list and the gap report of an opportunity.

The list is the one place where the sites the backlinks are made at live.  It
is independent of the projects - a project picks the sites it wants from it
(``POST /projects/{id}/websites/choose``).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, Pagination
from app.core.config import settings
from app.db.models import Opportunity, Project, Website
from app.schemas import (
    DetailsGapReport,
    PaginatedResponse,
    WebsiteAutomationDetectIn,
    WebsiteAutomationDetectOut,
    WebsiteAutomationFindOut,
    WebsiteAutomationIn,
    WebsiteChooseIn,
    WebsiteChooseResult,
    WebsiteCreateIn,
    WebsiteImportResult,
    WebsiteListItem,
    WebsiteRecipeBatchIn,
    WebsiteRecipeBatchOut,
    WebsiteRecipeOut,
    WebsiteRecipeRow,
    WebsiteStatsRow,
    WebsiteUpdateIn,
)
from app.services import access, automation_setup, form_finder, site_recipe
from app.services import site_details as details_service
from app.services import websites as website_service
from app.services.audit import record_audit
from app.services.events import record_event

router = APIRouter(tags=["websites"])

#: The file types the import understands (the campaign import uses the same).
ALLOWED_SUFFIXES = {".xlsx", ".xlsm", ".csv"}


def _owned_project(db, project_id: str, user) -> Project:
    """The project the user may work on."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "Project not found"}
        )
    if not access.owns_project(db, user, project.id):
        raise HTTPException(
            status_code=403, detail={"code": "forbidden", "message": "Access denied"}
        )
    return project


def _entry(db, website_id: str) -> Website:
    """The website of the central list."""
    website = db.get(Website, website_id)
    if website is None:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "Website not found"}
        )
    return website


@router.get("/websites", response_model=PaginatedResponse[WebsiteListItem])
def list_websites(
    db: DbSession,
    user: CurrentUser,
    page: Pagination,
    search: str | None = Query(default=None),
    category: str | None = Query(default=None),
    niche: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    project_id: str | None = Query(default=None),
) -> PaginatedResponse:
    """The rows of the central list.

    The list can be filtered by a search term, by category, by niche, by
    status and by the project a website is used in.
    """
    if project_id:
        _owned_project(db, project_id, user)
    items, total = website_service.list_entries(
        db,
        search=search,
        category=category,
        niche=niche,
        status=status_filter,
        project_id=project_id,
        page=page.page,
        page_size=page.page_size,
        sort=page.sort,
        order=page.order,
    )
    pages = max(1, (total + page.page_size - 1) // page.page_size)
    return PaginatedResponse(
        items=items,
        total=total,
        page=page.page,
        page_size=page.page_size,
        pages=pages,
    )


@router.post("/websites", response_model=WebsiteListItem, status_code=status.HTTP_201_CREATED)
def create_website(
    payload: WebsiteCreateIn, db: DbSession, user: CurrentUser
) -> WebsiteListItem:
    """Add a website to the central list (no project needed)."""
    if website_service.find_entry(db, payload.opportunity_url) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "duplicate",
                "message": "This opportunity URL is already in the central list",
            },
        )
    website = website_service.create_entry(
        db,
        opportunity_url=payload.opportunity_url,
        name=payload.name,
        category=payload.category,
        niche=payload.niche,
        notes=payload.notes,
        submission_method=payload.submission_method,
        signup_url=payload.signup_url,
        post_url=payload.post_url,
    )
    record_event(
        db,
        "website.added",
        f"Added {website.domain} to the central list",
        website_id=website.id,
        metadata={"url": website.opportunity_url, "niche": website.niche},
    )
    record_audit(
        db,
        "create",
        "website",
        website.id,
        actor_id=user.id,
        after={"url": website.opportunity_url, "niche": website.niche},
    )
    return WebsiteListItem(**website_service.item_payload(db, [website])[0])

@router.patch("/websites/{website_id}", response_model=WebsiteListItem)
def update_website(
    website_id: str, payload: WebsiteUpdateIn, db: DbSession, user: CurrentUser
) -> WebsiteListItem:
    """Change a website of the central list (name, category, niche, status, ...)."""
    website = _entry(db, website_id)
    changes = payload.model_dump(exclude_unset=True)
    updated = website_service.update_entry(db, website, changes)
    record_event(
        db,
        "website.updated",
        f"Updated {updated.domain} in the central list",
        website_id=updated.id,
        metadata={"fields": sorted(changes.keys())},
    )
    record_audit(
        db,
        "update",
        "website",
        updated.id,
        actor_id=user.id,
        after={"fields": sorted(changes.keys())},
    )
    return WebsiteListItem(**website_service.item_payload(db, [updated])[0])


@router.put("/websites/{website_id}/automation", response_model=WebsiteListItem)
def save_website_automation(
    website_id: str,
    payload: WebsiteAutomationIn,
    db: DbSession,
    user: CurrentUser,
) -> WebsiteListItem:
    """Configure automatic form submission for **one** website.

    The configuration is stored on the website (not on the project): every
    directory has a different form.  Saving an empty adapter clears the
    configuration and puts the website back on the manual path.
    """
    website = _entry(db, website_id)
    try:
        saved = automation_setup.save_automation(
            db, website, payload.model_dump(exclude_unset=False)
        )
    except automation_setup.AutomationSetupError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": "invalid_automation", "message": exc.message},
        ) from exc
    record_event(
        db,
        "website.automation_saved" if saved.adapter_id else "website.automation_cleared",
        (
            f"Saved automatic submission setup for {saved.domain}"
            if saved.adapter_id
            else f"Cleared automatic submission setup for {saved.domain}"
        ),
        website_id=saved.id,
        metadata={"adapter": saved.adapter.key if saved.adapter else None},
    )
    record_audit(
        db,
        "configure_automation",
        "website",
        saved.id,
        actor_id=user.id,
        after={"adapter": saved.adapter.key if saved.adapter else None},
    )
    return WebsiteListItem(**website_service.item_payload(db, [saved])[0])


@router.delete("/websites/{website_id}/automation", response_model=WebsiteListItem)
def clear_website_automation(
    website_id: str, db: DbSession, user: CurrentUser
) -> WebsiteListItem:
    """Remove the automatic form setup of a website (manual path)."""
    website = _entry(db, website_id)
    cleared = automation_setup.clear_automation(db, website)
    record_event(
        db,
        "website.automation_cleared",
        f"Cleared automatic submission setup for {cleared.domain}",
        website_id=cleared.id,
    )
    record_audit(db, "clear_automation", "website", cleared.id, actor_id=user.id)
    return WebsiteListItem(**website_service.item_payload(db, [cleared])[0])


@router.post(
    "/websites/{website_id}/automation/detect",
    response_model=WebsiteAutomationDetectOut,
)
def detect_website_automation_fields(
    website_id: str,
    payload: WebsiteAutomationDetectIn,
    db: DbSession,
    user: CurrentUser,
) -> WebsiteAutomationDetectOut:
    """Read the form page and propose selectors for the common values.

    This only inspects static HTML.  It never submits the form and never marks
    the website as automated - the operator has to review and save the result.
    """
    del user
    website = _entry(db, website_id)
    try:
        result = automation_setup.detect_fields(db, website, payload.form_url)
    except automation_setup.AutomationSetupError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": "detect_failed", "message": exc.message},
        ) from exc
    return WebsiteAutomationDetectOut(**result)


@router.post(
    "/websites/{website_id}/automation/find-form",
    response_model=WebsiteAutomationFindOut,
)
def find_website_submission_page(
    website_id: str,
    payload: WebsiteAutomationDetectIn,
    db: DbSession,
    user: CurrentUser,
) -> WebsiteAutomationFindOut:
    """Follow the "add listing" links from the homepage to the real form.

    The finder reads static HTML only.  It proposes the form URL and the field
    mapping; the operator still reviews them and saves the automation.
    """
    del user
    website = _entry(db, website_id)
    result = form_finder.find_submission_page(db, website, payload.form_url)
    return WebsiteAutomationFindOut(**result)


@router.post("/websites/{website_id}/recipe", response_model=WebsiteRecipeOut)
def refresh_website_recipe(
    website_id: str, db: DbSession, user: CurrentUser
) -> WebsiteRecipeOut:
    """Read this website now: sign-up page, verification and post page.

    The operator's ``signup_url`` / ``post_url`` hints are tried first, so a
    pasted URL is verified instead of guessed.  Only static HTML is read; no
    account is created and no form is submitted.
    """
    del user
    website = _entry(db, website_id)
    recipe = site_recipe.refresh(db, website)
    record_event(
        db,
        "website.recipe",
        f"Read the procedure of {website.domain}",
        website_id=website.id,
        metadata={
            "signup_url": website.signup_url,
            "post_url": website.post_url,
            "needs_signup": recipe.get("needs_signup"),
        },
    )
    return WebsiteRecipeOut(
        website_id=website.id,
        signup_url=website.signup_url,
        post_url=website.post_url,
        needs_signup=recipe.get("needs_signup"),
        steps=[str(step) for step in recipe.get("steps") or []],
        recipe=recipe,
    )


@router.post("/websites/recipes", response_model=WebsiteRecipeBatchOut)
def refresh_website_recipes(
    payload: WebsiteRecipeBatchIn, db: DbSession, user: CurrentUser
) -> WebsiteRecipeBatchOut:
    """Read several websites at once and store their procedures.

    The batch is deliberately small and bounded: a probe is a handful of GET
    requests, and the caller repeats the call for the next page of websites.
    """
    del user
    limit = max(1, min(int(payload.limit or 10), 25))
    statement = select(Website).where(Website.status != "DELETED")
    if payload.website_ids:
        statement = statement.where(Website.id.in_(payload.website_ids))
    rows = list(db.execute(statement.limit(200)).scalars())
    if payload.only_missing:
        rows = [
            row for row in rows
            if not (isinstance(row.recipe, dict) and row.recipe.get("checked_at"))
        ]
    chosen = rows[:limit]
    site_recipe.refresh_many(db, chosen)
    return WebsiteRecipeBatchOut(
        probed=len(chosen),
        rows=[
            WebsiteRecipeRow(
                website_id=row.id,
                domain=row.domain,
                state=(
                    "ok"
                    if isinstance(row.recipe, dict) and row.recipe.get("reachable")
                    else "unreachable"
                ),
                signup_url=row.signup_url,
                post_url=row.post_url,
            )
            for row in chosen
        ],
    )


@router.delete("/websites/{website_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_website(website_id: str, db: DbSession, user: CurrentUser) -> None:
    """Remove a website from the central list.

    The removal is soft: the status becomes ``DELETED``, the opportunities and
    the task history stay in the database so the reports remain truthful.
    """
    website = _entry(db, website_id)
    website_service.delete_entry(db, website)
    record_event(
        db,
        "website.deleted",
        f"Removed {website.domain} from the central list",
        website_id=website.id,
        metadata={"url": website.opportunity_url},
    )
    record_audit(db, "delete", "website", website.id, actor_id=user.id)


@router.post("/websites/{website_id}/restore", response_model=WebsiteListItem)
def restore_website(website_id: str, db: DbSession, user: CurrentUser) -> WebsiteListItem:
    """Bring a removed website back into the central list.

    This is the counterpart of the delete: the website was only *removed* from
    the list, its history was never thrown away.
    """
    website = _entry(db, website_id)
    restored = website_service.restore_entry(db, website)
    record_event(
        db,
        "website.restored",
        f"Restored {restored.domain} in the central list",
        website_id=restored.id,
    )
    record_audit(db, "restore", "website", restored.id, actor_id=user.id)
    return WebsiteListItem(**website_service.item_payload(db, [restored])[0])


@router.delete("/websites/{website_id}/purge", status_code=status.HTTP_204_NO_CONTENT)
def purge_website(website_id: str, db: DbSession, user: CurrentUser) -> None:
    """Delete a website **forever** - including its opportunities and tasks.

    This cannot be undone.  It exists for the cases where a site should not
    even be visible in the history any more (a wrong import, a site that was
    never real).
    """
    website = _entry(db, website_id)
    domain = website.domain
    removed = website_service.purge_entry(db, website)
    record_event(
        db,
        "website.purged",
        f"Purged {domain} and its history",
        metadata={"url": website.opportunity_url, "opportunities": removed},
    )
    record_audit(db, "purge", "website", website.id, actor_id=user.id, after={"domain": domain})


@router.post("/websites/import", response_model=WebsiteImportResult)
async def import_websites(
    db: DbSession,
    user: CurrentUser,
    file: UploadFile = File(...),
    category: str | None = Form(default=None),
    niche: str | None = Form(default=None),
    status_filter: str | None = Form(default=None, alias="status"),
) -> WebsiteImportResult:
    """Import a spreadsheet into the central list.

    The column names are the ones of the campaign import (``Website``,
    ``Opportunity URL``, ``Category``, ``Anchor Text``, ``Target URL``,
    ``Description``, ``Email``, ``Notes``).  A row with an unusable URL is
    reported as ``invalid`` with a reason - it is never dropped silently.
    """
    filename = file.filename or "upload"
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "unsupported_file",
                "message": f"Unsupported file type: {suffix or '(none)'}",
            },
        )
    content = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "code": "file_too_large",
                "message": f"File exceeds {settings.max_upload_mb} MB",
            },
        )

    settings.ensure_directories()
    target = settings.managed_files_dir / f"website-import-{_stamp()}-{Path(filename).name}"
    target.write_bytes(content)
    if status_filter:
        wanted = status_filter.strip().upper().replace(" ", "_").replace("-", "_")
        if wanted not in website_service.WEBSITE_STATUSES:
            target.unlink(missing_ok=True)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "invalid_status",
                    "message": (
                        f"'{status_filter}' is not a website status "
                        f"({', '.join(website_service.WEBSITE_STATUSES)})"
                    ),
                },
            )
    try:
        result = website_service.import_entries(
            db,
            target,
            category=category,
            niche=niche,
            status=status_filter,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "import_failed", "message": str(exc)},
        )
    finally:
        target.unlink(missing_ok=True)

    record_event(
        db,
        "website.imported",
        f"Imported {filename} into the central list",
        metadata={
            "created": result["created"],
            "updated": result["updated"],
            "skipped": result["skipped"],
            "invalid": result["invalid"],
        },
    )
    return WebsiteImportResult(**result)


def _stamp() -> str:
    from app.db.base import utcnow

    return utcnow().strftime("%Y%m%d%H%M%S")


@router.get("/websites/stats", response_model=list[WebsiteStatsRow])
def website_stats(
    db: DbSession,
    user: CurrentUser,
    project_id: str | None = Query(default=None),
) -> list[WebsiteStatsRow]:
    """The per website statistics.

    Without a project the numbers cover the whole list, with a project only
    the work of that project is counted.
    """
    if project_id:
        _owned_project(db, project_id, user)
    return [WebsiteStatsRow(**row) for row in website_service.stats_rows(db, project_id)]


@router.post("/projects/{project_id}/websites/choose", response_model=WebsiteChooseResult)
def choose_websites(
    project_id: str, payload: WebsiteChooseIn, db: DbSession, user: CurrentUser
) -> WebsiteChooseResult:
    """Add websites of the central list to a project.

    Every website that is taken creates an opportunity and a submission task.
    Websites that are filtered out (by category or niche), that are already
    linked or that were removed from the list are skipped.
    """
    project = _owned_project(db, project_id, user)
    result = website_service.choose_for_project(
        db,
        project,
        website_ids=payload.website_ids,
        category=payload.category,
        niche=payload.niche,
        anchor_text=payload.anchor_text,
        target_landing_page=payload.target_landing_page,
    )
    record_event(
        db,
        "website.chosen",
        f"Chose {result['linked']} website(s) for {project.name}",
        project_id=project.id,
        metadata={
            "linked": result["linked"],
            "skipped": result["skipped"],
            "tasks_created": result["tasks_created"],
        },
    )
    record_audit(
        db,
        "choose",
        "website",
        None,
        actor_id=user.id,
        after={"project_id": project.id, **result},
    )
    return WebsiteChooseResult(**result)


@router.get("/opportunities/{opportunity_id}/details/gaps", response_model=DetailsGapReport)
def opportunity_detail_gaps(
    opportunity_id: str, db: DbSession, user: CurrentUser
) -> DetailsGapReport:
    """Which details an opportunity still misses.

    The report separates the missing fields the business profile can fill from
    the ones it cannot - with a plain reason.  Nothing is invented.
    """
    opportunity = db.get(Opportunity, opportunity_id)
    if opportunity is None:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "Opportunity not found"}
        )
    if not access.owns_project(db, user, opportunity.project_id):
        raise HTTPException(
            status_code=403, detail={"code": "forbidden", "message": "Access denied"}
        )
    return DetailsGapReport(**details_service.gap_report(db, opportunity))
