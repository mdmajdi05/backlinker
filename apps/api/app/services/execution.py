"""Control of the background execution.

The operator can pause, resume or stop **all** automation from the user
interface, and configure how much of the machine the browser jobs may use.
The state lives in the database, so it survives a restart of the application
and is shared by every worker that runs against the same database.
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import AppSetting

log = get_logger(__name__)

ExecutionState = Literal["RUNNING", "PAUSED", "STOPPED"]

SETTING_KEY = "execution"

DEFAULT_SETTINGS: dict[str, Any] = {
    "state": "RUNNING",
    # How many browser jobs may run at the same time on this machine.
    "max_browser_jobs": 2,
    # "max_speed" | "balanced" | "save_resources"
    "resource_preference": "balanced",
    # Headless is the default; the headed mode uses an isolated profile too.
    "headless": True,
    # How many jobs may touch the same domain at the same time.
    "per_domain_limit": 1,
    # How many requests may go to the same domain per minute.
    "per_domain_requests_per_minute": 10,
    # A browser job that runs longer is cancelled.
    "task_timeout_seconds": 240,
    # Maximum time a single page may take.
    "page_timeout_seconds": 45,
}


@dataclass
class ExecutionSettings:
    state: ExecutionState = "RUNNING"
    max_browser_jobs: int = 2
    resource_preference: str = "balanced"
    headless: bool = True
    per_domain_limit: int = 1
    per_domain_requests_per_minute: int = 10
    task_timeout_seconds: int = 240
    page_timeout_seconds: int = 45

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ExecutionSettings:
        data = data or {}
        merged = {**DEFAULT_SETTINGS, **{k: v for k, v in data.items() if k in DEFAULT_SETTINGS}}
        return cls(
            state=merged["state"],  # type: ignore[arg-type]
            max_browser_jobs=int(merged["max_browser_jobs"]),
            resource_preference=str(merged["resource_preference"]),
            headless=bool(merged["headless"]),
            per_domain_limit=int(merged["per_domain_limit"]),
            per_domain_requests_per_minute=int(merged["per_domain_requests_per_minute"]),
            task_timeout_seconds=int(merged["task_timeout_seconds"]),
            page_timeout_seconds=int(merged["page_timeout_seconds"]),
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_lock = threading.Lock()


def _row(db: Session) -> AppSetting:
    row = db.execute(
        select_setting(SETTING_KEY)
    ).scalar_one_or_none()
    if row is None:
        row = AppSetting(key=SETTING_KEY, value=dict(DEFAULT_SETTINGS))
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def select_setting(key: str):
    from sqlalchemy import select

    return select(AppSetting).where(AppSetting.key == key)


def get_settings(db: Session) -> ExecutionSettings:
    row = _row(db)
    return ExecutionSettings.from_dict(row.value)


def update_settings(db: Session, changes: dict[str, Any]) -> ExecutionSettings:
    with _lock:
        row = _row(db)
        value = {**DEFAULT_SETTINGS, **(row.value or {})}
        for key, item in changes.items():
            if key in DEFAULT_SETTINGS and item is not None:
                value[key] = item
        row.value = value
        db.commit()
        db.refresh(row)
    settings = ExecutionSettings.from_dict(value)
    log.info("execution settings updated", extra={"extra_fields": {"settings": value}})
    return settings


def set_state(db: Session, state: ExecutionState) -> ExecutionSettings:
    return update_settings(db, {"state": state})


def pause(db: Session) -> ExecutionSettings:
    return set_state(db, "PAUSED")


def resume(db: Session) -> ExecutionSettings:
    return set_state(db, "RUNNING")


def stop(db: Session) -> ExecutionSettings:
    """Stop the execution: no new jobs are claimed, running ones are cancelled."""
    return set_state(db, "STOPPED")


def is_running(db: Session) -> bool:
    return get_settings(db).state == "RUNNING"


def describe(db: Session) -> dict[str, Any]:
    settings = get_settings(db)
    return {
        **settings.as_dict(),
        "states": {
            "RUNNING": "Jobs are claimed and executed.",
            "PAUSED": "No new job is claimed, running jobs finish.",
            "STOPPED": "No new job is claimed and running jobs are cancelled.",
        },
    }
