"""Website registry / opportunity services."""

from __future__ import annotations

import urllib.parse
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.models import Opportunity, Project, Website


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return urllib.parse.urlunparse(
        (parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.params, parsed.query, "")
    )


def extract_domain(url: str) -> str:
    parsed = urllib.parse.urlparse(url if "://" in url else f"https://{url}")
    host = (parsed.netloc or "").split("@")[-1].split(":")[0].lower()
    return host.removeprefix("www.")


def canonical_website_key(url: str) -> tuple[str, str]:
    """Deduplication key: registrable domain + normalised path."""
    normalized = normalize_url(url)
    return extract_domain(normalized), normalized


def find_website(db: Session, url: str) -> Website | None:
    domain, normalized = canonical_website_key(url)
    stmt = select(Website).where(Website.domain == domain)
    for website in db.execute(stmt).scalars().all():
        if normalize_url(website.opportunity_url) == normalized:
            return website
    # Fall back to the same domain when the exact URL differs
    return db.execute(
        select(Website).where(Website.domain == domain).order_by(Website.score.desc())
    ).scalars().first()


def create_website(
    db: Session,
    *,
    url: str,
    name: str = "",
    category: str = "BUSINESS_DIRECTORY",
    discovery_source: str = "manual",
    discovery_provider: str | None = None,
    description: str | None = None,
    language: str | None = None,
    region: str | None = None,
    submission_method: str = "UNKNOWN",
    registration_required: bool | None = None,
    requires_approval: bool | None = None,
    adapter_id: str | None = None,
    anchor_text: str | None = None,
    contact_email: str | None = None,
    score: float = 0.0,
    score_breakdown: dict[str, Any] | None = None,
    notes: str | None = None,
    is_manual: bool = False,
    discovery_run_id: str | None = None,
) -> tuple[Website, bool]:
    normalized = normalize_url(url)
    domain = extract_domain(normalized)
    existing = db.execute(
        select(Website).where(Website.domain == domain, Website.opportunity_url == normalized)
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False
    website = Website(
        name=name or domain,
        domain=domain,
        opportunity_url=normalized,
        category=category,
        discovery_source=discovery_source,
        discovery_provider=discovery_provider,
        description=description,
        language=language,
        region=region,
        submission_method=submission_method,
        registration_required=registration_required,
        requires_approval=requires_approval,
        adapter_id=adapter_id,
        anchor_text=anchor_text,
        contact_email=contact_email,
        score=score,
        score_breakdown=score_breakdown or {},
        notes=notes,
        is_manual=is_manual,
        discovery_run_id=discovery_run_id,
        status="DISCOVERED",
        backlink_status="PENDING",
    )
    db.add(website)
    db.flush()
    return website, True


def link_to_project(
    db: Session,
    project: Project,
    website: Website,
    *,
    target_landing_page: str | None = None,
    status_value: str = "NEEDS_REVIEW",
) -> tuple[Opportunity, bool]:
    existing = db.execute(
        select(Opportunity).where(
            Opportunity.project_id == project.id, Opportunity.website_id == website.id
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.deleted_at is not None:
            # The website was removed from the project before - adding it
            # again restores the old row instead of hiding a duplicate.
            existing.deleted_at = None
            existing.status = "NEEDS_REVIEW"
            db.flush()
            return existing, True
        return existing, False
    opportunity = Opportunity(
        project_id=project.id,
        website_id=website.id,
        target_landing_page=target_landing_page,
        status=status_value,
    )
    db.add(opportunity)
    db.flush()
    return opportunity, True


def is_excluded(db: Session, domain: str, excluded_domains: Iterable[str]) -> bool:
    domain = domain.lower()
    for excluded in excluded_domains or []:
        excluded = (excluded or "").lower().strip().removeprefix("www.")
        if not excluded:
            continue
        if domain == excluded or domain.endswith("." + excluded):
            return True
    return False


def website_excluded_now(website: Website) -> bool:
    if website.excluded_until is None:
        return False
    return website.excluded_until > utcnow()


def opportunity_to_dict(opportunity: Opportunity, website: Website) -> dict[str, Any]:
    data = {
        "id": opportunity.id,
        "project_id": opportunity.project_id,
        "website_id": website.id,
        "name": website.name,
        "domain": website.domain,
        "opportunity_url": website.opportunity_url,
        "category": website.category,
        "discovery_source": website.discovery_source,
        "discovery_provider": website.discovery_provider,
        "language": website.language,
        "region": website.region,
        "score": website.score,
        "score_breakdown": website.score_breakdown or None,
        "status": opportunity.status,
        "submission_method": website.submission_method,
        "registration_required": website.registration_required,
        "requires_approval": website.requires_approval,
        "adapter_id": website.adapter_id,
        "anchor_text": website.anchor_text,
        "description": website.description,
        "notes": opportunity.notes or website.notes,
        "contact_email": website.contact_email,
        "target_landing_page": opportunity.target_landing_page,
        "last_checked_at": website.last_checked_at,
        "last_result": website.last_result,
        "backlink_status": website.backlink_status,
        "error_detail": website.error_detail,
        "duplicate_of": website.duplicate_of,
        "excluded_until": website.excluded_until,
        "created_at": website.created_at,
        "updated_at": website.updated_at,
        "version": website.version,
    }
    return data
