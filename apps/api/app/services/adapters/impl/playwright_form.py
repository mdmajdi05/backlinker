"""Playwright browser adapter.

The adapter drives a real browser for sites whose submission form only
works with JavaScript. It is deliberately conservative:

* when the Playwright runtime (or the browser binary) is missing the task
  is paused for a human - the adapter never fakes a success,
* a CAPTCHA, a login wall or a cookie consent wall pauses the task as
  well; the automation never tries to bypass such a challenge,
* a screenshot of the final state is stored as evidence so an operator can
  see what happened.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from app.core.config import settings
from app.core.net import UnsafeUrlError, assert_public_url
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
    challenge_kind,
    rate_limit,
    render_template,
    robots_allowed,
    submission_values,
)
from app.services.browser import ISOLATION_ARGS

_DEFAULT_TIMEOUT_MS = 30_000
_MISSING_RUNTIME = "Playwright browser runtime is not installed"


class PlaywrightFormAdapter(BaseAdapter):
    """Permitted browser automation driven by the configured selectors."""

    key = "playwright_form"
    name = "Playwright browser adapter"
    kind = "BROWSER_AUTOMATION"
    description = "Permitted browser automation driven by configured selectors."
    supported_categories: tuple[str, ...] = ()
    supported_methods: tuple[str, ...] = ("BROWSER_FORM",)
    supported_environments: tuple[str, ...] = ("CLOUD", "LOCAL")
    required_config: ClassVar[dict[str, Any]] = {
        "form_url": "string - URL of the submission form",
        "fields": "object - CSS selector to value mapping",
        "success_selector": "string - CSS selector proving success",
    }
    required_user_fields: tuple[str, ...] = ("name", "website", "description")
    registration_required = False
    manual_approval_required = False
    automatable = True
    verification_method = "http_link_check"
    retryable_errors: tuple[str, ...] = ("timeout", "connection_reset", "http_5xx")
    restrictions = "Pauses for manual intervention when a CAPTCHA or login challenge is detected."
    success_signals: tuple[str, ...] = ("Success selector present after submission",)
    domains: tuple[str, ...] = ()

    def submit(self, ctx: SubmissionContext) -> SubmissionResult:
        """Fill the form in a real browser and look for the success signal."""
        if not settings.allow_browser_automation:
            return self._waiting("Browser automation is disabled in the application settings.")

        config = ctx.adapter_config or {}
        form_url = str(config.get("form_url") or "").strip()
        if not form_url:
            return self._failed("No 'form_url' is configured for the playwright_form adapter.")

        try:
            assert_public_url(form_url)
        except UnsafeUrlError as exc:
            return self._failed(f"The configured form URL is not allowed: {exc}")

        if not robots_allowed(form_url):
            return self._skipped("robots.txt does not allow automated submissions for this URL.")

        try:
            from app.services.browser import ensure_playwright_path

            ensure_playwright_path()
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError:
            return self._waiting(f"{_MISSING_RUNTIME} - install it with 'playwright install'.")

        values = submission_values(ctx)
        fields = config.get("fields") or {}
        if not isinstance(fields, dict):
            return self._failed("The 'fields' configuration must be an object of CSS selectors.")

        timeout_ms = int(config.get("timeout_ms") or _DEFAULT_TIMEOUT_MS)
        rate_limit()
        headless = ctx.headless
        try:
            with sync_playwright() as playwright:
                try:
                    browser = playwright.chromium.launch(
                        headless=headless,
                        args=list(ISOLATION_ARGS),
                    )
                except PlaywrightError as exc:
                    return self._waiting(f"{_MISSING_RUNTIME}: {exc}")
                try:
                    # A fresh, throw away context: no cookie, no storage and
                    # no profile of the personal browser of the user is used.
                    context = browser.new_context(
                        user_agent=settings.user_agent,
                        storage_state=None,
                    )
                    page = context.new_page()
                    page.set_default_timeout(timeout_ms)
                    return self._run_form(
                        ctx,
                        page,
                        form_url,
                        fields,
                        values,
                        config,
                        timeout_ms,
                        PlaywrightError,
                        PlaywrightTimeoutError,
                    )
                finally:
                    browser.close()
        except PlaywrightTimeoutError as exc:  # pragma: no cover - timing dependent
            return self._failed(f"The browser timed out: {exc}", retryable=True)
        except PlaywrightError as exc:
            return self._failed(f"The browser reported an error: {exc}", retryable=True)

    # -- helpers ------------------------------------------------------
    def _run_form(
        self,
        ctx: SubmissionContext,
        page: Any,
        form_url: str,
        fields: dict[str, Any],
        values: dict[str, str],
        config: dict[str, Any],
        timeout_ms: int,
        playwright_error: type[Exception],
        playwright_timeout: type[Exception],
    ) -> SubmissionResult:
        """Open the form, fill it, submit it and look for the success signal."""
        if ctx.cancelled():
            return self._cancelled()
        page.goto(form_url, wait_until="domcontentloaded", timeout=timeout_ms)
        content = page.content()
        challenge = challenge_kind(content)
        if challenge is not None:
            screenshot = self._screenshot(ctx, page)
            return self._waiting(
                f"The site answered with a {challenge.replace('_', ' ')} challenge on {form_url}. "
                "The automation was paused - please complete the submission manually.",
                evidence={"challenge": challenge, "url": form_url, "screenshot": screenshot},
            )

        for selector, template in fields.items():
            if ctx.cancelled():
                return self._cancelled()
            value = render_template(str(template), values)
            try:
                _fill(page, str(selector), value, timeout_ms)
            except playwright_error as exc:
                return self._failed(
                    f"The configured form field '{selector}' could not be filled: {exc}"
                )

        if ctx.cancelled():
            return self._cancelled()
        submit_selector = str(config.get("submit_selector") or "").strip()
        try:
            if submit_selector:
                page.click(submit_selector, timeout=timeout_ms)
            else:
                page.click("button[type=submit], input[type=submit]", timeout=timeout_ms)
        except playwright_timeout as exc:
            screenshot = self._screenshot(ctx, page)
            return self._failed(
                f"The submit button did not respond: {exc}",
                retryable=True,
                evidence={"screenshot": screenshot},
            )
        except playwright_error as exc:
            return self._failed(f"The form could not be submitted: {exc}")

        success_selector = str(config.get("success_selector") or "").strip()
        if not success_selector:
            screenshot = self._screenshot(ctx, page)
            return self._failed(
                "No 'success_selector' is configured - without it a successful submission "
                "could not be proven.",
                evidence={"screenshot": screenshot, "final_url": page.url},
            )
        try:
            page.wait_for_selector(success_selector, timeout=timeout_ms)
        except playwright_timeout as exc:
            screenshot = self._screenshot(ctx, page)
            return self._failed(
                f"The success selector '{success_selector}' never appeared: {exc}",
                retryable=True,
                evidence={"screenshot": screenshot, "final_url": page.url},
            )

        screenshot = self._screenshot(ctx, page)
        return SubmissionResult(
            status=RESULT_SUBMITTED,
            message=f"The form on {ctx.website.domain} was submitted and the success signal was found.",
            published_page_url=page.url if page.url != form_url else None,
            expected_destination_url=ctx.landing_page() or None,
            evidence={
                "form_url": form_url,
                "final_url": page.url,
                "success_signal": f"success_selector:{success_selector}",
                "screenshot": screenshot,
                "headless": bool(settings.playwright_headless),
            },
        )

    def _cancelled(self) -> SubmissionResult:
        """The task was cancelled (or the whole execution was stopped)."""
        return SubmissionResult(
            status=RESULT_WAITING_USER,
            message=(
                "The task was cancelled before the browser finished - nothing was submitted."
            ),
            error="Cancelled",
            requires_human=True,
            evidence={"cancelled": True},
        )

    def _screenshot(self, ctx: SubmissionContext, page: Any) -> str | None:
        """Store a screenshot of the current page as evidence."""
        directory = ctx.evidence_dir or (settings.managed_files_dir / "evidence")
        try:
            directory.mkdir(parents=True, exist_ok=True)
            name = f"playwright-{ctx.task.id}-{page.url[-40:].replace('/', '_')}.png"
            target: Path = directory / name
            page.screenshot(path=str(target))
            return str(target)
        except Exception:
            return None

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

    def _waiting(self, message: str, evidence: dict[str, Any] | None = None) -> SubmissionResult:
        return SubmissionResult(
            status=RESULT_WAITING_USER,
            message=message,
            error=message,
            requires_human=True,
            evidence=evidence or {},
        )


def _fill(page: Any, selector: str, value: str, timeout_ms: int) -> None:
    """Fill a single form control, whatever its type is."""
    element_type = str(
        page.eval_on_selector(
            selector,
            "el => (el.getAttribute('type') || el.tagName || '').toLowerCase()",
        )
        or ""
    )
    if element_type in ("checkbox", "radio"):
        page.check(selector, timeout=timeout_ms)
        return
    if element_type == "select":
        page.select_option(selector, value, timeout=timeout_ms)
        return
    page.fill(selector, value, timeout=timeout_ms)


register_adapter(PlaywrightFormAdapter())
