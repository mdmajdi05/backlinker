/**
 * The central website list - the places where the backlinks are made.
 *
 * The list lives next to the projects, not inside them: a project picks the
 * sites it wants from the list.  This module holds the parts that the website
 * list page, the "add to project" dialog and the report page share:
 *
 *   * the statuses a site may have,
 *   * the normalisation of the answers of the backend (a local sidecar may be
 *     older and answer partially - the view must never crash on it),
 *   * the endpoint that the shared client does not know yet (the retry of the
 *     failed submissions of a report).
 *
 * Everything runs against the local backend of this machine - the desktop
 * client never talks to anything else.
 */

import type { WebsiteStatsRow } from "@autobacklinker/api-client";
import type {
  Paginated,
  WebsiteAutomationConfig,
  WebsiteChooseResult,
  WebsiteImportResult,
  WebsiteListItem,
  WebsiteStats,
} from "@autobacklinker/shared-types";
import { api, apiClient } from "./api";
import { titleCase } from "./format";

/* ------------------------------------------------------------------ */
/* The states of a website                                             */
/* ------------------------------------------------------------------ */

/**
 * The state a removed website carries.
 *
 * The delete action does not destroy a website - it takes it out of the list
 * and marks it as `DELETED`.  The backend hides those rows from the normal
 * list and only shows them when the filter asks for them (the recycle bin).
 */
export const REMOVED_WEBSITE_STATUS = "DELETED";

/** The badge of a website that lives in the recycle bin. */
export const REMOVED_WEBSITE_LABEL = "Removed";

/**
 * The states an operator may set by hand.
 *
 * `DISCOVERED` and `DUPLICATE` exist in the data model but are set by the
 * backend - the operator picks one of the states below.  `DELETED` is not one
 * of them: a website leaves the list through the delete action, not through
 * the state drop-down.
 */
export const WEBSITE_STATUS_CHOICES = [
  "ACTIVE",
  "NEEDS_REVIEW",
  "APPROVED",
  "NOT_WORKING",
  "EXCLUDED",
  "REJECTED",
] as const;

export type WebsiteStatusChoice = (typeof WEBSITE_STATUS_CHOICES)[number];

const STATUS_LABELS: Record<string, string> = {
  ACTIVE: "Active",
  NEEDS_REVIEW: "Needs review",
  APPROVED: "Approved",
  NOT_WORKING: "Not working",
  EXCLUDED: "Excluded",
  REJECTED: "Rejected",
  DELETED: REMOVED_WEBSITE_LABEL,
  DISCOVERED: "Discovered",
  DUPLICATE: "Duplicate",
};

/** A readable label of a state. */
export function websiteStatusLabel(status: string | null | undefined): string {
  const key = (status ?? "").trim().toUpperCase();
  if (!key) return "Unknown";
  return STATUS_LABELS[key] ?? titleCase(key);
}

/**
 * True when the website was removed from the list.
 *
 * A removed website lives in the recycle bin: it is hidden in the normal
 * view, its history is kept and it can be restored.
 */
export function isRemovedWebsite(status: string | null | undefined): boolean {
  return (status ?? "").trim().toUpperCase() === REMOVED_WEBSITE_STATUS;
}

/** The states of the filter - every state plus "all". */
export const WEBSITE_STATUS_FILTERS: Array<{ value: string; label: string }> = [
  { value: "", label: "All states" },
  ...WEBSITE_STATUS_CHOICES.map((value) => ({
    value,
    label: websiteStatusLabel(value),
  })),
  { value: "DISCOVERED", label: "Discovered" },
  { value: "DUPLICATE", label: "Duplicate" },
];

/**
 * The states of a select - the current state is always part of the list, even
 * when the backend knows a state the operator may not set by hand.
 */
export function websiteStatusOptions(current: string): string[] {
  const value = (current ?? "").trim().toUpperCase();
  if (!value) return [...WEBSITE_STATUS_CHOICES];
  if ((WEBSITE_STATUS_CHOICES as readonly string[]).includes(value)) {
    return [...WEBSITE_STATUS_CHOICES];
  }
  return [value, ...WEBSITE_STATUS_CHOICES];
}

