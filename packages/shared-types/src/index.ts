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

export interface IntegrationCredential {
  id: string;
  provider: string;
  label: string;
  status: "CONFIGURED" | "MISSING" | "ERROR";
  has_value: boolean;
  updated_at: string;
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
