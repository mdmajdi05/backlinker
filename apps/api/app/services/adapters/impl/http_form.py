"""Configurable HTTP form adapter.

The adapter submits a plain HTML form with ``httpx`` - no JavaScript is
executed. Every request travels through :func:`app.core.net.safe_get`, so
the form URL *and* every redirect hop are validated against the SSRF rules
of the platform and ``settings.respect_robots`` is honoured.

The adapter never guesses: a submission is only reported as successful when
the configured success signal (a CSS selector or a success text) is really
present in the response. When the site answers with a CAPTCHA, a login wall
or a cookie consent wall the task is paused for a human - the automation
never tries to bypass such a challenge.
"""

from __future__ import annotations

import urllib.parse
from typing import Any, ClassVar

from bs4 import BeautifulSoup

from app.core.config import settings
from app.core.net import FetchResult, UnsafeUrlError, assert_public_url, safe_get
from app.services.adapters.base import (
    RESULT_SKIPPED,
    RESULT_SUBMITTED,
    RESULT_WAITING_USER,
    BaseAdapter,
    SubmissionContext,
    SubmissionResult,
    register_adapter,
)
from app.services.adapters.impl import (
    BodyClient,
    challenge_kind,
    rate_limit,
    render_template,
    submission_values,
)

_MAX_FOLLOW_UP_REDIRECTS = 3