/* ------------------------------------------------------------------ */
/* Normalisation                                                       */
/* ------------------------------------------------------------------ */

function text(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "";
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return "";
}

function count(value: unknown): number {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function optionalText(value: unknown): string | null {
  const result = text(value).trim();
  return result.length > 0 ? result : null;
}

function normalizeStats(raw: unknown): WebsiteStats {
  const data = (raw ?? {}) as Record<string, unknown>;
  return {
    opportunities: count(data.opportunities),
    submitted: count(data.submitted),
    verified: count(data.verified),
    failed: count(data.failed),
    pending: count(data.pending),
    waiting_for_details: count(data.waiting_for_details),
    last_attempt_at: optionalText(data.last_attempt_at),
  };
}

function normalizeAutomation(raw: unknown): WebsiteAutomationConfig | null {
  if (!raw || typeof raw !== "object") return null;
  const data = raw as Record<string, unknown>;
  const rawFields = (data.fields ?? {}) as Record<string, unknown>;
  const fields: Record<string, string> = {};
  Object.entries(rawFields).forEach(([selector, template]) => {
    const key = selector.trim();
    if (key) fields[key] = text(template);
  });
  const adapter = text(data.adapter).trim();
  if (!adapter && Object.keys(fields).length === 0) return null;
  return {
    adapter,
    form_url: text(data.form_url),
    fields,
    success_kind: text(data.success_kind) || "text",
    success_value: text(data.success_value),
    submit_selector: text(data.submit_selector),
    timeout_ms: typeof data.timeout_ms === "number" ? data.timeout_ms : null,
  };
}

/** One row of the central list - never trust the answer blindly. */
export function normalizeWebsite(raw: unknown): WebsiteListItem {
  const data = (raw ?? {}) as Record<string, unknown>;
  const projectIds = Array.isArray(data.project_ids)
    ? data.project_ids.map((item) => text(item).trim()).filter(Boolean)
    : [];
  return {
    id: text(data.id),
    name: text(data.name),
    domain: text(data.domain),
    opportunity_url: text(data.opportunity_url),
    signup_url: optionalText(data.signup_url),
    post_url: optionalText(data.post_url),
    recipe: (data.recipe ?? null) as WebsiteListItem["recipe"],
    registration_required:
      typeof data.registration_required === "boolean"
        ? data.registration_required
        : null,
    category: text(data.category),
    niche: text(data.niche),
    status: text(data.status).trim().toUpperCase() || "NEEDS_REVIEW",
    submission_method: text(data.submission_method),
    score: count(data.score),
    notes: optionalText(data.notes),
    excluded_until: optionalText(data.excluded_until),
    adapter_id: optionalText(data.adapter_id),
    adapter_key: optionalText(data.adapter_key),
    adapter_config: normalizeAutomation(data.adapter_config),
    project_ids: projectIds,
    project_count: count(data.project_count) || projectIds.length,
    stats: normalizeStats(data.stats),
    created_at: text(data.created_at),
    updated_at: text(data.updated_at),
  };
}

/** One row of the per website statistics. */
export function normalizeWebsiteStatsRow(raw: unknown): WebsiteStatsRow {
  const data = (raw ?? {}) as Record<string, unknown>;
  return {
    domain: text(data.domain),
    name: text(data.name),
    category: text(data.category),
    status: text(data.status),
    opportunities: count(data.opportunities),
    submitted: count(data.submitted),
    verified: count(data.verified),
    failed: count(data.failed),
    pending: count(data.pending),
    waiting_for_details: count(data.waiting_for_details),
    last_attempt_at: optionalText(data.last_attempt_at),
    notes: optionalText(data.notes),
  };
}

/* ------------------------------------------------------------------ */
/* The endpoints                                                       */
/* ------------------------------------------------------------------ */

export interface WebsiteListQuery {
  page?: number;
  page_size?: number;
  search?: string;
  category?: string;
  niche?: string;
  status?: string;
  project_id?: string;
  sort?: string;
  order?: "asc" | "desc";
}

/** The central list - the answers are normalised before they are shown. */
export async function fetchWebsites(
  query: WebsiteListQuery,
): Promise<Paginated<WebsiteListItem>> {
  const page = query.page ?? 1;
  const pageSize = query.page_size ?? 25;
  const raw = (await api.websites.list(apiClient, {
    page,
    page_size: pageSize,
    search: query.search || undefined,
    category: query.category || undefined,
    niche: query.niche || undefined,
    status: query.status || undefined,
    project_id: query.project_id || undefined,
    sort: query.sort || undefined,
    order: query.order || undefined,
  })) as Partial<Paginated<WebsiteListItem>> | null;

  const items = Array.isArray(raw?.items) ? raw.items.map(normalizeWebsite) : [];
  return {
    items,
    total: count(raw?.total),
    page: count(raw?.page) || page,
    page_size: count(raw?.page_size) || pageSize,
    pages: count(raw?.pages) || 1,
  };
}

/** The counters of every website (optionally of one project). */
export async function fetchWebsiteStats(
  projectId?: string,
): Promise<WebsiteStatsRow[]> {
  const raw = (await api.websites.stats(apiClient, projectId)) as unknown;
  if (!Array.isArray(raw)) return [];
  return raw.map(normalizeWebsiteStatsRow);
}

export interface WebsiteCreateInput {
  opportunity_url: string;
  /** The sign-up page, when the operator knows it (empty = find it). */
  signup_url?: string;
  /** The page where the link is posted (empty = find it). */
  post_url?: string;
  name?: string;
  category?: string;
  niche?: string;
  notes?: string;
  submission_method?: string;
}

/** The procedure of one website, as the local backend stored it. */
export interface WebsiteRecipeResult {
  website_id: string;
  signup_url: string | null;
  post_url: string | null;
  needs_signup: boolean | null;
  steps: string[];
  recipe: Record<string, unknown> & {
    checked_at?: string;
    reachable?: boolean;
    verification?: string;
    google?: boolean;
    captcha?: boolean;
    platform?: string;
    post_url?: string;
    notes?: string[];
  };
}

/** Read the procedure of one website now (sign-up, verification, post page). */
export async function refreshWebsiteRecipe(id: string): Promise<WebsiteRecipeResult> {
  return (await api.websites.refreshRecipe(apiClient, id)) as WebsiteRecipeResult;
}

/** Read several websites at once; ``probed`` is how many were opened. */
export async function refreshWebsiteRecipes(limit = 10): Promise<{
  probed: number;
  rows: { website_id: string; domain: string; state: string }[];
}> {
  return (await api.websites.refreshRecipes(apiClient, {
    limit,
    only_missing: true,
  })) as { probed: number; rows: { website_id: string; domain: string; state: string }[] };
}

/** Adds one website to the central list. */
export async function createWebsite(
  input: WebsiteCreateInput,
): Promise<WebsiteListItem> {
  const body: Record<string, unknown> = {
    opportunity_url: input.opportunity_url.trim(),
  };
  if (input.name?.trim()) body.name = input.name.trim();
  if (input.category?.trim()) body.category = input.category.trim();
  if (input.niche?.trim()) body.niche = input.niche.trim();
  if (input.notes?.trim()) body.notes = input.notes.trim();
  if (input.signup_url?.trim()) body.signup_url = input.signup_url.trim();
  if (input.post_url?.trim()) body.post_url = input.post_url.trim();
  if (input.submission_method?.trim()) {
    body.submission_method = input.submission_method.trim();
  }
  const raw = await api.websites.create(apiClient, body);
  return normalizeWebsite(raw);
}

/** Changes one website - only the fields that are sent are written. */
export async function updateWebsite(
  id: string,
  body: Record<string, unknown>,
): Promise<WebsiteListItem> {
  const raw = await api.websites.update(apiClient, id, body);
  return normalizeWebsite(raw);
}

/** Removes one website from the central list. */
export async function removeWebsite(id: string): Promise<void> {
  await api.websites.remove(apiClient, id);
}

/**
 * Brings a removed website back into the central list.
 *
 * The website was only *removed* - its opportunities, its tasks and its
 * verification records were never thrown away.
 */
export async function restoreWebsite(id: string): Promise<WebsiteListItem> {
  const raw = await api.websites.restore(apiClient, id);
  return normalizeWebsite(raw);
}

/**
 * Deletes a website forever - the website, its opportunities and its tasks
 * are gone.  This cannot be undone.
 */
export async function purgeWebsite(id: string): Promise<void> {
  await api.websites.purge(apiClient, id);
}

export interface WebsiteImportInput {
  category?: string;
  niche?: string;
  status?: string;
}

/** Imports a spreadsheet into the central list. */
export async function importWebsites(
  file: File,
  input: WebsiteImportInput,
): Promise<WebsiteImportResult> {
  const raw = (await api.websites.importFile(apiClient, file, {
    category: input.category?.trim() ?? "",
    niche: input.niche?.trim() ?? "",
    status: input.status?.trim() ?? "",
  })) as Partial<WebsiteImportResult> | null;

  const rows = Array.isArray(raw?.rows)
    ? raw.rows.map((row) => {
        const item = (row ?? {}) as Record<string, unknown>;
        return {
          row: count(item.row),
          action: text(item.action),
          reason: text(item.reason),
          domain: text(item.domain),
        };
      })
    : [];

  return {
    created: count(raw?.created),
    updated: count(raw?.updated),
    skipped: count(raw?.skipped),
    invalid: count(raw?.invalid),
    rows,
  };
}

export interface WebsiteChooseInput {
  website_ids: string[];
  category?: string;
  niche?: string;
  anchor_text?: string;
  target_landing_page?: string;
}

/** Adds the chosen websites to a project. */
export async function chooseWebsitesForProject(
  projectId: string,
  input: WebsiteChooseInput,
): Promise<WebsiteChooseResult> {
  const body: Record<string, unknown> = {
    website_ids: input.website_ids,
  };
  if (input.category?.trim()) body.category = input.category.trim();
  if (input.niche?.trim()) body.niche = input.niche.trim();
  if (input.anchor_text?.trim()) body.anchor_text = input.anchor_text.trim();
  if (input.target_landing_page?.trim()) {
    body.target_landing_page = input.target_landing_page.trim();
  }
  const raw = (await api.websites.chooseForProject(
    apiClient,
    projectId,
    body,
  )) as Partial<WebsiteChooseResult> | null;

  return {
    linked: count(raw?.linked),
    skipped: count(raw?.skipped),
    tasks_created: count(raw?.tasks_created),
    task_ids: Array.isArray(raw?.task_ids)
      ? raw.task_ids.map((item) => text(item).trim()).filter(Boolean)
      : [],
  };
}

/* ------------------------------------------------------------------ */
/* The retry of the failed submissions                                 */
/* ------------------------------------------------------------------ */

/**
 * The result of a retry run.
 *
 * `retried` is `null` when the backend does not report how many submissions
 * it queued - the view then says so instead of inventing a number.
 */
export interface RetryOutcome {
  retried: number | null;
  detail: string;
}

/**
 * Queues the failed submissions of a report again.
 *
 * The endpoint is newer than the shared client - a local backend that does
 * not know it answers with 404.  The caller turns that into a disabled
 * control, never into a fake success.
 */
export async function retryFailedSubmissions(
  exportId: string,
  body: { domain?: string; project_id?: string },
): Promise<RetryOutcome> {
  const raw = (await apiClient.post(
    `/api/v1/reports/${exportId}/retry-failed`,
    {
      domain: body.domain || undefined,
      project_id: body.project_id || undefined,
    },
  )) as Record<string, unknown> | null;

  const data = (raw ?? {}) as Record<string, unknown>;
  const candidates = ["retried", "queued", "count", "affected", "tasks_created"];
  for (const key of candidates) {
    const value = data[key];
    if (typeof value === "number" && Number.isFinite(value)) {
      return { retried: value, detail: "" };
    }
  }
  const message = optionalText(data.message) ?? optionalText(data.detail);
  return { retried: null, detail: message ?? "" };
}
