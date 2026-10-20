"""Storage mode management (local SQLite / cloud PostgreSQL / hybrid).

The application always runs against one *active* database (the local SQLite
file by default). Switching to cloud mode never deletes local data: the local
database is kept and a migration preview is produced before anything is
copied.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import Base, utcnow
from app.db.models import (
    AppSetting,
    BacklinkRecord,
    BusinessProfile,
    Opportunity,
    Project,
    SyncChange,
    Task,
)
from app.db.session import get_engine

log = get_logger(__name__)

STORAGE_SETTING_KEY = "storage"
CONNECTION_FILE = "cloud_connection.json"


def _connection_path() -> Path:
    return settings.managed_files_dir / CONNECTION_FILE


def read_cloud_connection() -> dict[str, Any] | None:
    path = _connection_path()
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def write_cloud_connection(payload: dict[str, Any]) -> None:
    settings.ensure_directories()
    path = _connection_path()
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def delete_cloud_connection() -> None:
    path = _connection_path()
    if path.exists():
        path.unlink()


def get_storage_mode(db: Session) -> str:
    row = db.execute(
        select(AppSetting).where(AppSetting.key == STORAGE_SETTING_KEY)
    ).scalar_one_or_none()
    if row and row.value.get("mode") in ("CLOUD", "HYBRID", "LOCAL"):
        return row.value["mode"]
    return settings.storage_mode_effective.upper()


def set_storage_mode(db: Session, mode: str) -> None:
    row = db.execute(
        select(AppSetting).where(AppSetting.key == STORAGE_SETTING_KEY)
    ).scalar_one_or_none()
    if row is None:
        row = AppSetting(key=STORAGE_SETTING_KEY, value={})
        db.add(row)
    row.value = {**(row.value or {}), "mode": mode, "updated_at": utcnow().isoformat()}
    db.commit()


def storage_status(db: Session) -> dict[str, Any]:
    engine = get_engine()
    dialect = engine.dialect.name
    connection = read_cloud_connection()
    last_backup = None
    backup_dir = settings.backup_dir
    if backup_dir.exists():
        files = sorted(backup_dir.glob("*.bak"), key=lambda p: p.stat().st_mtime, reverse=True)
        if files:
            last_backup = datetime.fromtimestamp(files[0].stat().st_mtime).isoformat()
    pending = int(
        db.execute(select(func.count()).select_from(SyncChange).where(SyncChange.synced_at.is_(None))).scalar_one() or 0
    )
    conflicts = int(
        db.execute(select(func.count()).select_from(SyncChange).where(SyncChange.conflict.is_(True))).scalar_one() or 0
    )
    return {
        "mode": get_storage_mode(db),
        "database_type": "postgresql" if dialect.startswith("postgres") else "sqlite",
        "database_url_masked": settings.masked_database_url(),
        "connected": True,
        "cloud_connected": bool(connection),
        "last_backup_at": last_backup,
        "pending_sync_changes": pending,
        "conflicts": conflicts,
        "schema_version": _schema_version(engine),
    }


def _schema_version(engine) -> str | None:
    inspector = inspect(engine)
    if "alembic_version" in inspector.get_table_names():
        with engine.connect() as conn:
            row = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).fetchone()
            return row[0] if row else None
    return "auto"


def test_connection(database_url: str) -> dict[str, Any]:
    """Validate a candidate database URL without changing the active one."""
    if not database_url.startswith(("sqlite://", "postgresql://", "postgresql+psycopg://")):
        return {"ok": False, "message": "Only SQLite and PostgreSQL URLs are supported", "dialect": ""}
    try:
        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        dialect = engine.dialect.name
        engine.dispose()
        return {"ok": True, "message": "Connection succeeded", "dialect": dialect}
    except Exception as exc:
        return {"ok": False, "message": f"{type(exc).__name__}: {exc}", "dialect": ""}


def migration_preview(db: Session) -> dict[str, Any]:
    """Count the records that would be transferred to a cloud database."""
    projects = int(db.execute(select(func.count()).select_from(Project)).scalar_one() or 0)
    opportunities = int(db.execute(select(func.count()).select_from(Opportunity)).scalar_one() or 0)
    tasks = int(db.execute(select(func.count()).select_from(Task)).scalar_one() or 0)
    backlinks = int(db.execute(select(func.count()).select_from(BacklinkRecord)).scalar_one() or 0)
    profiles = int(db.execute(select(func.count()).select_from(BusinessProfile)).scalar_one() or 0)
    connection = read_cloud_connection()
    notes = [
        "Local data is never deleted automatically - a backup is created before any migration.",
    ]
    if not connection:
        notes.append("No cloud connection configured yet; configure one in Database & Storage settings.")
    return {
        "projects": projects,
        "opportunities": opportunities,
        "tasks": tasks,
        "backlink_records": backlinks,
        "profiles": profiles,
        "duplicates": 0,
        "conflicts": 0,
        "compatible": bool(connection),
        "notes": notes,
    }


def migrate_to_cloud(db: Session) -> dict[str, Any]:
    """Copy the local dataset into the configured cloud database."""
    connection = read_cloud_connection()
    if not connection:
        raise RuntimeError("No cloud connection configured")
    url = connection.get("database_url")
    if not url:
        raise RuntimeError("Cloud connection is missing a database URL")
    target = create_engine(url, pool_pre_ping=True)
    Base.metadata.create_all(bind=target)

    copied = {"projects": 0, "opportunities": 0, "tasks": 0, "backlink_records": 0, "profiles": 0}
    with Session(target) as target_db:
        for model, key in (
            (BusinessProfile, "profiles"),
            (Project, "projects"),
            (Opportunity, "opportunities"),
            (Task, "tasks"),
            (BacklinkRecord, "backlink_records"),
        ):
            existing = {
                row[0]
                for row in target_db.execute(select(model.id)).all()
            }
            for row in db.execute(select(model)).scalars().all():
                if row.id in existing:
                    continue
                target_db.merge(row)
                copied[key] += 1
        target_db.commit()
    target.dispose()
    set_storage_mode(db, "HYBRID")
    return copied


def create_backup(label: str = "manual") -> dict[str, Any]:
    """Create a backup of the active database."""
    settings.ensure_directories()
    engine = get_engine()
    stamp = utcnow().strftime("%Y%m%d-%H%M%S")
    destination = settings.backup_dir / f"backup-{stamp}.bak"

    if engine.dialect.name == "sqlite":
        source = Path(settings.effective_database_url.replace("sqlite:///", ""))
        if source.exists():
            shutil.copy2(source, destination)
        else:
            destination.write_bytes(b"")
    else:
        # Logical backup (works without pg_dump installed).
        payload: dict[str, Any] = {}
        with Session(engine) as source_db:
            for table in Base.metadata.sorted_tables:
                rows = source_db.execute(select(table)).scalars().all()
                payload[table.name] = [dict(row.__dict__) for row in rows]
        destination.write_text(json.dumps(payload, default=str), encoding="utf-8")

    os.chmod(destination, stat.S_IRUSR | stat.S_IWUSR)
    return {"path": str(destination), "created_at": utcnow().isoformat(), "label": label}


def restore_backup(path: str | None = None) -> dict[str, Any]:
    """Restore a backup file into the active database."""
    if path:
        source = Path(path)
    else:
        backups = sorted(settings.backup_dir.glob("*.bak"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not backups:
            raise RuntimeError("No backup available")
        source = backups[0]
    if not source.exists():
        raise RuntimeError(f"Backup file not found: {source}")

    engine = get_engine()
    if engine.dialect.name == "sqlite":
        destination = Path(settings.effective_database_url.replace("sqlite:///", ""))
        shutil.copy2(source, destination)
    else:
        payload = json.loads(source.read_text(encoding="utf-8"))
        with Session(engine) as target_db:
            for table_name, rows in payload.items():
                table = Base.metadata.tables.get(table_name)
                if table is None:
                    continue
                model = table_mapper(table)
                if model is None:
                    continue
                target_db.query(model).delete()
                for row in rows:
                    target_db.merge(model(**row))
            target_db.commit()
    return {"restored": True, "source": str(source)}


def table_mapper(table) -> Any:
    from sqlalchemy.orm import class_mapper

    try:
        return class_mapper(table)
    except Exception:
        return None


def backup_history() -> list[dict[str, Any]]:
    settings.ensure_directories()
    items = []
    for path in sorted(settings.backup_dir.glob("*.bak"), key=lambda p: p.stat().st_mtime, reverse=True):
        stat_ = path.stat()
        items.append(
            {
                "path": str(path),
                "name": path.name,
                "size_bytes": stat_.st_size,
                "created_at": datetime.fromtimestamp(stat_.st_mtime).isoformat(),
            }
        )
    return items
