import {
  OpportunityCategory,
  OpportunityStatus,
  TaskStatus,
  TaskType,
  VerificationStatus,
} from "@autobacklinker/shared-types";

/** Human readable labels for enum-ish values. */
export const TASK_STATUS_LABELS: Record<string, string> = {
  DISCOVERED: "Discovered",
  NEEDS_REVIEW: "Needs review",
  APPROVED: "Approved",
  QUEUED: "Queued",
  RUNNING: "Running",
  WAITING_FOR_USER: "Waiting for user",
  WAITING_FOR_APPROVAL: "Waiting for approval",
  SUBMITTED: "Submitted",
  PUBLISHED_UNVERIFIED: "Published (unverified)",
  VERIFIED_LIVE: "Verified live",
  VERIFICATION_FAILED: "Verification failed",
  RETRY_SCHEDULED: "Retry scheduled",
  FAILED: "Failed",
  SKIPPED: "Skipped",
  CANCELLED: "Cancelled",
};

export const OPPORTUNITY_STATUS_LABELS: Record<string, string> = {
  DISCOVERED: "Discovered",
  NEEDS_REVIEW: "Needs review",
  APPROVED: "Approved",
  REJECTED: "Rejected",
  EXCLUDED: "Excluded",
  DUPLICATE: "Duplicate",
  QUEUED: "Queued",
  IN_PROGRESS: "In progress",
  COMPLETED: "Completed",
  FAILED: "Failed",
};

export const VERIFICATION_STATUS_LABELS: Record<string, string> = {
  PENDING: "Pending",
  SUBMITTED: "Submitted",
  PUBLISHED_UNVERIFIED: "Published (unverified)",
  VERIFIED_LIVE: "Verified live",
  VERIFICATION_FAILED: "Verification failed",
  TEMPORARILY_UNAVAILABLE: "Temporarily unavailable",
  REMOVED: "Removed",
  UNKNOWN: "Unknown",
};

export const TASK_TYPE_LABELS: Record<string, string> = {
  DISCOVER: "Discover",
  SUBMIT: "Submit",
  VERIFY: "Verify",
  IMPORT: "Import",
  EXPORT: "Export",
  MANUAL: "Manual",
};

export const CATEGORY_LABELS: Record<string, string> = {
  BUSINESS_DIRECTORY: "Business directory",
  INDUSTRY_DIRECTORY: "Industry directory",
  LOCAL_CITATION: "Local citation",
  BUSINESS_PROFILE: "Business profile",
  SOCIAL_PROFILE: "Social profile",
  PUBLIC_PROFILE: "Public profile",
  EDITORIAL: "Editorial",
  GUEST_POST: "Guest post",
  RESOURCE_PAGE: "Resource page",
  SUPPLIER_PARTNER: "Supplier partner",
  FORUM_COMMUNITY: "Forum / community",
  BLOG_COMMENT: "Blog comment",
  QA_CONTRIBUTION: "Q&A contribution",
  IMAGE_ATTRIBUTION: "Image attribution",
  DOCUMENT_SHARING: "Document sharing",
  BROKEN_LINK: "Broken link",
  UNLINKED_MENTION: "Unlinked mention",
  CUSTOM: "Custom",
};

export const IMPORT_ACTION_LABELS: Record<string, string> = {
  CREATE: "Create",
  UPDATE: "Update",
  SKIP: "Skip",
  RETRY: "Retry",
  VERIFY: "Verify",
  CONFLICT: "Conflict",
  INVALID: "Invalid",
};

export const SUBMISSION_METHOD_LABELS: Record<string, string> = {
  API: "API",
  INTEGRATION: "Integration",
  BROWSER_FORM: "Browser form",
  EMAIL_OUTREACH: "Email outreach",
  MANUAL: "Manual",
  UNKNOWN: "Unknown",
};

export const STORAGE_MODE_LABELS: Record<string, string> = {
  LOCAL: "Local Mode",
  CLOUD: "Cloud Mode",
  HYBRID: "Hybrid Mode",
};

export const ALL_OPPORTUNITY_CATEGORIES: OpportunityCategory[] = Object.values(
  OpportunityCategory,
) as OpportunityCategory[];

export const ALL_OPPORTUNITY_STATUSES: OpportunityStatus[] = Object.values(
  OpportunityStatus,
) as OpportunityStatus[];

export const ALL_TASK_STATUSES: TaskStatus[] = Object.values(TaskStatus) as TaskStatus[];

export const ALL_TASK_TYPES: TaskType[] = Object.values(TaskType) as TaskType[];

export const ALL_VERIFICATION_STATUSES: VerificationStatus[] = Object.values(
  VerificationStatus,
) as VerificationStatus[];

export const ALL_IMPORT_ACTIONS = [
  "CREATE",
  "UPDATE",
  "SKIP",
  "RETRY",
  "VERIFY",
  "CONFLICT",
  "INVALID",
] as const;

/** Score components rendered in the opportunity detail drawer. */
export const SCORE_COMPONENT_LABELS: Record<string, string> = {
  topical_relevance: "Topical relevance",
  site_quality: "Site quality",
  editorial_relevance: "Editorial relevance",
  links_allowed: "Links allowed",
  documented_submission: "Documented submission",
  effort: "Effort",
  business_value: "Business value",
  relationship: "Relationship",
  spam_penalty: "Spam penalty",
  total: "Total score",
};
