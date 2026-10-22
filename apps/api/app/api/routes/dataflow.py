"""Import centre and report export endpoints."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, func, or_, select

from app.api.deps import CurrentUser, DbSession, Pagination
from app.core.config import settings
from app.db.models import ExportJob, ImportJob, ImportRow, Opportunity, Task, Website
from app.db.repositories import paginate
from app.schemas import (
    ExportCreateRequest,
    ExportJobOut,
    ImportCommitRequest,
    ImportJobOut,
    ImportPreviewOut,
    ImportRowOut,
    PaginatedResponse,
    ReportRetryOut,
    ReportRetryRequest,
)
from app.services import access
from app.services.dataflow.exporter import scope_project_id
from app.services.events import record_event

imports_router = APIRouter(prefix="/imports", tags=["imports"])
reports_router = APIRouter(prefix="/reports", tags=["reports"])

ALLOWED_SUFFIXES = {".xlsx", ".xlsm", ".xls", ".csv"}
MAGIC = {
    ".xlsx": b"PK",
    ".xlsm": b"PK",
    ".xls": b"\xd0\xcf\x11\xe0",
    ".csv": None,
}


@imports_router.post("/preview", response_model=ImportPreviewOut)
async def preview_import(
    db: DbSession,
    user: CurrentUser,
    file: UploadFile = File(...),
    project_id: str | None = Form(default=None),
) -> ImportPreviewOut:
    from app.services.dataflow.importer import preview_import as run_preview

    filename = file.filename or "upload"
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "unsupported_file", "message": f"Unsupported file type: {suffix or '(none)'}"},
        )
    content = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"code": "file_too_large", "message": f"File exceeds {settings.max_upload_mb} MB"},
        )
    magic = MAGIC.get(suffix)
    if magic and not content.startswith(magic):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_file", "message": "File content does not match its extension"},
        )

    settings.ensure_directories()
    target = settings.managed_files_dir / f"import-{utc_stamp()}-{Path(filename).name}"
    target.write_bytes(content)

    try:
        result = run_preview(db, target, filename, project_id, user.id)
    except ValueError as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "import_failed", "message": str(exc)},
        )
    record_event(
        db,
        "import.previewed",
        f"Import previewed for {filename}",
        project_id=project_id,
        metadata={"rows": result["counts"]["total"]},
    )
    return ImportPreviewOut(**result)


def utc_stamp() -> str:
    from app.db.base import utcnow

    return utcnow().strftime("%Y%m%d%H%M%S")


@imports_router.post("/{import_id}/commit", response_model=ImportJobOut)
def commit_import(import_id: str, payload: ImportCommitRequest, db: DbSession, user: CurrentUser) -> ImportJob:
    from app.services.dataflow.importer import commit_import as run_commit

    job = db.get(ImportJob, import_id)
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Import job not found"})
    if job.status == "COMMITTED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "already_committed", "message": "This import was already committed"},
        )
    run_commit(db, job, payload.apply_actions, dry_run=payload.dry_run)
    db.refresh(job)
    record_event(
        db,
        "import.committed",
        f"Imported {job.file_name}",
        project_id=job.project_id,
        metadata={
            "created": job.created_count,
            "updated": job.updated_count,
            "skipped": job.skipped_count,
            "retried": job.retried_count,
            "verify": job.verify_count,
            "invalid": job.invalid_count,
        },
    )
    return job


@imports_router.get("", response_model=PaginatedResponse[ImportJobOut])
def list_imports(
    db: DbSession,
    user: CurrentUser,
    page: Pagination,
    project_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
) -> PaginatedResponse:
    stmt = select(ImportJob)
    count_stmt = select(func.count()).select_from(ImportJob)
    conditions = []
    if project_id:
        conditions.append(ImportJob.project_id == project_id)
    if status_filter:
        conditions.append(ImportJob.status == status_filter)
    if conditions:
        stmt = stmt.where(*conditions)
        count_stmt = count_stmt.where(*conditions)
    stmt = stmt.order_by(ImportJob.created_at.desc())
    result = paginate(db, stmt, ImportJob, page.page, page.page_size, count_stmt)
    return PaginatedResponse(
        items=[ImportJobOut.model_validate(j) for j in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        pages=result.pages,
    )


@imports_router.get("/{import_id}", response_model=ImportJobOut)
def get_import(import_id: str, db: DbSession, user: CurrentUser) -> ImportJob:
    job = db.get(ImportJob, import_id)
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Import job not found"})
    return job


@imports_router.get("/{import_id}/rows", response_model=list[ImportRowOut])
def get_import_rows(import_id: str, db: DbSession, user: CurrentUser) -> list[dict]:
    job = db.get(ImportJob, import_id)
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Import job not found"})
    rows = db.execute(
        select(ImportRow).where(ImportRow.import_job_id == import_id).order_by(ImportRow.row_number)
    ).scalars().all()
    return [
        ImportRowOut(
            row_number=row.row_number,
            action=row.action,
            reason=row.reason,
            errors=row.errors,
            raw=row.raw or {},
        )
        for row in rows
    ]


@imports_router.get("/{import_id}/error-report")
def import_error_report(import_id: str, db: DbSession, user: CurrentUser) -> StreamingResponse:
    job = db.get(ImportJob, import_id)
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Import job not found"})
    rows = db.execute(
        select(ImportRow).where(ImportRow.import_job_id == import_id, ImportRow.action == "INVALID")
    ).scalars().all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["row_number", "action", "errors", "raw"])
    for row in rows:
        writer.writerow([row.row_number, row.action, row.errors or "", row.raw])
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="import-errors-{import_id}.csv"'},
    )


# --------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------

@reports_router.post("", response_model=ExportJobOut, status_code=status.HTTP_202_ACCEPTED)
def create_report(payload: ExportCreateRequest, db: DbSession, user: CurrentUser) -> ExportJob:
    from app.services.dataflow.exporter import generate_report

    job = ExportJob(
        project_id=payload.project_id,
        user_id=user.id,
        scope=payload.scope if not payload.project_id else f"project:{payload.project_id}",
        status="RUNNING",
        format=payload.format,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    try:
        generate_report(db, job)
    except Exception as exc:  # pragma: no cover - defensive
        job.status = "FAILED"
        job.error = str(exc)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "report_failed", "message": str(exc)},
        )
    db.refresh(job)
    record_event(
        db,
        "report.generated",
        f"Report generated ({job.format.upper()})",
        project_id=payload.project_id,
        metadata={"rows": job.row_count},
    )
    return job


@reports_router.get("", response_model=PaginatedResponse[ExportJobOut])
def list_reports(
    db: DbSession,
    user: CurrentUser,
    page: Pagination,
    project_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    format_filter: str | None = Query(default=None, alias="format"),
) -> PaginatedResponse:
    stmt = select(ExportJob)
    count_stmt = select(func.count()).select_from(ExportJob)
    conditions = []
    if project_id:
        conditions.append(ExportJob.project_id == project_id)
    if status_filter:
        conditions.append(ExportJob.status == status_filter)
    if format_filter:
        conditions.append(ExportJob.format == format_filter)
    if conditions:
        stmt = stmt.where(*conditions)
        count_stmt = count_stmt.where(*conditions)
    stmt = stmt.order_by(ExportJob.created_at.desc())
    result = paginate(db, stmt, ExportJob, page.page, page.page_size, count_stmt)
    return PaginatedResponse(
        items=[ExportJobOut.model_validate(j) for j in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        pages=result.pages,
    )


@reports_router.get("/{export_id}/download")
def download_report(export_id: str, db: DbSession, user: CurrentUser) -> StreamingResponse:
    job = db.get(ExportJob, export_id)
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Report not found"})
    if not job.file_path or not Path(job.file_path).exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "file_missing", "message": "The report file is no longer available"},
        )
    media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if job.format == "xlsx" else "text/csv"
    return StreamingResponse(
        iter([Path(job.file_path).read_bytes()]),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{job.file_name}"'},
    )


@reports_router.delete("/{export_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_report(export_id: str, db: DbSession, user: CurrentUser) -> None:
    job = db.get(ExportJob, export_id)
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Report not found"})
    db.delete(job)
    db.commit()


@reports_router.post("/{export_id}/retry-failed", response_model=ReportRetryOut)
def retry_failed_submissions(
    export_id: str,
    db: DbSession,
    user: CurrentUser,
    payload: ReportRetryRequest | None = None,
) -> ReportRetryOut:
    """Re-queue the failed work of a report.

    The report decides *what* is retried, the queue decides *how*: the attempt
    history is preserved and the idempotency key makes sure that no second
    task is created for the same work.  A task that was retried in the
    meantime and is running now is skipped - it must not be queued twice.
    """
    from app.services import queue as queue_service

    job = db.get(ExportJob, export_id)
    if job is None:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "Report not found"}
        )

    request = payload or ReportRetryRequest()
    domain = (request.domain or "").strip().lower()
    for project_id in (scope_project_id(job), request.project_id):
        if project_id and not access.owns_project(db, user, project_id):
            raise HTTPException(
                status_code=403, detail={"code": "forbidden", "message": "Access denied"}
            )

    retried = 0
    skipped = 0
    task_ids: list[str] = []

    for task in _failed_tasks_of_report(
        db,
        job,
        user,
        project_id=request.project_id,
        domain=domain,
    ):
        if task.status != "FAILED":
            # The task was retried in the meantime: it is queued or running
            # already, so it must not be queued a second time.
            skipped += 1
            continue
        queue_service.retry_task(db, task)
        record_event(
            db,
            "task.retry",
            "Retried from a report",
            task_id=task.id,
            project_id=task.project_id,
            metadata={"report_id": job.id, "domain": domain or None},
        )
        retried += 1
        task_ids.append(task.id)

    return ReportRetryOut(
        retried=retried,
        skipped=skipped,
        task_ids=task_ids,
        message=_retry_message(retried, skipped),
    )


def _retry_message(retried: int, skipped: int) -> str:
    """A short summary of what the retry did."""
    parts = [f"{retried} task(s) queued again"]
    if skipped:
        parts.append(f"{skipped} skipped (already retried and running)")
    return ", ".join(parts)


#: The states of a task that is already on its way - it must not be queued
#: a second time.
IN_FLIGHT_STATUSES = ("QUEUED", "RUNNING", "RETRY_SCHEDULED")


def _failed_tasks_of_report(
    db: DbSession,
    job: ExportJob,
    user,
    *,
    project_id: str | None,
    domain: str,
) -> list[Task]:
    """The failed tasks a report contains.

    A report knows the project it was generated for; the optional filters
    narrow the selection down to one website or one project.  Only the tasks
    of the projects the user may work on are returned.

    A task that failed and was retried afterwards is on its way now: it is
    part of the failed work of the report, but it must not be queued a second
    time.  The attempts behind it tell the two apart from a task that was
    never run at all.
    """
    stmt = select(Task).where(
        or_(
            Task.status == "FAILED",
            and_(Task.status.in_(IN_FLIGHT_STATUSES), Task.attempts > 0),
        )
    )
    scope = access.scope_tasks(db, user)
    if scope is not None:
        stmt = stmt.where(scope)
    report_project = scope_project_id(job)
    if report_project:
        stmt = stmt.where(Task.project_id == report_project)
    if project_id:
        stmt = stmt.where(Task.project_id == project_id)
    if domain:
        websites = select(Website.id).where(func.lower(Website.domain) == domain)
        opportunities = select(Opportunity.id).where(Opportunity.website_id.in_(websites))
        stmt = stmt.where(
            or_(Task.website_id.in_(websites), Task.opportunity_id.in_(opportunities))
        )
    stmt = stmt.order_by(Task.created_at.asc(), Task.id.asc())
    return list(db.execute(stmt).scalars().all())
