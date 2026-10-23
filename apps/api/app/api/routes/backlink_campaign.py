"""The campaign cockpit of a project.

The endpoints behind one screen: add websites by URL, start the work with one
click and read the live state of every row.  The heavy lifting lives in
``app.services.campaign`` - a campaign is a view over the existing websites,
opportunities, tasks and backlink records.
"""

from __future__ import annotations

import csv
from io import StringIO
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.db.base import utcnow
from app.db.models import BacklinkRecord, Opportunity, Project, Website
from app.services import access
from app.services import campaign as campaign_service
from app.services import queue as queue_service
from app.services import websites as website_service
from app.services.events import record_event

router = APIRouter(tags=["campaign"])

#: The file types the spreadsheet import understands.
ALLOWED_SUFFIXES = {".xlsx", ".xlsm", ".csv"}

#: The status column of the CSV uses the same words as the table.
REPORT_STATUS = {
    "NOT_STARTED": "Not started",
    "NEEDS_DETAILS": "Details needed",
    "READY": "Ready to start",
    "QUEUED": "Queued",
    "SUBMITTING": "Submitting",
    "PAUSED": "Stopped",
    "WAITING_MANUAL": "Submit by hand",
    "SUBMITTED": "Submitted",
    "VERIFIED": "Verified",
    "FAILED": "Failed",
    "VERIFICATION_FAILED": "Verification failed",
    "EXCLUDED": "Excluded",
}


class AddWebsitesIn(BaseModel):
    """The input box of the campaign.

    ``text`` carries one URL or a list separated by a comma, a semicolon, a
    space or a new line.  ``urls`` is accepted as well for clients that
    already split the list themselves.
    """

    text: str = ""
    urls: list[str] = []


class ManualSubmitIn(BaseModel):
    published_url: str | None = None
    anchor_text: str | None = None
    verify: bool = True


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


def _opportunity(db, project: Project, opportunity_id: str) -> Opportunity:
    opportunity = campaign_service.campaign_row(db, project.id, opportunity_id)
    if opportunity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "opportunity_not_found",
                "message": "This website is not part of the project",
            },
        )
    return opportunity


@router.get("/projects/{project_id}/campaign")
def read_campaign(project_id: str, db: DbSession, user: CurrentUser) -> dict:
    """The live table: one row per website plus the counters above it."""
    project = _project(db, project_id, user)
    return campaign_service.campaign_payload(db, project)


@router.get("/projects/{project_id}/campaign/report.csv")
def export_campaign_report(
    project_id: str, db: DbSession, user: CurrentUser
) -> Response:
    """Download the live table as a spreadsheet-ready CSV file."""
    project = _project(db, project_id, user)
    payload = campaign_service.campaign_payload(db, project)
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "Website",
            "URL",
            "Category",
            "Status",
            "Data ready %",
            "Missing fields",
            "Published page",
            "Last update",
        ]
    )
    for row in payload["rows"]:
        writer.writerow(
            [
                row["name"],
                row["url"],
                row["category"].replace("_", " ").title(),
                REPORT_STATUS.get(row["status"], row["status"]),
                row["details_percent"],
                ", ".join(row["missing"]),
                row["published_page_url"] or "",
                row["last_update"].isoformat() if row["last_update"] else "",
            ]
        )
    record_event(
        db,
        "campaign.report_downloaded",
        f"Report of {project.name} downloaded",
        project_id=project.id,
    )
    filename = f"backlinks-{project.slug or project.id}.csv"
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/projects/{project_id}/campaign/websites")
def add_campaign_websites(
    project_id: str, payload: AddWebsitesIn, db: DbSession, user: CurrentUser
) -> dict:
    """Add one or many websites to the central list and to this project."""
    project = _project(db, project_id, user)
    text = payload.text or " ".join(payload.urls)
    results = campaign_service.add_websites(db, project, text)
    added = sum(1 for row in results if row["status"] == "added")
    linked = sum(1 for row in results if row["status"] == "linked")
    existing = sum(1 for row in results if row["status"] == "existing")
    if results:
        record_event(
            db,
            "campaign.websites_added",
            f"{added + linked} website(s) added to {project.name}",
            project_id=project.id,
            metadata={
                "added": added,
                "linked": linked,
                "existing": existing,
                "invalid": sum(1 for row in results if row["status"] == "invalid"),
            },
        )
    return {
        "results": results,
        "added": added,
        "linked": linked,
        "existing": existing,
        "invalid": sum(1 for row in results if row["status"] == "invalid"),
        "deleted": sum(1 for row in results if row["status"] == "deleted"),
    }


