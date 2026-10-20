"""Execution of the claimed tasks.

The executor reuses the adapter framework of the backend
(``apps/api/app/services/adapters``). The API sources are added to
``sys.path`` so the agent can import the very same adapters the cloud workers
use - no logic is duplicated here.

If the backend package (or one of its dependencies) is not importable the
agent reports a clear error instead of pretending that the task was executed.
"""

from __future__ import annotations

import logging
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .allowlist import TaskRejected, task_type_of, validate_task
from .browser import browser_runtime_status

LOG = logging.getLogger("agent.executor")

#: Status values reported to the backend (mirrors packages/shared-types).
STATUS_SUBMITTED = "SUBMITTED"
STATUS_PUBLISHED_UNVERIFIED = "PUBLISHED_UNVERIFIED"
STATUS_WAITING_FOR_USER = "WAITING_FOR_USER"
STATUS_WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
STATUS_VERIFIED_LIVE = "VERIFIED_LIVE"
STATUS_VERIFICATION_FAILED = "VERIFICATION_FAILED"
STATUS_FAILED = "FAILED"
STATUS_SKIPPED = "SKIPPED"

_RESULT_STATUS_MAP = {
    "SUBMITTED": STATUS_SUBMITTED,
    "PUBLISHED_UNVERIFIED": STATUS_PUBLISHED_UNVERIFIED,
    "WAITING_FOR_USER": STATUS_WAITING_FOR_USER,
    "WAITING_FOR_APPROVAL": STATUS_WAITING_FOR_APPROVAL,
    "FAILED": STATUS_FAILED,
    "SKIPPED": STATUS_SKIPPED,
}


class AdapterUnavailable(RuntimeError):
    """The backend adapter framework could not be loaded."""


@dataclass
class TaskOutcome:
    """The result of one task execution."""

    status: str
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    requires_human: bool = False

    def to_payload(self) -> dict[str, Any]:
        payload = dict(self.result)
        payload["requires_human"] = self.requires_human
        return payload


def _namespace(data: Any, **defaults: Any) -> SimpleNamespace:
    values = dict(defaults)
    if isinstance(data, dict):
        values.update(data)
    return SimpleNamespace(**values)


