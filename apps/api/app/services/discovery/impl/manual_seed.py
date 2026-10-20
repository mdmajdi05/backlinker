"""Manual seed discovery provider.

Uses the URLs (or domains) an operator supplies. The provider does not
guess anything: the page is only fetched when ``fetch_content`` is enabled
in the configuration of the run, and the fetched content is used to enrich
the record with the *observed* title, description and text.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.core.config import settings
from app.core.net import safe_get
from app.services.adapters.impl import rate_limit
from app.services.discovery.base import (
    DiscoveredSite,
    DiscoveryCriteria,
    DiscoveryProvider,
    register_provider,
)
from app.services.discovery.impl import extract_page_details
from app.services.opportunities import extract_domain, normalize_url


def _to_url(seed: str) -> str:
    """Turn a seed (URL or domain) into a normalised URL."""
    text = (seed or "").strip()
    if not text:
        return ""
    if "://" not in text:
        if "." not in text:
            return ""
        text = f"https://{text}"
    parsed = urlparse(text)
    if not parsed.netloc:
        return ""
    return normalize_url(text)


class ManualSeedProvider(DiscoveryProvider):
    """Discovery provider that uses the seeds of the operator."""

    key = "manual_seed"
    name = "User supplied seeds"
    description = "Uses the URLs and domains the operator provides."
    requires_credentials = False
    categories: tuple[str, ...] = ()
    default_limit = 25

    def discover(self, criteria: DiscoveryCriteria) -> list[DiscoveredSite]:
        """Turn every seed into a discovered site."""
        config: dict[str, Any] = criteria.config or {}
        seeds: list[str] = [str(seed) for seed in (criteria.seeds or [])]
        seeds.extend(str(seed) for seed in (config.get("seeds") or []))
        if not seeds and criteria.query:
            seeds.append(criteria.query)

        fetch_content = bool(config.get("fetch_content", False))
        category = str(criteria.category or config.get("category") or "BUSINESS_DIRECTORY")
        limit = int(criteria.limit or self.default_limit)

        sites: list[DiscoveredSite] = []
        seen: set[tuple[str, str]] = set()
        for seed in seeds:
            url = _to_url(seed)
            if not url:
                continue
            domain = extract_domain(url)
            key = (domain, url)
            if key in seen:
                continue
            seen.add(key)
            site = DiscoveredSite(
                name=str(config.get("name") or domain),
                domain=domain,
                url=url,
                category=category,
                source=self.key,
                provider=self.key,
                description=_optional(config.get("description")),
                language=criteria.language,
                region=criteria.countries[0] if criteria.countries else None,
                submission_method=str(config.get("submission_method") or "UNKNOWN"),
                registration_required=_optional_bool(config.get("registration_required")),
                requires_approval=_optional_bool(config.get("requires_approval")),
                contact_email=_optional(config.get("contact_email")),
                anchor_text=_optional(config.get("anchor_text")),
                raw={"seed": seed, "url": url},
            )
            if fetch_content:
                self._enrich(site)
            sites.append(site)
            if len(sites) >= limit:
                break
        return sites

    def _enrich(self, site: DiscoveredSite) -> None:
        """Fetch the page and store the observable details of it."""
        rate_limit()
        response = safe_get(site.url, allow_robots=settings.respect_robots)
        site.raw["http_status"] = response.status_code
        site.raw["reachable"] = bool(response.ok)
        if response.error:
            site.raw["error"] = response.error
            return
        details = extract_page_details(response.content, response.final_url)
        site.raw["page_title"] = details.get("title")
        site.raw["page_description"] = details.get("description")
        site.raw["page_text"] = details.get("text")
        if details.get("title"):
            site.name = str(details["title"])
        if details.get("description"):
            site.description = str(details["description"])


def _optional(value: Any) -> str | None:
    """Return *value* as a non empty string (or ``None``)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_bool(value: Any) -> bool | None:
    """Return *value* as a boolean (or ``None`` when it is unknown)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    return None


register_provider(ManualSeedProvider())
