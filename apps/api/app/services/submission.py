"""Submission orchestration.

This module is the glue between the durable queue and the adapter framework.
It resolves the adapter for a website, prepares the context, executes the
submission and persists the result as a *backlink record* (which is still
unverified until the verification engine confirms the link).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import (
    BacklinkRecord,
    BusinessProfile,
    Opportunity,
    Project,
    SubmissionEvidence,
    Task,
    Website,
)
from app.services.adapters.base import (
    RESULT_FAILED,
    RESULT_PUBLISHED,
    RESULT_SKIPPED,
    RESULT_SUBMITTED,
    RESULT_WAITING_APPROVAL,
    RESULT_WAITING_USER,
    SubmissionContext,
    SubmissionResult,
    adapter_for_website,
    get_adapter,
)
from app.services.events import record_event
from app.workers.runner import TaskOutcome


def _adapter_config(db: Session, adapter_id: str | None, project_id: str | None) -> dict[str, Any]:
    if not adapter_id:
        return {}
    row = db.execute(
        select_adapter_config(adapter_id, project_id)
    ).scalar_one_or_none()
    if row is None:
        row = db.execute(select_adapter_config(adapter_id, None)).scalar_one_or_none()
    return row.config if row else {}


def select_adapter_config(adapter_id: str, project_id: str | None):
    from sqlalchemy import select

    from app.db.models import AdapterConfiguration as AC

    return select(AC).where(AC.adapter_id == adapter_id, AC.project_id == project_id)


def execute_submission(db: Session, task: Task) -> TaskOutcome:
    website = db.get(Website, task.website_id) if task.website_id else None
    opportunity = db.get(Opportunity, task.opportunity_id) if task.opportunity_id else None
    if website is None:
        return TaskOutcome(
            status="FAILED",
            error="Task is not linked to a website",
            message="Task is not linked to a website",
            retryable=False,
        )

    project = db.get(Project, task.project_id) if task.project_id else None
    profile = (
        db.get(BusinessProfile, project.business_profile_id)
        if project and project.business_profile_id
        else None
    )

    adapter = get_adapter(task.adapter_id) or get_adapter(website.adapter_id)
    if adapter is None:
        adapter = adapter_for_website(website)
    if adapter is None:
        pack = _manual_pack(website, opportunity, project, profile)
        _store_manual_pack(db, task, website, pack)
        return TaskOutcome(
            status=RESULT_WAITING_USER,
            message=(
                f"No automated adapter is configured for {website.domain}. "
                "A manual submission pack was prepared."
            ),
            error="No adapter available for this website",
            requires_human=True,
            result=pack,
        )

    if not adapter.automatable:
        pack = _manual_pack(website, opportunity, project, profile, adapter)
        _store_manual_pack(db, task, website, pack)
        return TaskOutcome(
            status=RESULT_WAITING_USER,
            message=f"Adapter '{adapter.name}' requires manual completion. A submission pack was prepared.",
            error="Adapter is not automatable",
            requires_human=True,
            result=pack,
        )

    project_settings = project.settings.__dict__ if project and project.settings else {}
    config = _adapter_config(db, adapter.key, task.project_id)
    evidence_dir = settings.managed_files_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    def emit(message: str, level: str = "INFO", metadata: dict[str, Any] | None = None) -> None:
        record_event(
            db,
            "task.progress",
            message,
            level=level,
            task_id=task.id,
            project_id=task.project_id,
            website_id=website.id,
            execution_environment=task.execution_environment,
            metadata=metadata,
        )

    ctx = SubmissionContext(
        db=db,
        task=task,
        website=website,
        opportunity=opportunity,
        project=project,
        profile=profile,
        adapter_config=config,
        project_settings=project_settings,
        evidence_dir=evidence_dir,
        emit=emit,
    )

    try:
        pre = adapter.preflight(ctx)
    except Exception as exc:
        return TaskOutcome(
            status=RESULT_FAILED,
            error=f"Preflight failed: {exc}",
            message=f"Preflight failed for {website.domain}",
            retryable=True,
        )
    if pre is not None and not pre.succeeded:
        return _outcome_from_result(pre)

    try:
        result = adapter.submit(ctx)
    except Exception as exc:
        return TaskOutcome(
            status=RESULT_FAILED,
            error=f"{type(exc).__name__}: {exc}",
            message=f"Submission failed for {website.domain}",
            retryable=True,
        )

    outcome = _outcome_from_result(result)
    if result.succeeded:
        _persist_backlink_record(db, task, website, opportunity, project, result)
    website.last_checked_at = result_utcnow()
    website.last_result = outcome.message
    website.error_detail = outcome.error
    website.backlink_status = (
        "PUBLISHED_UNVERIFIED"
        if result.status == RESULT_PUBLISHED
        else "SUBMITTED"
        if result.status == RESULT_SUBMITTED
        else website.backlink_status
    )
    db.commit()
    return outcome


def result_utcnow():
    from app.db.base import utcnow

    return utcnow()


def _outcome_from_result(result: SubmissionResult) -> TaskOutcome:
    if result.status == RESULT_SUBMITTED:
        return TaskOutcome(
            status=RESULT_SUBMITTED,
            result=result.evidence,
            message=result.message,
            error=result.error,
        )
    if result.status == RESULT_PUBLISHED:
        return TaskOutcome(
            status=RESULT_PUBLISHED,
            result=result.evidence,
            message=result.message,
            error=result.error,
        )
    if result.status in (RESULT_WAITING_USER, RESULT_WAITING_APPROVAL):
        return TaskOutcome(
            status=result.status,
            result=result.evidence,
            message=result.message,
            error=result.error or result.message,
            requires_human=True,
            requires_approval=result.requires_approval,
        )
    if result.status == RESULT_SKIPPED:
        return TaskOutcome(status=RESULT_SKIPPED, result=result.evidence, message=result.message, error=result.error)
    return TaskOutcome(
        status=RESULT_FAILED,
        result=result.evidence,
        message=result.message or "Submission failed",
        error=result.error or result.message,
        retryable=result.retryable,
    )


def _manual_pack(
    website: Website,
    opportunity: Opportunity | None,
    project: Project | None,
    profile: BusinessProfile | None,
    adapter=None,
) -> dict[str, Any]:
    """Build the information an operator needs to submit manually."""
    landing = (
        opportunity.target_landing_page
        if opportunity and opportunity.target_landing_page
        else (project.target_website if project else "")
    )
    anchor = website.anchor_text or (
        profile.preferred_anchors[0] if profile and profile.preferred_anchors else ""
    )
    description = website.description or (profile.description if profile else "")
    return {
        "website": website.domain,
        "opportunity_url": website.opportunity_url,
        "target_website": landing,
        "anchor_text": anchor,
        "description": description,
        "contact_email": website.contact_email,
        "adapter": adapter.key if adapter else None,
        "instructions": (
            "Open the opportunity URL, submit the business details above and mark the task as "
            "completed once the listing is live. The verification engine will then confirm the link."
        ),
    }


def _store_manual_pack(db: Session, task: Task, website: Website, pack: dict[str, Any]) -> None:
    db.add(
        SubmissionEvidence(
            task_id=task.id,
            opportunity_id=task.opportunity_id,
            kind="submission_pack",
            excerpt=pack.get("instructions"),
            metadata=pack,
        )
    )
    db.commit()


def _persist_backlink_record(
    db: Session,
    task: Task,
    website: Website,
    opportunity: Opportunity | None,
    project: Project | None,
    result: SubmissionResult,
) -> BacklinkRecord:
    """Store the submitted link. It stays *unverified* until confirmed."""
    landing = (
        result.expected_destination_url
        or (opportunity.target_landing_page if opportunity else None)
        or (project.target_website if project else "")
    )
    published_page = result.published_page_url or website.opportunity_url
    existing = db.execute(
        select_backlink(project.id if project else None, published_page, landing)
    ).scalar_one_or_none()
    if existing is None:
        existing = BacklinkRecord(
            project_id=project.id if project else task.project_id,
            opportunity_id=opportunity.id if opportunity else None,
            task_id=task.id,
            target_website=published_page,
            expected_link_url=published_page,
            published_page_url=published_page,
            expected_destination_url=landing or "",
            observed_destination_url=result.expected_destination_url,
            observed_anchor_text=result.observed_anchor_text,
            link_present=None,
            destination_matched=None,
            is_live=None,
            verification_status="PUBLISHED_UNVERIFIED" if result.status == RESULT_PUBLISHED else "SUBMITTED",
            evidence=result.evidence,
        )
        db.add(existing)
    else:
        existing.task_id = task.id
        existing.updated_at = result_utcnow()
    if result.evidence:
        db.add(
            SubmissionEvidence(
                task_id=task.id,
                opportunity_id=opportunity.id if opportunity else None,
                kind="submission",
                excerpt=result.message,
                metadata=result.evidence,
            )
        )
    db.commit()
    return existing


def select_backlink(project_id: str | None, published_page: str, landing: str):
    from sqlalchemy import select

    from app.db.models import BacklinkRecord as BR

    stmt = select(BR).where(BR.published_page_url == published_page)
    if project_id:
        stmt = stmt.where(BR.project_id == project_id)
    if landing:
        stmt = stmt.where(BR.expected_destination_url == landing)
    return stmt
