/**
 * Shared API / domain contracts for Auto Backlinker.
 *
 * These types are the single source of truth shared by:
 *  - apps/web      (Next.js browser client)
 *  - apps/desktop  (Tauri 2 desktop client)
 *  - packages/api-client (typed transport layer)
 *
 * The Python backend mirrors these definitions in `apps/api/app/schemas`.
 */

export const API_VERSION = "1.0.0";

/* ------------------------------------------------------------------ */
/* Enumerations                                                        */
/* ------------------------------------------------------------------ */

export const TaskStatus = {
  DISCOVERED: "DISCOVERED",
  NEEDS_REVIEW: "NEEDS_REVIEW",
  APPROVED: "APPROVED",
  QUEUED: "QUEUED",
  RUNNING: "RUNNING",
  WAITING_FOR_USER: "WAITING_FOR_USER",
  WAITING_FOR_APPROVAL: "WAITING_FOR_APPROVAL",
  SUBMITTED: "SUBMITTED",
  PUBLISHED_UNVERIFIED: "PUBLISHED_UNVERIFIED",
  VERIFIED_LIVE: "VERIFIED_LIVE",
  VERIFICATION_FAILED: "VERIFICATION_FAILED",
  RETRY_SCHEDULED: "RETRY_SCHEDULED",
  FAILED: "FAILED",
  SKIPPED: "SKIPPED",
  CANCELLED: "CANCELLED",
  /** Internal terminal state for non-submission tasks (import, export, discover). */
  COMPLETED: "COMPLETED",
} as const;
export type TaskStatus = (typeof TaskStatus)[keyof typeof TaskStatus];

export const TASK_STATUSES = Object.values(TaskStatus) as TaskStatus[];

/** Statuses that represent a terminal, non-runnable state for the queue. */
export const TERMINAL_STATUSES: TaskStatus[] = [
  TaskStatus.VERIFIED_LIVE,
  TaskStatus.SKIPPED,
  TaskStatus.CANCELLED,
];

export const TaskType = {
  DISCOVER: "DISCOVER",
  SUBMIT: "SUBMIT",
  VERIFY: "VERIFY",
  IMPORT: "IMPORT",
  EXPORT: "EXPORT",
  MANUAL: "MANUAL",
} as const;
export type TaskType = (typeof TaskType)[keyof typeof TaskType];

export const ExecutionEnvironment = {
  CLOUD: "CLOUD",
  LOCAL: "LOCAL",
} as const;
export type ExecutionEnvironment =
  (typeof ExecutionEnvironment)[keyof typeof ExecutionEnvironment];

export const OpportunityStatus = {
  DISCOVERED: "DISCOVERED",
  NEEDS_REVIEW: "NEEDS_REVIEW",
  APPROVED: "APPROVED",
  REJECTED: "REJECTED",
  EXCLUDED: "EXCLUDED",
  DUPLICATE: "DUPLICATE",
  QUEUED: "QUEUED",
  IN_PROGRESS: "IN_PROGRESS",
  COMPLETED: "COMPLETED",
  FAILED: "FAILED",
} as const;
export type OpportunityStatus =
  (typeof OpportunityStatus)[keyof typeof OpportunityStatus];

export const VerificationStatus = {
  PENDING: "PENDING",
  SUBMITTED: "SUBMITTED",
  PUBLISHED_UNVERIFIED: "PUBLISHED_UNVERIFIED",
  VERIFIED_LIVE: "VERIFIED_LIVE",
  VERIFICATION_FAILED: "VERIFICATION_FAILED",
  TEMPORARILY_UNAVAILABLE: "TEMPORARILY_UNAVAILABLE",
  REMOVED: "REMOVED",
  UNKNOWN: "UNKNOWN",
} as const;
export type VerificationStatus =
  (typeof VerificationStatus)[keyof typeof VerificationStatus];

export const OpportunityCategory = {
  BUSINESS_DIRECTORY: "BUSINESS_DIRECTORY",
  INDUSTRY_DIRECTORY: "INDUSTRY_DIRECTORY",
  LOCAL_CITATION: "LOCAL_CITATION",
  BUSINESS_PROFILE: "BUSINESS_PROFILE",
  SOCIAL_PROFILE: "SOCIAL_PROFILE",
  PUBLIC_PROFILE: "PUBLIC_PROFILE",
  EDITORIAL: "EDITORIAL",
  GUEST_POST: "GUEST_POST",
  RESOURCE_PAGE: "RESOURCE_PAGE",
  SUPPLIER_PARTNER: "SUPPLIER_PARTNER",
  FORUM_COMMUNITY: "FORUM_COMMUNITY",
  BLOG_COMMENT: "BLOG_COMMENT",
  QA_CONTRIBUTION: "QA_CONTRIBUTION",
  IMAGE_ATTRIBUTION: "IMAGE_ATTRIBUTION",
  DOCUMENT_SHARING: "DOCUMENT_SHARING",
  BROKEN_LINK: "BROKEN_LINK",
  UNLINKED_MENTION: "UNLINKED_MENTION",
  CUSTOM: "CUSTOM",
} as const;
export type OpportunityCategory =
  (typeof OpportunityCategory)[keyof typeof OpportunityCategory];