class TaskExecutor:
    def __init__(self, api_dir: Path | None = None) -> None:
        self.api_dir = api_dir
        self._adapters_loaded = False
        self._adapter_module: Any = None

    # -- backend adapter framework -------------------------------------
    def _ensure_api_path(self) -> None:
        if not self.api_dir:
            return
        path = str(self.api_dir)
        if path not in sys.path:
            sys.path.insert(0, path)

    def load_adapters(self) -> Any:
        """Imports the adapter framework of the backend.

        Raises :class:`AdapterUnavailable` with an actionable message when the
        framework (or one of its dependencies) is missing.
        """
        if self._adapters_loaded and self._adapter_module is not None:
            return self._adapter_module

        self._ensure_api_path()
        errors: list[str] = []
        try:
            # Importing the package registers the concrete adapters.
            import app.services.adapters  # noqa: F401
        except Exception as error:  # pragma: no cover - depends on the backend
            errors.append(f"app.services.adapters: {error}")

        try:
            from app.services.adapters.base import (  # type: ignore
                SubmissionContext,
                get_adapter,
            )

            self._adapter_module = SimpleNamespace(
                SubmissionContext=SubmissionContext,
                get_adapter=get_adapter,
            )
            self._adapters_loaded = True
            return self._adapter_module
        except Exception as error:  # pragma: no cover - depends on the backend
            errors.append(f"app.services.adapters.base: {error}")

        detail = "; ".join(errors) or "unknown error"
        raise AdapterUnavailable(
            "The backend adapter framework is not available on this machine "
            f"({detail}). Install the API dependencies "
            "(pip install -r apps/api/requirements.txt) or point --api-dir at "
            "a checkout of apps/api."
        )

    # -- execution -----------------------------------------------------
    def execute(self, task: dict[str, Any]) -> TaskOutcome:
        try:
            task_type = validate_task(task)
        except TaskRejected as error:
            LOG.warning("Task rejected: %s", error)
            return TaskOutcome(
                status=STATUS_FAILED,
                result={"rejected": True, "reason": str(error)},
                error=str(error),
                requires_human=True,
            )

        payload = task.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}

        try:
            adapters = self.load_adapters()
        except AdapterUnavailable as error:
            LOG.error("%s", error)
            return TaskOutcome(
                status=STATUS_WAITING_FOR_USER,
                result={"requires_human": True},
                error=str(error),
                requires_human=True,
            )

        adapter_key = (
            payload.get("adapter_key")
            or payload.get("adapter")
            or task.get("adapter_id")
        )
        adapter = None
        if adapter_key:
            adapter = adapters.get_adapter(str(adapter_key))
        if adapter is None:
            return TaskOutcome(
                status=STATUS_WAITING_FOR_USER,
                result={"requires_human": True},
                error=(
                    "No submission adapter is registered for this task "
                    f"(adapter: {adapter_key or 'unknown'})."
                ),
                requires_human=True,
            )

        requires_browser = self._requires_browser(adapter, payload)
        if requires_browser:
            available, message = browser_runtime_status()
            if not available:
                LOG.error("%s", message)
                return TaskOutcome(
                    status=STATUS_WAITING_FOR_USER,
                    result={"requires_human": True, "browser_runtime": "missing"},
                    error=message,
                    requires_human=True,
                )

        context = self._build_context(task, payload, adapter)

        try:
            if task_type == "VERIFY":
                return self._execute_verify(context, adapter, payload)
            return self._execute_submit(context, adapter, payload)
        except Exception as error:  # pragma: no cover - defensive
            LOG.exception("Task %s failed", task.get("id"))
            return TaskOutcome(
                status=STATUS_FAILED,
                result={},
                error=f"{type(error).__name__}: {error}",
            )

    # -- helpers -------------------------------------------------------
    def _requires_browser(self, adapter: Any, payload: dict[str, Any]) -> bool:
        if payload.get("requires_browser"):
            return True
        if str(getattr(adapter, "kind", "")).upper() == "BROWSER_AUTOMATION":
            return True
        methods = getattr(adapter, "supported_methods", ()) or ()
        if "BROWSER_FORM" in {str(method).upper() for method in methods}:
            return True
        return False

    def _build_context(
        self,
        task: dict[str, Any],
        payload: dict[str, Any],
        adapter: Any,
    ) -> Any:
        adapters = self.load_adapters()
        website = _namespace(
            payload.get("website"),
            name="",
            domain="",
            opportunity_url="",
            category="",
            submission_method="UNKNOWN",
        )
        opportunity = _namespace(
            payload.get("opportunity"),
            name="",
            target_landing_page=None,
            anchor_text=None,
            contact_email=None,
            notes=None,
        )
        project = _namespace(
            payload.get("project"), name="", target_website="", id=""
        )
        profile = _namespace(
            payload.get("profile"),
            name="",
            business_descriptions=[],
            author_bios=[],
        )
        task_object = _namespace(
            task,
            id=task.get("id"),
            type=task_type_of(task),
            payload=payload,
        )

        adapter_config = payload.get("adapter_config")
        if not isinstance(adapter_config, dict):
            adapter_config = {}

        return adapters.SubmissionContext(
            db=None,
            task=task_object,
            website=website,
            opportunity=opportunity,
            project=project,
            profile=profile,
            adapter_config=adapter_config,
            project_settings=payload.get("project_settings") or {},
            evidence_dir=None,
            emit=None,
        )

    def _execute_submit(
        self,
        context: Any,
        adapter: Any,
        payload: dict[str, Any],
    ) -> TaskOutcome:
        result = adapter.submit(context)
        status = _RESULT_STATUS_MAP.get(str(result.status).upper(), STATUS_FAILED)
        details = {
            "adapter": getattr(adapter, "key", None),
            "message": getattr(result, "message", None),
            "published_page_url": getattr(result, "published_page_url", None),
            "expected_destination_url": getattr(result, "expected_destination_url", None),
            "observed_anchor_text": getattr(result, "observed_anchor_text", None),
            "evidence": getattr(result, "evidence", {}) or {},
        }
        error = getattr(result, "error", None)
        requires_human = bool(getattr(result, "requires_human", False)) or (
            status == STATUS_WAITING_FOR_USER
        )
        if status == STATUS_FAILED and error is None:
            error = details.get("message") or "The adapter did not report a result."
        return TaskOutcome(
            status=status,
            result=details,
            error=error,
            requires_human=requires_human,
        )

    def _execute_verify(
        self,
        context: Any,
        adapter: Any,
        payload: dict[str, Any],
    ) -> TaskOutcome:
        published_page_url = (
            payload.get("published_page_url")
            or payload.get("published_page")
            or payload.get("url")
        )
        expected_link = payload.get("expected_link_url") or payload.get("expected_link")
        expected_destination = payload.get("expected_destination_url") or payload.get(
            "expected_destination"
        )

        details: dict[str, Any] = {"adapter": getattr(adapter, "key", None)}
        evidence: dict[str, Any] = {}

        if published_page_url:
            verify = getattr(adapter, "verify", None)
            if callable(verify):
                try:
                    evidence = verify(context, str(published_page_url)) or {}
                except Exception as error:  # pragma: no cover - defensive
                    evidence = {"error": f"{type(error).__name__}: {error}"}
            else:
                evidence = self._http_verify(
                    str(published_page_url), expected_link, expected_destination
                )
            details["evidence"] = evidence

            link_present = evidence.get("link_present")
            destination_matched = evidence.get("destination_matched")
            if link_present and (destination_matched is not False):
                return TaskOutcome(
                    status=STATUS_VERIFIED_LIVE,
                    result=details,
                    error=None,
                )
            return TaskOutcome(
                status=STATUS_VERIFICATION_FAILED,
                result=details,
                error=evidence.get("error")
                or "The backlink was not found on the published page.",
            )

        return TaskOutcome(
            status=STATUS_WAITING_FOR_USER,
            result={**details, "requires_human": True},
            error="The task does not contain a published page - manual verification required.",
            requires_human=True,
        )

    def _http_verify(
        self,
        page_url: str,
        expected_link: str | None,
        expected_destination: str | None,
    ) -> dict[str, Any]:
        """A minimal link check (used when the adapter has no verify hook)."""
        parsed = urllib.parse.urlparse(page_url)
        if parsed.scheme not in ("http", "https"):
            return {"error": f"Unsupported URL scheme: {parsed.scheme}"}
        if not self._is_public_host(parsed.hostname or ""):
            return {"error": "Refusing to verify a private or local address"}

        request = urllib.request.Request(
            page_url,
            headers={"User-Agent": "AutoBacklinker-Agent/1.0 (+verification)"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read(2_000_000).decode("utf-8", errors="replace")
                status_code = response.status
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace") if hasattr(error, "read") else ""
            status_code = error.code
        except (urllib.error.URLError, OSError, TimeoutError) as error:
            return {"error": f"{type(error).__name__}: {error}"}

        link_present = bool(expected_link) and expected_link in body
        destination_matched = None
        if expected_destination:
            destination_matched = expected_destination in body
        return {
            "http_status": status_code,
            "link_present": link_present,
            "destination_matched": destination_matched,
            "checked_at": None,
        }

    @staticmethod
    def _is_public_host(host: str) -> bool:
        if not host:
            return False
        if host in ("localhost", "localhost.localdomain"):
            return False
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror:
            return False
        for info in infos:
            address = info[4][0]
            try:
                import ipaddress

                ip = ipaddress.ip_address(address)
            except ValueError:
                return False
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
        return True


__all__ = [
    "AdapterUnavailable",
    "TaskExecutor",
    "TaskOutcome",
]
