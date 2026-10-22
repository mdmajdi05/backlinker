"""Business profile endpoints (reusable across projects)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.db.base import utcnow
from app.db.models import BusinessProfile
from app.schemas import BusinessProfileIn, BusinessProfileOut
from app.services.audit import record_audit

router = APIRouter(prefix="/profiles", tags=["profiles"])


def _owned(db, profile_id: str, user) -> BusinessProfile:
    profile = db.get(BusinessProfile, profile_id)
    if profile is None or profile.deleted_at is not None:
        # A profile that waits in the recycle bin is gone for every reader.
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Profile not found"})
    if profile.owner_id and user and profile.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Access denied"})
    return profile


@router.get("", response_model=list[BusinessProfileOut])
def list_profiles(db: DbSession, user: CurrentUser) -> list[BusinessProfile]:
    stmt = select(BusinessProfile).order_by(BusinessProfile.created_at.desc())
    if not user.is_admin:
        stmt = stmt.where((BusinessProfile.owner_id == user.id) | (BusinessProfile.owner_id.is_(None)))
    stmt = stmt.where(BusinessProfile.deleted_at.is_(None))
    return list(db.execute(stmt).scalars().all())


@router.post("", response_model=BusinessProfileOut, status_code=status.HTTP_201_CREATED)
def create_profile(payload: BusinessProfileIn, db: DbSession, user: CurrentUser) -> BusinessProfile:
    duplicate = db.execute(
        select(BusinessProfile).where(
            BusinessProfile.owner_id == user.id,
            BusinessProfile.name == payload.name,
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "duplicate", "message": "A profile with this name already exists"},
        )
    profile = BusinessProfile(**payload.model_dump(), owner_id=user.id)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    record_audit(db, "create", "business_profile", profile.id, actor_id=user.id, after={"name": profile.name})
    return profile


@router.get("/{profile_id}", response_model=BusinessProfileOut)
def get_profile(profile_id: str, db: DbSession, user: CurrentUser) -> BusinessProfile:
    return _owned(db, profile_id, user)


@router.put("/{profile_id}", response_model=BusinessProfileOut)
def update_profile(
    profile_id: str, payload: BusinessProfileIn, db: DbSession, user: CurrentUser
) -> BusinessProfile:
    profile = _owned(db, profile_id, user)
    before = {"name": profile.name, "primary_website": profile.primary_website}
    for field, value in payload.model_dump().items():
        setattr(profile, field, value)
    db.commit()
    db.refresh(profile)
    record_audit(db, "update", "business_profile", profile.id, actor_id=user.id, before=before)
    return profile


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile(profile_id: str, db: DbSession, user: CurrentUser) -> None:
    """Move the profile into the recycle bin.

    The projects keep their reference, so a restore brings the profile back
    exactly where it was.  Only "delete forever" detaches them.
    """
    profile = _owned(db, profile_id, user)
    profile.deleted_at = utcnow()
    db.commit()
    record_audit(db, "delete", "business_profile", profile_id, actor_id=user.id)
