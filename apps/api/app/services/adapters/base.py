"""Submission adapter contract.

Adapters describe *how* a specific opportunity type is processed. Every
adapter must declare what it supports, what it needs, whether it can run
automatically and how a successful submission is recognised.

Design rules enforced by this framework:

* No adapter may report success because a button was clicked - a concrete
  success signal (confirmation message, published page, API response) is
  required.
* Adapters that need a human (payment, editorial approval, account creation)
  must return ``WAITING_FOR_USER`` instead of pretending to have submitted.
* Adapters must never attempt to bypass CAPTCHAs or anti-bot protections.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from sqlalchemy.orm import Session

from app.db.models import BusinessProfile, Opportunity, Project, Task, Website

# Result statuses produced by adapters.
RESULT_SUBMITTED = "SUBMITTED"
RESULT_PUBLISHED = "PUBLISHED_UNVERIFIED"
RESULT_WAITING_USER = "WAITING_FOR_USER"
RESULT_WAITING_APPROVAL = "WAITING_FOR_APPROVAL"
RESULT_FAILED = "FAILED"
RESULT_SKIPPED = "SKIPPED"


@dataclass
class SubmissionContext:
    db: Session
    task: Task
    website: Website
    opportunity: Opportunity | None
    project: Project
    profile: BusinessProfile | None
    adapter_config: dict[str, Any] = field(default_factory=dict)
    project_settings: dict[str, Any] = field(default_factory=dict)
    evidence_dir: Path | None = None
    emit: Callable[[str, str, dict[str, Any] | None], None] | None = None

    def log(self, message: str, level: str = "INFO", metadata: dict[str, Any] | None = None) -> None:
        if self.emit:
            self.emit(message, level, metadata or {})

    def landing_page(self) -> str:
        if self.opportunity and self.opportunity.target_landing_page:
            return self.opportunity.target_landing_page
        if self.project:
            return self.project.target_website
        return ""


@dataclass
class SubmissionResult:
    status: str
    message: str
    published_page_url: str | None = None
    expected_destination_url: str | None = None
    observed_anchor_text: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    retryable: bool = False
    requires_human: bool = False
    requires_approval: bool = False
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status in (RESULT_SUBMITTED, RESULT_PUBLISHED)


class BaseAdapter:
    """Base class for every submission adapter."""

    key: str = "base"
    name: str = "Base adapter"
    kind: str = "CUSTOM"
    description: str = ""
    supported_categories: tuple[str, ...] = ()
    supported_methods: tuple[str, ...] = ("MANUAL",)
    supported_environments: tuple[str, ...] = ("CLOUD", "LOCAL")
    required_config: ClassVar[dict[str, Any]] = {}
    required_user_fields: tuple[str, ...] = ()
    registration_required: bool = False
    manual_approval_required: bool = True
    automatable: bool = False
    verification_method: str = "manual"
    retryable_errors: tuple[str, ...] = ("timeout", "connection_reset", "http_5xx")
    restrictions: str = ""
    success_signals: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()

    def supports_category(self, category: str) -> bool:
        return not self.supported_categories or category in self.supported_categories

    def matches_domain(self, domain: str) -> bool:
        if not self.domains:
            return False
        domain = (domain or "").lower().lstrip(".")
        return any(domain == d.lower().lstrip(".") or domain.endswith("." + d.lower().lstrip(".")) for d in self.domains)

    def can_handle(self, website: Website) -> bool:
        if not self.supports_category(website.category):
            return False
        return self.matches_domain(website.domain)

    # -- workflow ------------------------------------------------------
    def preflight(self, ctx: SubmissionContext) -> SubmissionResult | None:
        """Optional hook executed before the submission (reachability checks)."""
        return None

    def submit(self, ctx: SubmissionContext) -> SubmissionResult:  # pragma: no cover - abstract
        raise NotImplementedError("Adapters must implement submit()")

    def verify(self, ctx: SubmissionContext, published_page_url: str) -> dict[str, Any]:
        """Optional adapter specific verification (defaults to shared engine)."""
        return {}


_REGISTRY: dict[str, BaseAdapter] = {}


def register_adapter(adapter: BaseAdapter) -> BaseAdapter:
    _REGISTRY[adapter.key] = adapter
    return adapter


def get_adapter(key: str | None) -> BaseAdapter | None:
    if not key:
        return None
    return _REGISTRY.get(key)


def all_adapters() -> list[BaseAdapter]:
    return list(_REGISTRY.values())


def adapter_for_website(website: Website) -> BaseAdapter | None:
    """Find the most specific adapter for a website.

    A domain specific adapter always wins over a generic one.  When no
    domain specific adapter exists, an adapter that supports the submission
    method of the website is preferred over any other automatable adapter.
    """
    domain_adapters = [a for a in _REGISTRY.values() if a.matches_domain(website.domain)]
    if domain_adapters:
        domain_adapters.sort(key=lambda a: max((len(d) for d in a.domains), default=0), reverse=True)
        candidate = domain_adapters[0]
        if candidate.supports_category(website.category):
            return candidate

    candidates = [
        a for a in _REGISTRY.values()
        if a.supports_category(website.category) and a.automatable
    ]
    if not candidates:
        return None
    method = (getattr(website, "submission_method", "") or "").upper()
    matching = [a for a in candidates if method and method in a.supported_methods]
    if matching:
        return matching[0]
    return candidates[0]
