"""Alembic environment.

The environment is intentionally simple and synchronous:

* the database URL is never stored in ``alembic.ini`` - it is resolved from
  :class:`app.core.config.Settings` so migrations always target the same
  database the application uses;
* ``render_as_batch`` is enabled, which keeps the migrations usable on SQLite
  (the desktop / local mode) as well as on PostgreSQL (the cloud mode);
* every model is imported so ``Base.metadata`` is complete and autogenerate
  produces meaningful diffs.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.db.base import Base

# Importing the models registers every table on ``Base.metadata``.
import app.db.models  # noqa: F401  isort:skip

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_database_url() -> str:
    """The URL of the database the migrations are applied to."""
    url = config.get_main_option("sqlalchemy.url") or ""
    if url:
        return url
    return settings.effective_database_url


def run_migrations_offline() -> None:
    """Emit the SQL statements without connecting to a database."""
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply the migrations against a live connection."""
    connectable = engine_from_config(
        {},
        prefix="sqlalchemy.",
        url=get_database_url(),
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
