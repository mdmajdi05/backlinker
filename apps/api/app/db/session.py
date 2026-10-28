"""Database engine / session management (SQLite + PostgreSQL)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import Base

log = get_logger(__name__)

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _engine_kwargs(url: str) -> dict:
    if url.startswith("sqlite"):
        return {
            "connect_args": {"check_same_thread": False, "timeout": 30},
            "pool_pre_ping": True,
            "echo": settings.db_echo,
        }
    return {
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_pool_size * 2,
        "pool_pre_ping": True,
        "pool_recycle": 1800,
        "echo": settings.db_echo,
    }


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is not None:
        return _engine
    url = settings.effective_database_url
    engine = create_engine(url, **_engine_kwargs(url))

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - driver hook
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    _engine = engine
    # autoflush + expire_on_commit keep the ORM state in sync with the database:
    # a query always sees pending changes and a committed object is re-read from
    # the database instead of serving a stale in-memory copy.
    _SessionLocal = sessionmaker(bind=engine, autoflush=True, expire_on_commit=True, future=True)
    log.info("database engine ready", extra={"extra_fields": {"dialect": engine.dialect.name}})
    return engine


def get_session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def session_scope() -> Session:
    """Session for worker / background code paths."""
    return get_session_factory()()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    db = session_scope()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_context() -> Iterator[Session]:
    db = session_scope()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Create tables when running in auto-create mode (local desktop / dev).

    Existing installations are updated as well: columns that were added in a
    later version are added to the existing tables, so an update never leaves
    the database in a broken state.
    """
    import app.db.models  # noqa: F401  (registers every table on the metadata)

    engine = get_engine()
    if settings.auto_create_schema:
        Base.metadata.create_all(bind=engine)
        added = _sync_missing_columns(engine)
        if added:
            log.info("schema updated", extra={"extra_fields": {"columns": added}})
        log.info("schema ensured", extra={"extra_fields": {"dialect": engine.dialect.name}})


def _sync_missing_columns(engine) -> list[str]:
    """Add columns that the models know but the database does not have yet."""
    from sqlalchemy import inspect, text

    added: list[str] = []
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        present = {column["name"] for column in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in present:
                continue
            ddl = _add_column_ddl(engine.dialect.name, table.name, column)
            if ddl is None:
                continue
            try:
                with engine.begin() as connection:
                    connection.execute(text(ddl))
                added.append(f"{table.name}.{column.name}")
            except Exception:  # pragma: no cover - defensive
                log.warning(
                    "could not add a column",
                    extra={"extra_fields": {"table": table.name, "column": column.name}},
                )
    return added


def _add_column_ddl(dialect: str, table: str, column) -> str | None:
    """The statement that adds a column (SQLite and PostgreSQL)."""
    type_name = column.type.compile(dialect=engine_dialect(dialect))
    default = ""
    if column.default is not None:
        if getattr(column.default, "is_scalar", False):
            value = column.default.arg
            if isinstance(value, bool):
                default = " DEFAULT 1" if value else " DEFAULT 0"
            elif isinstance(value, (int, float)):
                default = f" DEFAULT {value}"
            elif isinstance(value, str):
                default = f" DEFAULT '{value}'"
        elif getattr(column.default.arg, "__name__", "") == "dict":
            # A JSON column with ``default=dict`` exists on old databases as
            # ``JSON NOT NULL`` too, so the added column needs an empty object.
            default = " DEFAULT '{}'"
        elif getattr(column.default.arg, "__name__", "") == "list":
            default = " DEFAULT '[]'"
    if dialect.startswith("postgres"):
        return f'ALTER TABLE "{table}" ADD COLUMN "{column.name}" {type_name}{default}'
    return f'ALTER TABLE "{table}" ADD COLUMN "{column.name}" {type_name}{default}'


def engine_dialect(name: str):
    """A dialect object that can compile a type for the given dialect name."""
    from sqlalchemy.dialects import postgresql, sqlite

    return postgresql.dialect() if name.startswith("postgres") else sqlite.dialect()


def health_check() -> dict:
    engine = get_engine()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {
            "ok": True,
            "dialect": engine.dialect.name,
            "url": settings.masked_database_url(),
        }
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "dialect": engine.dialect.name, "error": str(exc)}


def dispose_engine() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
