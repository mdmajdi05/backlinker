"""Pydantic API schemas (mirrors `packages/shared-types` in the frontend)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=1, le=500)
    sort: str | None = None
    order: str = "desc"


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)
    name: str = Field(min_length=1, max_length=160)


class UserOut(ORMModel):
    id: str
    email: str
    name: str
    is_active: bool
    is_admin: bool
    created_at: datetime
    last_login_at: datetime | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105
    expires_in: int
    user: UserOut


# --------------------------------------------------------------------------
# Business profiles
# --------------------------------------------------------------------------

class BusinessProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    primary_website: str = Field(min_length=3, max_length=500)
    description: str = ""
    industry: str = ""
    niche: str = ""
    target_countries: list[str] = []
    target_regions: list[str] = []
    contact_email: str | None = None
    contact_phone: str | None = None
    social_profiles: dict[str, str] = {}
    preferred_language: str = "en"
    business_descriptions: list[str] = []
    author_bios: list[str] = []
    keywords: list[str] = []
    primary_landing_pages: list[str] = []
    secondary_landing_pages: list[str] = []
    preferred_anchors: list[str] = []
    anchor_preferences: dict[str, bool] = {}
    preferred_categories: list[str] = []
    excluded_domains: list[str] = []
    excluded_categories: list[str] = []
    target_domains: list[str] = []
    monthly_target: int | None = None
    campaign_goals: str = ""

    @field_validator("primary_website")
    @classmethod
    def _website(cls, v: str) -> str:
        from app.core.net import validate_http_url

        v = v.strip()
        if not v.startswith(("http://", "https://")):
            v = "https://" + v
        return validate_http_url(v).rstrip("/")


class BusinessProfileOut(ORMModel):
    id: str
    name: str
    primary_website: str
    description: str
    industry: str
    niche: str
    target_countries: list[str]
    target_regions: list[str]
    contact_email: str | None
    contact_phone: str | None
    social_profiles: dict[str, str]
    logo_path: str | None
    preferred_language: str
    business_descriptions: list[str]
    author_bios: list[str]
    keywords: list[str]
    primary_landing_pages: list[str]
    secondary_landing_pages: list[str]
    preferred_anchors: list[str]
    anchor_preferences: dict[str, bool]
    preferred_categories: list[str]
    excluded_domains: list[str]
    excluded_categories: list[str]
    target_domains: list[str]
    monthly_target: int | None
    campaign_goals: str
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------
# Projects
# --------------------------------------------------------------------------

class ProjectSettingsIn(BaseModel):
    max_concurrency: int = Field(default=3, ge=1, le=50)
    global_concurrency: int = Field(default=8, ge=1, le=200)
    per_domain_concurrency: int = Field(default=1, ge=1, le=20)
    per_provider_concurrency: int = Field(default=2, ge=1, le=50)
    request_rate_per_minute: int = Field(default=30, ge=1, le=600)
    max_retries: int = Field(default=3, ge=0, le=20)
    backoff_base_seconds: int = Field(default=30, ge=1, le=3600)
    jitter_seconds: int = Field(default=15, ge=0, le=600)
    operating_schedule: dict[str, Any] = {}
    verify_interval_hours: int = Field(default=168, ge=1, le=8760)
    verify_backoff_hours: int = Field(default=24, ge=1, le=8760)
    daily_discovery_limit: int = Field(default=100, ge=1, le=10000)
    allow_browser_automation: bool = True
    require_approval: bool = True
    execution_environment: str = "CLOUD"
    auto_queue_approved: bool = False
    timezone: str = "UTC"


class ProjectSettingsOut(ORMModel):
    id: str
    project_id: str
    max_concurrency: int
    global_concurrency: int
    per_domain_concurrency: int
    per_provider_concurrency: int
    request_rate_per_minute: int
    max_retries: int
    backoff_base_seconds: int
    jitter_seconds: int
    operating_schedule: dict[str, Any]
    verify_interval_hours: int
    verify_backoff_hours: int
    daily_discovery_limit: int
    allow_browser_automation: bool
    require_approval: bool
    execution_environment: str
    auto_queue_approved: bool
    timezone: str


class LandingPageIn(BaseModel):
    name: str
    url: str
    kind: str = "LANDING"


class TargetWebsiteOut(ORMModel):
    """A landing page of a project (the targets a backlink may point to)."""

    id: str
    project_id: str
    name: str
    url: str
    domain: str
    kind: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProjectPatch(BaseModel):
    """Partial update - every field is optional."""

    name: str | None = None
    description: str | None = None
    target_website: str | None = None
    business_profile_id: str | None = None
    status: str | None = None

    @field_validator("target_website")
    @classmethod
    def _website(cls, v: str | None) -> str | None:
        if v is None:
            return v
        from app.core.net import validate_http_url

        v = v.strip()
        if not v.startswith(("http://", "https://")):
            v = "https://" + v
        return validate_http_url(v).rstrip("/")


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    target_website: str = Field(min_length=3, max_length=500)
    business_profile_id: str | None = None
    settings: ProjectSettingsIn | None = None
    landing_pages: list[LandingPageIn] = []

    @field_validator("target_website")
    @classmethod
    def _website(cls, v: str) -> str:
        from app.core.net import validate_http_url

        v = v.strip()
        if not v.startswith(("http://", "https://")):
            v = "https://" + v
        return validate_http_url(v).rstrip("/")


class ProjectOut(ORMModel):
    id: str
    name: str
    slug: str
    description: str | None
    business_profile_id: str | None
    target_website: str
    status: str
    created_at: datetime
    updated_at: datetime
    version: int


class ProjectDetailOut(ProjectOut):
    settings: ProjectSettingsOut | None = None
    counts: dict[str, int] = {}


# --------------------------------------------------------------------------
# Opportunities / registry
# --------------------------------------------------------------------------

class OpportunityOut(BaseModel):
    id: str
    project_id: str | None = None
    name: str
    domain: str
    opportunity_url: str
    category: str
    discovery_source: str
    discovery_provider: str | None = None
    language: str | None = None
    region: str | None = None
    score: float
    score_breakdown: dict[str, Any] | None = None
    status: str
    submission_method: str
    registration_required: bool | None = None
    requires_approval: bool | None = None
    adapter_id: str | None = None
    anchor_text: str | None = None
    description: str | None = None
    notes: str | None = None
    contact_email: str | None = None
    target_landing_page: str | None = None
    last_checked_at: datetime | None = None
    last_result: str | None = None
    backlink_status: str
    error_detail: str | None = None
    duplicate_of: str | None = None
    excluded_until: datetime | None = None
    task_id: str | None = None
    created_at: datetime
    updated_at: datetime
    version: int


class OpportunityIn(BaseModel):
    name: str | None = None
    opportunity_url: str
    category: str = "BUSINESS_DIRECTORY"
    domain: str | None = None
    discovery_source: str = "manual"
    submission_method: str = "UNKNOWN"
    adapter_id: str | None = None
    anchor_text: str | None = None
    description: str | None = None
    notes: str | None = None
    contact_email: str | None = None
    target_landing_page: str | None = None
    registration_required: bool | None = None
    requires_approval: bool | None = None
    project_id: str | None = None

    @field_validator("opportunity_url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        from app.core.net import validate_http_url

        return validate_http_url(value)

    @field_validator("target_landing_page")
    @classmethod
    def _validate_landing_page(cls, value: str | None) -> str | None:
        if not value:
            return value
        from app.core.net import validate_http_url

        return validate_http_url(value)


class OpportunityUpdate(BaseModel):
    name: str | None = None
    opportunity_url: str | None = None
    category: str | None = None
    status: str | None = None
    adapter_id: str | None = None
    anchor_text: str | None = None
    description: str | None = None
    notes: str | None = None
    contact_email: str | None = None
    target_landing_page: str | None = None
    submission_method: str | None = None


class BulkActionRequest(BaseModel):
    opportunity_ids: list[str] = Field(min_length=1)
    action: str
    project_id: str | None = None
    reason: str | None = None
    excluded_until: datetime | None = None


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------

class DiscoveryRequest(BaseModel):
    project_id: str
    provider: str
    query: str | None = None
    keywords: list[str] = []
    countries: list[str] = []
    language: str | None = None
    category: str | None = None
    limit: int = Field(default=25, ge=1, le=500)
    seeds: list[str] = []
    config: dict[str, Any] = {}


class DiscoveryRunOut(ORMModel):
    id: str
    project_id: str
    provider: str
    status: str
    query: str | None
    requested_limit: int
    discovered_count: int
    new_count: int
    duplicate_count: int
    rejected_count: int
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


# --------------------------------------------------------------------------
# Queue / tasks
# --------------------------------------------------------------------------

class TaskOut(ORMModel):
    id: str
    project_id: str | None
    opportunity_id: str | None
    campaign_id: str | None
    type: str
    status: str
    priority: int
    execution_environment: str
    adapter_id: str | None
    idempotency_key: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int
    scheduled_for: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    lease_expires_at: datetime | None
    lease_owner: str | None
    next_retry_at: datetime | None
    last_error: str | None
    skip_reason: str | None
    requires_human: bool
    progress: float
    created_at: datetime
    updated_at: datetime
    version: int


class TaskAttemptOut(ORMModel):
    id: str
    task_id: str
    attempt_number: int
    started_at: datetime
    finished_at: datetime | None
    outcome: str
    error: str | None
    evidence: dict[str, Any]
    worker: str | None
    execution_environment: str


class TaskEventOut(ORMModel):
    id: str
    task_id: str | None
    project_id: str | None
    event_type: str
    message: str
    level: str
    execution_environment: str | None
    metadata: dict[str, Any]
    created_at: datetime


class QueueCreateRequest(BaseModel):
    project_ids: list[str] = []
    opportunity_ids: list[str] = []
    type: str = "SUBMIT"
    priority: int = 0
    scheduled_for: datetime | None = None
    execution_environment: str = "CLOUD"
    adapter_id: str | None = None
    payload: dict[str, Any] = {}


class TaskControlRequest(BaseModel):
    action: str
    reason: str | None = None
    task_ids: list[str] = []


class ReorderRequest(BaseModel):
    task_ids: list[str]


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------

class BacklinkRecordOut(ORMModel):
    id: str
    project_id: str
    opportunity_id: str | None
    task_id: str | None
    target_website: str
    expected_link_url: str
    published_page_url: str | None
    expected_destination_url: str
    observed_destination_url: str | None
    observed_anchor_text: str | None
    link_present: bool | None
    destination_matched: bool | None
    is_live: bool | None
    link_attribute: str | None
    http_status: int | None
    verification_status: str
    verified_at: datetime | None
    last_success_at: datetime | None
    next_verification_at: datetime | None
    evidence: dict[str, Any]
    error: str | None
    created_at: datetime
    updated_at: datetime


class VerificationRunOut(ORMModel):
    id: str
    backlink_id: str
    status: str
    link_present: bool | None
    destination_matched: bool | None
    http_status: int | None
    observed_anchor_text: str | None
    observed_destination_url: str | None
    link_attribute: str | None
    error: str | None
    evidence: dict[str, Any]
    verified_at: datetime


class VerifyRequest(BaseModel):
    backlink_ids: list[str] = []
    project_id: str | None = None
    force: bool = False


# --------------------------------------------------------------------------
# Imports / exports
# --------------------------------------------------------------------------

class ImportPreviewOut(BaseModel):
    import_job_id: str
    file_name: str
    sheets: list[str]
    detected_mapping: list[dict[str, Any]]
    rows: list[dict[str, Any]]
    counts: dict[str, int]


class ImportCommitRequest(BaseModel):
    apply_actions: list[str] | None = None
    dry_run: bool = False


class ImportJobOut(ORMModel):
    id: str
    project_id: str | None
    file_name: str
    status: str
    dry_run: bool
    total_rows: int
    created_count: int
    updated_count: int
    skipped_count: int
    retried_count: int
    verify_count: int
    conflict_count: int
    invalid_count: int
    error_report_path: str | None
    created_at: datetime
    committed_at: datetime | None


class ImportRowOut(BaseModel):
    """One row of an import job together with the planned action."""

    row_number: int
    action: str
    reason: str | None = None
    errors: str | None = None
    raw: dict[str, Any] = {}


class ExportJobOut(ORMModel):
    id: str
    project_id: str | None
    scope: str
    status: str
    format: str
    file_name: str | None
    file_path: str | None
    row_count: int | None
    error: str | None
    created_at: datetime
    completed_at: datetime | None


class ExportCreateRequest(BaseModel):
    project_id: str | None = None
    format: str = "xlsx"
    scope: str = "workspace"


# --------------------------------------------------------------------------
# Misc
# --------------------------------------------------------------------------

class AdapterOut(ORMModel):
    id: str
    key: str
    name: str
    kind: str
    description: str | None
    supported_categories: list[str]
    supported_methods: list[str]
    supported_environments: list[str]
    required_config: dict[str, Any]
    required_user_fields: list[str]
    registration_required: bool
    manual_approval_required: bool
    automatable: bool
    verification_method: str
    retryable_errors: list[str]
    restrictions: str | None
    success_signals: list[str]
    domains: list[str]
    enabled: bool


class AdapterConfigurationOut(ORMModel):
    """Per project configuration of an adapter."""

    id: str
    adapter_id: str
    project_id: str | None = None
    config: dict[str, Any] = {}


class DiscoveryProviderOut(BaseModel):
    """A discovery provider and whether it can be used right now."""

    key: str
    name: str
    description: str = ""
    requires_credentials: bool = False
    categories: list[str] = []
    enabled: bool = True
    available: bool = False
    reason: str | None = None


class ActivityEventOut(BaseModel):
    id: str
    event_type: str
    level: str
    message: str
    project_id: str | None = None
    project_name: str | None = None
    task_id: str | None = None
    opportunity_id: str | None = None
    website: str | None = None
    execution_environment: str | None = None
    metadata: dict[str, Any] = {}
    created_at: datetime


class DashboardMetricsOut(BaseModel):
    projects: int
    opportunities: int
    approved: int
    queued: int
    running: int
    published: int
    verified_live: int
    pending_manual: int
    failed: int
    awaiting_retry: int
    requiring_verification: int
    connected_devices: int
    cloud_workers: int
    running_local_jobs: int
    sync_errors: int
    by_status: dict[str, int]
    by_category: list[dict[str, Any]]
    generated_at: datetime


class StorageStatusOut(BaseModel):
    mode: str
    database_type: str
    database_url_masked: str
    connected: bool
    cloud_connected: bool
    last_backup_at: datetime | None
    pending_sync_changes: int
    conflicts: int
    schema_version: str | None


class StorageConnectionRequest(BaseModel):
    database_url: str = Field(min_length=8)
    label: str = "cloud"


class StorageMigrationPreviewOut(BaseModel):
    projects: int
    opportunities: int
    tasks: int
    backlink_records: int
    profiles: int
    duplicates: int
    conflicts: int
    compatible: bool
    notes: list[str]


class DeviceOut(ORMModel):
    id: str
    name: str
    platform: str
    status: str
    capabilities: list[str]
    last_seen_at: datetime | None
    version: str | None
    created_at: datetime


class DeviceRegisterRequest(BaseModel):
    name: str
    platform: str = "unknown"
    version: str | None = None
    capabilities: list[str] = []


class DeviceRegisterResponse(BaseModel):
    device_id: str
    api_key: str
    poll_interval_seconds: int


class DeviceHeartbeatRequest(BaseModel):
    status: str = "ONLINE"
    capabilities: list[str] = []


class DeviceTaskReport(BaseModel):
    status: str
    result: dict[str, Any] = {}
    error: str | None = None


class HealthOut(BaseModel):
    status: str
    version: str
    database: dict[str, Any]
    worker: dict[str, Any]
    storage_mode: str


class SystemInfoOut(BaseModel):
    """Static information about the running backend."""

    name: str
    version: str
    environment: str
    storage_mode: str
    database_type: str
    data_dir: str
    ai_enabled: bool
    celery_enabled: bool


class SyncChangeOut(BaseModel):
    """A single change of the hybrid synchronisation protocol."""

    entity_type: str
    entity_id: str
    operation: str
    version: int
    payload: dict[str, Any] = {}
    created_at: str | None = None


class SyncChangesOut(BaseModel):
    changes: list[SyncChangeOut] = []
