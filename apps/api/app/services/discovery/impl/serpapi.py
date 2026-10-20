"""SerpAPI discovery provider.

Queries SerpAPI (``https://serpapi.com/search?engine=google&q=...``). The
API key is read from the configuration of the run, from the environment or
from the application settings - without a key the provider reports itself
as unavailable instead of pretending to work.

Only what the API really returned is mapped onto a discovered site.
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

API_URL = "https://serpapi.com/search"


class SerpApiProvider(DiscoveryProvider):
    """Search results through SerpAPI (Google, Bing, ...)."""

    key = "serpapi"
    name = "SerpAPI"
    description = "Search results through SerpAPI (Google, Bing, ...)."
    requires_credentials = True
    categories: tuple[str, ...] = ()
    default_limit = 25

    def available(self, config: dict[str, Any] | None = None) -> tuple[bool, str]:
        """Report whether an API key is configured."""
        if not resolve_api_key(self.key, config):
            return False, "SerpAPI key not configured"
        return True, ""

    def discover(self, criteria: DiscoveryCriteria) -> list[DiscoveredSite]:
        """Query the API and map the results onto discovered sites."""
        api_key = resolve_api_key(self.key, criteria.config)
        if not api_key:
            return []

        query = build_query(criteria)
        if not query:
            return []

        params: dict[str, Any] = {
            "engine": str(criteria.config.get("engine") or "google"),
            "q": query,
            "api_key": api_key,
            "num": min(100, max(1, criteria.limit or 10)),
        }
        if criteria.language:
            params["hl"] = str(criteria.language)
        if criteria.countries:
            params["gl"] = str(criteria.countries[0]).lower()

        url = f"{API_URL}?{urllib.parse.urlencode(params)}"
        rate_limit()
        response = safe_get(url, headers={"Accept": "application/json"}, allow_robots=False)
        if response.error:
            raise RuntimeError(f"SerpAPI request failed: {response.error}")
        if response.status_code >= 400:
            raise RuntimeError(f"SerpAPI answered with HTTP {response.status_code}")
        try:
            document = json.loads(response.content or "{}")
        except (ValueError, TypeError) as exc:
            raise RuntimeError("SerpAPI did not answer with JSON") from exc

        results = _results(document)
        category = criteria.category or infer_category(query, criteria.keywords)
        sites: list[DiscoveredSite] = []
        seen: set[str] = set()
        for item in results:
            link = str(item.get("link") or item.get("url") or "").strip()
            if not link:
                continue
            normalized = normalize_url(link)
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
                    description=str(item.get("snippet") or "") or None,
                    language=criteria.language,
                    region=criteria.countries[0] if criteria.countries else None,
                    submission_method="UNKNOWN",
                    registration_required=None,
                    requires_approval=None,
                    raw={
                        "title": item.get("title"),
                        "snippet": item.get("snippet"),
                        "position": item.get("position"),
                        "category_inferred": not criteria.category,
                    },
                )
            )
            if len(sites) >= (criteria.limit or self.default_limit):
                break
        return sites


def _results(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Read the ``organic_results`` array of an API answer."""
    results = document.get("organic_results")
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


register_provider(SerpApiProvider())
