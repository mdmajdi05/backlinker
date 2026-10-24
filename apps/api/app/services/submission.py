"""Submission orchestration.

This module is the glue between the durable queue and the adapter framework.
It resolves the adapter for a website, prepares the context, executes the
submission and persists the result as a *backlink record* (which is still
unverified until the verification engine confirms the link).
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import (
    AdapterConfiguration,
    AutomationAdapter,
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


def _adapter_config(db: Session, adapter, project_id: str | None) -> dict[str, Any]:
    """Read the configuration of an adapter for a project.

    The configuration is stored with the *row id* of the adapter, the registry
    is keyed by the adapter *key* - both identifiers are therefore tried.
    """
    identifiers: list[str] = []
    if isinstance(adapter, str):
        identifiers.append(adapter)
    else:
        identifiers.append(adapter.key)
        row = db.execute(
            select(AutomationAdapter).where(AutomationAdapter.key == adapter.key)
        ).scalar_one_or_none()
        if row is not None:
            identifiers.append(row.id)
    for identifier in identifiers:
        row = db.execute(
            select(AdapterConfiguration).where(
                AdapterConfiguration.adapter_id == identifier,
                AdapterConfiguration.project_id == project_id,
            )
        ).scalar_one_or_none()
        if row is not None:
            return row.config
    for identifier in identifiers:
        row = db.execute(
            select(AdapterConfiguration).where(
                AdapterConfiguration.adapter_id == identifier,
                AdapterConfiguration.project_id.is_(None),
            )
        ).scalar_one_or_none()
        if row is not None:
            return row.config
    return {}


def resolve_adapter(db: Session, identifier: str | None):
    """Resolve an adapter from a registry key **or** a database row id.

    The database stores the id of the ``automation_adapters`` row, while the
    registry is keyed by the adapter key (``playwright_form``).  Both have to
    resolve to the same adapter, otherwise a manually chosen adapter would
    silently be ignored.
    """
    if not identifier:
        return None
    adapter = get_adapter(identifier)
    if adapter is not None:
        return adapter
    row = db.get(AutomationAdapter, identifier)
    if row is not None:
        return get_adapter(row.key)
    return None


def _cancel_requested(db: Session, task_id: str) -> bool:
    """Is the task cancelled (or the whole execution stopped)?

    The check is throttled because it runs between the steps of a workflow.
    """
    from app.db.models import Task as TaskModel

    now = time.monotonic()
    last = _CANCEL_CHECKS.get(task_id)
    if last is not None and now - last < 2.0:
        return False
    _CANCEL_CHECKS[task_id] = now

    row = db.execute(
        select(TaskModel.cancel_requested).where(TaskModel.id == task_id)
    ).scalar_one_or_none()
    if row:
        return True

    from app.services.execution import get_settings as get_execution_settings

    return get_execution_settings(db).state == "STOPPED"


#: The last time a task was checked for cancellation.
_CANCEL_CHECKS: dict[str, float] = {}


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

    adapter = resolve_adapter(db, task.adapter_id) or resolve_adapter(db, website.adapter_id)
    if adapter is None:
        adapter = adapter_for_website(website)

    # A generic adapter that declares required configuration but has none for
    # this project can only fail.  Most discovered directories hit this path:
    # they have a BROWSER_FORM submission method but nobody configured the
    # selectors.  Prepare the real manual pack instead of queueing a task that
    # is guaranteed to end in FAILED.  An explicitly assigned *domain* adapter
    # may carry built-in defaults, so it is never downgraded here.
    config: dict[str, Any] = {}
    if adapter is not None:
        config = _adapter_config(db, adapter, task.project_id)
        # A configuration stored on the website itself wins over the project
        # wide configuration: two directories of the same project have
        # different forms.  The ``adapter`` marker prevents a stale website
        # configuration from being applied to another adapter.
        site_config = website.adapter_config if isinstance(website.adapter_config, dict) else {}
        if site_config and (
            not site_config.get("adapter") or str(site_config.get("adapter")) == adapter.key
        ):
            config = {**config, **site_config}
        if (
            adapter.automatable
            and not adapter.domains
            and adapter.required_config
            and not config
        ):
            adapter = None
            config = {}

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
            result={"submission_pack": pack},
        )

    if not adapter.automatable:
        pack = _manual_pack(website, opportunity, project, profile, adapter)
        _store_manual_pack(db, task, website, pack)
        return TaskOutcome(
            status=RESULT_WAITING_USER,
            message=f"Adapter '{adapter.name}' requires manual completion. A submission pack was prepared.",
            error="Adapter is not automatable",
            requires_human=True,
            result={"submission_pack": pack},
        )

    project_settings = project.settings.__dict__ if project and project.settings else {}
    evidence_dir = settings.managed_files_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    from app.services.execution import get_settings as get_execution_settings

    execution_settings = get_execution_settings(db)

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
        should_cancel=lambda: _cancel_requested(db, task.id),
        timeout_seconds=execution_settings.task_timeout_seconds,
        headless=execution_settings.headless,
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
    elif result.status in (RESULT_WAITING_USER, RESULT_WAITING_APPROVAL):
        # A task that waits for a human always carries the pack with the
        # values the operator needs - no matter which adapter produced it.
        evidence = dict(result.evidence or {})
        if "submission_pack" not in evidence:
            adapter_for_pack = adapter if adapter.automatable else get_adapter("generic_manual")
            evidence["submission_pack"] = _manual_pack(
                website, opportunity, project, profile, adapter_for_pack
            )
            result.evidence = evidence
            outcome = _outcome_from_result(result)
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
