"""FastAPI application factory."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import (
    ai,
    auth,
    campaigns,
    dataflow,
    discovery,
    integrations,
    misc,
    profiles,
    projects,
    queue,
    registry,
    storage,
    sync,
    verification,
)
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.session import health_check, init_db

log = get_logger(__name__)

API_VERSION = "1.0.0"

DESCRIPTION = """
Autonomous backlink discovery, automation, verification and reporting platform.

All endpoints operate on real, persisted data. Nothing is simulated: tasks,
verifications and metrics always reflect the database state.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings.ensure_directories()
    init_db()
    from app.db.session import session_scope
    from app.services.seed import seed_registry

    with session_scope() as db:
        seed_registry(db)

    from app.services.discovery import load_providers

    load_providers()

    worker = None
    if settings.worker_enabled:
        from app.workers.runner import EmbeddedWorker

        worker = EmbeddedWorker()
        worker.start()
        app.state.worker = worker
        log.info("embedded worker started")

    try:
        yield
    finally:
        if worker is not None:
            worker.stop()
        from app.db.session import dispose_engine

        dispose_engine()


def _safe_errors(errors: list[dict]) -> list[dict]:
    """Make validation errors JSON serialisable.

    Pydantic puts the raised exception object into ``ctx``; those objects are
    not serialisable and are not useful for the client anyway.
    """
    cleaned: list[dict] = []
    for error in errors:
        item = {key: value for key, value in error.items() if key != "ctx"}
        context = error.get("ctx")
        if context:
            item["ctx"] = {key: str(value) for key, value in context.items()}
        input_value = item.get("input")
        if not isinstance(input_value, (str, int, float, bool, type(None), list, dict)):
            item["input"] = str(input_value)
        cleaned.append(item)
    return cleaned


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        description=DESCRIPTION,
        version=API_VERSION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Process-Time-Ms"] = f"{duration_ms:.1f}"
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        detail = exc.detail
        if isinstance(detail, dict):
            payload = {
                "error": {
                    "code": detail.get("code", "error"),
                    "message": detail.get("message", "Request failed"),
                    "details": detail.get("details"),
                    "request_id": request.headers.get("x-request-id"),
                }
            }
        else:
            payload = {"error": {"code": "error", "message": str(detail)}}
        return JSONResponse(status_code=exc.status_code, content=payload, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "The request payload is invalid",
                    "details": _safe_errors(exc.errors()),
                }
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        log.exception("unhandled error", extra={"extra_fields": {"path": request.url.path}})
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "An unexpected error occurred"}},
        )

    prefix = settings.api_prefix
    app.include_router(auth.router, prefix=prefix)
    app.include_router(profiles.router, prefix=prefix)
    app.include_router(projects.router, prefix=prefix)
    app.include_router(registry.router, prefix=prefix)
    app.include_router(discovery.router, prefix=prefix)
    app.include_router(integrations.router, prefix=prefix)
    app.include_router(queue.router, prefix=prefix)
    app.include_router(verification.router, prefix=prefix)
    app.include_router(dataflow.imports_router, prefix=prefix)
    app.include_router(dataflow.reports_router, prefix=prefix)
    app.include_router(misc.activity_router, prefix=prefix)
    app.include_router(misc.adapters_router, prefix=prefix)
    app.include_router(misc.devices_router, prefix=prefix)
    app.include_router(misc.dashboard_router, prefix=prefix)
    app.include_router(misc.events_router, prefix=prefix)
    app.include_router(campaigns.router, prefix=prefix)
    app.include_router(storage.router, prefix=prefix)
    app.include_router(sync.router, prefix=prefix)
    app.include_router(ai.router, prefix=prefix)

    @app.get("/health", tags=["system"])
    def health() -> dict:
        worker = getattr(app.state, "worker", None)
        return {
            "status": "ok",
            "version": API_VERSION,
            "database": health_check(),
            "worker": worker.status() if worker else {"running": False, "mode": "external"},
            "storage_mode": settings.storage_mode_effective,
        }

    @app.get("/api/v1/system/info", tags=["system"])
    def system_info() -> dict:
        return {
            "name": settings.app_name,
            "version": API_VERSION,
            "environment": settings.environment,
            "storage_mode": settings.storage_mode_effective,
            "database_type": "postgresql" if not settings.is_sqlite else "sqlite",
            "data_dir": str(settings.data_dir),
            "ai_enabled": bool(settings.ai_api_key and settings.ai_provider),
            "celery_enabled": settings.use_celery,
        }

    return app


app = create_app()
