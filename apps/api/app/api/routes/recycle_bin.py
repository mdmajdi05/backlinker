"""Recycle bin endpoints.

Everything that was deleted is reachable here: a project, a website, a
business profile or an opportunity.  Restoring brings the row back with its
history; deleting it forever is the explicit, irreversible step.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession
from app.schemas import RecycleBinItem, RecycleBinPage
from app.services import recycle_bin
from app.services.audit import record_audit

router = APIRouter(prefix="/recycle-bin", tags=["recycle-bin"])


@router.get("", response_model=RecycleBinPage)
def list_bin(
    db: DbSession,
    user: CurrentUser,
    kind: str | None = Query(default=None, description="project, website, profile, opportunity"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
) -> RecycleBinPage:
    """Everything that waits in the recycle bin, newest first."""
    try:
        payload = recycle_bin.list_items(db, user, kind=kind, page=page, page_size=page_size)
    except recycle_bin.RecycleBinError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": "invalid_kind", "message": error.message},
        ) from error
    return RecycleBinPage(**payload)


@router.get("/counts")
def bin_counts(db: DbSession, user: CurrentUser) -> dict[str, int]:
    """Only the counts - used for the badge in the navigation."""
    return recycle_bin.counts(db, user)


@router.post("/{kind}/{item_id}/restore", response_model=RecycleBinItem)
def restore(kind: str, item_id: str, db: DbSession, user: CurrentUser) -> RecycleBinItem:
    """Bring a removed row back into the normal lists."""
    try:
        item = recycle_bin.restore_item(db, user, kind, item_id)
    except recycle_bin.RecycleBinError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": "not_found" if error.status_code == 404 else "forbidden",
                    "message": error.message},
        ) from error
    record_audit(db, "restore", kind, item_id, actor_id=user.id)
    return RecycleBinItem(**item)


@router.delete("/{kind}/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def purge(kind: str, item_id: str, db: DbSession, user: CurrentUser) -> None:
    """Delete a row from the recycle bin forever, with everything that depends on it."""
    try:
        recycle_bin.purge_item(db, user, kind, item_id)
    except recycle_bin.RecycleBinError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": "not_found" if error.status_code == 404 else "forbidden",
                    "message": error.message},
        ) from error
    record_audit(db, "purge", kind, item_id, actor_id=user.id)
