"""Shared helpers for the automation layer.

The submission adapters and the discovery providers need the same low level
utilities, therefore they live here:

* :class:`RateLimiter` - a small in-process throttle that honours
  ``settings.max_requests_per_minute`` so the automation never hammers a
  third party site.
* :func:`challenge_kind` - detection of CAPTCHA / login / cookie-consent
  interstitials. The automation layer never tries to bypass such a
  challenge, it pauses the task and asks a human to take over.
* :func:`render_template` / :func:`render_value` - rendering of
  ``{{placeholder}}`` templates used by the form and API adapters.
* :class:`BodyClient` - an ``httpx`` client that attaches a prepared request
  body. It allows POST requests to travel through
  :func:`app.core.net.safe_get` and therefore keeps the SSRF protection of
  the platform (including the validation of every redirect hop).
* :func:`robots_allowed` - a ``robots.txt`` check for the browser adapter
  (the HTTP adapter relies on ``safe_get(allow_robots=True)``).
* :func:`submission_values` - the placeholder values (``{{name}}``,
  ``{{website}}``, ``{{description}}``, ...) used by the templates.
"""

from __future__ import annotations

import re
import threading
import time
import urllib.parse
import urllib.robotparser
from collections import deque
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from app.core.config import settings
from app.services.adapters.base import SubmissionContext

__all__ = [
    "BodyClient",
    "RateLimiter",
    "challenge_kind",
    "rate_limit",
    "render_template",
    "render_value",
    "robots_allowed",
    "submission_values",
]


class RateLimiter:
    """In-process throttle enforcing ``settings.max_requests_per_minute``."""

    def __init__(self, max_per_minute: int | None = None) -> None:
        limit = max_per_minute if max_per_minute is not None else settings.max_requests_per_minute
        self._limit = max(0, int(limit))
        self._timestamps: deque[float] = deque()
        self._lock = threading.Lock()

    @property
    def limit(self) -> int:
        """Maximum number of requests allowed per minute."""
        return self._limit

    def acquire(self) -> None:
        """Block until the next outbound request may be sent."""
        if self._limit <= 0:
            return
        while True:
            with self._lock:
                now = time.monotonic()
                while self._timestamps and (now - self._timestamps[0]) >= 60.0:
                    self._timestamps.popleft()
                if len(self._timestamps) < self._limit:
                    self._timestamps.append(now)
                    return
                wait = 60.0 - (now - self._timestamps[0])
            time.sleep(max(0.05, min(wait, 5.0)))


_LIMITER = RateLimiter()


def rate_limit() -> None:
    """Wait until the next outbound request is allowed."""
    _LIMITER.acquire()


# Challenge markers. A challenge always pauses the automation - the platform
# never attempts to solve a CAPTCHA, spoof a fingerprint or rotate proxies.
_CHALLENGE_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "captcha",
        (
            "captcha",
            "recaptcha",
            "hcaptcha",
            "g-recaptcha",
            "px-captcha",
            "are you a robot",
            "verify you are human",
            "verify that you are human",
            "unusual traffic from your computer",
            "checking your browser before accessing",
        ),
    ),
    (
        "login",
        (
            "sign in to continue",
            "log in to continue",
            "please log in",
            "please sign in",
            "login required",
            "you must log in",
            "you must be logged in",
            "authentication required",
            "session expired",
            "create a free account to continue",
        ),
    ),
    (
        "cookie_consent",
        (
            "accept all cookies",
            "cookie consent",
            "consent to continue",
            "gdpr consent",
            "cookie settings",
            "we value your privacy",
        ),
    ),
)


def challenge_kind(html: str) -> str | None:
    """Return the kind of human challenge found in *html* (or ``None``)."""
    lowered = (html or "").lower()
    for kind, markers in _CHALLENGE_MARKERS:
        for marker in markers:
            if marker in lowered:
                return kind
    return None


_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")


def render_template(value: str, mapping: Mapping[str, str]) -> str:
    """Replace every ``{{name}}`` placeholder of *value* with the mapping."""
    if not value:
        return ""

    def _replace(match: re.Match[str]) -> str:
        replacement = mapping.get(match.group(1))
        return match.group(0) if replacement is None else str(replacement)

    return _PLACEHOLDER.sub(_replace, value)


