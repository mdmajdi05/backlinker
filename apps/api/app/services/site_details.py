"""Structured details of a submission site.

A directory asks for a handful of values (company name, website, description,
...).  This module stores them **per opportunity**, reports which of them are
still missing and fills the empty ones from the business profile of the
project.

Two rules apply everywhere:

* Nothing is invented.  A value is only written when it exists in the
  business profile (or when the operator entered it).
* The assistant is optional.  Every helper of the AI layer has a
  deterministic fallback, so the generation always returns a usable result -
  even without a configured provider.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.models import (
    AutomationAdapter,
    BusinessProfile,
    Opportunity,
    OpportunityCategory,
    Project,
    SiteDetails,
    Website,
)
from app.services import ai as ai_service

#: The fixed fields a submission form may ask for.
FIXED_FIELDS: tuple[str, ...] = (
    "company_name",
    "description",
    "email",
    "phone",
    "website",
    "address",
    "city",
    "state",
    "country",
    "postal_code",
    "logo_path",
    "categories",
    "founded_year",
    "employee_count",
)

#: Human readable labels of the fixed fields.
FIELD_LABELS: dict[str, str] = {
    "company_name": "Company name",
    "description": "Description",
    "email": "E-mail address",
    "phone": "Phone number",
    "website": "Website",
    "address": "Street address",
    "city": "City",
    "state": "State / region",
    "country": "Country",
    "postal_code": "Postal code",
    "logo_path": "Logo",
    "categories": "Categories",
    "founded_year": "Year founded",
    "employee_count": "Number of employees",
}

#: Registry field names that address one of the fixed fields.
FIELD_ALIASES: dict[str, str] = {
    "name": "company_name",
    "company": "company_name",
    "company_name": "company_name",
    "business_name": "company_name",
    "title": "company_name",
    "description": "description",
    "summary": "description",
    "about": "description",
    "email": "email",
    "contact_email": "email",
    "mail": "email",
    "phone": "phone",
    "telephone": "phone",
    "contact_phone": "phone",
    "website": "website",
    "url": "website",
    "primary_website": "website",
    "homepage": "website",
    "address": "address",
    "street": "address",
    "street_address": "address",
    "city": "city",
    "town": "city",
    "state": "state",
    "region": "state",
    "address_region": "state",
    "country": "country",
    "postal_code": "postal_code",
    "zip": "postal_code",
    "zip_code": "postal_code",
    "logo": "logo_path",
    "logo_path": "logo_path",
    "logo_url": "logo_path",
    "categories": "categories",
    "category": "categories",
    "founded_year": "founded_year",
    "year_founded": "founded_year",
    "employee_count": "employee_count",
    "employees": "employee_count",
    "number_of_employees": "employee_count",
}

#: The fields that are stored as text and are never ``NULL``.
_TEXT_FIELDS = ("company_name", "description")


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def normalize_field(field: str) -> str:
    """Normalise a registry field name (``Address-Region`` -> ``address_region``)."""
    return (field or "").strip().lower().replace("-", "_").replace(" ", "_")


def target_field(field: str) -> str:
    """The fixed field a registry field addresses (or the field itself)."""
    normalized = normalize_field(field)
    return FIELD_ALIASES.get(normalized, normalized)


def label_for(field: str) -> str:
    """A human readable label of a field."""
    target = target_field(field)
    if target in FIELD_LABELS:
        return FIELD_LABELS[target]
    return target.replace("_", " ").capitalize() or field


def _clean_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def is_filled(details: SiteDetails | None, field: str) -> bool:
    """Is the field filled for these details?

    A field counts as filled when it holds a non empty value.  Fields without
    a fixed counterpart (a ``pitch`` for example) are looked up in ``extra``.
    """
    if details is None:
        return False
    target = target_field(field)
    if target in FIXED_FIELDS:
        value = getattr(details, target, None)
    else:
        extra = details.extra or {}
        value = extra.get(target)
        if value in (None, ""):
            value = extra.get(normalize_field(field))
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple, set)):
        return bool(value)
    return True


def field_value(details: SiteDetails | None, field: str) -> Any:
    """The value of a field (used by the submission adapters)."""
    if details is None:
        return None
    target = target_field(field)
    if target in FIXED_FIELDS:
        return getattr(details, target, None)
    extra = details.extra or {}
    value = extra.get(target)
    if value in (None, ""):
        value = extra.get(normalize_field(field))
    return value


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------
def get_details(db: Session, opportunity_id: str) -> SiteDetails | None:
    """The stored details of an opportunity (``None`` when there are none)."""
    return db.execute(
        select(SiteDetails).where(SiteDetails.opportunity_id == opportunity_id)
    ).scalar_one_or_none()


def apply_values(details: SiteDetails, values: dict[str, Any]) -> SiteDetails:
    """Write the supplied values into the record.

    Only the keys that are present are changed.  A field that is edited by
    hand is no longer reported as machine generated.
    """
    for key, value in values.items():
        if key == "extra":
            extra = dict(details.extra or {})
            extra.update(value or {})
            details.extra = extra
            for name in value or {}:
                _forget_generated(details, normalize_field(name))
            continue
        if key not in FIXED_FIELDS:
            continue
        if key == "categories":
            details.categories = [str(item).strip() for item in (value or []) if str(item).strip()]
        elif key in ("founded_year", "employee_count"):
            setattr(details, key, _as_int(value))
        else:
            text = _clean_text(value)
            setattr(details, key, text if key in _TEXT_FIELDS else (text or None))
        _forget_generated(details, key)
    details.updated_at = utcnow()
    return details


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def generated_map(details: SiteDetails | None) -> dict[str, Any]:
    """The generated fields as a map.

    Older rows stored a plain list of field names - both shapes are accepted so
    that an upgraded database keeps working.
    """
    raw = getattr(details, "generated", None)
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, (list, tuple, set)):
        return {str(item): "generated" for item in raw}
    return {}


def _forget_generated(details: SiteDetails, field: str) -> None:
    """A field that was edited by hand is no longer machine generated."""
    details.generated = {
        key: value for key, value in generated_map(details).items() if key != field
    }


def upsert_details(
    db: Session, opportunity: Opportunity, values: dict[str, Any]
) -> SiteDetails:
    """Create or update the details of an opportunity."""
    details = get_details(db, opportunity.id)
    if details is None:
        details = SiteDetails(
            opportunity_id=opportunity.id,
            project_id=opportunity.project_id,
            website_id=opportunity.website_id,
        )
        db.add(details)
    apply_values(details, values)
    db.commit()
    db.refresh(details)
    return details


def delete_details(db: Session, opportunity_id: str) -> bool:
    """Delete the details of an opportunity. Returns ``True`` when a row was removed."""
    details = get_details(db, opportunity_id)
    if details is None:
        return False
    db.delete(details)
    db.commit()
    return True


# --------------------------------------------------------------------------
# Required fields
# --------------------------------------------------------------------------
def _adapter_row(db: Session, website: Website | None) -> AutomationAdapter | None:
    """The automation adapter row of a website (if there is one)."""
    if website is None:
        return None
    if website.adapter_id:
        row = db.get(AutomationAdapter, website.adapter_id)
        if row is not None:
            return row
    return None


def required_field_names(db: Session, opportunity: Opportunity) -> list[str]:
    """The fields a submission needs for this opportunity.

    The ``required_fields`` of the category and the ``required_user_fields``
    of the automation adapter are merged and de-duplicated.  The order of the
    registry is preserved.
    """
    website = db.get(Website, opportunity.website_id)
    names: list[str] = []

    category = (website.category if website else "") or ""
    if category:
        row = db.execute(
            select(OpportunityCategory).where(OpportunityCategory.key == category)
        ).scalar_one_or_none()
        if row is not None:
            names.extend(str(item) for item in (row.required_fields or []))

    adapter = _adapter_row(db, website)
    if adapter is not None:
        names.extend(str(item) for item in (adapter.required_user_fields or []))

    unique: list[str] = []
    for name in names:
        cleaned = normalize_field(name)
        if cleaned and cleaned not in unique:
            unique.append(cleaned)
    return unique


def required_details(
    db: Session, opportunity: Opportunity, details: SiteDetails | None
) -> dict[str, Any]:
    """Which details are required and which of them are still missing.

    ``required`` and ``missing`` carry the names the registry uses (``name``
    for example), ``labels`` the human readable version of every name.
    """
    required = required_field_names(db, opportunity)
    missing = [name for name in required if not is_filled(details, name)]
    return {
        "required": required,
        "missing": missing,
        "complete": not missing,
        "labels": {name: label_for(name) for name in required},
    }


def details_payload(
    db: Session, opportunity: Opportunity, details: SiteDetails | None
) -> dict[str, Any]:
    """The API payload of the details of an opportunity.

    The payload also carries the required and the missing fields so a client
    does not have to ask for them a second time.
    """
    required = required_details(db, opportunity, details)
    payload: dict[str, Any] = {
        "id": details.id if details is not None else None,
        "opportunity_id": opportunity.id,
        "project_id": opportunity.project_id,
        "website_id": opportunity.website_id,
        "company_name": None,
        "description": None,
        "email": None,
        "phone": None,
        "website": None,
        "address": None,
        "city": None,
        "state": None,
        "country": None,
        "postal_code": None,
        "logo_path": None,
        "categories": [],
        "founded_year": None,
        "employee_count": None,
        "extra": {},
        "generated": {},
        "updated_at": None,
    }
    if details is not None:
        payload.update(
            {
                "id": details.id,
                "company_name": details.company_name or None,
                "description": details.description or None,
                "email": details.email,
                "phone": details.phone,
                "website": details.website,
                "address": details.address,
                "city": details.city,
                "state": details.state,
                "country": details.country,
                "postal_code": details.postal_code,
                "logo_path": details.logo_path,
                "categories": list(details.categories or []),
                "founded_year": details.founded_year,
                "employee_count": details.employee_count,
                "extra": dict(details.extra or {}),
                "generated": generated_map(details),
                "updated_at": details.updated_at,
            }
        )
    payload.update(required)
    return payload


# --------------------------------------------------------------------------
# Generation from the business profile
# --------------------------------------------------------------------------
def _profile_of(db: Session, opportunity: Opportunity) -> BusinessProfile | None:
    """The business profile of the project of the opportunity."""
    project = db.get(Project, opportunity.project_id)
    if project is None or not project.business_profile_id:
        return None
    return db.get(BusinessProfile, project.business_profile_id)


def profile_payload(profile: BusinessProfile | None) -> dict[str, Any]:
    """The profile as the AI layer expects it."""
    if profile is None:
        return {}
    return {
        "name": profile.name,
        "primary_website": profile.primary_website,
        "description": profile.description,
        "industry": profile.industry,
        "niche": profile.niche,
        "contact_email": profile.contact_email,
        "contact_phone": profile.contact_phone,
        "business_descriptions": list(profile.business_descriptions or []),
        "author_bios": list(profile.author_bios or []),
        "keywords": list(profile.keywords or []),
        "preferred_anchors": list(profile.preferred_anchors or []),
        "preferred_categories": list(profile.preferred_categories or []),
        "target_countries": list(profile.target_countries or []),
        "target_regions": list(profile.target_regions or []),
    }


def _listing_category(db: Session, website: Website | None) -> tuple[str, bool]:
    """The category the business is listed under.

    The registry category wins when it is known.  Only when the registry does
    not know the category the AI layer classifies the target page - and its
    deterministic fallback is used when no provider is configured.

    Returns ``(category, classified)``.
    """
    category = ((website.category if website else "") or "").strip().upper()
    if category and category not in ("CUSTOM", "UNKNOWN"):
        return category, False
    keys = [
        row.key
        for row in db.execute(
            select(OpportunityCategory).where(OpportunityCategory.is_active.is_(True))
        ).scalars()
    ]
    if not keys:
        return category, False
    text = " ".join(
        part
        for part in (
            (website.name if website else ""),
            (website.description if website else ""),
        )
        if part
    )
    result = ai_service.classify_opportunity(
        text, (website.opportunity_url if website else ""), keys
    )
    classified = str(result.get("category") or category)
    return classified, bool(result.get("ai_generated"))


def _profile_has_content(profile: BusinessProfile | None) -> bool:
    """Does the profile carry anything that can be turned into a description?"""
    if profile is None:
        return False
    return any(
        [
            profile.name,
            profile.description,
            profile.industry,
            profile.niche,
            profile.business_descriptions,
            profile.keywords,
        ]
    )


def generate_details(
    db: Session, opportunity: Opportunity
) -> tuple[SiteDetails, list[str], str]:
    """Fill the empty detail fields from the business profile.

    Returns ``(details, generated_fields, source)``.  ``source`` is ``ai``
    when the assistant produced the text and ``profile`` when the values were
    copied from the profile.  Facts that are not part of the profile are never
    written - a missing phone number stays missing.
    """
    profile = _profile_of(db, opportunity)
    website = db.get(Website, opportunity.website_id)
    project = db.get(Project, opportunity.project_id)
    payload = profile_payload(profile)
    category, classified = _listing_category(db, website)

    details = get_details(db, opportunity.id)
    if details is None:
        details = SiteDetails(
            opportunity_id=opportunity.id,
            project_id=opportunity.project_id,
            website_id=opportunity.website_id,
        )
        db.add(details)

    generated: list[str] = []
    sources: dict[str, str] = {}
    source = "profile"

    def fill(name: str, value: Any, origin: str = "profile") -> None:
        """Write a value and remember that the assistant produced it."""
        setattr(details, name, value)
        generated.append(name)
        sources[name] = origin

    if not details.company_name and profile and profile.name:
        fill("company_name", profile.name.strip())

    if not details.description and _profile_has_content(profile):
        text = ai_service.draft_directory_description(payload, category)
        if _clean_text(text):
            origin = "ai" if getattr(text, "ai_generated", False) else "profile"
            fill("description", _clean_text(text), origin)
            if origin == "ai":
                source = "ai"

    if not details.email and profile and profile.contact_email:
        fill("email", profile.contact_email.strip())
    if not details.phone and profile and profile.contact_phone:
        fill("phone", profile.contact_phone.strip())
    if not details.website and profile and profile.primary_website:
        fill("website", profile.primary_website.strip())
    if not details.logo_path and profile and profile.logo_path:
        fill("logo_path", profile.logo_path.strip())
    if not details.categories and profile and profile.preferred_categories:
        categories = [str(item).strip() for item in profile.preferred_categories if str(item).strip()]
        if categories:
            fill("categories", categories)
    if not details.address and profile and profile.address:
        fill("address", profile.address.strip())
    if not details.city and profile and profile.city:
        fill("city", profile.city.strip())
    if not details.postal_code and profile and profile.postal_code:
        fill("postal_code", profile.postal_code.strip())
    if not details.country and profile:
        country = (profile.country or "").strip()
        if not country and profile.target_countries:
            country = str(profile.target_countries[0]).strip()
        if country:
            fill("country", country)
    if not details.state and profile:
        region = (profile.state or "").strip()
        if not region and profile.target_regions:
            region = str(profile.target_regions[0]).strip()
        if region:
            fill("state", region)
    if not details.founded_year and profile and profile.founded_year:
        fill("founded_year", int(profile.founded_year))
    if not details.employee_count and profile and profile.employee_count:
        fill("employee_count", int(profile.employee_count))

    extra = dict(details.extra or {})
    if not extra.get("anchor_text"):
        landing = (
            opportunity.target_landing_page
            or (project.target_website if project else "")
            or (profile.primary_website if profile else "")
        )
        anchors = ai_service.suggest_anchors(payload, landing, 1)
        if anchors:
            origin = "ai" if getattr(anchors, "ai_generated", False) else "profile"
            extra["anchor_text"] = str(anchors[0])
            generated.append("anchor_text")
            sources["anchor_text"] = origin
            if origin == "ai":
                source = "ai"
    if not extra.get("category") and category:
        extra["category"] = category
        if classified:
            generated.append("category")
            sources["category"] = "ai"
            source = "ai"
    details.extra = extra

    details.generated = {**generated_map(details), **sources}
    details.updated_at = utcnow()
    db.commit()
    db.refresh(details)
    return details, generated, source


# --------------------------------------------------------------------------
# The gap report
# --------------------------------------------------------------------------
#: The business profile attribute a field can be derived from.
PROFILE_SOURCE: dict[str, str] = {
    "company_name": "name",
    "email": "contact_email",
    "phone": "contact_phone",
    "website": "primary_website",
    "logo_path": "logo_path",
    "categories": "preferred_categories",
    "address": "address",
    "city": "city",
    "state": "state",
    "country": "country",
    "postal_code": "postal_code",
    "founded_year": "founded_year",
    "employee_count": "employee_count",
}

#: Business-profile attribute -> the field of a stored detail record.
#: When the profile changes, these values are copied into the detail records
#: that still carry the old value (a value typed for one website is kept).
PROFILE_TO_DETAIL: dict[str, str] = {
    "name": "company_name",
    "description": "description",
    "contact_email": "email",
    "contact_phone": "phone",
    "primary_website": "website",
    "address": "address",
    "city": "city",
    "state": "state",
    "country": "country",
    "postal_code": "postal_code",
    "founded_year": "founded_year",
    "employee_count": "employee_count",
    "preferred_categories": "categories",
    "logo_path": "logo_path",
}


def _comparable(value: Any) -> Any:
    """A value that can be compared across the database and the profile."""
    if value is None:
        return ""
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str):
        return value.strip()
    return value


def refresh_derived_details(
    db: Session, profile: BusinessProfile, before: dict[str, Any]
) -> int:
    """Re-align the detail records with a changed business profile.

    A detail record belongs to one opportunity, so the operator may adapt it to
    one website.  Therefore only the values that still carry the old profile
    value (or are empty) are updated - a value typed for a website is never
    overwritten.  Returns the number of changed detail rows.
    """
    project_ids = list(
        db.execute(
            select(Project.id).where(Project.business_profile_id == profile.id)
        ).scalars().all()
    )
    if not project_ids:
        return 0

    rows = (
        db.execute(select(SiteDetails).where(SiteDetails.project_id.in_(project_ids)))
        .scalars()
        .all()
    )
    changed_rows = 0
    for row in rows:
        changed = False
        for attribute, field in PROFILE_TO_DETAIL.items():
            old = _comparable(before.get(attribute))
            new = _comparable(getattr(profile, attribute, None))
            if old == new:
                continue
            current = _comparable(getattr(row, field, None))
            if current in ("", ()) or current == old:
                setattr(row, field, getattr(profile, attribute, None))
                changed = True
        if changed:
            changed_rows += 1
    db.flush()
    return changed_rows


#: The plain reason why a field cannot be derived from the business profile.
NOT_DERIVABLE_REASON: dict[str, str] = {
    "company_name": "the business profile has no company name",
    "description": "the business profile has no description that could be reused",
    "email": "the business profile has no e-mail address",
    "phone": "the business profile has no phone number",
    "website": "the business profile has no website",
    "address": "the business profile has no street address",
    "city": "the business profile has no city",
    "state": "the business profile has no state or region",
    "country": "the business profile has no target country",
    "postal_code": "the business profile has no postal code",
    "logo_path": "the business profile has no logo",
    "categories": "the business profile has no preferred categories",
    "founded_year": "the business profile has no year founded",
    "employee_count": "the business profile has no number of employees",
}


def derivable_from_profile(profile: BusinessProfile | None, field: str) -> bool:
    """Could this field be filled from the business profile?

    The rules are the ones of :func:`generate_details`: a field is derivable
    when the profile really carries a value for it.  Everything else stays
    missing - nothing is invented.
    """
    if profile is None:
        return False
    fixed = target_field(field)
    if fixed == "description":
        return _profile_has_content(profile)
    if fixed in ("country", "state"):
        own = getattr(profile, fixed, "")
        if str(own or "").strip():
            return True
        fallback = profile.target_countries if fixed == "country" else profile.target_regions
        return bool(fallback)
    attribute = PROFILE_SOURCE.get(fixed)
    if attribute is None:
        return False
    value = getattr(profile, attribute, None)
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return bool(str(value or "").strip())


def not_derivable_reason(profile: BusinessProfile | None, field: str) -> str:
    """Why this field cannot be derived from the business profile."""
    if profile is None:
        return "the project has no business profile"
    reason = NOT_DERIVABLE_REASON.get(target_field(field))
    if reason:
        return reason
    return f"the business profile cannot provide '{label_for(field)}'"


def gap_report(db: Session, opportunity: Opportunity) -> dict[str, Any]:
    """Which details an opportunity still misses.

    The report answers three questions:

    * which details does the target site ask for (``required``),
    * which of them are filled already (``filled``) and which are still
      missing (``missing``),
    * which of the missing ones the business profile could provide
      (``derivable``) and which ones it cannot (``not_derivable``) - the
      latter with a plain reason.
    """
    details = get_details(db, opportunity.id)
    required = required_field_names(db, opportunity)
    filled = [name for name in required if is_filled(details, name)]
    missing = [name for name in required if not is_filled(details, name)]

    profile = _profile_of(db, opportunity)
    derivable: list[str] = []
    not_derivable: list[dict[str, str]] = []
    for name in missing:
        if derivable_from_profile(profile, name):
            derivable.append(name)
        else:
            not_derivable.append(
                {
                    "field": name,
                    "label": label_for(name),
                    "reason": not_derivable_reason(profile, name),
                }
            )

    return {
        "required": required,
        "filled": filled,
        "missing": missing,
        "derivable": derivable,
        "not_derivable": not_derivable,
        "source": "profile" if profile is not None else "none",
    }
