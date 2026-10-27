"""Find the submission form of a directory.

Most directories do not publish their form URL in a machine readable way: the
homepage has a link called "Add your business", "Submit a listing" or "Get
listed".  This module follows those links (best effort), inspects the candidate
pages and returns the first one that really contains a form with named
controls.  It never submits anything - the operator still reviews and saves the
mapping.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any

from bs4 import BeautifulSoup

from app.core.config import settings
from app.core.net import safe_get, validate_http_url
from app.services.automation_setup import inspect_form_url

#: Words that appear in the link that leads to a submission form.
_LINK_WORDS = (
    "add your business",
    "add business",
    "add your listing",
    "add listing",
    "add a listing",
    "submit your business",
    "submit business",
    "submit a listing",
    "submit listing",
    "submit your website",
    "submit website",
    "submit your site",
    "submit site",
    "submit url",
    "add url",
    "add website",
    "add your website",
    "get listed",
    "list your business",
    "create listing",
    "create a listing",
    "post your business",
    "post a listing",
    "new listing",
    "add company",
    "submit company",
)

#: URL fragments that usually point at a submission page.
_URL_WORDS = (
    "add",
    "submit",
    "listing",
    "list-your",
    "get-listed",
    "new",
    "create",
    "post",
    "directory",
    "business",
)

#: Links that are never a submission form.
_SKIP_WORDS = (
    "login",
    "signin",
    "sign-in",
    "register",
    "privacy",
    "terms",
    "contact",
    "about",
    "pricing",
    "blog",
)

MAX_CANDIDATES = 8
MAX_INSPECT = 4


def find_submission_page(
    db: Any, website: Any, start_url: str | None = None
) -> dict[str, Any]:
    """Return the best submission form URL and its proposed field mapping."""
    del db  # the finder only needs HTTP, not the database
    base = (
        (start_url or "").strip()
        or (website.opportunity_url or "").strip()
        or (website.domain or "").strip()
    )
    if not base:
        return _empty("", "No website URL is known.")
    if not base.startswith(("http://", "https://")):
        base = "https://" + base
    try:
        base = validate_http_url(base)
    except ValueError as exc:
        return _empty(base, str(exc))

    # The URL may already be the form page - try it first.
    direct = inspect_form_url(base)
    if direct.get("fields") and not _is_login_form(direct):
        return {
            **direct,
            "found": True,
            "start_url": base,
            "candidates": [],
        }

    response = safe_get(base, allow_robots=settings.respect_robots)
    if response.error:
        return {
            **_empty(base, response.error),
            "candidates": [],
        }
    if response.status_code >= 400:
        return {
            **_empty(base, f"The website answered with HTTP {response.status_code}."),
            "candidates": [],
        }

    soup = BeautifulSoup(response.content, "lxml")
    candidates = _candidates(soup, response.final_url or base)
    inspected: list[dict[str, Any]] = []
    for candidate in candidates[:MAX_INSPECT]:
        result = inspect_form_url(candidate["url"])
        inspected.append(
            {
                "url": candidate["url"],
                "label": candidate["label"],
                "fields": len(result.get("fields") or []),
                "message": result.get("message"),
            }
        )
        if result.get("fields") and not _is_login_form(result):
            return {
                **result,
                "found": True,
                "start_url": base,
                "candidates": candidates,
                "inspected": inspected,
            }

    message = (
        "No submission form was found. The page may need JavaScript, or the "
        "site may only accept listings after a login. Add the form URL and the "
        "selectors by hand, or keep this website on the manual path."
    )
    return {
        **_empty(base, message),
        "candidates": candidates,
        "inspected": inspected,
    }


def _empty(url: str, message: str) -> dict[str, Any]:
    return {
        "start_url": url,
        "found": False,
        "form_url": "",
        "final_url": "",
        "reachable": False,
        "http_status": 0,
        "form_found": False,
        "fields": [],
        "has_captcha": False,
        "has_password": False,
        "message": message,
        "candidates": [],
        "inspected": [],
    }


def _candidates(soup: BeautifulSoup, base: str) -> list[dict[str, Any]]:
    """Score the links of a page and return the plausible submission pages."""
    host = urllib.parse.urlparse(base).netloc.lower()
    scored: dict[str, dict[str, Any]] = {}
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        url = urllib.parse.urljoin(base, href)
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            continue
        if parsed.netloc.lower() != host:
            continue
        path = (parsed.path or "/").lower()
        if any(word in path for word in _SKIP_WORDS):
            continue
        label = " ".join(anchor.get_text(" ", strip=True).split())
        haystack = f"{label} {path}".lower()
        score = 0
        for word in _LINK_WORDS:
            if word in haystack:
                score += 10
        for word in _URL_WORDS:
            if word in path:
                score += 2
        if "/add" in path or "/submit" in path or "listing" in path:
            score += 5
        if score <= 0:
            continue
        key = url.rstrip("/")
        existing = scored.get(key)
        if existing is None or existing["score"] < score:
            scored[key] = {
                "url": key,
                "label": label or path,
                "score": score,
            }
    return sorted(scored.values(), key=lambda item: (-item["score"], item["url"]))


def looks_like_login(url: str) -> bool:
    """A cheap guard so a login link is never proposed as the form."""
    path = urllib.parse.urlparse(url).path.lower()
    return bool(re.search(r"/(log-?in|sign-?in|register|auth)(/|$)", path))


def _is_login_form(result: dict[str, Any]) -> bool:
    """Whether an inspected page is a login form instead of a submission form.

    A page that redirected to a login URL, or that only has a password and one
    more control, must never be offered as the submission form - the operator
    would configure a form that can only fail.
    """
    url = str(result.get("final_url") or result.get("form_url") or "")
    if looks_like_login(url):
        return True
    fields = result.get("fields") or []
    return bool(result.get("has_password")) and len(fields) <= 2