def render_value(value: Any, mapping: Mapping[str, str]) -> Any:
    """Recursively render placeholders inside strings, mappings and lists."""
    if isinstance(value, str):
        return render_template(value, mapping)
    if isinstance(value, Mapping):
        return {str(key): render_value(item, mapping) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [render_value(item, mapping) for item in value]
    return value


class BodyClient(httpx.Client):
    """``httpx`` client that attaches a prepared body to every request.

    :func:`app.core.net.safe_get` does not accept a request body, therefore
    the adapters use this client to post a form or a JSON document while the
    request itself still travels through ``safe_get`` - and therefore through
    the SSRF protection of the platform.
    """

    def __init__(self, body: bytes, content_type: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._body = body
        self._content_type = content_type

    def request(self, method: str, url: str | httpx.URL, **kwargs: Any) -> httpx.Response:
        """Send *method* to *url* with the prepared body attached."""
        headers = dict(kwargs.get("headers") or {})
        headers.setdefault("Content-Type", self._content_type)
        kwargs["headers"] = headers
        kwargs["content"] = self._body
        return super().request(method, url, **kwargs)


_ROBOT_PARSERS: dict[str, urllib.robotparser.RobotFileParser | None] = {}


def _robot_parser(origin: str) -> urllib.robotparser.RobotFileParser | None:
    """Parse (and cache) the ``robots.txt`` of *origin*."""
    if origin in _ROBOT_PARSERS:
        return _ROBOT_PARSERS[origin]
    from app.core.net import safe_get

    parser: urllib.robotparser.RobotFileParser | None = None
    response = safe_get(f"{origin}/robots.txt", allow_robots=False)
    if response.error is None and response.status_code == 200 and "html" not in response.headers.get(
        "content-type", ""
    ):
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(f"{origin}/robots.txt")
        parser.parse(response.content.splitlines())
    _ROBOT_PARSERS[origin] = parser
    return parser


def robots_allowed(url: str) -> bool:
    """Return ``True`` when ``robots.txt`` allows fetching *url*."""
    if not settings.respect_robots:
        return True
    parsed = urllib.parse.urlparse(url if "://" in url else f"https://{url}")
    origin = f"{parsed.scheme}://{parsed.netloc}"
    parser = _robot_parser(origin)
    if parser is None:
        return True
    return parser.can_fetch(settings.user_agent, url)


def submission_values(ctx: SubmissionContext) -> dict[str, str]:
    """Build the placeholder values available to the adapter templates.

    Only facts of the project / business profile are used - the automation
    never invents content for the operator.
    """
    website = ctx.website
    profile = ctx.profile
    project = ctx.project
    opportunity = ctx.opportunity
    landing_page = ctx.landing_page()
    anchor_text = website.anchor_text or _first(profile.preferred_anchors if profile else None)
    description = website.description or (profile.description if profile else "") or ""
    return {
        "name": (profile.name if profile else "") or website.name or website.domain,
        "website": (profile.primary_website if profile else "") or (project.target_website if project else ""),
        "url": landing_page,
        "landing_page": landing_page,
        "description": description,
        "anchor": anchor_text,
        "anchor_text": anchor_text,
        "email": (profile.contact_email if profile else "") or "",
        "phone": (profile.contact_phone if profile else "") or "",
        "address": (profile.address if profile else "") or "",
        "city": (profile.city if profile else "") or "",
        "state": (profile.state if profile else "") or "",
        "country": (profile.country if profile else "") or "",
        "postal_code": (profile.postal_code if profile else "") or "",
        "logo": (profile.logo_path if profile else "") or "",
        "industry": (profile.industry if profile else "") or "",
        "niche": (profile.niche if profile else "") or "",
        "category": website.category,
        "region": website.region or "",
        "language": website.language or "",
        "opportunity_url": website.opportunity_url,
        "contact_email": website.contact_email or "",
        "opportunity": (opportunity.notes if opportunity else "") or "",
    }


def _first(values: list[str] | None) -> str:
    """Return the first non empty entry of *values*."""
    for value in values or []:
        text = str(value or "").strip()
        if text:
            return text
    return ""
