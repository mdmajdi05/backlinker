"""Application configuration.

All settings are environment driven so the same code runs in:
  * local desktop mode (SQLite, embedded worker)
  * self-hosted web mode (SQLite or PostgreSQL)
  * cloud mode (PostgreSQL + Redis/Celery)
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

StorageMode = Literal["auto", "local", "cloud", "hybrid"]


def _default_data_dir() -> Path:
    override = os.environ.get("AUTOBL_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "AutoBacklinker"
    if os.sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "AutoBacklinker"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "auto-backlinker"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AUTOBL_",
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- identity -----------------------------------------------------
    app_name: str = "Auto Backlinker"
    environment: Literal["local", "self_hosted", "cloud", "desktop", "test"] = "local"
    debug: bool = False
    api_prefix: str = "/api/v1"

    # --- security -----------------------------------------------------
    secret_key: str = "dev-only-insecure-secret-key-change-me-please-000000"  # noqa: S105
    access_token_expire_minutes: int = 60 * 12
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",  # the web client
            "http://127.0.0.1:3000",
            "http://localhost:1420",  # the desktop client in the browser preview
            "http://127.0.0.1:1420",
            "tauri://localhost",  # the packaged desktop client
            "http://tauri.localhost",
        ]
    )
    local_token: str = ""
    allow_private_network: bool = False
    allow_file_uploads: bool = True

    # --- storage ------------------------------------------------------
    storage_mode: StorageMode = "auto"
    database_url: str | None = None
    data_dir: Path = Field(default_factory=_default_data_dir)
    sqlite_filename: str = "autobacklinker.db"
    db_echo: bool = False
    db_pool_size: int = 5
    auto_create_schema: bool = True
    backup_dir_name: str = "backups"
    managed_files_dir_name: str = "files"
    logs_dir_name: str = "logs"
    max_upload_mb: int = 25

    # --- queue / workers ---------------------------------------------
    worker_enabled: bool = True
    worker_poll_interval: float = 1.0
    worker_batch_size: int = 5
    worker_id: str = ""
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None
    use_celery: bool = False

    # --- automation ----------------------------------------------------
    http_timeout: float = 25.0
    user_agent: str = (
        "AutoBacklinker/1.0 (+https://localhost; respectful crawler; contact via app settings)"
    )
    max_requests_per_minute: int = 30
    respect_robots: bool = True
    allow_browser_automation: bool = True
    playwright_headless: bool = True
    verification_interval_hours: int = 168
    verification_batch_size: int = 25

    # --- AI ------------------------------------------------------------
    ai_provider: str | None = None
    ai_base_url: str | None = None
    ai_api_key: str | None = None
    ai_model: str | None = None
    ai_enabled: bool = True

    # --- local agent / devices -----------------------------------------
    device_heartbeat_seconds: int = 30
    task_lease_seconds: int = 300

    @field_validator("data_dir", mode="before")
    @classmethod
    def _expand(cls, v: str | Path) -> Path:
        return Path(v).expanduser()

    @property
    def database_file(self) -> Path:
        return self.data_dir / self.sqlite_filename

    @property
    def managed_files_dir(self) -> Path:
        return self.data_dir / self.managed_files_dir_name

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / self.backup_dir_name

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / self.logs_dir_name

    @property
    def is_sqlite(self) -> bool:
        url = self.effective_database_url
        return url.startswith("sqlite")

    @property
    def effective_database_url(self) -> str:
        """The database URL actually used (falls back to local SQLite)."""
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.database_file}"

    @property
    def storage_mode_effective(self) -> str:
        if self.storage_mode != "auto":
            return self.storage_mode
        return "cloud" if self.database_url and not self.is_sqlite else "local"

    def ensure_directories(self) -> None:
        for path in (
            self.data_dir,
            self.managed_files_dir,
            self.backup_dir,
            self.logs_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def masked_database_url(self) -> str:
        url = self.effective_database_url
        if "@" not in url:
            return url
        prefix, _, tail = url.partition("://")
        _, _, host = tail.partition("@")
        return f"{prefix}://***@{host}"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    if not settings.worker_id:
        import socket

        settings.worker_id = f"{socket.gethostname()}:{os.getpid()}"
    return settings


settings = get_settings()
