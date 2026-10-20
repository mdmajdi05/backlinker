"""Discovery provider registry.

Providers are implemented in :mod:`app.services.discovery.impl` and register
themselves through :func:`app.services.discovery.base.register_provider`.

:func:`load_providers` imports the implementation package once, so the
registry is filled no matter whether the API, the worker or a script calls
it. Calling it repeatedly is safe.
"""

from __future__ import annotations

from app.core.logging import get_logger

log = get_logger(__name__)

_LOADED = False


def load_providers() -> None:
    """Import and register every discovery provider implementation.

    Safe to call repeatedly - the implementations register themselves
    exactly once and the registry is keyed by the provider key.
    """
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    try:
        from app.services.discovery import impl  # noqa: F401
    except Exception as exc:
        log.error("discovery providers could not be loaded", extra={"extra_fields": {"error": str(exc)}})
