"""Built-in catalogue of public submission pages.

The provider ships a curated catalogue of well known platforms that
document a public way to add a business, a profile or a document. Every
entry points at a real, publicly reachable page of the platform.

The catalogue contains **no metrics at all** - there is no invented traffic
figure, no invented authority score and no invented publication status.
What is known about a platform is stated as a plain flag
(``registration_required`` / ``requires_approval``) and can be refined by
the signals that were actually observed on the fetched page.

When an entry is discovered its URL is probed once with
:func:`app.core.net.safe_get` (respecting ``robots.txt``). An entry whose
page does not exist is dropped, an entry that exists but cannot be fetched
by the crawler is kept and flagged. The probe result is cached in-process
for a week so a repeated run does not hammer the platforms.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

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

_CACHE_TTL_SECONDS = 7 * 24 * 3600
_DEFAULT_PROBE_BUDGET = 12

# Signals that make a registration unavoidable. They are only used to turn
# a flag on - a flag is never turned off by a missing signal.
_REGISTRATION_MARKERS = (
    "create an account",
    "create a free account",
    "sign up to",
    "register as a business",
    "you need an account",
    "log in to add",
    "login to add",
)

# Signals that a human reviews the listing before it goes live.
_APPROVAL_MARKERS = (
    "pending approval",
    "after approval",
    "approved by our",
    "reviewed by our team",
    "review team",
    "manual review",
    "moderation team",
)


@dataclass(frozen=True)
class DirectoryEntry:
    """A platform that documents a public submission page."""

    name: str
    url: str
    domain: str
    category: str
    region: str
    language: str
    submission_method: str
    registration_required: bool
    requires_approval: bool
    notes: str = ""


DIRECTORY_ENTRIES: tuple[DirectoryEntry, ...] = (
    DirectoryEntry(
        "Google Business Profile",
        "https://www.google.com/business/",
        "google.com",
        "BUSINESS_PROFILE",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        True,
        "Google verifies the listing before it is published.",
    ),
    DirectoryEntry(
        "Bing Places",
        "https://www.bingplaces.com/",
        "bingplaces.com",
        "BUSINESS_PROFILE",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        True,
    ),
    DirectoryEntry(
        "Apple Business Connect",
        "https://businessconnect.apple.com/",
        "businessconnect.apple.com",
        "BUSINESS_PROFILE",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        True,
    ),
    DirectoryEntry(
        "Yelp for Business",
        "https://business.yelp.com/",
        "business.yelp.com",
        "LOCAL_CITATION",
        "US",
        "en",
        "BROWSER_FORM",
        True,
        True,
    ),
    DirectoryEntry(
        "Yellow Pages",
        "https://www.yellowpages.com/",
        "yellowpages.com",
        "BUSINESS_DIRECTORY",
        "US",
        "en",
        "BROWSER_FORM",
        True,
        True,
    ),
    DirectoryEntry(
        "Better Business Bureau",
        "https://www.bbb.org/",
        "bbb.org",
        "BUSINESS_DIRECTORY",
        "US",
        "en",
        "BROWSER_FORM",
        True,
        True,
    ),
    DirectoryEntry(
        "Foursquare",
        "https://foursquare.com/",
        "foursquare.com",
        "BUSINESS_PROFILE",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        True,
    ),
    DirectoryEntry(
        "Clutch",
        "https://clutch.co/get-listed",
        "clutch.co",
        "INDUSTRY_DIRECTORY",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        True,
    ),
    DirectoryEntry(
        "Crunchbase",
        "https://www.crunchbase.com/add-company",
        "crunchbase.com",
        "BUSINESS_PROFILE",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        True,
    ),
    DirectoryEntry(
        "Capterra",
        "https://www.capterra.com/vendors/get-listed",
        "capterra.com",
        "INDUSTRY_DIRECTORY",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        True,
    ),
    DirectoryEntry(
        "G2",
        "https://www.g2.com/",
        "g2.com",
        "INDUSTRY_DIRECTORY",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        True,
    ),
    DirectoryEntry(
        "Trustpilot",
        "https://www.trustpilot.com/",
        "trustpilot.com",
        "BUSINESS_PROFILE",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        False,
        "Reviews are published without a manual approval step.",
    ),
    DirectoryEntry(
        "Alignable",
        "https://www.alignable.com/",
        "alignable.com",
        "BUSINESS_DIRECTORY",
        "US",
        "en",
        "BROWSER_FORM",
        True,
        False,
    ),
    DirectoryEntry(
        "Hotfrog",
        "https://www.hotfrog.com/",
        "hotfrog.com",
        "BUSINESS_DIRECTORY",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        True,
    ),
    DirectoryEntry(
        "Mahalo",
        "https://www.mahalo.com/",
        "mahalo.com",
        "SOCIAL_PROFILE",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        True,
    ),
    DirectoryEntry(
        "Yell",
        "https://www.yell.com/",
        "yell.com",
        "BUSINESS_DIRECTORY",
        "GB",
        "en",
        "BROWSER_FORM",
        True,
        True,
    ),
    DirectoryEntry(
        "PagesJaunes",
        "https://annuaire.pagesjaunes.fr/",
        "annuaire.pagesjaunes.fr",
        "BUSINESS_DIRECTORY",
        "FR",
        "fr",
        "BROWSER_FORM",
        True,
        True,
    ),
    DirectoryEntry(
        "Das Oertliche",
        "https://www.dasoertliche.de/",
        "dasoertliche.de",
        "BUSINESS_DIRECTORY",
        "DE",
        "de",
        "BROWSER_FORM",
        True,
        True,
    ),
    DirectoryEntry(
        "Houzz",
        "https://www.houzz.com/",
        "houzz.com",
        "LOCAL_CITATION",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        True,
    ),
    DirectoryEntry(
        "Thumbtack",
        "https://www.thumbtack.com/",
        "thumbtack.com",
        "LOCAL_CITATION",
        "US",
        "en",
        "BROWSER_FORM",
        True,
        True,
    ),
    DirectoryEntry(
        "Bark",
        "https://www.bark.com/",
        "bark.com",
        "LOCAL_CITATION",
        "US",
        "en",
        "BROWSER_FORM",
        True,
        False,
    ),
    DirectoryEntry(
        "Nextdoor",
        "https://nextdoor.com/",
        "nextdoor.com",
        "LOCAL_CITATION",
        "US",
        "en",
        "BROWSER_FORM",
        True,
        True,
    ),
    DirectoryEntry(
        "LinkedIn",
        "https://www.linkedin.com/",
        "linkedin.com",
        "BUSINESS_PROFILE",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        True,
    ),
    DirectoryEntry(
        "Product Hunt",
        "https://www.producthunt.com/",
        "producthunt.com",
        "BUSINESS_PROFILE",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        True,
    ),
    DirectoryEntry(
        "Wellfound",
        "https://wellfound.com/",
        "wellfound.com",
        "BUSINESS_PROFILE",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        True,
    ),
    DirectoryEntry(
        "BetaList",
        "https://betalist.com/",
        "betalist.com",
        "BUSINESS_DIRECTORY",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        True,
    ),
    DirectoryEntry(
        "F6S",
        "https://f6s.com/",
        "f6s.com",
        "BUSINESS_PROFILE",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        False,
    ),
    DirectoryEntry(
        "GitHub",
        "https://github.com/",
        "github.com",
        "SOCIAL_PROFILE",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        False,
        "A link can be placed in the profile README.",
    ),
    DirectoryEntry(
        "Stack Overflow",
        "https://stackoverflow.com/users",
        "stackoverflow.com",
        "PUBLIC_PROFILE",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        False,
    ),
    DirectoryEntry(
        "Quora",
        "https://www.quora.com/",
        "quora.com",
        "PUBLIC_PROFILE",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        False,
    ),
    DirectoryEntry(
        "Reddit",
        "https://www.reddit.com/",
        "reddit.com",
        "FORUM_COMMUNITY",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        True,
    ),
    DirectoryEntry(
        "Medium",
        "https://medium.com/",
        "medium.com",
        "SOCIAL_PROFILE",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        False,
    ),
    DirectoryEntry(
        "About.me",
        "https://about.me/",
        "about.me",
        "PUBLIC_PROFILE",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        False,
    ),
    DirectoryEntry(
        "Pinterest",
        "https://www.pinterest.com/",
        "pinterest.com",
        "SOCIAL_PROFILE",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        False,
    ),
    DirectoryEntry(
        "Tumblr",
        "https://www.tumblr.com/",
        "tumblr.com",
        "SOCIAL_PROFILE",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        False,
    ),
    DirectoryEntry(
        "Craft",
        "https://www.craft.co/",
        "craft.co",
        "PUBLIC_PROFILE",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        False,
    ),
    DirectoryEntry(
        "Dev.to",
        "https://dev.to/",
        "dev.to",
        "GUEST_POST",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        False,
    ),
    DirectoryEntry(
        "Hashnode",
        "https://hashnode.com/",
        "hashnode.com",
        "PUBLIC_PROFILE",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        False,
    ),
    DirectoryEntry(
        "Indie Hackers",
        "https://www.indiehackers.com/",
        "indiehackers.com",
        "PUBLIC_PROFILE",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        False,
    ),
    DirectoryEntry(
        "Peerlist",
        "https://peerlist.io/",
        "peerlist.io",
        "PUBLIC_PROFILE",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        False,
    ),
    DirectoryEntry(
        "CodePen",
        "https://codepen.io/",
        "codepen.io",
        "PUBLIC_PROFILE",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        False,
    ),
    DirectoryEntry(
        "Dribbble",
        "https://dribbble.com/",
        "dribbble.com",
        "PUBLIC_PROFILE",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        False,
    ),
    DirectoryEntry(
        "Behance",
        "https://www.behance.net/",
        "behance.net",
        "PUBLIC_PROFILE",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        False,
    ),
    DirectoryEntry(
        "Vimeo",
        "https://vimeo.com/",
        "vimeo.com",
        "PUBLIC_PROFILE",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        False,
    ),
    DirectoryEntry(
        "SlideShare",
        "https://www.slideshare.net/",
        "slideshare.net",
        "DOCUMENT_SHARING",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        False,
    ),
    DirectoryEntry(
        "Scribd",
        "https://www.scribd.com/",
        "scribd.com",
        "DOCUMENT_SHARING",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        False,
    ),
    DirectoryEntry(
        "Issuu",
        "https://issuu.com/",
        "issuu.com",
        "DOCUMENT_SHARING",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        False,
    ),
    DirectoryEntry(
        "Flipboard",
        "https://flipboard.com/",
        "flipboard.com",
        "SOCIAL_PROFILE",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        True,
    ),
    DirectoryEntry(
        "Mastodon",
        "https://joinmastodon.org/",
        "joinmastodon.org",
        "SOCIAL_PROFILE",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        False,
    ),
    DirectoryEntry(
        "Wikipedia",
        "https://en.wikipedia.org/wiki/Wikipedia:Requests_for_administration",
        "wikipedia.org",
        "EDITORIAL",
        "GLOBAL",
        "en",
        "BROWSER_FORM",
        True,
        True,
        "Wikipedia applies a strict notability policy - most submissions are rejected.",
    ),
)

# url -> (timestamp, reachable, http_status, signals, drop)
_REACHABILITY_CACHE: dict[str, tuple[float, bool, int, dict[str, Any], bool]] = {}


class DirectoryIndexProvider(DiscoveryProvider):
    """Built-in catalogue of publicly documented submission pages."""

    key = "directory_index"
    name = "Public directory index"
    description = (
        "Built-in catalogue of publicly documented submission pages. Reachability is verified live."
    )
    requires_credentials = False
    categories: tuple[str, ...] = (
        "BUSINESS_DIRECTORY",
        "INDUSTRY_DIRECTORY",
        "BUSINESS_PROFILE",
        "LOCAL_CITATION",
        "SOCIAL_PROFILE",
        "PUBLIC_PROFILE",
        "GUEST_POST",
        "DOCUMENT_SHARING",
        "EDITORIAL",
        "FORUM_COMMUNITY",
    )
    default_limit = 25

    def discover(self, criteria: DiscoveryCriteria) -> list[DiscoveredSite]:
        """Probe the catalogue and return the entries that still exist.

        An entry is dropped when its URL does not exist (404 / 410) or when
        the host cannot be reached at all. An entry that exists but cannot
        be fetched by the crawler (robots.txt) is kept and flagged - the
        operator can still submit to it manually.
        """
        entries = _filtered(criteria)
        limit = int(criteria.limit or self.default_limit)
        budget = int((criteria.config or {}).get("probe_budget", _DEFAULT_PROBE_BUDGET))
        budget = max(1, min(budget, max(limit, 1)))

        sites: list[DiscoveredSite] = []
        for entry in entries[:budget]:
            probe = self._probe(entry)
            if probe.get("drop"):
                continue
            sites.append(self._to_site(entry, probe))
        return sites

    # -- helpers ------------------------------------------------------
    def _probe(self, entry: DirectoryEntry) -> dict[str, Any]:
        """Check (and cache) the reachability of a catalogue entry."""
        cached = _REACHABILITY_CACHE.get(entry.url)
        if cached is not None:
            age = time.time() - cached[0]
            if age < _CACHE_TTL_SECONDS:
                return {
                    "reachable": cached[1],
                    "http_status": cached[2],
                    "signals": cached[3],
                    "cached": True,
                    "drop": cached[4],
                }
        rate_limit()
        response = safe_get(entry.url, allow_robots=settings.respect_robots)
        robots_blocked = bool(response.error and "robots.txt" in response.error)
        reachable = bool(response.ok) and not response.error
        signals = _signals(response.content) if reachable else {}
        drop = _must_be_dropped(response.status_code, response.error, robots_blocked)
        _REACHABILITY_CACHE[entry.url] = (
            time.time(),
            reachable,
            response.status_code,
            signals,
            drop,
        )
        return {
            "reachable": reachable,
            "http_status": response.status_code,
            "signals": signals,
            "cached": False,
            "drop": drop,
            "robots_blocked": robots_blocked,
            "error": response.error,
        }

    def _to_site(self, entry: DirectoryEntry, probe: dict[str, Any]) -> DiscoveredSite:
        """Build the discovered site of a catalogue entry."""
        signals: dict[str, Any] = probe.get("signals") or {}
        registration = bool(entry.registration_required or signals.get("registration"))
        approval = bool(entry.requires_approval or signals.get("approval"))
        return DiscoveredSite(
            name=entry.name,
            domain=entry.domain,
            url=entry.url,
            category=entry.category,
            source=self.key,
            provider=self.key,
            description=entry.notes or None,
            language=entry.language,
            region=entry.region,
            submission_method=entry.submission_method,
            registration_required=registration,
            requires_approval=approval,
            raw={
                "http_status": probe.get("http_status"),
                "reachable": probe.get("reachable", False),
                "robots_blocked": probe.get("robots_blocked", False),
                "cached": probe.get("cached", False),
                "observed_signals": signals,
                "catalogue_notes": entry.notes,
            },
        )


def _filtered(criteria: DiscoveryCriteria) -> list[DirectoryEntry]:
    """Apply the filters of the run to the catalogue."""
    countries = {str(country).strip().upper() for country in (criteria.countries or [])}
    language = (criteria.language or "").strip().lower()
    category = (criteria.category or "").strip().upper()
    entries: list[DirectoryEntry] = []
    for entry in DIRECTORY_ENTRIES:
        if countries and entry.region.upper() not in countries and entry.region != "GLOBAL":
            continue
        if language and entry.language.lower() != language:
            continue
        if category and entry.category != category:
            continue
        entries.append(entry)
    return entries


def _signals(html: str) -> dict[str, Any]:
    """Look for the registration / approval signals on a fetched page."""
    lowered = (html or "").lower()
    return {
        "registration": any(marker in lowered for marker in _REGISTRATION_MARKERS),
        "approval": any(marker in lowered for marker in _APPROVAL_MARKERS),
    }


def _must_be_dropped(status_code: int, error: str | None, robots_blocked: bool) -> bool:
    """Should the entry be removed from the result of a run?

    A page that does not exist (404 / 410) or a host that cannot be
    reached at all is dropped. A page that exists but forbids the crawler
    is kept - the platform is real, the operator can submit manually.
    """
    if robots_blocked:
        return False
    if status_code in (404, 410):
        return True
    return bool(error and status_code == 0)


def describe_catalogue() -> list[dict[str, Any]]:
    """Return the catalogue as plain data (used by the self check)."""
    return [
        {
            "name": entry.name,
            "url": entry.url,
            "domain": entry.domain,
            "category": entry.category,
            "region": entry.region,
            "language": entry.language,
            "submission_method": entry.submission_method,
            "registration_required": entry.registration_required,
            "requires_approval": entry.requires_approval,
        }
        for entry in DIRECTORY_ENTRIES
    ]


def page_details(url: str) -> dict[str, Any]:
    """Fetch a page of the catalogue and return its observable details."""
    rate_limit()
    response = safe_get(url, allow_robots=settings.respect_robots)
    if response.error or response.status_code >= 400:
        return {"url": url, "http_status": response.status_code, "error": response.error}
    details = extract_page_details(response.content, response.final_url)
    details["http_status"] = response.status_code
    details["url"] = response.final_url
    return details


register_provider(DirectoryIndexProvider())