@router.post("/projects/{project_id}/campaign/import")
async def import_campaign_websites(
    project_id: str,
    db: DbSession,
    user: CurrentUser,
    file: UploadFile = File(...),
) -> dict:
    """Import a spreadsheet and link the imported rows to this project."""
    project = _project(db, project_id, user)
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
    stamp = utcnow().strftime("%Y%m%d%H%M%S")
    target = settings.managed_files_dir / f"campaign-import-{stamp}-{Path(filename).name}"
    target.write_bytes(content)
    try:
        result = website_service.import_entries(db, target)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "import_failed", "message": str(exc)},
        )
    finally:
        target.unlink(missing_ok=True)

    result = campaign_service.link_imported(db, project, result)
    record_event(
        db,
        "campaign.imported",
        f"Imported {filename} into {project.name}",
        project_id=project.id,
        metadata={
            "created": result["created"],
            "updated": result["updated"],
            "skipped": result["skipped"],
            "invalid": result["invalid"],
            "linked": result["linked"],
        },
    )
    return result


@router.post("/projects/{project_id}/campaign/start")
def start_campaign(project_id: str, db: DbSession, user: CurrentUser) -> dict:
    """Fill the details and queue every ready website of the project."""
    project = _project(db, project_id, user)
    result = campaign_service.start_campaign(db, project)
    record_event(
        db,
        "campaign.started",
        (
            f"{result['queued']} website(s) queued for {project.name}"
            f" ({len(result['needs_details'])} need details)"
        ),
        project_id=project.id,
        metadata={
            "queued": result["queued"],
            "already_queued": result["already_queued"],
            "needs_details": len(result["needs_details"]),
            "done": result["done"],
        },
    )
    return result


@router.post("/projects/{project_id}/campaign/stop")
def stop_campaign(project_id: str, db: DbSession, user: CurrentUser) -> dict:
    """Pause every website of the project.  Start resumes the same work."""
    project = _project(db, project_id, user)
    result = campaign_service.stop_campaign(db, project)
    record_event(
        db,
        "campaign.stopped",
        f"Stopped {project.name}: {result['message']}",
        project_id=project.id,
        metadata={
            "paused": result["paused"],
            "stopping": result["stopping"],
        },
    )
    return result


@router.post("/projects/{project_id}/campaign/restart-failed")
def restart_failed_campaign_rows(
    project_id: str, db: DbSession, user: CurrentUser
) -> dict:
    """Queue every failed submission and failed verification again."""
    project = _project(db, project_id, user)
    result = campaign_service.restart_failed(db, project)
    record_event(
        db,
        "campaign.failed_restarted",
        (
            f"{result['retried']} failed website(s) and "
            f"{result['verifications']} verification(s) restarted"
        ),
        project_id=project.id,
    )
    return result


@router.delete(
    "/projects/{project_id}/campaign/{opportunity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_campaign_row(
    project_id: str, opportunity_id: str, db: DbSession, user: CurrentUser
) -> Response:
    """Remove one website from the project; the website itself stays."""
    project = _project(db, project_id, user)
    opportunity = _opportunity(db, project, opportunity_id)
    campaign_service.unassign(db, project, opportunity)
    record_event(
        db,
        "campaign.website_removed",
        "Website removed from the project",
        project_id=project.id,
        metadata={"opportunity_id": opportunity_id},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/projects/{project_id}/campaign/{opportunity_id}/submit")
def mark_campaign_row_submitted(
    project_id: str,
    opportunity_id: str,
    payload: ManualSubmitIn,
    db: DbSession,
    user: CurrentUser,
) -> dict:
    """Record a submission the operator made by hand."""
    project = _project(db, project_id, user)
    opportunity = _opportunity(db, project, opportunity_id)
    result = campaign_service.mark_submitted(
        db,
        project,
        opportunity,
        published_url=payload.published_url,
        anchor_text=payload.anchor_text,
        verify=payload.verify,
    )
    record_event(
        db,
        "campaign.submitted",
        f"Marked {opportunity_id} as submitted",
        project_id=project.id,
        metadata={"backlink_id": result["backlink_id"]},
    )
    return result


@router.post("/projects/{project_id}/campaign/{opportunity_id}/verify")
def verify_campaign_row(
    project_id: str, opportunity_id: str, db: DbSession, user: CurrentUser
) -> dict:
    """Queue a verification of the backlink of one row."""
    project = _project(db, project_id, user)
    opportunity = _opportunity(db, project, opportunity_id)
    record = (
        db.execute(
            select(BacklinkRecord)
            .where(BacklinkRecord.opportunity_id == opportunity.id)
            .order_by(BacklinkRecord.updated_at.desc())
        )
        .scalars()
        .first()
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "nothing_to_verify",
                "message": "This row has no submission to verify yet",
            },
        )
    website = db.get(Website, opportunity.website_id)
    task, created = queue_service.enqueue(
        db,
        task_type="VERIFY",
        project_id=project.id,
        opportunity_id=opportunity.id,
        website_id=website.id if website else None,
        payload={"backlink_id": record.id, "force": True},
        priority=3,
        idempotency_key=(
            f"VERIFY:{record.id}:manual:{int(utcnow().timestamp())}"
        ),
    )
    record_event(
        db,
        "campaign.verification_queued",
        "Verification queued",
        project_id=project.id,
        task_id=task.id,
    )
    return {"task_id": task.id, "backlink_id": record.id, "created": created}
