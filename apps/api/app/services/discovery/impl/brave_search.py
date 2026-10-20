"""Brave Search discovery provider.

Queries the official Brave Search API
(``https://api.search.brave.com/res/v1/web/search``). The API key is read
from the configuration of the run, from the environment or from the
application settings - without a key the provider reports itself as
unavailable instead of pretending to work.

The provider only reports what the API returned: no traffic, no authority
and no publication status is invented for a result.
"""

from __future__ import annotations

import json
import urllib.parse
from typing import Any

from app.core.net import safe_get
from app.services.adapters.impl import rate_limit
from app.services.discovery.base import (
    DiscoveredSite,
    DiscoveryCriteria,
    DiscoveryProvider,
    register_provider,
)
from app.services.discovery.impl import (
    build_query,
    extract_page_details,
    infer_category,
    resolve_api_key,
)
from app.services.opportunities import extract_domain, normalize_url

API_URL = "https://api.search.brave.com/res/v1/web/search"


class BraveSearchProvider(DiscoveryProvider):
    """Web search results from the official Brave Search API."""

    key = "brave_search"
    name = "Brave Search API"
    description = "Web search results from the official Brave Search API."
    requires_credentials = True
    categories: tuple[str, ...] = ()
    default_limit = 25

    def available(self, config: dict[str, Any] | None = None) -> tuple[bool, str]:
        """Report whether an API key is configured."""
        if not resolve_api_key(self.key, config):
            return False, "Brave Search API key not configured"
        return True, ""

    def discover(self, criteria: DiscoveryCriteria) -> list[DiscoveredSite]:
        """Query the API and map the results onto discovered sites."""
        api_key = resolve_api_key(self.key, criteria.config)
        if not api_key:
            return []

        query = build_query(criteria)
        if not query:
            return []

        params: dict[str, Any] = {"q": query, "count": min(50, max(1, criteria.limit or 10))}
        if criteria.countries:
            params["country"] = str(criteria.countries[0]).upper()
        if criteria.language:
            params["search_lang"] = str(criteria.language)
        if criteria.config.get("country"):
            params["country"] = str(criteria.config["country"]).upper()

        url = f"{API_URL}?{urllib.parse.urlencode(params)}"
        rate_limit()
        response = safe_get(
            url,
            headers={
                "X-Subscription-Token": api_key,
                "Accept": "application/json",
            },
            allow_robots=False,
        )
        if response.error:
            raise RuntimeError(f"Brave Search API request failed: {response.error}")
        if response.status_code >= 400:
            raise RuntimeError(f"Brave Search API answered with HTTP {response.status_code}")
        try:
            document = json.loads(response.content or "{}")
        except (ValueError, TypeError) as exc:
            raise RuntimeError("Brave Search API did not answer with JSON") from exc

        results = _results(document)
        category = criteria.category or infer_category(query, criteria.keywords)
        sites: list[DiscoveredSite] = []
        seen: set[str] = set()
        for item in results:
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            normalized = normalize_url(url)
            domain = extract_domain(normalized)
            if not domain or domain in seen:
                continue
            seen.add(domain)
            sites.append(
                DiscoveredSite(
                    name=str(item.get("title") or domain),
                    domain=domain,
                    url=normalized,
                    category=str(category),
                    source=self.key,
                    provider=self.key,
                    description=str(item.get("description") or "") or None,
                    language=criteria.language,
                    region=criteria.countries[0] if criteria.countries else None,
                    submission_method="UNKNOWN",
                    registration_required=None,
                    requires_approval=None,
                    raw={
                        "title": item.get("title"),
                        "snippet": item.get("description"),
                        "page_age": item.get("page_age"),
                        "category_inferred": not criteria.category,
                    },
                )
            )
            if len(sites) >= (criteria.limit or self.default_limit):
                break
        return sites


def _results(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Read the ``web.results`` array of an API answer."""
    web = document.get("web")
    if not isinstance(web, dict):
        return []
    results = web.get("results")
    if not isinstance(results, list):
        return []
    return [item for item in results if isinstance(item, dict)]


def probe_page(url: str) -> dict[str, Any]:
    """Fetch a result page and return its observable details."""
    rate_limit()
    response = safe_get(url, allow_robots=True)
    if response.error or response.status_code >= 400:
        return {"url": url, "http_status": response.status_code, "error": response.error}
    details = extract_page_details(response.content, response.final_url)
    details["http_status"] = response.status_code
    details["url"] = response.final_url
    return details


register_provider(BraveSearchProvider())
