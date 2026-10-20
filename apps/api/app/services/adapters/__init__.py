"""Submission adapter registry.

Importing this package registers every adapter implementation with
:func:`app.services.adapters.base.register_adapter`. The import is
idempotent - the registry is keyed by the adapter key, so importing the
package several times never creates duplicates.
"""

from __future__ import annotations

from app.services.adapters.base import (
    RESULT_FAILED,
    RESULT_PUBLISHED,
    RESULT_SKIPPED,
    RESULT_SUBMITTED,
    RESULT_WAITING_APPROVAL,
    RESULT_WAITING_USER,
    BaseAdapter,
    SubmissionContext,
    SubmissionResult,
    adapter_for_website,
    all_adapters,
    get_adapter,
    register_adapter,
)
from app.services.adapters.impl.email_outreach import EmailOutreachAdapter
from app.services.adapters.impl.http_form import HttpFormAdapter
from app.services.adapters.impl.json_api import JsonApiAdapter
from app.services.adapters.impl.manual import ManualAdapter
from app.services.adapters.impl.playwright_form import PlaywrightFormAdapter

__all__ = [
    "RESULT_FAILED",
    "RESULT_PUBLISHED",
    "RESULT_SKIPPED",
    "RESULT_SUBMITTED",
    "RESULT_WAITING_APPROVAL",
    "RESULT_WAITING_USER",
    "BaseAdapter",
    "EmailOutreachAdapter",
    "HttpFormAdapter",
    "JsonApiAdapter",
    "ManualAdapter",
    "PlaywrightFormAdapter",
    "SubmissionContext",
    "SubmissionResult",
    "adapter_for_website",
    "all_adapters",
    "get_adapter",
    "load_adapters",
    "register_adapter",
]


def load_adapters() -> list[BaseAdapter]:
    """Return every registered adapter (import side effect of this package)."""
    return all_adapters()
