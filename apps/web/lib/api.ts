"use client";

import { ApiClient, ApiError } from "@autobacklinker/api-client";

/** Key used to persist the JWT in localStorage. */
export const TOKEN_STORAGE_KEY = "abk.token";

/**
 * Base URL of the FastAPI backend. Override with NEXT_PUBLIC_API_BASE_URL
 * (e.g. http://127.0.0.1:8000) when the backend does not run on :8000.
 *
 * The loopback address is used on purpose: `localhost` resolves to IPv6 on
 * some systems while the development server listens on IPv4 only, which would
 * end in a confusing CORS error.
 */
export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000"
).replace(/\/$/, "");

function readStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function persistToken(token: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (token) window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
    else window.localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    /* storage unavailable (private mode) - ignore */
  }
}

let redirecting = false;

/**
 * Singleton transport shared by every page. The bearer token is kept in
 * sync with localStorage by the auth provider.
 */
export const apiClient = new ApiClient({
  baseUrl: API_BASE_URL,
  token: readStoredToken(),
  onUnauthorized: () => {
    persistToken(null);
    apiClient.setToken(null);
    if (typeof window === "undefined") return;
    if (redirecting) return;
    redirecting = true;
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.assign(`/login?next=${next}`);
  },
});

export function setApiToken(token: string | null): void {
  persistToken(token);
  apiClient.setToken(token);
}

/** Human readable message for any thrown value. */
export function errorMessage(error: unknown): string {
  if (!error) return "Unknown error";
  if (typeof error === "string") return error;
  if (error instanceof Error) return error.message;
  return String(error);
}

/** True when the backend answered with 404 (endpoint or record not there). */
export function isNotFoundError(error: unknown): boolean {
  if (error instanceof ApiError) return error.status === 404;
  if (error && typeof error === "object" && "status" in error) {
    return (error as { status?: number }).status === 404;
  }
  return false;
}

/** True when the backend could not be reached at all. */
export function isNetworkError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 0;
}

/* ------------------------------------------------------------------ */
/* Automatic submission: submission details + auto pilot               */
/* ------------------------------------------------------------------ */

/**
 * Everything a target site may ask for before it accepts a listing.
 * The shape mirrors the backend contract
 * (`GET/PUT /api/v1/opportunities/{id}/details`).
 */
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
  /** Site specific values that have no dedicated field. */
  extra: Record<string, unknown>;
  /** Field name -> how the value was produced ("ai", "profile", ...). */
  generated: Record<string, unknown>;
  updated_at: string | null;
  /** Field names the target site asks for. */
  required: string[];
  /** Required fields that are still empty. */
  missing: string[];
  /** False while `missing` is not empty. */
  complete: boolean;
  /** True when the backend actually reported the `missing` list. */
  missingReported: boolean;
}

/** Body of `PUT /api/v1/opportunities/{id}/details`. */
export interface SubmissionDetailsUpdate {
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
}

/** Result of `POST /api/v1/opportunities/{id}/details/generate`. */
export interface GenerateDetailsResult {
  details: SubmissionDetails;
  /** Names of the fields the backend produced. */
  generated: string[];
  /** "ai" or "profile" - where the values came from. */
  source: string;
}

/** State of `GET /api/v1/projects/{id}/autopilot`. */
export interface AutoPilotState {
  enabled: boolean;
  categories: string[];
  /** Opportunities that are approved and waiting for the worker. */
  waiting: number;
  /** Opportunities that were submitted automatically. */
  submitted: number;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function asString(value: unknown): string | null {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return null;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return null;
}

function asNumber(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function asStringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => asString(item)).filter((item): item is string => item !== null);
  }
  if (typeof value === "string") {
    return value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return [];
}

/** Fills the gaps of a partial backend payload so the UI never crashes. */
export function normalizeSubmissionDetails(raw: unknown): SubmissionDetails {
  const body = asRecord(raw);
  const missingReported = Array.isArray(body.missing);
  const missing = asStringList(body.missing);
  return {
    opportunity_id: asString(body.opportunity_id) ?? "",
    company_name: asString(body.company_name),
    description: asString(body.description),
    email: asString(body.email),
    phone: asString(body.phone),
    website: asString(body.website),
    address: asString(body.address),
    city: asString(body.city),
    state: asString(body.state),
    country: asString(body.country),
    postal_code: asString(body.postal_code),
    logo_path: asString(body.logo_path),
    categories: asStringList(body.categories),
    founded_year: asNumber(body.founded_year),
    employee_count: asNumber(body.employee_count),
    extra: asRecord(body.extra),
    generated: asRecord(body.generated),
    updated_at: asString(body.updated_at),
    required: asStringList(body.required),
    missing,
    complete: typeof body.complete === "boolean" ? body.complete : missing.length === 0,
    missingReported,
  };
}

/** Normalizes the answer of the generate endpoint. */
export function normalizeGenerateResult(raw: unknown): GenerateDetailsResult {
  const body = asRecord(raw);
  const rawDetails = asRecord(body.details);
  const generatedList = Array.isArray(body.generated)
    ? body.generated.map((item) => String(item))
    : Array.isArray(rawDetails.generated)
      ? rawDetails.generated.map((item) => String(item))
      : Object.keys(asRecord(rawDetails.generated));
  return {
    details: normalizeSubmissionDetails({ ...rawDetails, generated: asRecord(rawDetails.generated) }),
    generated: generatedList,
    source: asString(body.source) ?? "unknown",
  };
}

/** Normalizes the auto pilot state of a project. */
export function normalizeAutoPilot(raw: unknown): AutoPilotState {
  const body = asRecord(raw);
  return {
    enabled: body.enabled === true,
    categories: asStringList(body.categories),
    waiting: asNumber(body.waiting) ?? 0,
    submitted: asNumber(body.submitted) ?? 0,
  };
}

/**
 * Submission details of one opportunity.
 *
 * The endpoints live behind the shared transport; they are not part of the
 * typed `api` object of `@autobacklinker/api-client` yet, therefore they are
 * wrapped here.
 */
export const submissionDetailsApi = {
  get: (opportunityId: string) =>
    apiClient
      .get<unknown>(`/api/v1/opportunities/${opportunityId}/details`)
      .then(normalizeSubmissionDetails),
  update: (opportunityId: string, body: SubmissionDetailsUpdate) =>
    apiClient
      .put<unknown>(`/api/v1/opportunities/${opportunityId}/details`, body)
      .then(normalizeSubmissionDetails),
  remove: (opportunityId: string) =>
    apiClient.delete<void>(`/api/v1/opportunities/${opportunityId}/details`),
  generate: (opportunityId: string) =>
    apiClient
      .post<unknown>(`/api/v1/opportunities/${opportunityId}/details/generate`)
      .then(normalizeGenerateResult),
};

/** Automatic submission state of a project. */
export const autoPilotApi = {
  get: (projectId: string) =>
    apiClient
      .get<unknown>(`/api/v1/projects/${projectId}/autopilot`)
      .then(normalizeAutoPilot),
  update: (projectId: string, body: { enabled: boolean; categories: string[] }) =>
    apiClient
      .post<unknown>(`/api/v1/projects/${projectId}/autopilot`, body)
      .then(normalizeAutoPilot),
};
