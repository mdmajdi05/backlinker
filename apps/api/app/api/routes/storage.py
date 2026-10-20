"""Database & storage settings endpoints (dual database mode)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession
from app.schemas import (
    StorageConnectionRequest,
    StorageMigrationPreviewOut,
    StorageStatusOut,
)
from app.services import storage as storage_service

router = APIRouter(prefix="/storage", tags=["storage"])


@router.get("/status", response_model=StorageStatusOut)
def storage_status(db: DbSession, user: CurrentUser) -> dict:
    return storage_service.storage_status(db)


@router.post("/test")
def test_connection(payload: StorageConnectionRequest, user: CurrentUser) -> dict:
    return storage_service.test_connection(payload.database_url)


@router.post("/connect", response_model=StorageStatusOut)
def connect_cloud(payload: StorageConnectionRequest, db: DbSession, user: CurrentUser) -> dict:
    result = storage_service.test_connection(payload.database_url)
    if not result["ok"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "connection_failed", "message": result["message"]},
        )
    storage_service.write_cloud_connection(
        {"database_url": payload.database_url, "label": payload.label, "connected_at": None}
    )
    storage_service.set_storage_mode(db, "HYBRID")
    return storage_service.storage_status(db)


@router.post("/disconnect", response_model=StorageStatusOut)
def disconnect_cloud(db: DbSession, user: CurrentUser) -> dict:
    """Disconnect the cloud without deleting any local data."""
    storage_service.delete_cloud_connection()
    storage_service.set_storage_mode(db, "LOCAL")
    return storage_service.storage_status(db)


@router.get("/migration/preview", response_model=StorageMigrationPreviewOut)
def migration_preview(db: DbSession, user: CurrentUser) -> dict:
    return storage_service.migration_preview(db)


@router.post("/migration/run")
def run_migration(db: DbSession, user: CurrentUser) -> dict:
    try:
        copied = storage_service.migrate_to_cloud(db)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "migration_failed", "message": str(exc)},
        )
    preview = storage_service.migration_preview(db)
    preview.update(copied)
    return preview


@router.post("/backup")
def create_backup(db: DbSession, user: CurrentUser) -> dict:
    return storage_service.create_backup()


@router.post("/restore")
def restore_backup(payload: dict, db: DbSession, user: CurrentUser) -> dict:
    try:
        return storage_service.restore_backup(payload.get("path"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "restore_failed", "message": str(exc)},
        )


@router.get("/history")
def backup_history(db: DbSession, user: CurrentUser) -> list[dict]:
    return storage_service.backup_history()
