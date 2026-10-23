"""The details a backlink submission needs, kept in one place.

A directory asks for the same company facts over and over: name, description,
e-mail, phone, website, address, categories, anchors.  Typing them for every
website would be duplication, so they live in the **business profile** of the
project - this module reads them for the project page and writes them back
there.

The project itself only owns what is really project specific: the target
website, the landing pages and (through the profile) the anchor texts.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import BusinessProfile, Opportunity, Project, TargetWebsite, User
from app.services import site_details as details_service

#: The fields a directory asks for most of the time.  Used when the project has
#: no website yet, so the page still shows a meaningful completeness.
DEFAULT_REQUIRED: tuple[str, ...] = (
    "company_name",
    "description",
    "email",
    "website",
    "categories",
)


def _profile_of(db: Session, project: Project) -> BusinessProfile | None:
    if not project.business_profile_id:
        return None
    profile = db.get(BusinessProfile, project.business_profile_id)
    if profile is None or profile.deleted_at is not None:
        return None
    return profile


def _landing_pages(db: Session, project: Project) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            select(TargetWebsite)
            .where(TargetWebsite.project_id == project.id, TargetWebsite.is_active.is_(True))
            .order_by(TargetWebsite.created_at)
        )
        .scalars()
        .all()
    )
    return [{"id": row.id, "name": row.name, "url": row.url, "kind": row.kind} for row in rows]


def _required_fields(db: Session, project: Project) -> list[str]:
    """The union of what the websites of the project ask for."""
    opportunities = (
        db.execute(
            select(Opportunity).where(
                Opportunity.project_id == project.id,
                Opportunity.deleted_at.is_(None),
            )
        )
        .scalars()
        .all()
    )
    names: list[str] = []
    for opportunity in opportunities:
        for name in details_service.required_field_names(db, opportunity):
            if name not in names:
                names.append(name)
    if not names:
        names = list(DEFAULT_REQUIRED)
    return names


def _available(db: Session, project: Project, profile: BusinessProfile | None, field: str) -> bool:
    """Is the value available - from the profile or from a stored submission?"""
    if details_service.derivable_from_profile(profile, field):
        return True
    opportunities = (
        db.execute(
            select(Opportunity).where(
                Opportunity.project_id == project.id,
                Opportunity.deleted_at.is_(None),
            )
        )
        .scalars()
        .all()
    )
    for opportunity in opportunities:
        stored = details_service.get_details(db, opportunity.id)
        if stored is not None and details_service.is_filled(stored, field):
            return True
    return False


def read(db: Session, project: Project) -> dict[str, Any]:
    """Everything the project page shows (and sends back when it saves)."""
    profile = _profile_of(db, project)
    required = _required_fields(db, project)
    filled = [name for name in required if _available(db, project, profile, name)]
    missing = [name for name in required if name not in filled]

    shared_with = 0
    notes: list[str] = []
    if profile is not None:
        shared_with = int(
            db.execute(
                select(func.count())
                .select_from(Project)
                .where(
                    Project.business_profile_id == profile.id,
                    Project.deleted_at.is_(None),
                )
            ).scalar_one()
        )
        if shared_with > 1:
            notes.append(
                f"These details live in the business profile '{profile.name}' and are "
                f"shared with {shared_with - 1} other project(s). Saving them here gives "
                "this project its own copy - the other project stays untouched."
            )
    else:
        notes.append(
            "The project has no business profile yet - fill the details and they will be "
            "stored in a new one, so every website of this project can reuse them."
        )

    return {
        "profile_id": profile.id if profile else None,
        "profile_name": profile.name if profile else None,
        "shared_with_projects": shared_with,
        "target_website": project.target_website,
        "landing_pages": _landing_pages(db, project),
        "company_name": profile.name if profile else "",
        "description": profile.description if profile else "",
        "email": (profile.contact_email or "") if profile else "",
        "phone": (profile.contact_phone or "") if profile else "",
        "website": profile.primary_website if profile else project.target_website,
        "address": profile.address if profile else "",
        "city": profile.city if profile else "",
        "state": profile.state if profile else "",
        "country": profile.country if profile else "",
        "postal_code": profile.postal_code if profile else "",
        "categories": list(profile.preferred_categories or []) if profile else [],
        "founded_year": profile.founded_year if profile else None,
        "employee_count": profile.employee_count if profile else None,
        "anchors": list(profile.preferred_anchors or []) if profile else [],
        "required": required,
        "filled": filled,
        "missing": missing,
        "notes": notes,
    }


def _normalise_website(value: str) -> str:
    value = value.strip()
    if not value:
        return value
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    return value.rstrip("/")


def _copy_profile(db: Session, profile: BusinessProfile, user: User) -> BusinessProfile:
    """Give a project its own copy of a shared profile.

    A project must never change the details of another project behind its
    back.  The first save of a shared profile therefore copies every value
    into a new profile and points the project at the copy.
    """
    clone = BusinessProfile(
        owner_id=profile.owner_id or user.id,
        name=profile.name,
        primary_website=profile.primary_website,
        description=profile.description,
        industry=profile.industry,
        niche=profile.niche,
        target_countries=list(profile.target_countries or []),
        target_regions=list(profile.target_regions or []),
        contact_email=profile.contact_email,
        contact_phone=profile.contact_phone,
        social_profiles=dict(profile.social_profiles or {}),
        logo_path=profile.logo_path,
        preferred_language=profile.preferred_language,
        business_descriptions=list(profile.business_descriptions or []),
        author_bios=list(profile.author_bios or []),
        keywords=list(profile.keywords or []),
        primary_landing_pages=list(profile.primary_landing_pages or []),
        secondary_landing_pages=list(profile.secondary_landing_pages or []),
        preferred_anchors=list(profile.preferred_anchors or []),
        anchor_preferences=dict(profile.anchor_preferences or {}),
        preferred_categories=list(profile.preferred_categories or []),
        excluded_domains=list(profile.excluded_domains or []),
        excluded_categories=list(profile.excluded_categories or []),
        target_domains=list(profile.target_domains or []),
        monthly_target=profile.monthly_target,
        campaign_goals=profile.campaign_goals,
        address=profile.address,
        city=profile.city,
        state=profile.state,
        country=profile.country,
        postal_code=profile.postal_code,
        founded_year=profile.founded_year,
        employee_count=profile.employee_count,
    )
    db.add(clone)
    db.flush()
    return clone


def write(db: Session, project: Project, user: User, payload: dict[str, Any]) -> dict[str, Any]:
    """Store the details of the project - in its business profile.

    The profile is created when the project has none.  Only the values that are
    sent are changed, so the page can save a single field without wiping the
    rest.
    """
    profile = _profile_of(db, project)

    if profile is None:
        company = str(payload.get("company_name") or "").strip() or project.name
        website = str(payload.get("website") or "").strip() or project.target_website
        profile = BusinessProfile(
            owner_id=user.id,
            name=company,
            primary_website=_normalise_website(website),
        )
        db.add(profile)
        db.flush()
        project.business_profile_id = profile.id
    else:
        shared = int(
            db.execute(
                select(func.count())
                .select_from(Project)
                .where(
                    Project.business_profile_id == profile.id,
                    Project.deleted_at.is_(None),
                )
            ).scalar_one()
        )
        if shared > 1:
            # Never edit the profile another project is still using.
            profile = _copy_profile(db, profile, user)
            project.business_profile_id = profile.id

    # The stored details of the opportunities copy these values.  Remember the
    # old ones so they can be refreshed - a value typed for one website stays.
    detail_before = {
        attribute: getattr(profile, attribute, None)
        for attribute in details_service.PROFILE_TO_DETAIL
    }

    mapping = {
        "company_name": "name",
        "description": "description",
        "email": "contact_email",
        "phone": "contact_phone",
        "website": "primary_website",
        "address": "address",
        "city": "city",
        "state": "state",
        "country": "country",
        "postal_code": "postal_code",
        "categories": "preferred_categories",
        "founded_year": "founded_year",
        "employee_count": "employee_count",
        "anchors": "preferred_anchors",
    }
    for field, attribute in mapping.items():
        if field not in payload or payload[field] is None:
            continue
        value = payload[field]
        if field in ("website", "primary_website") and isinstance(value, str):
            value = _normalise_website(value)
        if field in ("categories", "anchors"):
            value = [str(item).strip() for item in value if str(item).strip()]
        setattr(profile, attribute, value)

    if payload.get("target_website"):
        project.target_website = _normalise_website(str(payload["target_website"]))
    project.version += 1
    db.flush()
    details_service.refresh_derived_details(db, profile, detail_before)

    db.commit()
    db.refresh(project)
    db.refresh(profile)
    return read(db, project)