export const SubmissionMethod = {
  API: "API",
  INTEGRATION: "INTEGRATION",
  BROWSER_FORM: "BROWSER_FORM",
  EMAIL_OUTREACH: "EMAIL_OUTREACH",
  MANUAL: "MANUAL",
  UNKNOWN: "UNKNOWN",
} as const;
export type SubmissionMethod =
  (typeof SubmissionMethod)[keyof typeof SubmissionMethod];

export const AdapterKind = {
  OFFICIAL_API: "OFFICIAL_API",
  DOCUMENTED_INTEGRATION: "DOCUMENTED_INTEGRATION",
  BROWSER_AUTOMATION: "BROWSER_AUTOMATION",
  EMAIL_OUTREACH: "EMAIL_OUTREACH",
  MANUAL_ASSISTED: "MANUAL_ASSISTED",
  CUSTOM: "CUSTOM",
} as const;
export type AdapterKind = (typeof AdapterKind)[keyof typeof AdapterKind];

export const ImportAction = {
  CREATE: "CREATE",
  UPDATE: "UPDATE",
  SKIP: "SKIP",
  RETRY: "RETRY",
  VERIFY: "VERIFY",
  CONFLICT: "CONFLICT",
  INVALID: "INVALID",
} as const;
export type ImportAction = (typeof ImportAction)[keyof typeof ImportAction];

export const ImportStatus = {
  PENDING: "PENDING",
  PREVIEWED: "PREVIEWED",
  COMMITTED: "COMMITTED",
  FAILED: "FAILED",
} as const;
export type ImportStatus = (typeof ImportStatus)[keyof typeof ImportStatus];

export const ExportStatus = {
  PENDING: "PENDING",
  RUNNING: "RUNNING",
  COMPLETED: "COMPLETED",
  FAILED: "FAILED",
} as const;
export type ExportStatus = (typeof ExportStatus)[keyof typeof ExportStatus];

export const DiscoveryRunStatus = {
  PENDING: "PENDING",
  RUNNING: "RUNNING",
  COMPLETED: "COMPLETED",
  FAILED: "FAILED",
  CANCELLED: "CANCELLED",
} as const;
export type DiscoveryRunStatus =
  (typeof DiscoveryRunStatus)[keyof typeof DiscoveryRunStatus];

export const DeviceStatus = {
  REGISTERED: "REGISTERED",
  ONLINE: "ONLINE",
  OFFLINE: "OFFLINE",
  DISABLED: "DISABLED",
} as const;
export type DeviceStatus = (typeof DeviceStatus)[keyof typeof DeviceStatus];

export const SyncState = {
  SYNCED: "SYNCED",
  SYNCING: "SYNCING",
  OFFLINE: "OFFLINE",
  PENDING_CHANGES: "PENDING_CHANGES",
  CONFLICT: "CONFLICT",
  AGENT_DISCONNECTED: "AGENT_DISCONNECTED",
} as const;
export type SyncState = (typeof SyncState)[keyof typeof SyncState];

export const StorageMode = {
  LOCAL: "LOCAL",
  CLOUD: "CLOUD",
  HYBRID: "HYBRID",
} as const;
export type StorageMode = (typeof StorageMode)[keyof typeof StorageMode];

export const ReportSheet = {
  EXECUTIVE_SUMMARY: "Executive Summary",
  ALL_OPPORTUNITIES: "All Opportunities",
  /** One row per website with the counters of the work that was done. */
  PER_WEBSITE: "Per website",
  VERIFIED_BACKLINKS: "Verified Backlinks",
  PENDING_TASKS: "Pending Tasks",
  FAILED_TASKS: "Failed Tasks",
  SKIPPED_TASKS: "Skipped Tasks",
  VERIFICATION_HISTORY: "Verification History",
  ACTIVITY_LOG: "Activity Log",
  IMPORT_ERRORS: "Import Errors",
} as const;
export type ReportSheet = (typeof ReportSheet)[keyof typeof ReportSheet];

/* ------------------------------------------------------------------ */
/* Envelope / pagination                                                */
/* ------------------------------------------------------------------ */

export interface ApiError {
  error: {
    code: string;
    message: string;
    details?: unknown;
    request_id?: string;
  };
}

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface PageParams {
  page?: number;
  page_size?: number;
  sort?: string;
  order?: "asc" | "desc";
}

/* ------------------------------------------------------------------ */
/* Domain objects                                                      */
/* ------------------------------------------------------------------ */

