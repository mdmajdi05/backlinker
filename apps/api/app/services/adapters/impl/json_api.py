"""Documented JSON API adapter.

The adapter posts a configured JSON document to an endpoint the site
documents for public submissions. The endpoint is validated with
:func:`app.core.net.assert_public_url` before anything is sent, and the
request itself travels through :func:`app.core.net.safe_get` so the SSRF
protection of the platform applies.

A submission is only reported as successful when the configured
``success_field`` is really present in the JSON answer - the adapter never
guesses that an API accepted the payload.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from app.core.config import settings
from app.core.net import UnsafeUrlError, assert_public_url, safe_get
from app.services.adapters.base import (
    RESULT_SKIPPED,
    RESULT_SUBMITTED,
    BaseAdapter,
    SubmissionContext,
    SubmissionResult,
    register_adapter,
)
from app.services.adapters.impl import BodyClient, rate_limit, render_value, submission_values


class JsonApiAdapter(BaseAdapter):
    """Submits to a documented JSON endpoint using a templated payload."""

    key = "json_api"
    name = "Documented JSON API adapter"
    kind = "OFFICIAL_API"
    description = (
        "Submits to a documented JSON endpoint using configured headers and payload template."
    )
    supported_categories: tuple[str, ...] = ()
    supported_methods: tuple[str, ...] = ("API",)
    supported_environments: tuple[str, ...] = ("CLOUD", "LOCAL")
    required_config: ClassVar[dict[str, Any]] = {
        "endpoint": "string - fully qualified API endpoint",
        "method": "string - HTTP method (default POST)",
        "headers": "object - static headers (secrets belong in integration credentials)",
        "payload_template": "object - JSON body template with {{placeholders}}",
        "success_field": "string - JSON field proving success",
    }
    required_user_fields: tuple[str, ...] = ("name", "website", "description")
    registration_required = False
    manual_approval_required = False
    automatable = True
    verification_method = "http_link_check"
    retryable_errors: tuple[str, ...] = ("timeout", "connection_reset", "http_5xx", "http_429")
    restrictions = "Only use endpoints the site documents for public submissions."
    success_signals: tuple[str, ...] = ("Response contains the configured success field",)
    domains: tuple[str, ...] = ()

    def submit(self, ctx: SubmissionContext) -> SubmissionResult:
        """Post the templated payload and look for the success field."""
        config = ctx.adapter_config or {}
        endpoint = str(config.get("endpoint") or "").strip()
        if not endpoint:
            return self._failed("No 'endpoint' is configured for the json_api adapter.")

        try:
            assert_public_url(endpoint)
        except UnsafeUrlError as exc:
            return self._failed(f"The configured endpoint is not allowed: {exc}")

        template = config.get("payload_template")
        if template is None:
            template = {}
        if not isinstance(template, dict):
            return self._failed("The 'payload_template' configuration must be a JSON object.")

        payload = render_value(template, submission_values(ctx))
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        method = str(config.get("method") or "POST").strip().upper() or "POST"
        headers = {str(k): str(v) for k, v in (config.get("headers") or {}).items()}

        rate_limit()
        client = BodyClient(
            body,
            "application/json",
            follow_redirects=False,
            timeout=settings.http_timeout,
        )
        try:
            response = safe_get(
                endpoint,
                method=method,
                headers=headers,
                client=client,
                max_redirects=0,
                allow_robots=False,
            )
        finally:
            client.close()

        evidence: dict[str, Any] = {
            "endpoint": endpoint,
            "method": method,
            "http_status": response.status_code,
            "response_url": response.final_url,
        }

        if response.error and "robots.txt" in response.error:
            return self._skipped("robots.txt does not allow automated submissions for this URL.")
        if response.error:
            retryable = True
            return SubmissionResult(
                status="FAILED",
                message=f"The API request failed: {response.error}",
                error=response.error,
                retryable=retryable,
                evidence=evidence,
            )
        if response.status_code >= 500 or response.status_code == 429:
            return SubmissionResult(
                status="FAILED",
                message=f"The API answered with HTTP {response.status_code}.",
                error=f"HTTP {response.status_code}",
                retryable=True,
                evidence=evidence,
            )
        if response.status_code >= 400:
            return SubmissionResult(
                status="FAILED",
                message=f"The API rejected the submission with HTTP {response.status_code}.",
                error=f"HTTP {response.status_code}",
                retryable=False,
                evidence=evidence,
            )

        try:
            document = json.loads(response.content or "{}")
        except (ValueError, TypeError):
            document = None
        if not isinstance(document, dict):
            return self._failed(
                "The API did not answer with a JSON document - the success signal could not be read.",
                evidence=evidence,
            )

        success_field = str(config.get("success_field") or "").strip()
        if not success_field:
            return self._failed(
                "No 'success_field' is configured - without it a successful submission "
                "could not be proven.",
                evidence=evidence,
            )
        value = _dig(document, success_field)
        evidence["success_field"] = success_field
        evidence["success_field_value"] = value if isinstance(value, (str, int, float, bool)) else None
        if value is None or value is False or value == "":
            return self._failed(
                f"The API response does not contain the configured success field '{success_field}'.",
                evidence=evidence,
            )

        return SubmissionResult(
            status=RESULT_SUBMITTED,
            message=f"The API accepted the submission for {ctx.website.domain}.",
            expected_destination_url=ctx.landing_page() or None,
            evidence=evidence,
        )

    def _failed(self, message: str, evidence: dict[str, Any] | None = None) -> SubmissionResult:
        return SubmissionResult(
            status="FAILED",
            message=message,
            error=message,
            retryable=False,
            evidence=evidence or {},
        )

    def _skipped(self, message: str) -> SubmissionResult:
        return SubmissionResult(
            status=RESULT_SKIPPED,
            message=message,
            error=message,
            retryable=False,
            evidence={"skipped_reason": "robots"},
        )


def _dig(document: dict[str, Any], path: str) -> Any:
    """Read a dotted path (``data.id``) from a JSON document."""
    current: Any = document
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


register_adapter(JsonApiAdapter())
