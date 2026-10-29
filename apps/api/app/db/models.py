"""Normalized data model for the Auto Backlinker platform.

The schema is dialect agnostic so the exact same models run on SQLite
(local / desktop mode) and PostgreSQL (cloud mode).

Design rules:
  * A discovered **website** (registry entry) is separate from a
    project-specific **opportunity** and from an actual **backlink record**.
  * Every long running unit of work is a **task** with a stable
    ``idempotency_key`` so re-imports never duplicate work.
  * Historical attempts are append-only (``task_attempts``), never overwritten.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TimestampMixin, utcnow


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    profiles: Mapped[list[BusinessProfile]] = relationship(back_populates="owner")


class BusinessProfile(IdMixin, TimestampMixin, Base):
    __tablename__ = "business_profiles"

    owner_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    primary_website: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    industry: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    niche: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    target_countries: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    target_regions: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    contact_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(60), nullable=True)
    social_profiles: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    logo_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    preferred_language: Mapped[str] = mapped_column(String(16), default="en", nullable=False)
    business_descriptions: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    author_bios: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    keywords: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    primary_landing_pages: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    secondary_landing_pages: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    preferred_anchors: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    anchor_preferences: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    preferred_categories: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    excluded_domains: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    excluded_categories: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    target_domains: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    monthly_target: Mapped[int | None] = mapped_column(Integer, nullable=True)
    campaign_goals: Mapped[str] = mapped_column(Text, default="", nullable=False)
    #: The address of the company - a directory submission asks for it and the
    #: profile is the one place where it is kept.
    address: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    city: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    state: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    country: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    postal_code: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    founded_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    employee_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Set when the profile is removed - it waits in the recycle bin until it
    #: is restored or deleted forever.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    owner: Mapped[User | None] = relationship(back_populates="profiles")
    projects: Mapped[list[Project]] = relationship(back_populates="business_profile")


class Project(IdMixin, TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("slug", name="uq_projects_slug"),)

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    business_profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("business_profiles.id", ondelete="SET NULL"), nullable=True
    )
    target_website: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    #: Set when the project is removed - it waits in the recycle bin together
    #: with its opportunities and tasks.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    business_profile: Mapped[BusinessProfile | None] = relationship(back_populates="projects")
    settings: Mapped[ProjectSettings | None] = relationship(
        back_populates="project", uselist=False, cascade="all, delete-orphan"
    )
    target_websites: Mapped[list[TargetWebsite]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ProjectSettings(IdMixin, TimestampMixin, Base):
    __tablename__ = "project_settings"
    __table_args__ = (UniqueConstraint("project_id", name="uq_project_settings_project_id"),)

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    max_concurrency: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    global_concurrency: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    per_domain_concurrency: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    per_provider_concurrency: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    request_rate_per_minute: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    backoff_base_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    jitter_seconds: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    operating_schedule: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    verify_interval_hours: Mapped[int] = mapped_column(Integer, default=168, nullable=False)
    verify_backoff_hours: Mapped[int] = mapped_column(Integer, default=24, nullable=False)
    daily_discovery_limit: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    allow_browser_automation: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    require_approval: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    execution_environment: Mapped[str] = mapped_column(String(16), default="CLOUD", nullable=False)
    auto_queue_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: Auto pilot: queue every approved opportunity for submission.
    auto_submit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: Categories the auto pilot is limited to (empty = every category).
    auto_submit_categories: Mapped[list | None] = mapped_column(JSON, default=list, nullable=True)
    #: Sign-up details the operator chose once per project: the username, the
    #: e-mail that receives the codes and the password (encrypted) typed by
    #: hand.  Empty fields are generated per website.
    signup_details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)

    project: Mapped[Project] = relationship(back_populates="settings")


class ProjectLoginProfile(IdMixin, TimestampMixin, Base):
    """The isolated browser profile and Google session of one project.

    Every project owns its own profile directory.  A cookie exported from that
    profile is encrypted before it touches the database, so two projects never
    share a session and a database dump never contains a usable login.
    """

    __tablename__ = "project_login_profiles"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_project_login_profiles_project_id"),
    )

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), default="google", nullable=False)
    #: NOT_CONNECTED | LOGIN_OPEN | CONNECTED | EXPIRED | ERROR
    status: Mapped[str] = mapped_column(
        String(24), default="NOT_CONNECTED", nullable=False, index=True
    )
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    profile_dir: Mapped[str] = mapped_column(String(800), default="", nullable=False)
    #: Playwright ``storage_state`` JSON, encrypted with the local key file of
    #: the installation (``<data>/files/login-profile.key``).
    storage_state_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class WebsiteLoginSession(IdMixin, TimestampMixin, Base):
    """The login state of one website inside one project."""

    __tablename__ = "website_login_sessions"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "website_id", name="uq_website_login_sessions_project_website"
        ),
    )

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    website_id: Mapped[str] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: UNKNOWN | CONNECTED | LOGIN_REQUIRED | EXPIRED
    status: Mapped[str] = mapped_column(
        String(24), default="UNKNOWN", nullable=False, index=True
    )
    method: Mapped[str] = mapped_column(String(24), default="UNKNOWN", nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class SiteAccount(IdMixin, TimestampMixin, Base):
    """The account this project uses on one backlink website.

    The strategy is decided per site: a website that offers *Continue with
    Google* is entered with the project's Google session, every other site
    gets a generated username / password.  The password is encrypted with the
    per-installation key and the associated data of *this* row, so a value can
    never be swapped into the row of another project or website.
    """

    __tablename__ = "site_accounts"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "website_id", name="uq_site_accounts_project_website"
        ),
    )

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    website_id: Mapped[str] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: GOOGLE | SIGNUP | EXISTING | MANUAL | UNKNOWN
    strategy: Mapped[str] = mapped_column(String(24), default="UNKNOWN", nullable=False)
    #: NOT_STARTED | QUEUED | DETECTING | CREATING | OTP_PENDING | ACTIVE |
    #: NEEDS_HUMAN | FAILED
    status: Mapped[str] = mapped_column(
        String(24), default="NOT_STARTED", nullable=False, index=True
    )
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    username: Mapped[str | None] = mapped_column(String(160), nullable=True)
    password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    login_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    account_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    #: The plus/dot alias this site signs up with.  It is the binding key of
    #: the OTP pipeline: a code is only accepted for the alias of its row.
    otp_alias: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    #: NONE | WAITING | RECEIVED | USED | EXPIRED
    otp_state: Mapped[str] = mapped_column(String(24), default="NONE", nullable=False)
    otp_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    otp_message_id: Mapped[str | None] = mapped_column(String(400), nullable=True)
    otp_received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    otp_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: The page that really carries the backlink form / profile editor.
    backlink_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    backlink_form: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    backlink_confidence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    backlink_found_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: NONE | POSTED | VERIFIED | NEEDS_HUMAN | FAILED - the real state of the
    #: post that the account made (not the account itself).
    backlink_status: Mapped[str] = mapped_column(String(24), default="NONE", nullable=False)
    #: The public page that carries the posted link (the tracking URL).
    backlink_published_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    #: Why the post stopped / what the site answered (never a fake success).
    backlink_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: What the site's own code showed (platform, sign-up routes, public form).
    site_intel: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class TargetWebsite(IdMixin, TimestampMixin, Base):
    __tablename__ = "target_websites"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), default="OTHER", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    project: Mapped[Project] = relationship(back_populates="target_websites")


class OpportunityCategory(IdMixin, TimestampMixin, Base):
    """Registry of backlink opportunity categories (extensible, not hardcoded)."""

    __tablename__ = "opportunity_categories"
    __table_args__ = (UniqueConstraint("key", name="uq_opportunity_categories_key"),)

    key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    submission_methods: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    required_fields: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    verification_rules: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    automatable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Website(IdMixin, TimestampMixin, Base):
    """A discovered website / opportunity page in the global registry.

    A website is *not* bound to a project: several projects may reference the
    same website through their own :class:`Opportunity` rows.
    """

    __tablename__ = "websites"
    __table_args__ = (
        UniqueConstraint("domain", "opportunity_url", name="uq_websites_domain_url"),
        Index("ix_websites_status_source", "status", "discovery_source"),
    )

    name: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    opportunity_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    #: Free text niche of the site ("pet care", "saas", ...).  It is the second
    #: axis the central list is filtered by (beside the category).
    niche: Mapped[str] = mapped_column(String(160), default="", nullable=False, index=True)
    discovery_source: Mapped[str] = mapped_column(String(120), default="manual", nullable=False, index=True)
    discovery_provider: Mapped[str | None] = mapped_column(String(120), nullable=True)
    discovery_run_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    region: Mapped[str | None] = mapped_column(String(120), nullable=True)
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False, index=True)
    score_breakdown: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="DISCOVERED", nullable=False, index=True)
    submission_method: Mapped[str] = mapped_column(String(32), default="UNKNOWN", nullable=False)
    registration_required: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    requires_approval: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    adapter_id: Mapped[str | None] = mapped_column(
        ForeignKey("automation_adapters.id", ondelete="SET NULL"), nullable=True
    )
    #: The per website configuration of the assigned adapter (form URL,
    #: selector mapping, success signal).  Each website can have its own
    #: configuration; a project wide AdapterConfiguration remains supported.
    adapter_config: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)
    anchor_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    language_hint: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    backlink_status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False, index=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    duplicate_of: Mapped[str | None] = mapped_column(
        ForeignKey("websites.id", ondelete="SET NULL"), nullable=True
    )
    excluded_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    excluded_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    #: Set when the website is removed from the central list.  The status
    #: ``DELETED`` and this column are kept in sync.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    adapter: Mapped[AutomationAdapter | None] = relationship()
    opportunities: Mapped[list[Opportunity]] = relationship(
        back_populates="website", cascade="all, delete-orphan"
    )


class Opportunity(IdMixin, TimestampMixin, Base):
    """Project specific use of a registry website."""

    __tablename__ = "opportunities"
    __table_args__ = (
        UniqueConstraint("project_id", "website_id", name="uq_opportunities_project_website"),
    )

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    website_id: Mapped[str] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_landing_page: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="NEEDS_REVIEW", nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    #: Set when the opportunity is removed - it waits in the recycle bin.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[Project] = relationship()
    website: Mapped[Website] = relationship(back_populates="opportunities")


class SiteDetails(IdMixin, TimestampMixin, Base):
    """The values a directory asks for, stored **per opportunity**.

    The record is attached to the opportunity (and not to the website) so the
    very same website can be listed with different details in two projects.
    ``extra`` holds everything a specific form needs that has no fixed field.
    """

    __tablename__ = "site_details"
    __table_args__ = (UniqueConstraint("opportunity_id", name="uq_site_details_opportunity_id"),)

    opportunity_id: Mapped[str] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    website_id: Mapped[str] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_name: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(60), nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    city: Mapped[str | None] = mapped_column(String(160), nullable=True)
    state: Mapped[str | None] = mapped_column(String(160), nullable=True)
    country: Mapped[str | None] = mapped_column(String(160), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    logo_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    categories: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    founded_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    employee_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Everything a specific form needs that has no fixed field.
    extra: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    #: The fields the assistant filled: field name -> how it was produced.
    generated: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class DiscoverySource(IdMixin, TimestampMixin, Base):
    """Registry of discovery providers (seeded from code + configurable)."""

    __tablename__ = "discovery_sources"
    __table_args__ = (UniqueConstraint("key", name="uq_discovery_sources_key"),)

    key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    kind: Mapped[str] = mapped_column(String(64), default="search_api", nullable=False)
    requires_credentials: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    config_schema: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    categories: Mapped[list] = mapped_column(JSON, default=list, nullable=False)


class DiscoveryRun(IdMixin, TimestampMixin, Base):
    __tablename__ = "discovery_runs"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False, index=True)
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    keywords: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    requested_limit: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    discovered_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    new_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AutomationAdapter(IdMixin, TimestampMixin, Base):
    """Declaration of a submission adapter (site specific workflow contract)."""

    __tablename__ = "automation_adapters"
    __table_args__ = (UniqueConstraint("key", name="uq_automation_adapters_key"),)

    key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    supported_categories: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    supported_methods: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    supported_environments: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    required_config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    required_user_fields: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    registration_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    manual_approval_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    automatable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verification_method: Mapped[str] = mapped_column(String(64), default="manual", nullable=False)
    retryable_errors: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    restrictions: Mapped[str | None] = mapped_column(Text, nullable=True)
    success_signals: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    domains: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    implementation: Mapped[str | None] = mapped_column(String(160), nullable=True)


class AdapterConfiguration(IdMixin, TimestampMixin, Base):
    __tablename__ = "adapter_configurations"

    adapter_id: Mapped[str] = mapped_column(
        ForeignKey("automation_adapters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class Campaign(IdMixin, TimestampMixin, Base):
    __tablename__ = "campaigns"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", nullable=False)
    goal_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_value: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Task(IdMixin, TimestampMixin, Base):
    """Durable unit of work."""

    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_tasks_idempotency_key"),
        Index("ix_tasks_claim", "status", "scheduled_for", "priority"),
    )

    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    opportunity_id: Mapped[str | None] = mapped_column(
        ForeignKey("opportunities.id", ondelete="SET NULL"), nullable=True, index=True
    )
    website_id: Mapped[str | None] = mapped_column(
        ForeignKey("websites.id", ondelete="SET NULL"), nullable=True, index=True
    )
    campaign_id: Mapped[str | None] = mapped_column(
        ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True, index=True
    )
    type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="QUEUED", nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    execution_environment: Mapped[str] = mapped_column(String(16), default="CLOUD", nullable=False)
    adapter_id: Mapped[str | None] = mapped_column(
        ForeignKey("automation_adapters.id", ondelete="SET NULL"), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    skip_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    requires_human: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    result: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class TaskAttempt(IdMixin, TimestampMixin, Base):
    __tablename__ = "task_attempts"
    __table_args__ = (
        UniqueConstraint("task_id", "attempt_number", name="uq_task_attempts_task_number"),
    )

    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    outcome: Mapped[str] = mapped_column(String(32), default="RUNNING", nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    worker: Mapped[str | None] = mapped_column(String(120), nullable=True)
    execution_environment: Mapped[str] = mapped_column(String(16), default="CLOUD", nullable=False)


class TaskEvent(IdMixin, Base):
    __tablename__ = "task_events"
    __table_args__ = (Index("ix_task_events_task_created", "task_id", "created_at"),)

    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True, index=True
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    website_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    level: Mapped[str] = mapped_column(String(16), default="INFO", nullable=False)
    execution_environment: Mapped[str | None] = mapped_column(String(16), nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)


class SubmissionEvidence(IdMixin, TimestampMixin, Base):
    __tablename__ = "submission_evidence"

    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True, index=True
    )
    opportunity_id: Mapped[str | None] = mapped_column(
        ForeignKey("opportunities.id", ondelete="SET NULL"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), default="confirmation", nullable=False)
    path: Mapped[str | None] = mapped_column(String(800), nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class BacklinkRecord(IdMixin, TimestampMixin, Base):
    """A submitted (or believed submitted) backlink and its verification state."""

    __tablename__ = "backlink_records"
    __table_args__ = (
        Index("ix_backlink_verification", "verification_status", "next_verification_at"),
    )

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    opportunity_id: Mapped[str | None] = mapped_column(
        ForeignKey("opportunities.id", ondelete="SET NULL"), nullable=True, index=True
    )
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    target_website: Mapped[str] = mapped_column(String(500), nullable=False)
    expected_link_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    published_page_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    expected_destination_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    observed_destination_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    observed_anchor_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    link_present: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    destination_matched: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_live: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    link_attribute: Mapped[str | None] = mapped_column(String(32), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verification_status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_verification_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class VerificationRun(IdMixin, Base):
    __tablename__ = "verification_runs"

    backlink_id: Mapped[str] = mapped_column(
        ForeignKey("backlink_records.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    link_present: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    destination_matched: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    observed_anchor_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    observed_destination_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    link_attribute: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)


class ImportJob(IdMixin, TimestampMixin, Base):
    __tablename__ = "import_jobs"

    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    file_name: Mapped[str] = mapped_column(String(400), nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(800), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="PENDING", nullable=False, index=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sheet_names: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    detected_mapping: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    total_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    retried_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    verify_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    conflict_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    invalid_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_report_path: Mapped[str | None] = mapped_column(String(800), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ImportRow(IdMixin, Base):
    __tablename__ = "import_rows"

    import_job_id: Mapped[str] = mapped_column(
        ForeignKey("import_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    errors: Mapped[str | None] = mapped_column(Text, nullable=True)
    website_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(32), nullable=True)


class ExportJob(IdMixin, TimestampMixin, Base):
    __tablename__ = "export_jobs"

    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    scope: Mapped[str] = mapped_column(String(160), default="workspace", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="PENDING", nullable=False, index=True)
    format: Mapped[str] = mapped_column(String(8), default="xlsx", nullable=False)
    file_name: Mapped[str | None] = mapped_column(String(400), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(800), nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class IntegrationCredential(IdMixin, TimestampMixin, Base):
    __tablename__ = "integration_credentials"
    __table_args__ = (UniqueConstraint("provider", "label", name="uq_integration_credentials_provider_label"),)

    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(120), default="default", nullable=False)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="CONFIGURED", nullable=False)


class Schedule(IdMixin, TimestampMixin, Base):
    __tablename__ = "schedules"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cron: Mapped[str | None] = mapped_column(String(120), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class AuditLog(IdMixin, Base):
    __tablename__ = "audit_logs"

    actor_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    before: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    after: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)


class Device(IdMixin, TimestampMixin, Base):
    """Registered local automation agent / desktop machine."""

    __tablename__ = "devices"

    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    platform: Mapped[str] = mapped_column(String(64), default="unknown", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="REGISTERED", nullable=False, index=True)
    capabilities: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    api_key_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ManagedFile(IdMixin, TimestampMixin, Base):
    """Metadata for files stored in the managed application data directory."""

    __tablename__ = "managed_files"

    kind: Mapped[str] = mapped_column(String(48), default="upload", nullable=False, index=True)
    original_name: Mapped[str] = mapped_column(String(400), nullable=False)
    path: Mapped[str] = mapped_column(String(800), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(160), nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AppSetting(IdMixin, TimestampMixin, Base):
    """Key/value application settings (storage mode, cloud connection, ...)."""

    __tablename__ = "app_settings"
    __table_args__ = (UniqueConstraint("key", name="uq_app_settings_key"),)

    key: Mapped[str] = mapped_column(String(120), nullable=False)
    value: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class SyncChange(IdMixin, TimestampMixin, Base):
    """Pending change queue used by hybrid (local <-> cloud) synchronisation."""

    __tablename__ = "sync_changes"
    __table_args__ = (
        Index("ix_sync_changes_pending", "synced_at", "entity_type"),
    )

    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(32), nullable=False)
    operation: Mapped[str] = mapped_column(String(16), default="upsert", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    conflict: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
