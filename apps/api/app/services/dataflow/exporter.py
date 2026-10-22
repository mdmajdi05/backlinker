"""Reporting / export engine.

Builds the operational reports of the platform as an ``.xlsx`` workbook (or a
flat ``.csv``) and stores them inside the managed data directory.

Ten sheets are produced, using the sheet names of the shared contract
(``ReportSheet``):

``Executive Summary``, ``All Opportunities``, ``Per website``,
``Verified Backlinks``, ``Pending Tasks``, ``Failed Tasks``,
``Skipped Tasks``, ``Verification History``, ``Activity Log`` and
``Import Errors``.

The ``Per website`` sheet holds one row per website (domain) with the
counters of the submissions: how many opportunities it has, how many of them
were submitted, verified, failed, are still pending or wait for the details of
the site.  It is the sheet the operator uses to decide what to retry.

Unknown values are written as empty cells - the exporter never invents data.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import utcnow
from app.db.models import (
    BacklinkRecord,
    ExportJob,
    ImportJob,
    ImportRow,
    Opportunity,
    Project,
    Task,
    TaskAttempt,
    TaskEvent,
    VerificationRun,
    Website,
)

log = get_logger(__name__)

__all__ = [
    "COLUMNS",
    "REPORT_SHEETS",
    "WEBSITE_COLUMNS",
    "generate_report",
    "scope_project_id",
]

#: Sheet names (mirrors ``ReportSheet`` in ``packages/shared-types``).
REPORT_SHEETS: tuple[str, ...] = (
    "Executive Summary",
    "All Opportunities",
    "Per website",
    "Verified Backlinks",
    "Pending Tasks",
    "Failed Tasks",
    "Skipped Tasks",
    "Verification History",
    "Activity Log",
    "Import Errors",
)

#: The column set of the "Per website" sheet (one row per website / domain).
WEBSITE_COLUMNS: tuple[str, ...] = (
    "Domain",
    "Website",
    "Category",
    "Status",
    "Opportunities",
    "Submitted",
    "Verified",
    "Failed",
    "Pending",
    "Waiting for details",
    "Last attempt",
    "Notes",
)

#: Task statuses that count as "the backlink was submitted" in the sheet.
WEBSITE_SUBMITTED_STATUSES = ("SUBMITTED", "PUBLISHED_UNVERIFIED", "VERIFIED_LIVE")

#: Task statuses that count as "the backlink is live" in the sheet.
WEBSITE_VERIFIED_STATUSES = ("VERIFIED_LIVE",)

#: Task statuses that count as "the submission failed" in the sheet.
WEBSITE_FAILED_STATUSES = ("FAILED",)

#: Task statuses that count as "the work is still in flight" in the sheet.
#:
#: ``WAITING_FOR_USER`` is *not* part of it: a task that waits for a human has
#: its own counter so the two numbers never overlap.
WEBSITE_PENDING_STATUSES = ("QUEUED", "RUNNING", "RETRY_SCHEDULED")

#: Task statuses that count as "a human has to provide the site details".
WEBSITE_WAITING_STATUSES = ("WAITING_FOR_USER",)

#: The column set of the opportunity / task shaped sheets.
COLUMNS: tuple[str, ...] = (
    "Project ID",
    "Project Name",
    "Source Website",
    "Domain",
    "Opportunity URL",
    "Target Website",
    "Target Landing Page",
    "Backlink Category",
    "Discovery Source",
    "Anchor Text",
    "Submission Status",
    "Verification Status",
    "Actual Published URL",
    "Detected Destination URL",
    "Detected Anchor Text",
    "Link Attribute",
    "First Attempt Date",
    "Latest Attempt Date",
    "Publication Date",
    "Last Verification Date",
    "Retry Count",
    "Next Scheduled Retry",
    "Last Error",
    "Skip Reason",
    "Notes",
    "Task ID",
    "Execution Environment",
)

#: Columns that hold a URL and are rendered as a hyperlink.
URL_COLUMNS = frozenset(
    {
        "Opportunity URL",
        "Target Website",
        "Target Landing Page",
        "Actual Published URL",
        "Detected Destination URL",
    }
)

#: Task statuses considered "still in flight".
PENDING_TASK_STATUSES = (
    "QUEUED",
    "RETRY_SCHEDULED",
    "RUNNING",
    "WAITING_FOR_USER",
    "WAITING_FOR_APPROVAL",
    "PENDING",
    "DISCOVERED",
    "NEEDS_REVIEW",
    "APPROVED",
)

ACTIVITY_COLUMNS = (
    "Timestamp",
    "Event Type",
    "Level",
    "Message",
    "Project ID",
    "Project Name",
    "Task ID",
    "Website ID",
    "Execution Environment",
    "Metadata",
)

IMPORT_ERROR_COLUMNS = (
    "Row Number",
    "Import Job ID",
    "File Name",
    "Created At",
    "Action",
    "Reason",
    "Errors",
    "Raw",
)

SUMMARY_COLUMNS = ("Metric", "Value")

DATE_COLUMNS = frozenset(
    {
        "First Attempt Date",
        "Latest Attempt Date",
        "Publication Date",
        "Last Verification Date",
        "Next Scheduled Retry",
        "Timestamp",
        "Created At",
        "Last attempt",
    }
)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def generate_report(db: Session, job: ExportJob) -> None:
    """Generate the report of an export job and fill in the job record."""
    scope_project = scope_project_id(job)
    data = _collect(db, scope_project)

    directory = settings.managed_files_dir / "reports"
    directory.mkdir(parents=True, exist_ok=True)
    suffix = "csv" if str(job.format or "xlsx").lower() == "csv" else "xlsx"
    path = directory / f"report-{job.id}.{suffix}"

    if suffix == "csv":
        # The flat CSV carries the opportunities and, after them, one row per
        # website with the counters of the work.
        csv_rows = list(data["opportunities"]) + list(data["websites"])
        _write_csv(path, csv_rows)
    else:
        _write_workbook(path, data)

    job.file_path = str(path)
    job.file_name = path.name
    job.row_count = len(data["opportunities"])
    job.status = "COMPLETED"
    job.error = None
    job.completed_at = utcnow()
    db.commit()
    db.refresh(job)

    log.info(
        "report generated",
        extra={
            "extra_fields": {
                "job": job.id,
                "file": path.name,
                "rows": job.row_count,
            }
        },
    )


def scope_project_id(job: ExportJob) -> str | None:
    """Return the project the report is limited to (``None`` = workspace)."""
    if job.project_id:
        return job.project_id
    scope = str(job.scope or "")
    if scope.startswith("project:"):
        candidate = scope.split(":", 1)[1].strip()
        return candidate or None
    return None


# --------------------------------------------------------------------------
# Data collection
# --------------------------------------------------------------------------


def _collect(db: Session, project_id: str | None) -> dict[str, Any]:
    """Gather every dataset of the report."""
    opportunity_stmt = select(Opportunity)
    backlink_stmt = select(BacklinkRecord)
    task_stmt = select(Task)
    event_stmt = select(TaskEvent)
    import_stmt = select(ImportRow).where(
        ImportRow.action.in_(("INVALID", "CONFLICT"))
    )

    if project_id:
        opportunity_stmt = opportunity_stmt.where(Opportunity.project_id == project_id)
        backlink_stmt = backlink_stmt.where(BacklinkRecord.project_id == project_id)
        task_stmt = task_stmt.where(Task.project_id == project_id)
        event_stmt = event_stmt.where(TaskEvent.project_id == project_id)
        import_stmt = import_stmt.where(
            ImportRow.import_job_id.in_(
                select(ImportJob.id).where(ImportJob.project_id == project_id)
            )
        )

    opportunities = list(db.execute(opportunity_stmt).scalars().all())
    backlinks = list(db.execute(backlink_stmt).scalars().all())
    tasks = list(db.execute(task_stmt).scalars().all())
    events = list(db.execute(event_stmt).scalars().all())
    import_rows = list(db.execute(import_stmt).scalars().all())

    backlink_ids = [record.id for record in backlinks]
    runs: list[VerificationRun] = []
    if backlink_ids:
        runs = list(
            db.execute(
                select(VerificationRun)
                .where(VerificationRun.backlink_id.in_(backlink_ids))
                .order_by(VerificationRun.verified_at.asc())
            ).scalars().all()
        )

    projects = {p.id: p for p in db.execute(select(Project)).scalars().all()}
    websites = {w.id: w for w in db.execute(select(Website)).scalars().all()}

    opportunities_by_id = {o.id: o for o in opportunities}
    backlinks_by_opportunity: dict[str, BacklinkRecord] = {}
    for record in backlinks:
        if record.opportunity_id:
            backlinks_by_opportunity.setdefault(record.opportunity_id, record)

    tasks_by_opportunity: dict[str, Task] = {}
    for task in tasks:
        if task.opportunity_id:
            tasks_by_opportunity.setdefault(task.opportunity_id, task)

    attempts = _attempts_by_task(db, [t.id for t in tasks])

    def build_row(
        opportunity: Opportunity | None,
        task: Task | None,
        record: BacklinkRecord | None,
    ) -> dict[str, Any]:
        website = websites.get(opportunity.website_id) if opportunity else None
        project = projects.get(opportunity.project_id) if opportunity else None
        return _opportunity_row(
            opportunity=opportunity,
            website=website,
            project=project,
            task=task,
            record=record,
            attempts=attempts.get(task.id, []) if task else [],
        )

    opportunity_rows = [
        build_row(
            opportunity,
            tasks_by_opportunity.get(opportunity.id),
            backlinks_by_opportunity.get(opportunity.id),
        )
        for opportunity in opportunities
    ]

    task_rows = {
        task.id: build_row(
            opportunities_by_id.get(task.opportunity_id or ""),
            task,
            backlinks_by_opportunity.get(task.opportunity_id or ""),
        )
        for task in tasks
    }

    verified_rows = []
    for record in backlinks:
        if str(record.verification_status or "").upper() != "VERIFIED_LIVE":
            continue
        opportunity = opportunities_by_id.get(record.opportunity_id or "")
        verified_rows.append(
            build_row(
                opportunity,
                tasks_by_opportunity.get(opportunity.id) if opportunity else None,
                record,
            )
        )

    history_rows = []
    for run in runs:
        record = next((r for r in backlinks if r.id == run.backlink_id), None)
        opportunity = opportunities_by_id.get(record.opportunity_id or "") if record else None
        task = tasks_by_opportunity.get(opportunity.id) if opportunity else None
        row = build_row(opportunity, task, record)
        row["Verification Status"] = run.status or ""
        row["Detected Anchor Text"] = run.observed_anchor_text or ""
        row["Detected Destination URL"] = run.observed_destination_url or ""
        row["Link Attribute"] = run.link_attribute or ""
        row["Last Verification Date"] = run.verified_at or ""
        row["Last Error"] = run.error or ""
        history_rows.append(row)

    activity_rows = [
        {
            "Timestamp": event.created_at,
            "Event Type": event.event_type or "",
            "Level": event.level or "",
            "Message": event.message or "",
            "Project ID": event.project_id or "",
            "Project Name": projects[event.project_id].name
            if event.project_id in projects
            else "",
            "Task ID": event.task_id or "",
            "Website ID": event.website_id or "",
            "Execution Environment": event.execution_environment or "",
            "Metadata": _json(event.metadata),
        }
        for event in events
    ]

    import_jobs = {job.id: job for job in db.execute(select(ImportJob)).scalars().all()}
    import_error_rows = []
    for row in import_rows:
        import_job = import_jobs.get(row.import_job_id)
        import_error_rows.append(
            {
                "Row Number": row.row_number,
                "Import Job ID": row.import_job_id or "",
                "File Name": import_job.file_name if import_job else "",
                "Created At": import_job.created_at if import_job else "",
                "Action": row.action or "",
                "Reason": row.reason or "",
                "Errors": row.errors or "",
                "Raw": _json(row.raw),
            }
        )

    pending_rows = [
        task_rows[task.id] for task in tasks if task.status in PENDING_TASK_STATUSES
    ]
    failed_rows = [task_rows[task.id] for task in tasks if task.status == "FAILED"]
    skipped_rows = [task_rows[task.id] for task in tasks if task.status == "SKIPPED"]

    summary_rows = _summary_rows(
        project_id=project_id,
        opportunities=opportunity_rows,
        verified=verified_rows,
        pending=pending_rows,
        failed=failed_rows,
        skipped=skipped_rows,
        history=history_rows,
        activity=activity_rows,
        import_errors=import_error_rows,
    )

    website_rows = _website_rows(
        opportunities=opportunities,
        tasks=tasks,
        websites=websites,
    )

    return {
        "summary": summary_rows,
        "opportunities": opportunity_rows,
        "websites": website_rows,
        "verified": verified_rows,
        "pending": pending_rows,
        "failed": failed_rows,
        "skipped": skipped_rows,
        "history": history_rows,
        "activity": activity_rows,
        "import_errors": import_error_rows,
    }


def _attempts_by_task(db: Session, task_ids: list[str]) -> dict[str, list[TaskAttempt]]:
    """Return the attempt history of the given tasks (oldest first)."""
    if not task_ids:
        return {}
    rows = db.execute(
        select(TaskAttempt)
        .where(TaskAttempt.task_id.in_(task_ids))
        .order_by(TaskAttempt.attempt_number.asc())
    ).scalars().all()
    grouped: dict[str, list[TaskAttempt]] = {}
    for attempt in rows:
        grouped.setdefault(attempt.task_id, []).append(attempt)
    return grouped


def _opportunity_row(
    *,
    opportunity: Opportunity | None,
    website: Website | None,
    project: Project | None,
    task: Task | None,
    record: BacklinkRecord | None,
    attempts: Sequence[TaskAttempt],
) -> dict[str, Any]:
    """Build one report row (blanks for every unknown value)."""
    first_attempt = attempts[0].started_at if attempts else None
    latest_attempt: datetime | None = None
    if attempts:
        latest = attempts[-1]
        latest_attempt = latest.finished_at or latest.started_at
    target_website = ""
    if record is not None and record.target_website:
        target_website = record.target_website
    elif project is not None:
        target_website = project.target_website or ""
    return {
        "Project ID": project.id if project else "",
        "Project Name": project.name if project else "",
        "Source Website": (website.name if website else "") or "",
        "Domain": (website.domain if website else "") or "",
        "Opportunity URL": (website.opportunity_url if website else "") or "",
        "Target Website": target_website,
        "Target Landing Page": (opportunity.target_landing_page if opportunity else "") or "",
        "Backlink Category": (website.category if website else "") or "",
        "Discovery Source": (website.discovery_source if website else "") or "",
        "Anchor Text": (website.anchor_text if website else "") or "",
        "Submission Status": (task.status if task else "") or "",
        "Verification Status": (
            (record.verification_status if record else "")
            or (website.backlink_status if website else "")
            or ""
        ),
        "Actual Published URL": (record.published_page_url if record else "") or "",
        "Detected Destination URL": (record.observed_destination_url if record else "") or "",
        "Detected Anchor Text": (record.observed_anchor_text if record else "") or "",
        "Link Attribute": (record.link_attribute if record else "") or "",
        "First Attempt Date": first_attempt or "",
        "Latest Attempt Date": latest_attempt or "",
        "Publication Date": (
            (record.verified_at or record.last_success_at) if record else ""
        )
        or "",
        "Last Verification Date": (record.verified_at if record else "") or "",
        "Retry Count": task.attempts if task is not None else "",
        "Next Scheduled Retry": (task.next_retry_at if task else "") or "",
        "Last Error": (
            (task.last_error if task else "")
            or (record.error if record else "")
            or ""
        ),
        "Skip Reason": (task.skip_reason if task else "") or "",
        "Notes": (
            (opportunity.notes if opportunity else "")
            or (website.notes if website else "")
            or ""
        ),
        "Task ID": (task.id if task else "") or "",
        "Execution Environment": (task.execution_environment if task else "") or "",
    }


def _website_rows(
    *,
    opportunities: list[Opportunity],
    tasks: list[Task],
    websites: dict[str, Website],
) -> list[dict[str, Any]]:
    """One row per domain with the counters of the work that was done.

    The numbers are computed from the tasks and the opportunities of the
    domain - they are never stored, so a report always reflects the current
    state of the database.  A domain can carry several website records (one
    per opportunity URL); their values are merged, the counters are summed.
    """
    domain_of_website = {
        website_id: (website.domain or "").strip().lower()
        for website_id, website in websites.items()
    }
    # A task without a website is still attributed to the site its
    # opportunity belongs to.
    website_of_opportunity = {
        opportunity.id: opportunity.website_id for opportunity in opportunities
    }

    domains: dict[str, dict[str, Any]] = {}

    def bucket(website_id: str | None) -> dict[str, Any] | None:
        domain = domain_of_website.get(website_id or "")
        if not domain:
            return None
        if domain not in domains:
            domains[domain] = {
                "names": [],
                "categories": [],
                "statuses": [],
                "notes": [],
                "Opportunities": 0,
                "Submitted": 0,
                "Verified": 0,
                "Failed": 0,
                "Pending": 0,
                "Waiting for details": 0,
                "Last attempt": None,
            }
        return domains[domain]

    def merge(website_id: str | None) -> None:
        website = websites.get(website_id) if website_id else None
        if website is None:
            return
        row = bucket(website_id)
        if row is None:
            return
        _merge_value(row["names"], (website.name or "").strip())
        _merge_value(row["categories"], (website.category or "").strip())
        _merge_value(row["statuses"], (website.status or "").strip())
        _merge_value(row["notes"], (website.notes or "").strip())

    for opportunity in opportunities:
        row = bucket(opportunity.website_id)
        if row is None:
            continue
        row["Opportunities"] += 1
        merge(opportunity.website_id)

    for task in tasks:
        website_id = task.website_id or website_of_opportunity.get(task.opportunity_id or "")
        row = bucket(website_id)
        if row is None:
            continue
        status = (task.status or "").upper()
        if status in WEBSITE_SUBMITTED_STATUSES:
            row["Submitted"] += 1
        if status in WEBSITE_VERIFIED_STATUSES:
            row["Verified"] += 1
        if status in WEBSITE_FAILED_STATUSES:
            row["Failed"] += 1
        if status in WEBSITE_PENDING_STATUSES:
            row["Pending"] += 1
        if status in WEBSITE_WAITING_STATUSES:
            row["Waiting for details"] += 1
        started = task.started_at
        if started is not None and (row["Last attempt"] is None or started > row["Last attempt"]):
            row["Last attempt"] = started
        merge(website_id)

    rows: list[dict[str, Any]] = []
    for domain in sorted(domains):
        row = domains[domain]
        rows.append(
            {
                "Domain": domain,
                "Website": ", ".join(row["names"]),
                "Category": ", ".join(row["categories"]),
                "Status": ", ".join(row["statuses"]),
                "Opportunities": row["Opportunities"],
                "Submitted": row["Submitted"],
                "Verified": row["Verified"],
                "Failed": row["Failed"],
                "Pending": row["Pending"],
                "Waiting for details": row["Waiting for details"],
                "Last attempt": row["Last attempt"] or "",
                "Notes": " | ".join(row["notes"]),
            }
        )
    return rows


def _merge_value(target: list[str], value: str) -> None:
    """Add a value to the list - without duplicates and without empty values."""
    if value and value not in target:
        target.append(value)


def _summary_rows(
    *,
    project_id: str | None,
    opportunities: list[dict[str, Any]],
    verified: list[dict[str, Any]],
    pending: list[dict[str, Any]],
    failed: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    history: list[dict[str, Any]],
    activity: list[dict[str, Any]],
    import_errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build the executive summary (metric / value pairs + a totals row)."""
    scope = f"project:{project_id}" if project_id else "workspace"
    generated = utcnow().isoformat(sep=" ", timespec="seconds")
    metrics: list[tuple[str, Any]] = [
        ("Scope", scope),
        ("Generated At", generated),
        ("Total Opportunities", len(opportunities)),
        ("Verified Live Backlinks", len(verified)),
        ("Pending Tasks", len(pending)),
        ("Failed Tasks", len(failed)),
        ("Skipped Tasks", len(skipped)),
        ("Verification Runs", len(history)),
        ("Activity Events", len(activity)),
        ("Import Error Rows", len(import_errors)),
    ]
    rows = [{"Metric": name, "Value": value} for name, value in metrics]
    rows.append({"Metric": "TOTAL OPPORTUNITIES", "Value": len(opportunities)})
    return rows


