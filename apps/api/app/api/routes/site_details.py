"""Per site details endpoints.

The details of a submission (company name, website, description, ...) are
stored per opportunity, so the same website can be listed with different
values in two projects.  The endpoints also report which values are still
missing and can fill the empty ones from the business profile of the project.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession
from app.db.models import Opportunity, Website
from app.schemas import (
    RequiredDetailsOut,
    SiteDetailsGenerateOut,
    SiteDetailsIn,
    SiteDetailsOut,
)
from app.services import access
from app.services import site_details as details_service
from app.services.audit import record_audit

router = APIRouter(tags=["site-details"])


def _load(db, opportunity_id: str, user) -> tuple[Opportunity, Website]:
    """Load an opportunity the user may access."""
    opportunity = db.get(Opportunity, opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Opportunity not found"})
    if not access.owns_project(db, user, opportunity.project_id):
        raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Access denied"})
    website = db.get(Website, opportunity.website_id)
    if website is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Website not found"})
    return opportunity, website


@router.get("/opportunities/{opportunity_id}/details", response_model=SiteDetailsOut)
def get_opportunity_details(opportunity_id: str, db: DbSession, user: CurrentUser) -> SiteDetailsOut:
    """The stored details of an opportunity.

    The answer also carries the fields the target site asks for and the ones
    that are still missing.  An opportunity without details is *not* an error:
    the record is simply empty.
    """
    opportunity, _website = _load(db, opportunity_id, user)
    details = details_service.get_details(db, opportunity.id)
    return SiteDetailsOut(**details_service.details_payload(db, opportunity, details))


@router.put("/opportunities/{opportunity_id}/details", response_model=SiteDetailsOut)
def update_opportunity_details(
    opportunity_id: str, payload: SiteDetailsIn, db: DbSession, user: CurrentUser
) -> SiteDetailsOut:
    """Create or update the details of an opportunity.

    Only the fields that are sent are changed.
    """
    opportunity, _website = _load(db, opportunity_id, user)
    values = payload.model_dump(exclude_unset=True)
    details = details_service.upsert_details(db, opportunity, values)
    record_audit(
        db,
        "update",
        "site_details",
        details.id,
        actor_id=user.id,
        after={"fields": sorted(values.keys())},
    )
    return SiteDetailsOut(**details_service.details_payload(db, opportunity, details))


@router.delete(
    "/opportunities/{opportunity_id}/details", status_code=status.HTTP_204_NO_CONTENT
)
def delete_opportunity_details(opportunity_id: str, db: DbSession, user: CurrentUser) -> None:
    """Delete the details of an opportunity."""
    opportunity, _website = _load(db, opportunity_id, user)
    if details_service.delete_details(db, opportunity.id):
        record_audit(db, "delete", "site_details", opportunity.id, actor_id=user.id)


@router.get(
    "/opportunities/{opportunity_id}/details/required", response_model=RequiredDetailsOut
)
def required_opportunity_details(
    opportunity_id: str, db: DbSession, user: CurrentUser
) -> RequiredDetailsOut:
    """Which details are required for this opportunity and which are missing."""
    opportunity, _website = _load(db, opportunity_id, user)
    details = details_service.get_details(db, opportunity.id)
    result = details_service.required_details(db, opportunity, details)
    return RequiredDetailsOut(**result)


@router.post(
    "/opportunities/{opportunity_id}/details/generate", response_model=SiteDetailsGenerateOut
)
def generate_opportunity_details(
    opportunity_id: str, db: DbSession, user: CurrentUser
) -> SiteDetailsGenerateOut:
    """Fill the empty detail fields from the business profile of the project.

    The assistant is optional: without a provider the deterministic
    fallbacks are used.  Facts that are not part of the profile are never
    written.
    """
    opportunity, _website = _load(db, opportunity_id, user)
    details, generated, source = details_service.generate_details(db, opportunity)
    record_audit(
        db,
        "generate",
        "site_details",
        details.id,
        actor_id=user.id,
        after={"fields": generated, "source": source},
    )
    return SiteDetailsGenerateOut(
        details=SiteDetailsOut(**details_service.details_payload(db, opportunity, details)),
        generated=generated,
        source=source,
    )