export interface User {
  id: string;
  email: string;
  name: string;
  is_active: boolean;
  is_admin: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface AuthTokens {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: User;
}

export interface BusinessProfile {
  id: string;
  name: string;
  primary_website: string;
  description: string;
  industry: string;
  niche: string;
  target_countries: string[];
  target_regions: string[];
  contact_email: string | null;
  contact_phone: string | null;
  social_profiles: Record<string, string>;
  logo_path: string | null;
  preferred_language: string;
  business_descriptions: string[];
  author_bios: string[];
  keywords: string[];
  primary_landing_pages: string[];
  secondary_landing_pages: string[];
  preferred_anchors: string[];
  anchor_preferences: {
    branded?: boolean;
    generic?: boolean;
    naked_url?: boolean;
    descriptive?: boolean;
  };
  preferred_categories: string[];
  excluded_domains: string[];
  excluded_categories: string[];
  target_domains: string[];
  monthly_target: number | null;
  campaign_goals: string;
  /** The address of the company - a directory submission asks for it. */
  address: string;
  city: string;
  state: string;
  country: string;
  postal_code: string;
  founded_year: number | null;
  employee_count: number | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectSettings {
  id: string;
  project_id: string;
  max_concurrency: number;
  global_concurrency: number;
  per_domain_concurrency: number;
  per_provider_concurrency: number;
  request_rate_per_minute: number;
  max_retries: number;
  backoff_base_seconds: number;
  jitter_seconds: number;
  operating_schedule: {
    days: number[];
    start_hour: number;
    end_hour: number;
  };
  verify_interval_hours: number;
  verify_backoff_hours: number;
  daily_discovery_limit: number;
  allow_browser_automation: boolean;
  require_approval: boolean;
  execution_environment: ExecutionEnvironment;
  auto_queue_approved: boolean;
  timezone: string;
}

export interface Project {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  business_profile_id: string | null;
  target_website: string;
  target_website_id: string | null;
  status: "ACTIVE" | "PAUSED" | "ARCHIVED";
  settings: ProjectSettings | null;
  counts?: ProjectCounts;
  created_at: string;
  updated_at: string;
  version: number;
}

export interface ProjectCounts {
  opportunities: number;
  approved: number;
  queued: number;
  running: number;
  completed: number;
  failed: number;
  verified_live: number;
  pending_manual: number;
}

export interface TargetWebsite {
  id: string;
  project_id: string;
  name: string;
  url: string;
  domain: string;
  kind: "MAIN" | "LANDING" | "BLOG" | "OTHER";
  is_active: boolean;
  created_at: string;
  updated_at?: string;
}

export interface ScoreBreakdown {
  topical_relevance: number;
  site_quality: number;
  editorial_relevance: number;
  links_allowed: number;
  documented_submission: number;
  effort: number;
  business_value: number;
  relationship: number;
  spam_penalty: number;
  total: number;
  reasons: string[];
  unavailable_metrics: string[];
}

export interface Opportunity {
  id: string;
  project_id: string;
  name: string;
  domain: string;
  opportunity_url: string;
  category: OpportunityCategory;
  discovery_source: string;
  discovery_provider: string | null;
  language: string | null;
  region: string | null;
  score: number;
  score_breakdown: ScoreBreakdown | null;
  status: OpportunityStatus;
  submission_method: SubmissionMethod;
  registration_required: boolean | null;
  requires_approval: boolean | null;
  adapter_id: string | null;
  anchor_text: string | null;
  description: string | null;
  notes: string | null;
  contact_email: string | null;
  target_landing_page: string | null;
  last_checked_at: string | null;
  last_result: string | null;
  backlink_status: VerificationStatus;
  error_detail: string | null;
  duplicate_of: string | null;
  excluded_until: string | null;
  project_ids?: string[];
  task_id?: string | null;
  created_at: string;
  updated_at: string;
  version: number;
}

export interface Task {
  id: string;
  project_id: string | null;
  opportunity_id: string | null;
  campaign_id: string | null;
  type: TaskType;
  status: TaskStatus;
  priority: number;
  execution_environment: ExecutionEnvironment;
  adapter_id: string | null;
  idempotency_key: string;
  payload: Record<string, unknown>;
  attempts: number;
  max_attempts: number;
  scheduled_for: string | null;
  started_at: string | null;
  finished_at: string | null;
  lease_expires_at: string | null;
  lease_owner: string | null;
  next_retry_at: string | null;
  last_error: string | null;
  skip_reason: string | null;
  requires_human: boolean;
  progress: number;
  created_at: string;
  updated_at: string;
  version: number;
}

export interface TaskAttempt {
  id: string;
  task_id: string;
  attempt_number: number;
  started_at: string;
  finished_at: string | null;
  outcome: string;
  error: string | null;
  evidence: Record<string, unknown> | null;
  worker: string | null;
  execution_environment: ExecutionEnvironment;
}

export interface TaskEvent {
  id: string;
  task_id: string | null;
  project_id: string | null;
  event_type: string;
  message: string;
  level: "INFO" | "WARNING" | "ERROR" | "SUCCESS";
  execution_environment: ExecutionEnvironment | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface BacklinkRecord {
  id: string;
  project_id: string;
  opportunity_id: string | null;
  task_id: string | null;
  target_website: string;
  expected_link_url: string;
  published_page_url: string | null;
  expected_destination_url: string;
  observed_destination_url: string | null;
  observed_anchor_text: string | null;
  link_present: boolean | null;
  destination_matched: boolean | null;
  is_live: boolean | null;
  link_attribute: string | null;
  http_status: number | null;
  verification_status: VerificationStatus;
  verified_at: string | null;
  last_success_at: string | null;
  next_verification_at: string | null;
  evidence: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface VerificationRun {
  id: string;
  backlink_id: string;
  status: VerificationStatus;
  link_present: boolean | null;
  destination_matched: boolean | null;
  http_status: number | null;
  observed_anchor_text: string | null;
  observed_destination_url: string | null;
  link_attribute: string | null;
  error: string | null;
  evidence: Record<string, unknown> | null;
  verified_at: string;
}

export interface DiscoveryRun {
  id: string;
  project_id: string;
  provider: string;
  status: DiscoveryRunStatus;
  query: string | null;
  requested_limit: number;
  discovered_count: number;
  new_count: number;
  duplicate_count: number;
  rejected_count: number;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export interface Adapter {
  id: string;
  key: string;
  name: string;
  kind: AdapterKind;
  description: string | null;
  supported_categories: string[];
  supported_methods: SubmissionMethod[];
  supported_environments: ExecutionEnvironment[];
  required_config: Record<string, unknown>;
  required_user_fields: string[];
  registration_required: boolean;
  manual_approval_required: boolean;
  automatable: boolean;
  verification_method: string;
  retryable_errors: string[];
  restrictions: string | null;
  enabled: boolean;
  domains: string[];
  success_signals: string[];
}

export interface ImportColumnMapping {
  source_column: string;
  target_field: string;
  confidence: number;
  required: boolean;
}

export interface ImportRowPlan {
  row_number: number;
  action: ImportAction;
  reason: string;
  opportunity_id: string | null;
  task_id: string | null;
  values: Record<string, unknown>;
  errors: string[];
}

export interface ImportPreview {
  import_job_id: string;
  file_name: string;
  sheets: string[];
  detected_mapping: ImportColumnMapping[];
  rows: ImportRowPlan[];
  counts: {
    total: number;
    create: number;
    update: number;
    skip: number;
    retry: number;
    verify: number;
    conflict: number;
    invalid: number;
  };
}

export interface ImportJob {
  id: string;
  project_id: string | null;
  file_name: string;
  status: ImportStatus;
  dry_run: boolean;
  total_rows: number;
  created_count: number;
  updated_count: number;
  skipped_count: number;
  retried_count: number;
  verify_count: number;
  conflict_count: number;
  invalid_count: number;
  error_report_path: string | null;
  created_at: string;
  committed_at: string | null;
}

export interface ImportRow {
  id: string;
  import_job_id: string;
  row_number: number;
  action: ImportAction;
  reason: string | null;
  raw: Record<string, unknown>;
  errors: string | null;
}

export interface ExportJob {
  id: string;
  project_id: string | null;
  scope: string;
  status: ExportStatus;
  format: "xlsx" | "csv";
  file_name: string | null;
  file_path: string | null;
  row_count: number | null;
  error: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface ActivityEvent {
  id: string;
  event_type: string;
  level: "INFO" | "WARNING" | "ERROR" | "SUCCESS";
  message: string;
  project_id: string | null;
  project_name: string | null;
  task_id: string | null;
  opportunity_id: string | null;
  website: string | null;
  execution_environment: ExecutionEnvironment | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface DashboardMetrics {
  projects: number;
  opportunities: number;
  approved: number;
  queued: number;
  running: number;
  published: number;
  verified_live: number;
  pending_manual: number;
  failed: number;
  awaiting_retry: number;
  requiring_verification: number;
  connected_devices: number;
  cloud_workers: number;
  running_local_jobs: number;
  sync_errors: number;
  by_status: Record<string, number>;
  by_category: Array<{ category: string; count: number }>;
  generated_at: string;
}

export interface Device {
  id: string;
  name: string;
  platform: string;
  status: DeviceStatus;
  capabilities: string[];
  last_seen_at: string | null;
  version: string | null;
  created_at: string;
}

export interface AuditLog {
  id: string;
  actor_id: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  ip_address: string | null;
  created_at: string;
}

export interface StorageStatus {
  mode: StorageMode;
  database_type: "sqlite" | "postgresql";
  database_url_masked: string;
  connected: boolean;
  cloud_connected: boolean;
  last_backup_at: string | null;
  pending_sync_changes: number;
  conflicts: number;
  schema_version: string | null;
}

/** Browser runtime - always an isolated browser owned by this application. */
export interface BrowserRuntimeStatus {
  available: boolean;
  headless: boolean;
  browser_path: string | null;
  browsers_dir: string | null;
  profile_dir: string | null;
  version: string | null;
  detail: string;
  isolation: {
    personal_profile_used: boolean;
    own_profile_directory: boolean;
    headless_by_default: boolean;
    extensions_disabled: boolean;
    synchronisation_disabled: boolean;
    arguments: string[];
    note: string;
  };
}

/** Measurement of the machine the browser jobs run on. */
export interface ResourceStatus {
  resources: {
    cpu_percent: number;
    load_average: number;
    memory_total_mb: number;
    memory_available_mb: number;
    memory_used_percent: number;
    disk_free_mb: number;
    cpu_count: number;
    overloaded: boolean;
    busy: boolean;
  };
  configured_limit: number;
  preference: string;
  effective_limit: number;
  reason: string;
  measured_at: number;
}

export interface ExecutionSettings {
  state: "RUNNING" | "PAUSED" | "STOPPED";
  max_browser_jobs: number;
  resource_preference: "max_speed" | "balanced" | "save_resources";
  headless: boolean;
  per_domain_limit: number;
  per_domain_requests_per_minute: number;
  task_timeout_seconds: number;
  page_timeout_seconds: number;
  states?: Record<string, string>;
}

/** State of a website in the central list. */
export const WebsiteStatus = {
  DISCOVERED: "DISCOVERED",
  NEEDS_REVIEW: "NEEDS_REVIEW",
  APPROVED: "APPROVED",
  ACTIVE: "ACTIVE",
  /** The site is reachable but does not accept listings any more. */
  NOT_WORKING: "NOT_WORKING",
  /** The site closed down. */
  DELETED: "DELETED",
  EXCLUDED: "EXCLUDED",
  REJECTED: "REJECTED",
  DUPLICATE: "DUPLICATE",
} as const;
export type WebsiteStatus = (typeof WebsiteStatus)[keyof typeof WebsiteStatus];

export const WEBSITE_STATUSES = Object.values(WebsiteStatus) as WebsiteStatus[];

/** How the work on one website went. */
export interface WebsiteStats {
  opportunities: number;
  submitted: number;
  verified: number;
  failed: number;
  pending: number;
  waiting_for_details: number;
  last_attempt_at: string | null;
}

/** One row of the central website list. */
export interface WebsiteListItem {
  id: string;
  name: string;
  domain: string;
  opportunity_url: string;
  category: string;
  niche: string;
  status: string;
  submission_method: string;
  score: number;
  notes: string | null;
  excluded_until: string | null;
  project_ids: string[];
  project_count: number;
  stats: WebsiteStats;
  created_at: string;
  updated_at: string;
}

/** The result of importing websites into the central list. */
export interface WebsiteImportResult {
  created: number;
  updated: number;
  skipped: number;
  invalid: number;
  rows: Array<{ row: number; action: string; reason: string; domain: string }>;
}

/** The result of adding websites from the central list to a project. */
export interface WebsiteChooseResult {
  linked: number;
  skipped: number;
  tasks_created: number;
  task_ids: string[];
}

/** Which details could not be derived from the business profile. */
export interface DetailsGapReport {
  required: string[];
  filled: string[];
  missing: string[];
  derivable: string[];
  not_derivable: Array<{ field: string; label: string; reason: string }>;
  source: string;
}

export interface WorkerStatus {
  execution: ExecutionSettings;
  running_jobs: number;
  running_browser_jobs: number;
  resources: ResourceStatus;
  browser: BrowserRuntimeStatus;
  queue: Record<string, number>;
}

/** The details one directory asks for, stored per opportunity. */
export interface SubmissionDetails {
  opportunity_id: string;
  company_name: string | null;
  description: string | null;
  email: string | null;
  phone: string | null;
  website: string | null;
  address: string | null;
  city: string | null;
  state: string | null;
  country: string | null;
  postal_code: string | null;
  logo_path: string | null;
  categories: string[];
  founded_year: number | null;
  employee_count: number | null;
  extra: Record<string, unknown>;
  /** Which fields the assistant produced. */
  generated: Record<string, unknown>;
  updated_at: string | null;
  /** The fields the target site asks for. */
  required: string[];
  /** The fields that are still missing. */
  missing: string[];
  complete: boolean;
}

export interface SubmissionDetailsUpdate {
  company_name?: string | null;
  description?: string | null;
  email?: string | null;
  phone?: string | null;
  website?: string | null;
  address?: string | null;
  city?: string | null;
  state?: string | null;
  country?: string | null;
  postal_code?: string | null;
  logo_path?: string | null;
  categories?: string[];
  founded_year?: number | null;
  employee_count?: number | null;
  extra?: Record<string, unknown>;
}

export interface GenerateDetailsResult {
  details: SubmissionDetails;
  /** The names of the fields the assistant filled in. */
  generated: string[];
  /** "ai" or "profile" - where the values came from. */
  source: string;
}

/** State of the automatic submission of a project. */
export interface AutoPilotState {
  enabled: boolean;
  categories: string[];
  /** Approved opportunities that are waiting for the worker. */
  waiting: number;
  /** Opportunities that were submitted automatically. */
  submitted: number;
}

export interface IntegrationCredential {
  id: string;
  provider: string;
  label: string;
  status: "CONFIGURED" | "MISSING" | "ERROR";
  has_value: boolean;
  updated_at: string;
}

/** A provider the platform knows about and whether a secret is stored for it. */
export interface IntegrationProvider {
  key: string;
  name: string;
  purpose: string;
  docs: string;
  configured: boolean;
}

/** A stored credential - the secret itself is never returned. */
export interface IntegrationCredentialSummary {
  id: string;
  provider: string;
  label: string;
  status: string;
  has_value: boolean;
  masked_hint: string;
  updated_at: string;
}

/** Per project configuration of an adapter. */
export interface AdapterConfiguration {
  id: string;
  adapter_id: string;
  project_id: string | null;
  config: Record<string, unknown>;
}

/** A discovery provider and whether it can be used right now. */
export interface DiscoveryProvider {
  key: string;
  name: string;
  description?: string;
  requires_credentials: boolean;
  categories: string[];
  enabled?: boolean;
  available?: boolean;
  reason?: string | null;
}

/** A campaign groups the tasks of a project towards one goal. */
export interface Campaign {
  id: string;
  project_id: string;
  name: string;
  description: string | null;
  status: string;
  goal_type: string | null;
  target_value: number | null;
  created_at: string;
  updated_at: string;
}

/**
 * The state of one row of the campaign table of a project.
 *
 * ``NEEDS_DETAILS``  - the profile does not carry every value the site asks for
 * ``READY``          - complete, waiting for the start button
 * ``QUEUED``         - a task waits for a worker
 * ``SUBMITTING``     - a worker is submitting right now
 * ``WAITING_MANUAL`` - the form has to be filled by hand - the values are ready
 * ``SUBMITTED``      - submitted, the link is not verified yet
 * ``VERIFIED``       - the link was found on the page
 * ``FAILED``         - the submission failed and can be retried
 * ``VERIFICATION_FAILED`` - the page was checked but the link was not found
 */
export type CampaignRowStatus =
  | "NOT_STARTED"
  | "NEEDS_DETAILS"
  | "READY"
  | "QUEUED"
  | "SUBMITTING"
  | "WAITING_MANUAL"
  | "SUBMITTED"
  | "VERIFIED"
  | "FAILED"
  | "VERIFICATION_FAILED"
  | "EXCLUDED";

export interface CampaignRow {
  opportunity_id: string;
  website_id: string;
  name: string;
  domain: string;
  url: string;
  category: string;
  status: CampaignRowStatus;
  /** How many of the values the site asks for are filled (0-100). */
  details_percent: number;
  details_complete: boolean;
  /** Human readable names of the values that are still missing. */
  missing: string[];
  task_id: string | null;
  task_status: string | null;
  backlink_id: string | null;
  verification_status: string | null;
  published_page_url: string | null;
  last_update: string | null;
}

export interface CampaignSummary {
  total: number;
  /** Verified + submitted - the work that is done. */
  done: number;
  verified: number;
  submitted: number;
  in_progress: number;
  waiting_manual: number;
  needs_details: number;
  not_started: number;
  failed: number;
  excluded: number;
  remaining: number;
  /** Done / total, 0-100. */
  percent: number;
}

export interface CampaignView {
  project_id: string;
  project_status: string;
  generated_at: string;
  rows: CampaignRow[];
  summary: CampaignSummary;
}

export interface CampaignAddRow {
  input: string;
  url: string;
  status: "added" | "linked" | "existing" | "invalid" | "deleted";
  message: string;
  website_id?: string;
  opportunity_id?: string;
}

export interface CampaignAddResult {
  results: CampaignAddRow[];
  added: number;
  linked: number;
  existing: number;
  invalid: number;
  deleted: number;
}

export interface CampaignStartResult {
  queued: number;
  already_queued: number;
  needs_details: Array<{ opportunity_id: string; website: string; missing: string[] }>;
  done: number;
  excluded: number;
  skipped: number;
  total: number;
}

export interface CampaignSubmitResult {
  backlink_id: string;
  published_page_url: string | null;
  verification_status: string;
  verify_task_id: string | null;
  opportunity_id: string;
}

/** A recurring job (discovery or verification) of the scheduler. */
export interface Schedule {
  id: string;
  name: string;
  kind: "discovery" | "verification";
  target_id: string | null;
  interval_seconds: number | null;
  cron: string | null;
  next_run_at: string | null;
  last_run_at: string | null;
  enabled: boolean;
  config: Record<string, unknown>;
}

/** Static information about the backend a client talks to. */
export interface SystemInfo {
  name: string;
  version: string;
  environment: string;
  storage_mode: StorageMode | string;
  database_type: "sqlite" | "postgresql";
  data_dir: string;
  ai_enabled: boolean;
  celery_enabled: boolean;
}

/** The health payload of `GET /health`. */
export interface HealthStatus {
  status: string;
  version: string;
  database: Record<string, unknown>;
  worker: Record<string, unknown>;
  storage_mode: string;
}

/** State of the hybrid synchronisation between a local and a cloud workspace. */
export interface SyncStatus {
  pending: number;
  conflicts: number;
  last_sync_at: string | null;
  online: boolean;
}

export interface SyncPushResult {
  ok: boolean;
  message?: string;
  pushed: number;
  conflicts: number;
}

export interface SyncPullResult {
  ok: boolean;
  message?: string;
  applied: number;
  skipped: number;
}

export interface SyncResolveResult {
  ok: boolean;
  message?: string;
  strategy?: string;
}

/** One change of the hybrid synchronisation protocol. */
export interface SyncChange {
  entity_type: string;
  entity_id: string;
  operation: string;
  version: number;
  payload: Record<string, unknown>;
  created_at: string | null;
}

export interface SyncChangesResponse {
  changes: SyncChange[];
}

/** Result of `POST /api/v1/storage/test`. */
export interface StorageTestResult {
  ok: boolean;
  message: string;
  dialect: string;
}

/** A backup file of the local database. */
export interface StorageBackup {
  path: string;
  created_at: string;
  label?: string;
}

export interface StorageRestoreResult {
  restored: boolean;
  source?: string;
}

/** One entry of the backup history. */
export interface StorageBackupEntry {
  path: string;
  name: string;
  size_bytes: number;
  created_at: string;
  /** Keeps the entry assignable to `Record<string, unknown>`. */
  [key: string]: unknown;
}

/** The status of the configured AI stack. */
export interface AiStatus {
  configured: boolean;
  provider: string | null;
  model: string | null;
}

/** Registration of a local agent (device). */
export interface DeviceRegisterRequest {
  name: string;
  platform?: string;
  version?: string | null;
  capabilities?: string[];
}

export interface DeviceRegisterResponse {
  device_id: string;
  api_key: string;
  poll_interval_seconds: number;
}

/** Heartbeat of a local agent. */
export interface DeviceHeartbeatRequest {
  status?: string;
  capabilities?: string[];
}

/** The result a local agent reports for a finished task. */
export interface DeviceTaskReport {
  status: string;
  result?: Record<string, unknown>;
  error?: string | null;
}

/** The queue counters per task status. */
export type QueueStats = Record<string, number>;

/** The response of `POST /api/v1/queue`. */
export interface QueueCreateResponse {
  created: number;
  task_ids: string[];
  skipped?: number;
}

/** The response of `POST /api/v1/queue/reorder`. */
export interface ReorderResult {
  updated: number;
}

/** The response of the bulk endpoints (`/opportunities/bulk`, `/queue/bulk-control`). */
export interface BulkActionResult {
  affected: number;
}

/** The response of `POST /api/v1/verification/run`. */
export interface VerificationScheduleResult {
  scheduled: number;
  task_ids?: string[];
}

/** The response of `POST /api/v1/registry/exclusions`. */
export interface DomainExclusionResult {
  domain: string;
  affected: number;
  until: string | null;
}

/** The response of `POST /api/v1/registry/merge`. */
export interface MergeDuplicatesResult {
  primary_id: string;
  merged: number;
}

/* ------------------------------------------------------------------ */
/* Request payload contracts                                           */
/* ------------------------------------------------------------------ */

export interface LoginRequest {
  email: string;
  password: string;
}

export interface RegisterRequest {
  email: string;
  password: string;
  name: string;
}

export interface BusinessProfileUpsert {
  name: string;
  primary_website: string;
  description?: string;
  industry?: string;
  niche?: string;
  target_countries?: string[];
  target_regions?: string[];
  contact_email?: string | null;
  contact_phone?: string | null;
  social_profiles?: Record<string, string>;
  preferred_language?: string;
  business_descriptions?: string[];
  author_bios?: string[];
  keywords?: string[];
  primary_landing_pages?: string[];
  secondary_landing_pages?: string[];
  preferred_anchors?: string[];
  anchor_preferences?: Partial<BusinessProfile["anchor_preferences"]>;
  preferred_categories?: string[];
  excluded_domains?: string[];
  excluded_categories?: string[];
  target_domains?: string[];
  monthly_target?: number | null;
  campaign_goals?: string;
}

export interface ProjectCreate {
  name: string;
  description?: string;
  target_website: string;
  business_profile_id?: string | null;
  settings?: Partial<ProjectSettings>;
  landing_pages?: Array<{
    name: string;
    url: string;
    kind?: TargetWebsite["kind"];
  }>;
}

export interface DiscoveryRequest {
  project_id: string;
  provider: string;
  query?: string;
  keywords?: string[];
  countries?: string[];
  language?: string;
  category?: OpportunityCategory;
  limit?: number;
  seeds?: string[];
  config?: Record<string, unknown>;
}

export interface OpportunityUpdate {
  name?: string;
  opportunity_url?: string;
  category?: OpportunityCategory;
  status?: OpportunityStatus;
  adapter_id?: string | null;
  anchor_text?: string | null;
  description?: string | null;
  notes?: string | null;
  contact_email?: string | null;
  target_landing_page?: string | null;
  score?: number;
  submission_method?: SubmissionMethod;
}

/** Manual addition of a website to the registry. */
export interface OpportunityCreate {
  opportunity_url: string;
  name?: string;
  category?: OpportunityCategory | string;
  domain?: string;
  discovery_source?: string;
  submission_method?: SubmissionMethod | string;
  adapter_id?: string | null;
  anchor_text?: string | null;
  description?: string | null;
  notes?: string | null;
  contact_email?: string | null;
  target_landing_page?: string | null;
  registration_required?: boolean | null;
  requires_approval?: boolean | null;
  project_id?: string | null;
}

/** Exclusion of every website of one domain. */
export interface DomainExclusionRequest {
  domain: string;
  until?: string;
  reason?: string;
}

/** Merge of duplicate registry entries into one primary record. */
export interface MergeDuplicatesRequest {
  primary_id: string;
  duplicate_ids: string[];
}

export interface BulkActionRequest {
  opportunity_ids: string[];
  action: "approve" | "reject" | "exclude" | "delete" | "queue" | "add_to_project";
  project_id?: string;
  reason?: string;
  excluded_until?: string;
}

export interface QueueCreateRequest {
  project_ids?: string[];
  opportunity_ids?: string[];
  type?: TaskType;
  priority?: number;
  scheduled_for?: string | null;
  execution_environment?: ExecutionEnvironment;
  adapter_id?: string | null;
  payload?: Record<string, unknown>;
}

export interface TaskControlRequest {
  action: "pause" | "resume" | "cancel" | "retry" | "requeue";
  reason?: string;
}

/** The bulk variant of {@link TaskControlRequest}. */
export interface TaskBulkControlRequest extends TaskControlRequest {
  task_ids: string[];
}

export interface VerifyRequest {
  backlink_ids?: string[];
  project_id?: string;
  force?: boolean;
}

export interface ImportCommitRequest {
  apply_actions?: ImportAction[];
  dry_run?: boolean;
}

export interface StorageConnectionRequest {
  database_url: string;
  label?: string;
}

export interface StorageMigrationPreview {
  projects: number;
  opportunities: number;
  tasks: number;
  backlink_records: number;
  profiles: number;
  duplicates: number;
  conflicts: number;
  compatible: boolean;
  notes: string[];
}

/** The request of `POST /api/v1/reports`. */
export interface ReportCreateRequest {
  project_id?: string;
  format?: "xlsx" | "csv";
  scope?: string;
}

/** The configuration of one adapter for one project. */
export interface AdapterConfigurationUpdate {
  project_id?: string | null;
  config?: Record<string, unknown>;
}

/** A change pushed to a cloud workspace. */
export interface SyncEntityPushRequest {
  entity_id: string;
  operation?: string;
  version?: number;
  payload: Record<string, unknown>;
}

/** One row of an import job together with the planned action. */
export interface ImportRowDetail {
  row_number: number;
  action: ImportAction | string;
  reason: string | null;
  errors: string | null;
  raw: Record<string, unknown>;
}

/* ------------------------------------------------------------------ */
/* Recycle bin                                                         */
/* ------------------------------------------------------------------ */

/** The kinds of rows that can wait in the recycle bin. */
export type RecycleBinKind = "project" | "website" | "profile" | "opportunity";

/** One removed row that waits in the recycle bin. */
export interface RecycleBinItem {
  kind: RecycleBinKind | string;
  id: string;
  title: string;
  subtitle?: string | null;
  deleted_at?: string | null;
  meta?: Record<string, unknown>;
}

/** A page of the recycle bin plus the count of every kind. */
export interface RecycleBinPage {
  items: RecycleBinItem[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
  counts: Record<string, number>;
}

/* ------------------------------------------------------------------ */
/* Backlink details of a project                                       */
/* ------------------------------------------------------------------ */

/** The company facts and anchors a submission needs. */
export interface BacklinkDetails {
  profile_id?: string | null;
  profile_name?: string | null;
  shared_with_projects: number;
  target_website: string;
  landing_pages: Array<{ id?: string; name: string; url: string; kind?: string }>;
  company_name: string;
  description: string;
  email: string;
  phone: string;
  website: string;
  address: string;
  city: string;
  state: string;
  country: string;
  postal_code: string;
  categories: string[];
  founded_year?: number | null;
  employee_count?: number | null;
  anchors: string[];
  required: string[];
  filled: string[];
  missing: string[];
  notes: string[];
}

/** The values that can be written - every field is optional. */
export type BacklinkDetailsUpdate = Partial<
  Omit<BacklinkDetails, "profile_id" | "profile_name" | "shared_with_projects" | "landing_pages" | "required" | "filled" | "missing" | "notes">
>;