def _json(value: Any) -> str:
    """Render a JSON column as a readable string."""
    if value is None:
        return ""
    try:
        return json.dumps(value, default=str, ensure_ascii=False)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return str(value)


# --------------------------------------------------------------------------
# Writers
# --------------------------------------------------------------------------


#: The columns of the flat CSV: the opportunities first, then the columns
#: that only the per website rows have.
CSV_COLUMNS: tuple[str, ...] = COLUMNS + tuple(
    column for column in WEBSITE_COLUMNS if column not in COLUMNS
)


def _write_csv(path: Path, data: dict[str, Any]) -> None:
    """Write the flat CSV version of the report.

    The file carries the opportunities of the report and, after them, one row
    per website with the counters of the work.  The header is the union of the
    columns of both, so the file stays one flat table.
    """
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_COLUMNS)
        for row in data["opportunities"]:
            writer.writerow([_csv_value(row.get(column)) for column in CSV_COLUMNS])
        for row in data["websites"]:
            writer.writerow([_csv_value(row.get(column)) for column in CSV_COLUMNS])


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    return value


def _write_workbook(path: Path, data: dict[str, Any]) -> None:
    """Write the multi sheet XLSX report."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    workbook.remove(workbook.active)

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="1F4E79")
    header_alignment = Alignment(vertical="center", horizontal="left")

    def add_sheet(
        name: str, columns: Sequence[str], rows: Iterable[dict[str, Any]]
    ) -> None:
        worksheet = workbook.create_sheet(title=name)
        worksheet.append(list(columns))
        for index, _column in enumerate(columns, start=1):
            cell = worksheet.cell(row=1, column=index)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
        materialised = list(rows)
        for row in materialised:
            worksheet.append([row.get(column) for column in columns])
        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = worksheet.dimensions
        for index, column in enumerate(columns, start=1):
            worksheet.column_dimensions[get_column_letter(index)].width = _column_width(
                materialised, column
            )
        _format_sheet(worksheet, columns)

    add_sheet(REPORT_SHEETS[0], SUMMARY_COLUMNS, data["summary"])
    add_sheet(REPORT_SHEETS[1], COLUMNS, data["opportunities"])
    add_sheet(REPORT_SHEETS[2], WEBSITE_COLUMNS, data["websites"])
    add_sheet(REPORT_SHEETS[3], COLUMNS, data["verified"])
    add_sheet(REPORT_SHEETS[4], COLUMNS, data["pending"])
    add_sheet(REPORT_SHEETS[5], COLUMNS, data["failed"])
    add_sheet(REPORT_SHEETS[6], COLUMNS, data["skipped"])
    add_sheet(REPORT_SHEETS[7], COLUMNS, data["history"])
    add_sheet(REPORT_SHEETS[8], ACTIVITY_COLUMNS, data["activity"])
    add_sheet(REPORT_SHEETS[9], IMPORT_ERROR_COLUMNS, data["import_errors"])

    workbook.save(path)


def _format_sheet(worksheet, columns: Sequence[str]) -> None:
    """Apply the date format and the hyperlinks to a worksheet."""
    for index, column in enumerate(columns, start=1):
        for row_index in range(2, worksheet.max_row + 1):
            cell = worksheet.cell(row=row_index, column=index)
            if cell.value is None:
                continue
            if column in DATE_COLUMNS and isinstance(cell.value, datetime):
                cell.number_format = "yyyy-mm-dd hh:mm"
            if (
                column in URL_COLUMNS
                and isinstance(cell.value, str)
                and cell.value.startswith(("http://", "https://"))
            ):
                cell.hyperlink = cell.value
                cell.style = "Hyperlink"


def _column_width(rows: list[dict[str, Any]], column: str) -> int:
    """Compute a readable width for a column."""
    longest = len(column)
    for row in rows[:400]:
        value = row.get(column)
        if value is None:
            continue
        if isinstance(value, datetime):
            text = value.isoformat(sep=" ", timespec="seconds")
        else:
            text = str(value)
        longest = max(longest, min(len(text), 60))
    return min(max(longest + 2, 10), 60)