class HttpFormAdapter(BaseAdapter):
    """Submits a plain HTML form using the configured selectors."""

    key = "http_form"
    name = "Configurable HTTP form adapter"
    kind = "BROWSER_AUTOMATION"
    description = "Submits a plain HTML form using configured selectors. No JavaScript execution."
    supported_categories: tuple[str, ...] = ()
    supported_methods: tuple[str, ...] = ("BROWSER_FORM",)
    supported_environments: tuple[str, ...] = ("CLOUD", "LOCAL")
    required_config: ClassVar[dict[str, Any]] = {
        "form_url": "string - URL of the submission form",
        "fields": "object - CSS selector to value mapping",
        "success_selector": "string - CSS selector proving success",
        "submit_selector": "string - CSS selector of the submit button",
    }
    required_user_fields: tuple[str, ...] = ("name", "website", "description")
    registration_required = False
    manual_approval_required = False
    automatable = True
    verification_method = "http_link_check"
    retryable_errors: tuple[str, ...] = ("timeout", "connection_reset", "http_5xx")
    restrictions = "Only works on sites that accept standard form posts without JavaScript challenges."
    success_signals: tuple[str, ...] = ("Success selector present in the response",)
    domains: tuple[str, ...] = ()

    def submit(self, ctx: SubmissionContext) -> SubmissionResult:
        """Fetch the form, fill it and post it."""
        config = ctx.adapter_config or {}
        form_url = str(config.get("form_url") or "").strip()
        if not form_url:
            # No adapter configuration for this site - the task needs a
            # human, it is not a technical failure.
            return self._needs_human(
                "This site has no http_form configuration yet (form_url is missing). "
                "Configure the adapter or complete the listing by hand."
            )

        try:
            assert_public_url(form_url)
        except UnsafeUrlError as exc:
            return self._failed(f"The configured form URL is not allowed: {exc}")

        rate_limit()
        page = safe_get(form_url, allow_robots=settings.respect_robots)
        blocked = _robots_blocked(page)
        if blocked is not None:
            return self._skipped(blocked)
        failure = _network_failure(page, "the submission form could not be loaded")
        if failure is not None:
            return failure
        if page.status_code >= 500:
            return self._failed(
                f"The form page answered with HTTP {page.status_code}.",
                retryable=True,
                evidence={"http_status": page.status_code},
            )
        if page.status_code >= 400:
            return self._failed(
                f"The form page answered with HTTP {page.status_code}.",
                evidence={"http_status": page.status_code},
            )

        challenge = challenge_kind(page.content)
        if challenge is not None:
            return self._waiting(challenge, page.final_url)

        form, _soup = _select_form(page.content, str(config.get("form_selector") or ""))
        if form is None:
            return self._failed("No <form> element was found on the configured form page.")

        values = submission_values(ctx)
        fields = config.get("fields") or {}
        if not isinstance(fields, dict):
            return self._failed("The 'fields' configuration must be an object of CSS selectors.")
        payload, missing = _apply_fields(form, fields, values)
        if missing:
            return self._failed(
                "The configured form fields were not found on the page: " + ", ".join(sorted(missing))
            )
        if not payload:
            return self._failed("The submission form does not expose any named field.")

        action_url = _action_url(form, page.final_url)
        method = str(form.get("method") or "POST").strip().upper() or "POST"
        try:
            assert_public_url(action_url)
        except UnsafeUrlError as exc:
            return self._failed(f"The form action URL is not allowed: {exc}")

        response = self._post(action_url, method, payload, config)
        if response is None:
            return self._failed("The form could not be submitted.")

        blocked = _robots_blocked(response)
        if blocked is not None:
            return self._skipped(blocked)
        failure = _network_failure(response, "the form submission failed")
        if failure is not None:
            return failure
        if response.status_code >= 500:
            return self._failed(
                f"The form submission was rejected with HTTP {response.status_code}.",
                retryable=True,
                evidence={"response_url": response.final_url, "http_status": response.status_code},
            )
        if response.status_code >= 400:
            return self._failed(
                f"The form submission was rejected with HTTP {response.status_code}.",
                evidence={"response_url": response.final_url, "http_status": response.status_code},
            )

        challenge = challenge_kind(response.content)
        if challenge is not None:
            return self._waiting(challenge, response.final_url)

        success, signal = _success_signal(response.content, config)
        if not success:
            return self._failed(
                "The form was submitted but no success signal was found in the response.",
                evidence={"response_url": response.final_url, "http_status": response.status_code},
            )

        published_page = _published_page(response.final_url, form_url)
        return SubmissionResult(
            status=RESULT_SUBMITTED,
            message=f"The form on {ctx.website.domain} was submitted and the success signal was found.",
            published_page_url=published_page,
            expected_destination_url=ctx.landing_page() or None,
            evidence={
                "form_url": form_url,
                "action_url": action_url,
                "method": method,
                "http_status": response.status_code,
                "response_url": response.final_url,
                "success_signal": signal,
                "submitted_fields": sorted(payload),
                "published_page_url_inferred": published_page is not None,
                "robots_respected": bool(settings.respect_robots),
            },
        )

    # -- helpers ------------------------------------------------------
    def _post(
        self,
        action_url: str,
        method: str,
        payload: dict[str, str],
        config: dict[str, Any],
    ) -> FetchResult | None:
        """Post *payload* to *action_url* and follow the redirect manually."""
        body = urllib.parse.urlencode(payload).encode("utf-8")
        headers = {str(k): str(v) for k, v in (config.get("headers") or {}).items()}
        client = BodyClient(
            body,
            "application/x-www-form-urlencoded",
            follow_redirects=False,
            timeout=settings.http_timeout,
        )
        try:
            response = safe_get(
                action_url,
                method=method,
                headers=headers,
                client=client,
                max_redirects=0,
                allow_robots=settings.respect_robots,
            )
        finally:
            client.close()

        # ``safe_get`` refuses to follow a redirect on its own for POST
        # requests (a redirect must become a GET), so it is handled here.
        hops = 0
        while response.error == "Too many redirects" and response.redirects:
            if hops >= _MAX_FOLLOW_UP_REDIRECTS:
                break
            location = response.redirects[-1]
            rate_limit()
            response = safe_get(location, method="GET", allow_robots=settings.respect_robots)
            hops += 1
        return response

    def _failed(
        self,
        message: str,
        retryable: bool = False,
        evidence: dict[str, Any] | None = None,
    ) -> SubmissionResult:
        return SubmissionResult(
            status="FAILED",
            message=message,
            error=message,
            retryable=retryable,
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

    def _needs_human(self, message: str) -> SubmissionResult:
        """The workflow needs a human - it is not a technical failure."""
        return SubmissionResult(
            status=RESULT_WAITING_USER,
            message=message,
            error=message,
            requires_human=True,
            evidence={"needs_human": True},
        )

    def _waiting(self, challenge: str, url: str) -> SubmissionResult:
        message = (
            f"The site answered with a {challenge.replace('_', ' ')} challenge on {url}. "
            "The automation was paused - please complete the submission manually."
        )
        return SubmissionResult(
            status=RESULT_WAITING_USER,
            message=message,
            error=message,
            requires_human=True,
            evidence={"challenge": challenge, "url": url},
        )


# -- module level helpers -------------------------------------------------


def _robots_blocked(result: FetchResult) -> str | None:
    """Return a message when the request was blocked by ``robots.txt``."""
    if result.error and "robots.txt" in result.error:
        return "robots.txt does not allow automated submissions for this URL - skipped."
    return None


def _network_failure(result: FetchResult, message: str) -> SubmissionResult | None:
    """Map a transport error onto a (retryable) failed result."""
    if not result.error:
        return None
    if "robots.txt" in result.error:
        return None
    if result.status_code >= 500:
        return SubmissionResult(
            status="FAILED",
            message=f"{message}: HTTP {result.status_code}.",
            error=result.error,
            retryable=True,
            evidence={"http_status": result.status_code},
        )
    return SubmissionResult(
        status="FAILED",
        message=f"{message}: {result.error}",
        error=result.error,
        retryable=True,
        evidence={},
    )


def _select_form(html: str, selector: str) -> tuple[Any, BeautifulSoup]:
    """Return the form element of *html* (and the parsed document)."""
    try:
        soup = BeautifulSoup(html or "", "lxml")
    except Exception:  # pragma: no cover - defensive, lxml is installed
        soup = BeautifulSoup(html or "", "html.parser")
    if selector:
        node = soup.select_one(selector)
        if node is None:
            return None, soup
        if node.name == "form":
            return node, soup
        found = node.find("form")
        return found, soup
    return soup.find("form"), soup


def _form_defaults(form: Any) -> dict[str, str]:
    """Collect the default values of the named form controls."""
    values: dict[str, str] = {}
    for element in form.find_all(["input", "textarea", "select", "button"]):
        name = element.get("name")
        if not name:
            continue
        tag = element.name
        if tag == "input":
            input_type = (element.get("type") or "text").strip().lower()
            if input_type in ("submit", "button", "image", "reset", "file"):
                continue
            if input_type in ("checkbox", "radio"):
                if element.has_attr("checked"):
                    values[name] = element.get("value") or "on"
                continue
            values[name] = element.get("value") or ""
        elif tag == "textarea":
            values[name] = element.get_text()
        elif tag == "select":
            option = element.find("option", selected=True) or element.find("option")
            if option is None:
                continue
            values[name] = option.get("value") if option.has_attr("value") else option.get_text(strip=True)
        elif tag == "button":
            values.setdefault(name, element.get("value") or "")
    return values


def _apply_fields(
    form: Any,
    fields: dict[str, Any],
    values: dict[str, str],
) -> tuple[dict[str, str], list[str]]:
    """Fill the configured fields. Returns ``(payload, missing_selectors)``."""
    payload = _form_defaults(form)
    missing: list[str] = []
    for selector, template in fields.items():
        element = form.select_one(str(selector))
        if element is None:
            missing.append(str(selector))
            continue
        name = element.get("name")
        if not name:
            missing.append(str(selector))
            continue
        value = render_template(str(template), values)
        input_type = (element.get("type") or "").strip().lower()
        if input_type == "checkbox":
            if value.strip().lower() in ("1", "true", "yes", "on"):
                payload[name] = element.get("value") or "on"
            else:
                payload.pop(name, None)
        elif input_type == "radio":
            if (element.get("value") or "") == value:
                payload[name] = value
            else:
                payload.pop(name, None)
        else:
            payload[name] = value
    return payload, missing


def _action_url(form: Any, page_url: str) -> str:
    """Resolve the URL the form is posted to."""
    action = (form.get("action") or "").strip()
    if not action:
        return page_url
    return urllib.parse.urljoin(page_url, action)


def _success_signal(html: str, config: dict[str, Any]) -> tuple[bool, str]:
    """Look for the configured success signal in the response."""
    success_text = str(config.get("success_text") or "").strip()
    if success_text and success_text.lower() in (html or "").lower():
        return True, f"success_text:{success_text}"
    selector = str(config.get("success_selector") or "").strip()
    if not selector:
        return False, ""
    try:
        soup = BeautifulSoup(html or "", "lxml")
    except Exception:  # pragma: no cover - defensive, lxml is installed
        soup = BeautifulSoup(html or "", "html.parser")
    try:
        found = soup.select_one(selector)
    except Exception:  # pragma: no cover - invalid selector
        found = None
    if found is not None:
        return True, f"success_selector:{selector}"
    return False, ""


def _published_page(response_url: str, form_url: str) -> str | None:
    """The page the site answered with is the best available guess."""
    if not response_url or response_url == form_url:
        return None
    if urllib.parse.urlparse(response_url).netloc != urllib.parse.urlparse(form_url).netloc:
        return None
    return response_url


register_adapter(HttpFormAdapter())
