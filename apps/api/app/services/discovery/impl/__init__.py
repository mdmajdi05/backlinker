"""Discovery provider implementations.

Every provider lives in its own module and registers itself through
:func:`app.services.discovery.base.register_provider`. The helpers of this
package are shared by the implementations:

* :func:`resolve_api_key` - finds the API key of a provider in the run
  configuration, in the environment or in the application settings.
* :func:`extract_page_details` - reads the observable title, description
  and text of a fetched page (nothing else is invented).
* :func:`build_query` - turns the criteria of a run into a search query.
* :func:`infer_category` - a small, documented keyword based classifier.

Importing this package registers every provider implementation.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from app.core.config import settings
from app.core.net import html_text
from app.services.discovery.base import DiscoveryCriteria

__all__ = [
    "brave_search",
    "build_query",
    "directory_index",
    "extract_page_details",
    "infer_category",
    "manual_seed",
    "resolve_api_key",
    "serpapi",
]

# Environment variables that may hold the API key of a provider.
_API_KEY_ENV: dict[str, tuple[str, ...]] = {
    "brave_search": ("AUTOBL_BRAVE_SEARCH_API_KEY", "BRAVE_SEARCH_API_KEY"),
    "serpapi": ("AUTOBL_SERPAPI_API_KEY", "SERPAPI_API_KEY"),
}

# Categories that can be recognised from the query of a run.
_CATEGORY_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("BUSINESS_DIRECTORY", ("business directory", "local listing", "yellow pages", "listing site")),
    ("INDUSTRY_DIRECTORY", ("industry directory", "niche directory", "vendor directory")),
    ("LOCAL_CITATION", ("local citation", "local seo", "map listing")),
    ("BUSINESS_PROFILE", ("business profile", "company profile", "about us page")),
    ("SOCIAL_PROFILE", ("social profile", "social media")),
    ("PUBLIC_PROFILE", ("author profile", "portfolio", "creator profile")),
    ("EDITORIAL", ("guest post", "write for us", "contribute an article", "editorial")),
    ("GUEST_POST", ("guest post", "guest article", "write for us")),
    ("RESOURCE_PAGE", ("resource page", "curated list", "list of tools", "link list", "resources")),
    ("FORUM_COMMUNITY", ("forum", "community", "discussion board", "reddit")),
    ("QA_CONTRIBUTION", ("stack overflow", "quora", "q&a", "answer")),
    ("DOCUMENT_SHARING", ("slideshare", "scribd", "issuu", "document sharing")),
    ("IMAGE_ATTRIBUTION", ("flickr", "unsplash", "pexels", "image attribution")),
    ("BROKEN_LINK", ("broken link", "dead link")),
    ("UNLINKED_MENTION", ("unlinked mention", "brand mention")),
)


def resolve_api_key(provider_key: str, config: Mapping[str, Any] | None) -> str | None:
    """Find the API key of a provider.

    The key is looked up in the configuration of the run first (that is
    what the API endpoint sends), then in the environment and finally in
    the application settings. ``None`` is returned when no key is
    configured - the provider then reports itself as unavailable.
    """
    config = config or {}
    for key in ("api_key", "apiKey", "token", "subscription_token"):
        value = config.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for env_name in _API_KEY_ENV.get(provider_key, ()):
        value = os.environ.get(env_name)
        if value and value.strip():
            return value.strip()
    settings_value = getattr(settings, f"{provider_key}_api_key", None)
    if isinstance(settings_value, str) and settings_value.strip():
        return settings_value.strip()
    return None


def extract_page_details(html: str, base_url: str = "") -> dict[str, Any]:
    """Read the observable title, description and text of a fetched page."""
    details: dict[str, Any] = {"title": "", "description": "", "text": ""}
    if not html:
        return details
    try:
        from bs4 import BeautifulSoup

        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:  # pragma: no cover - defensive, lxml is installed
            soup = BeautifulSoup(html, "html.parser")
        if soup.title and soup.title.string:
            details["title"] = soup.title.string.strip()
        for meta in soup.find_all("meta"):
            name = (meta.get("name") or meta.get("property") or "").strip().lower()
            if name in ("description", "og:description") and meta.get("content"):
                details["description"] = str(meta["content"]).strip()
                break
    except ImportError:  # pragma: no cover - beautifulsoup is a hard dependency
        pass
    details["text"] = html_text(html)
    if base_url:
        details["url"] = base_url
    return details


def build_query(criteria: DiscoveryCriteria) -> str:
    """Build the search query of a run."""
    parts: list[str] = []
    if criteria.query:
        parts.append(criteria.query.strip())
    for keyword in criteria.keywords or []:
        text = str(keyword).strip()
        if text and text.lower() not in [part.lower() for part in parts]:
            parts.append(text)
    return " ".join(parts).strip()


def infer_category(query: str, keywords: list[str] | None = None) -> str:
    """Classify a search result with documented keyword rules."""
    haystack = " ".join([query or ""] + [str(item) for item in (keywords or [])]).lower()
    for category, hints in _CATEGORY_HINTS:
        if any(hint in haystack for hint in hints):
            return category
    return "RESOURCE_PAGE"


def host_of(url: str) -> str:
    """Return the host of *url* without the ``www.`` prefix."""
    cleaned = (url or "").strip().lower()
    for scheme in ("https://", "http://"):
        if cleaned.startswith(scheme):
            cleaned = cleaned[len(scheme) :]
            break
    host = cleaned.split("/")[0].split(":")[0]
    return host.removeprefix("www.")


def _register_implementations() -> None:
    """Import every implementation module so that it registers itself."""
    from importlib import import_module

    for name in ("brave_search", "directory_index", "manual_seed", "serpapi"):
        import_module(f"{__name__}.{name}")


_register_implementations()
