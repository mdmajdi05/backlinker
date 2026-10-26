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

import time
from contextlib import suppress
from pathlib import Path
from typing import Any, ClassVar

from app.core.config import settings
from app.core.net import UnsafeUrlError, assert_public_url
from app.services import project_login
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
        "success_selector": "string - CSS selector proving success (or success_text / success_url_contains)",
    }
    required_user_fields: tuple[str, ...] = ("name", "website", "description")
    registration_required = False
    manual_approval_required = False
    automatable = True
    verification_method = "http_link_check"
    retryable_errors: tuple[str, ...] = ("timeout", "connection_reset", "http_5xx")
    restrictions = "Pauses for manual intervention when a CAPTCHA or login challenge is detected."
    success_signals: tuple[str, ...] = (
        "Success selector present after submission",
        "Success text present after submission",
        "Success URL fragment present after submission",
    )
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
                        storage_state=ctx.login_state,
                    )
                    page = context.new_page()
                    page.set_default_timeout(timeout_ms)
                    try:
                        return self._run_form(
                            ctx,
                            context,
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
                        self._persist_state(ctx, context)
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
        context: Any,
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

        # A login wall is not a CAPTCHA: when the project carries a Google
        # session the site's own "Continue with Google" button is clicked.
        # The Google password / account chooser is never filled by the
        # automation - a human finishes that in the project login window.
        if project_login.page_requires_login(page):
            if ctx.login_state and self._try_google_login(
                context, page, form_url, timeout_ms
            ):
                if project_login.page_requires_login(page):
                    return self._login_required(
                        form_url, "The site still asks for a login after Google sign-in."
                    )
            else:
                return self._login_required(
                    form_url,
                    "This website asks for a login. Connect Google for this project "
                    "or log in to the website, then start the work again.",
                )

        content = page.content()
        challenge = challenge_kind(content)
        if challenge == "login":
            return self._login_required(
                form_url, "The site answered with a login challenge."
            )
        if challenge is not None:
            screenshot = self._screenshot(ctx, page)
            return self._waiting(
                f"The site answered with a {challenge.replace('_', ' ')} challenge on {form_url}. "
                "The automation was paused - please complete the submission manually.",
                evidence={"challenge": challenge, "url": form_url, "screenshot": screenshot},
            )

        # Refuse to submit anything when the configuration cannot prove the
        # result.  A form that was sent without a success signal is exactly the
        # case where the application would otherwise have to guess.
        success_selector = str(config.get("success_selector") or "").strip()
        success_text = str(config.get("success_text") or "").strip()
        success_url_contains = str(config.get("success_url_contains") or "").strip()
        if not (success_selector or success_text or success_url_contains):
            return self._failed(
                "No success signal is configured (success_selector, success_text or "
                "success_url_contains) - nothing was submitted."
            )
        if success_selector:
            # A broken selector must be reported before the form is sent, not
            # after a submission that cannot be checked.
            try:
                page.locator(success_selector).count()
            except playwright_error as exc:
                return self._failed(
                    f"The configured success selector is not valid: {exc}"
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
        click_error: Exception | None = None
        try:
            if submit_selector:
                page.click(submit_selector, timeout=timeout_ms)
            else:
                page.click("button[type=submit], input[type=submit]", timeout=timeout_ms)
        except (playwright_timeout, playwright_error) as exc:
            # The click may have been dispatched before the error.  Do not
            # return a retryable failure - a retry could submit twice.  We
            # still check the success signal below; if it is absent the task
            # is handed to a human.
            click_error = exc

        signal = self._wait_for_success(
            page,
            success_selector,
            success_text,
            success_url_contains,
            timeout_ms,
            playwright_error,
        )
        if signal is None:
            screenshot = self._screenshot(ctx, page)
            if click_error is not None:
                message = (
                    "The submit button reported an error, so it is not clear whether "
                    "the form was sent. Check the site; if the submission exists, "
                    "mark it submitted. It was not marked submitted automatically."
                )
            else:
                message = (
                    "The form was sent, but the configured success signal did not appear. "
                    "Check the site; if the submission exists, mark it submitted. "
                    "It was not marked submitted automatically."
                )
            return self._waiting(
                message,
                evidence={
                    "screenshot": screenshot,
                    "final_url": page.url,
                    "success_signal_timeout": f"{timeout_ms} ms",
                    "submit_click_error": str(click_error) if click_error else None,
                },
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
                "success_signal": signal,
                "screenshot": screenshot,
                "headless": bool(settings.playwright_headless),
            },
        )

    @staticmethod
    def _wait_for_success(
        page: Any,
        success_selector: str,
        success_text: str,
        success_url_contains: str,
        timeout_ms: int,
        playwright_error: type[Exception],
    ) -> str | None:
        """Poll for the success signal across page navigations.

        ``wait_for_function`` can fail with "execution context was destroyed"
        when the form navigates to a confirmation page.  The loop treats that
        as "not yet" and keeps checking the new document, so a real success is
        not turned into a failed task (which could submit the form twice).
        """
        deadline = time.monotonic() + (timeout_ms / 1000.0)
        while time.monotonic() < deadline:
            try:
                if success_selector:
                    locator = page.locator(success_selector)
                    if locator.count() > 0 and locator.first.is_visible():
                        return f"success_selector:{success_selector}"
                elif success_text:
                    body = page.evaluate(
                        "() => (document.body ? document.body.innerText : '')"
                    )
                    if success_text.lower() in str(body or "").lower():
                        return f"success_text:{success_text}"
                elif success_url_contains and success_url_contains in page.url:
                    return f"success_url_contains:{success_url_contains}"
            except playwright_error:
                # A navigation destroys the old execution context.  Keep
                # polling the new page instead of declaring a failure.
                pass
            try:
                page.wait_for_timeout(250)
            except playwright_error:
                return None
        return None

    def _try_google_login(
        self,
        context: Any,
        page: Any,
        form_url: str,
        timeout_ms: int,
    ) -> bool:
        """Click the site's Google button and see whether the wall disappears.

        Only the site's own button is clicked.  Google's account chooser,
        password field and two factor prompt are handled by the operator in the
        visible login window; if they appear here the task is handed back.
        """
        import re

        pattern = re.compile(
            r"(continue|sign in|log in|login).{0,24}google|google.{0,24}(continue|sign in|log in|login)",
            re.IGNORECASE,
        )
        locator = (
            page.locator("button, a, input[type=submit]")
            .filter(has_text=pattern)
            .first
        )
        try:
            if locator.count() == 0 or not locator.is_visible():
                return False
            popup = None
            try:
                with context.expect_page(timeout=8_000) as popup_info:
                    locator.click(timeout=5_000)
                popup = popup_info.value
            except Exception:
                popup = None

            if popup is not None:
                with suppress(Exception):
                    popup.wait_for_load_state("domcontentloaded", timeout=15_000)
                # Google may show an account chooser.  Wait briefly for an
                # automatic continuation, then give the task back to the human.
                deadline = 10
                while deadline > 0 and "accounts.google.com" in str(popup.url or ""):
                    with suppress(Exception):
                        popup.wait_for_timeout(500)
                    deadline -= 0.5
                still_google = "accounts.google.com" in str(popup.url or "")
                with suppress(Exception):
                    popup.close()
                if still_google:
                    return False
            else:
                # The OAuth flow may stay in the same tab.  Give Google time to
                # redirect back - and hand the task back when it still shows
                # the account chooser instead of filling it.
                deadline = 10.0
                while deadline > 0 and "accounts.google.com" in str(page.url or ""):
                    with suppress(Exception):
                        page.wait_for_timeout(500)
                    deadline -= 0.5
                if "accounts.google.com" in str(page.url or ""):
                    return False
                with suppress(Exception):
                    page.wait_for_timeout(1_000)

            # The site usually redirects to a dashboard after the OAuth flow.
            if str(page.url or "") != form_url:
                page.goto(form_url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_timeout(1_000)
            except Exception:
                return False
            return not project_login.page_requires_login(page)
        except Exception:
            return False

    def _persist_state(self, ctx: SubmissionContext, context: Any) -> None:
        """Store a refreshed session after the browser was used."""
        if ctx.login_state is None or ctx.save_login_state is None:
            return
        with suppress(Exception):
            # The browser may already be gone; a lost cookie refresh must not
            # fail the submission that just succeeded.
            ctx.save_login_state(context.storage_state())

    def _login_required(self, form_url: str, message: str) -> SubmissionResult:
        return SubmissionResult(
            status=RESULT_WAITING_USER,
            message=message,
            error=f"{project_login.LOGIN_REQUIRED_PREFIX} {message}",
            requires_human=True,
            evidence={"login_required": True, "url": form_url},
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
