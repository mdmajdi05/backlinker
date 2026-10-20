"""Discovery provider contract.

Providers are pluggable: a new source only has to implement
:class:`DiscoveryProvider` and register itself. Providers never fabricate
metrics - if a value cannot be observed it must stay ``None``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.db.models import BusinessProfile


@dataclass
class DiscoveryCriteria:
    query: str = ""
    keywords: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    language: str | None = None
    category: str | None = None
    limit: int = 25
    seeds: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    profile: BusinessProfile | None = None
    project_id: str | None = None
    excluded_domains: list[str] = field(default_factory=list)


@dataclass
class DiscoveredSite:
    name: str
    domain: str
    url: str
    category: str
    source: str
    provider: str
    description: str | None = None
    language: str | None = None
    region: str | None = None
    submission_method: str = "UNKNOWN"
    registration_required: bool | None = None
    requires_approval: bool | None = None
    contact_email: str | None = None
    anchor_text: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class DiscoveryProvider:
    key: str = "base"
    name: str = "Base provider"
    description: str = ""
    requires_credentials: bool = False
    categories: tuple[str, ...] = ()
    default_limit: int = 25

    def available(self, config: dict[str, Any] | None = None) -> tuple[bool, str]:
        """Return ``(available, reason)`` - used to surface missing credentials."""
        return True, ""

    def discover(self, criteria: DiscoveryCriteria) -> list[DiscoveredSite]:  # pragma: no cover
        raise NotImplementedError("Providers must implement discover()")


_REGISTRY: dict[str, DiscoveryProvider] = {}


def register_provider(provider: DiscoveryProvider) -> DiscoveryProvider:
    _REGISTRY[provider.key] = provider
    return provider


def get_provider(key: str) -> DiscoveryProvider | None:
    return _REGISTRY.get(key)


def all_providers() -> list[DiscoveryProvider]:
    return list(_REGISTRY.values())
