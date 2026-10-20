"""Discovery task runner.

Turns the raw output of a discovery provider into persisted rows:

* every candidate is de-duplicated (same domain + URL -> duplicate),
* excluded domains are rejected (the exclusion list of the profile and
  websites that are on a temporary exclusion list),
* every accepted candidate is scored with :mod:`app.services.scoring`,
* the counters of the :class:`~app.db.models.DiscoveryRun` are updated and
  the progress is published as task events.

Nothing is fabricated: the counters describe what really happened and the
score only contains values that were observed.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.base import utcnow
from app.db.models import (
    BusinessProfile,
    DiscoveryRun,
    IntegrationCredential,
    Project,
    Task,
    Website,
)
from app.services.discovery.base import (
    DiscoveredSite,
    DiscoveryCriteria,
    DiscoveryProvider,
    get_provider,
)
from app.services.events import record_event
from app.services.opportunities import (
    create_website,
    extract_domain,
    is_excluded,
    link_to_project,
    normalize_url,
)
from app.services.scoring import score_opportunity
from app.workers.runner import TaskOutcome

log = get_logger(__name__)


def run_discovery_task(db: Session, task: Task) -> TaskOutcome:
    """Execute a discovery run and persist everything it found."""
    payload: dict[str, Any] = task.payload or {}
    run = _load_run(db, payload.get("run_id"))
    if run is None:
        message = "The discovery run of this task no longer exists."
        return TaskOutcome(status="FAILED", error=message, message=message, retryable=False)

    provider_key = str(payload.get("provider") or run.provider or "")
    provider = get_provider(provider_key)
    if provider is None:
        message = f"Unknown discovery provider: {provider_key}"
        _finish_run(db, run, status="FAILED", error=message)
        return TaskOutcome(status="FAILED", error=message, message=message, retryable=False)

    project = db.get(Project, run.project_id)
    profile = _profile_of(db, project)
    criteria = _build_criteria(db, run, payload, profile)
    criteria.config = _with_credentials(db, provider, criteria.config)

    available, reason = provider.available(criteria.config)
    if not available:
        message = reason or f"The provider '{provider.key}' is not configured."
        _finish_run(db, run, status="FAILED", error=message)
        record_event(
            db,
            "discovery.failed",
            message,
            level="ERROR",
            task_id=task.id,
            project_id=run.project_id,
            metadata={"provider": provider.key},
        )
        return TaskOutcome(status="FAILED", error=message, message=message, retryable=False)

    run.status = "RUNNING"
    run.started_at = utcnow()
    db.commit()
    record_event(
        db,
        "discovery.started",
        f"Discovery run started with {provider.key}",
        task_id=task.id,
        project_id=run.project_id,
        execution_environment=task.execution_environment,
        metadata={"provider": provider.key, "limit": criteria.limit},
    )

    try:
        sites = provider.discover(criteria)
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        _finish_run(db, run, status="FAILED", error=message)
        log.exception("discovery provider failed", extra={"extra_fields": {"provider": provider.key}})
        return TaskOutcome(status="FAILED", error=message, message=message, retryable=False)

    counters = _persist_sites(db, run, project, profile, provider, criteria, sites)
    run.discovered_count = counters["discovered"]
    run.new_count = counters["new"]
    run.duplicate_count = counters["duplicate"]
    run.rejected_count = counters["rejected"]
    run.status = "COMPLETED"
    run.finished_at = utcnow()
    run.error = None
    db.commit()

    result = {
        "run_id": run.id,
        "provider": provider.key,
        "discovered": counters["discovered"],
        "new": counters["new"],
        "duplicate": counters["duplicate"],
        "rejected": counters["rejected"],
    }
    record_event(
        db,
        "discovery.completed",
        (
            f"Discovery finished: {counters['new']} new, {counters['duplicate']} duplicate, "
            f"{counters['rejected']} rejected"
        ),
        level="SUCCESS",
        task_id=task.id,
        project_id=run.project_id,
        execution_environment=task.execution_environment,
        metadata=result,
    )
    return TaskOutcome(status="COMPLETED", result=result, message="Discovery completed.")


# -- helpers --------------------------------------------------------------


def _load_run(db: Session, run_id: Any) -> DiscoveryRun | None:
    """Load the discovery run of a task."""
    if not run_id:
        return None
    return db.get(DiscoveryRun, str(run_id))


def _profile_of(db: Session, project: Project | None) -> BusinessProfile | None:
    """The business profile of the project of a run."""
    if project is None or not project.business_profile_id:
        return None
    return db.get(BusinessProfile, project.business_profile_id)


def _build_criteria(
    db: Session,
    run: DiscoveryRun,
    payload: dict[str, Any],
    profile: BusinessProfile | None,
) -> DiscoveryCriteria:
    """Build the criteria of a run from the task payload and the run row."""
    raw: dict[str, Any] = payload.get("criteria") or {}
    config: dict[str, Any] = dict(run.config or {})
    config.update(raw.get("config") or {})
    excluded = [str(item) for item in (raw.get("excluded_domains") or [])]
    if profile is not None:
        excluded.extend(str(item) for item in (profile.excluded_domains or []))
    return DiscoveryCriteria(
        query=str(raw.get("query") or run.query or ""),
        keywords=[str(item) for item in (raw.get("keywords") or run.keywords or [])],
        countries=[str(item) for item in (raw.get("countries") or [])],
        language=raw.get("language"),
        category=raw.get("category"),
        limit=int(raw.get("limit") or run.requested_limit or 25),
        seeds=[str(item) for item in (raw.get("seeds") or [])],
        config=config,
        profile=profile,
        project_id=run.project_id,
        excluded_domains=excluded,
    )


def _with_credentials(
    db: Session, provider: DiscoveryProvider, config: dict[str, Any]
) -> dict[str, Any]:
    """Add the stored integration credential of a provider to the config."""
    merged = dict(config or {})
    if merged.get("api_key"):
        return merged
    credential = db.execute(
        select(IntegrationCredential)
        .where(IntegrationCredential.provider == provider.key)
        .order_by(IntegrationCredential.created_at)
    ).scalars().first()
    if credential is not None and credential.secret_encrypted:
        merged["api_key"] = credential.secret_encrypted
    return merged


def _finish_run(db: Session, run: DiscoveryRun, *, status: str, error: str | None) -> None:
    """Close a discovery run with a status."""
    run.status = status
    run.error = error
    run.finished_at = utcnow()
    db.commit()


def _persist_sites(
    db: Session,
    run: DiscoveryRun,
    project: Project | None,
    profile: BusinessProfile | None,
    provider: DiscoveryProvider,
    criteria: DiscoveryCriteria,
    sites: list[DiscoveredSite],
) -> dict[str, int]:
    """Persist the discovered sites and return the counters of the run."""
    counters = {"discovered": 0, "new": 0, "duplicate": 0, "rejected": 0}
    excluded = list(criteria.excluded_domains or [])
    if profile is not None:
        excluded.extend(str(item) for item in (profile.excluded_domains or []))
    limit = int(criteria.limit or provider.default_limit)
    seen: set[tuple[str, str]] = set()

    for site in sites[:limit]:
        counters["discovered"] += 1
        url = normalize_url(site.url)
        domain = extract_domain(url)
        if not domain or not url:
            counters["rejected"] += 1
            continue
        key = (domain, url)
        if key in seen:
            counters["duplicate"] += 1
            continue
        seen.add(key)
        if is_excluded(db, domain, excluded):
            counters["rejected"] += 1
            continue
        if _on_hold(db, domain):
            counters["rejected"] += 1
            continue
        existing = db.execute(
            select(Website).where(Website.domain == domain, Website.opportunity_url == url)
        ).scalar_one_or_none()
        if existing is not None:
            counters["duplicate"] += 1
            continue

        breakdown = _score(site, criteria, profile, domain)
        website, created = create_website(
            db,
            url=url,
            name=site.name or domain,
            category=site.category or "BUSINESS_DIRECTORY",
            discovery_source=provider.key,
            discovery_provider=provider.key,
            description=site.description,
            language=site.language,
            region=site.region,
            submission_method=site.submission_method or "UNKNOWN",
            registration_required=site.registration_required,
            requires_approval=site.requires_approval,
            anchor_text=site.anchor_text,
            contact_email=site.contact_email,
            score=float(breakdown["total"]),
            score_breakdown=breakdown,
            discovery_run_id=run.id,
        )
        if not created:
            counters["duplicate"] += 1
            continue
        if project is not None:
            link_to_project(
                db,
                project,
                website,
                target_landing_page=project.target_website,
                status_value="NEEDS_REVIEW",
            )
        counters["new"] += 1

    db.commit()
    return counters


def _on_hold(db: Session, domain: str) -> bool:
    """Is there a website of this domain that is excluded for now?"""
    row = db.execute(
        select(Website.id)
        .where(Website.domain == domain, Website.excluded_until.isnot(None))
        .where(Website.excluded_until > utcnow())
        .limit(1)
    ).scalars().first()
    return row is not None


def _score(
    site: DiscoveredSite,
    criteria: DiscoveryCriteria,
    profile: BusinessProfile | None,
    domain: str,
) -> dict[str, Any]:
    """Score a discovered site with the scoring engine."""
    raw = site.raw or {}
    keywords = criteria.keywords or []
    if profile is not None:
        keywords = keywords or [str(item) for item in (profile.keywords or [])]
    return score_opportunity(
        website_url=site.url,
        title=str(raw.get("page_title") or site.name or ""),
        description=str(raw.get("page_description") or site.description or ""),
        text=str(raw.get("page_text") or ""),
        category=site.category or "",
        domain=domain,
        profile=profile,
        profile_keywords=keywords,
        submission_method=site.submission_method or "UNKNOWN",
        registration_required=site.registration_required,
        requires_approval=site.requires_approval,
        language=site.language,
        region=site.region,
        contact_email=site.contact_email,
    )
