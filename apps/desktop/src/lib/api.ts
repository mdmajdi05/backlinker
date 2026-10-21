/**
 * The transport of the desktop client.
 *
 * The desktop app is *local first*: it talks to the bundled FastAPI sidecar
 * that runs on the loopback interface of this machine and it never needs a
 * hosted ("cloud") backend.  Everything in this module is built around that
 * rule:
 *
 *   * the client always starts on the local sidecar,
 *   * the machine token of the sidecar is sent as `X-Local-Token` and *only*
 *     to a loopback address - it never leaves the machine,
 *   * a hosted backend is used only when the operator selects one explicitly
 *     (Settings -> Cloud synchronisation) and the switch is reversible,
 *   * if the local backend is not reachable yet the client waits and retries
 *     instead of talking to something else.
 *
 * The desktop client speaks the same protocol as the web client - only the
 * base URL differs.
 */

import { ApiClient, ApiError, api as sharedApi } from "@autobacklinker/api-client";
import { DEFAULT_BACKEND_PORT } from "./backend";

export type SessionMode = "local" | "cloud";

/** The hosted backend the operator selected (never used automatically). */
const CLOUD_URL_KEY = "autobacklinker.desktop.cloudUrl";
/** Base URL of an older version - migrated, never connected to silently. */
const LEGACY_BASE_URL_KEY = "autobacklinker.desktop.baseUrl";
/** The JWT of the *cloud* session. */
const TOKEN_KEY = "autobacklinker.desktop.token";
/** The last selected session mode (informational - see `getSessionMode`). */
const MODE_KEY = "autobacklinker.desktop.mode";
/** The generated password of the local account. */
const LOCAL_ACCOUNT_KEY = "autobacklinker.desktop.localAccount";
/** The id of the local account of this installation. */
const LOCAL_ACCOUNT_ID_KEY = "autobacklinker.desktop.localAccountId";

export const LOCAL_ACCOUNT_DOMAIN = "auto-backlinker.app";
/** The default address of the local account (see `getLocalAccountEmail`). */
export const LOCAL_ACCOUNT_EMAIL = `local@${LOCAL_ACCOUNT_DOMAIN}`;

export const DEFAULT_BASE_URL = `http://127.0.0.1:${DEFAULT_BACKEND_PORT}`;

/**
 * How long a request waits for the local backend to come up.  The Rust
 * supervisor starts the sidecar a moment after the window opens and the
 * bundled CPython needs a few seconds to boot - the client waits for it
 * instead of failing (and instead of falling back to anything else).
 */
const LOCAL_RETRY_DELAYS_MS = [250, 500, 1000, 2000, 4000, 5000, 5000, 5000];

/** How long a request waits for the local session to become usable. */
const LOCAL_SESSION_WAIT_MS = 15000;

/* ------------------------------------------------------------------ */
/* Storage helpers                                                      */
/* ------------------------------------------------------------------ */

function safeGet(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeSet(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    /* storage unavailable (private mode) - the session simply is not sticky */
  }
}

/* ------------------------------------------------------------------ */
/* Loopback detection                                                   */
/* ------------------------------------------------------------------ */

const LOOPBACK_HOSTS = new Set([
  "localhost",
  "127.0.0.1",
  "::1",
  "[::1]",
  "0.0.0.0",
]);

/**
 * True for every address that belongs to this machine.
 *
 * Only loopback targets receive the local machine token - a hosted backend
 * must never see it.
 */
export function isLoopbackUrl(url: string): boolean {
  try {
    const host = new URL(url).hostname.toLowerCase();
    if (LOOPBACK_HOSTS.has(host)) return true;
    return /^127(?:\.\d{1,3}){3}$/.test(host);
  } catch {
    return false;
  }
}

/* ------------------------------------------------------------------ */
/* Credentials                                                          */
/* ------------------------------------------------------------------ */

/**
 * The shared token of the local backend (sent as `X-Local-Token`).
 *
 * The bundled backend authenticates loopback clients with that token (see
 * apps/api/app/api/deps.py).  A cloud session uses the regular
 * `Authorization: Bearer <jwt>` header instead.
 */
let localToken: string | null = null;

/**
 * The JWT of the local account.  It is used for the event stream (an
 * `EventSource` cannot send headers) and in the browser preview, where the
 * Rust supervisor that owns the machine token is not available.
 */
let localAccessToken: string | null = null;

/** The JWT of the signed in cloud account. */
let cloudToken: string | null = safeGet(TOKEN_KEY);

/** The base URL of the local sidecar (the Rust supervisor may change it). */
let localBaseUrl = DEFAULT_BASE_URL;

/**
 * Refreshes the local token. The backend may have been restarted (or a second
 * instance of the app may own it), in which case the token of the previous
 * launch is stale and every request would answer with 401.
 */
let tokenProvider: (() => Promise<string | null>) | null = null;

export function setTokenProvider(provider: (() => Promise<string | null>) | null): void {
  tokenProvider = provider;
}

/* ------------------------------------------------------------------ */
/* Session mode                                                         */
/* ------------------------------------------------------------------ */

type SessionModeListener = (mode: SessionMode) => void;
const sessionModeListeners = new Set<SessionModeListener>();

/** Notifies the UI when the client switches between local and cloud. */
export function onSessionModeChange(listener: SessionModeListener): () => void {
  sessionModeListeners.add(listener);
  return () => {
    sessionModeListeners.delete(listener);
  };
}

function notifySessionMode(): void {
  const mode = getSessionMode();
  sessionModeListeners.forEach((listener) => {
    try {
      listener(mode);
    } catch {
      /* a broken listener must not break the transport */
    }
  });
}

/* ------------------------------------------------------------------ */
/* The local session gate                                               */
/* ------------------------------------------------------------------ */

/**
 * The local session needs a credential: the machine token of the sidecar (or
 * the JWT of the local account).  It is not available in the first
 * milliseconds of the application, therefore the requests wait for it instead
 * of running into a 401.
 */
let sessionReadyPromise: Promise<void> | null = null;
let sessionReadyResolve: (() => void) | null = null;
let accessTokenPromise: Promise<void> | null = null;
let accessTokenResolve: (() => void) | null = null;

function sessionReady(): Promise<void> {
  if (!sessionReadyPromise) {
    sessionReadyPromise = new Promise((resolve) => {
      sessionReadyResolve = resolve;
    });
  }
  return sessionReadyPromise;
}

function accessTokenReady(): Promise<void> {
  if (!accessTokenPromise) {
    accessTokenPromise = new Promise((resolve) => {
      accessTokenResolve = resolve;
    });
  }
  return accessTokenPromise;
}

function markSessionReady(): void {
  const resolve = sessionReadyResolve;
  sessionReadyPromise = null;
  sessionReadyResolve = null;
  resolve?.();
}

function markAccessTokenReady(): void {
  const resolve = accessTokenResolve;
  accessTokenPromise = null;
  accessTokenResolve = null;
  resolve?.();
}

/** Waits for the local session; returns false when it does not arrive. */
async function waitForLocalSession(timeoutMs: number): Promise<boolean> {
  if (localToken || localAccessToken) return true;
  return waitFor(sessionReady(), timeoutMs);
}

/** Waits for the JWT of the local account (the event stream needs it). */
async function waitForAccessToken(timeoutMs: number): Promise<boolean> {
  if (localAccessToken) return true;
  return waitFor(accessTokenReady(), timeoutMs);
}

async function waitFor(
  promise: Promise<void>,
  timeoutMs: number,
): Promise<boolean> {
  let timer: number | undefined;
  const timeout = new Promise<boolean>((resolve) => {
    timer = window.setTimeout(() => resolve(false), timeoutMs);
  });
  try {
    return await Promise.race([promise.then(() => true), timeout]);
  } finally {
    if (timer !== undefined) window.clearTimeout(timer);
  }
}

/* ------------------------------------------------------------------ */
/* Transport                                                            */
/* ------------------------------------------------------------------ */

function requestUrl(input: RequestInfo | URL): string | null {
  try {
    if (typeof input === "string") return input;
    if (input instanceof URL) return input.toString();
    if (typeof Request !== "undefined" && input instanceof Request) {
      return input.url;
    }
    return null;
  } catch {
    return null;
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function desktopFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  const url = requestUrl(input);
  // The machine token belongs to this machine - it is only ever sent to a
  // loopback address.
  const local = url !== null && isLoopbackUrl(url);

  const attempt = async (): Promise<Response> => {
    const headers = new Headers(init?.headers);
    if (local) {
      if (localToken) headers.set("X-Local-Token", localToken);
      // The shared client builds the headers before the request is sent; the
      // local account token may only be known later (the account is created
      // on the first start), therefore it is added here as well.
      if (localAccessToken && !headers.has("Authorization")) {
        headers.set("Authorization", `Bearer ${localAccessToken}`);
      }
    }
    return fetch(input, { ...init, headers });
  };

  let response: Response;

  try {
    response = await attempt();
  } catch (error) {
    if (!local) throw error;
    // The local backend is not reachable *yet* (it is still starting): wait
    // for it and retry.  The client never falls back to another host.
    response = await retryLocalBackend(attempt, error);
  }

  if (response.status === 401 && local) {
    if (localToken && tokenProvider) {
      // The token of the running backend changed - fetch it once more and
      // repeat the request exactly once.
      try {
        const fresh = await tokenProvider();
        if (fresh && fresh !== localToken) {
          localToken = fresh;
          response = await attempt();
        }
      } catch {
        /* the refresh failed - the original response is returned */
      }
    }
    if (response.status === 401 && !(localToken || localAccessToken)) {
      // The local session was not ready yet (the local account is created on
      // the first start) - wait for it and repeat the request once.
      if (await waitForLocalSession(LOCAL_SESSION_WAIT_MS)) {
        response = await attempt();
      }
    }
    if (response.status === 401 && localAccessToken && !localToken) {
      // The JWT of the local account expired - sign in again and repeat the
      // request exactly once.
      if (await refreshLocalAccessToken()) {
        response = await attempt();
      }
    }
  }

  return response;
}

async function retryLocalBackend(
  attempt: () => Promise<Response>,
  lastError: unknown,
): Promise<Response> {
  for (const delay of LOCAL_RETRY_DELAYS_MS) {
    await sleep(delay);
    try {
      return await attempt();
    } catch {
      /* the sidecar is still starting - keep waiting */
    }
  }
  throw lastError;
}

/**
 * Makes sure that *every* request to the local backend carries the machine
 * token - also the ones that do not go through the shared API client (for
 * example the report download).
 */
function installLocalTokenInterceptor(): void {
  if (typeof window === "undefined" || typeof window.fetch !== "function") {
    return;
  }
  const original = window.fetch.bind(window);
  const marker = original as typeof original & { __autobacklinker?: boolean };
  if (marker.__autobacklinker) return;

  const patched = async (
    input: RequestInfo | URL,
    init?: RequestInit,
  ): Promise<Response> => {
    try {
      const url = requestUrl(input);
      if (url && isLoopbackUrl(url) && localToken) {
        const headers = new Headers(
          init?.headers ?? (input instanceof Request ? input.headers : undefined),
        );
        if (!headers.has("X-Local-Token")) {
          headers.set("X-Local-Token", localToken);
          if (input instanceof Request) {
            return original(new Request(input, { headers }));
          }
          return original(input, { ...init, headers });
        }
      }
    } catch {
      /* the interceptor must never break a request */
    }
    return original(input, init);
  };

  (patched as typeof patched & { __autobacklinker?: boolean }).__autobacklinker =
    true;
  window.fetch = patched;
}

installLocalTokenInterceptor();

/**
 * The desktop client.
 *
 * The only difference to the shared client is the event stream: an
 * `EventSource` cannot send headers, therefore the token travels as the
 * `access_token` query parameter.  In the local mode the stream waits for
 * the local account - an unauthenticated stream would be rejected by the
 * backend and would retry forever.
 */
class DesktopApiClient extends ApiClient {
  override subscribe(
    path: string,
    onMessage: (event: unknown, type: string) => void,
    onError?: (err: unknown) => void,
  ): () => void {
    if (getSessionMode() === "cloud" || this.token) {
      return super.subscribe(path, onMessage, onError);
    }

    // The local session is not ready yet (the local account is created on the
    // first start).  An `EventSource` cannot send the `X-Local-Token` header,
    // it needs the JWT of the account - an unauthenticated stream would be
    // rejected by the backend and would retry forever.  The stream therefore
    // starts as soon as the account exists.
    let stopped = false;
    let close: (() => void) | null = null;
    const start = () => {
      if (stopped || close || !this.token) return;
      close = super.subscribe(path, onMessage, onError);
    };
    void waitForAccessToken(LOCAL_SESSION_WAIT_MS).then((ready) => {
      if (ready) start();
    });
    return () => {
      stopped = true;
      close?.();
    };
  }
}

export const apiClient = new DesktopApiClient({
  // The client always starts on the local sidecar.  A hosted backend is only
  // used after the operator selected one explicitly.
  baseUrl: DEFAULT_BASE_URL,
  token: null,
  fetchImpl: desktopFetch,
  onUnauthorized: () => {
    // Only a cloud session can be invalidated by a 401 - the local machine
    // session is restored by the token provider.
    if (getSessionMode() === "cloud") {
      cloudToken = null;
      safeSet(TOKEN_KEY, null);
    }
    window.dispatchEvent(new CustomEvent("autobacklinker:unauthorized"));
  },
});

/* ------------------------------------------------------------------ */
/* Target (local sidecar / hosted backend)                              */
/* ------------------------------------------------------------------ */

/** The base URL of the local sidecar. */
export function getLocalBaseUrl(): string {
  return localBaseUrl;
}

/** The hosted backend the operator selected - `null` when there is none. */
export function getCloudBaseUrl(): string | null {
  const stored = safeGet(CLOUD_URL_KEY);
  if (stored && !isLoopbackUrl(stored)) return stored;
  const legacy = safeGet(LEGACY_BASE_URL_KEY);
  if (legacy && !isLoopbackUrl(legacy)) {
    // An older version stored the active base URL.  Keep the hosted backend
    // as a suggestion - but never connect to it automatically.
    safeSet(CLOUD_URL_KEY, legacy);
    return legacy;
  }
  return null;
}

/**
 * The mode follows the target: a loopback base URL is the local sidecar,
 * everything else is a hosted backend.
 */
export function getSessionMode(): SessionMode {
  return isLoopbackUrl(apiClient.baseUrl) ? "local" : "cloud";
}

/** True while the client talks to the backend of this machine. */
export function isLocalSession(): boolean {
  return getSessionMode() === "local";
}

/**
 * Points the client at another backend.
 *
 * A loopback address is the local sidecar (the default).  Every other address
 * is a hosted backend: it is remembered as the cloud URL and the session
 * switches to the cloud mode - the machine token of this machine is never
 * sent to it.
 */
export function setApiBaseUrl(url: string): void {
  const normalized = url.trim().replace(/\/$/, "");
  if (!normalized) return;

  const local = isLoopbackUrl(normalized);
  apiClient.setBaseUrl(normalized);

  if (local) {
    localBaseUrl = normalized;
  } else {
    safeSet(CLOUD_URL_KEY, normalized);
  }

  // The credentials always belong to the current target.
  apiClient.setToken(local ? localAccessToken : cloudToken);
  notifySessionMode();
}

/**
 * Switches between the local sidecar and the remembered hosted backend.
 */
export function setSessionMode(mode: SessionMode): void {
  safeSet(MODE_KEY, mode);
  if (mode === "local") {
    setApiBaseUrl(localBaseUrl);
    return;
  }
  const cloud = getCloudBaseUrl();
  if (cloud) {
    setApiBaseUrl(cloud);
    return;
  }
  // No hosted backend was selected - the client stays local.
  notifySessionMode();
}

/**
 * The session token of the *current* target.
 *
 * In the cloud mode this is the JWT of the signed in account, in the local
 * mode the JWT of the local account (the machine token is sent separately as
 * `X-Local-Token`).
 */
export function setApiToken(token: string | null): void {
  apiClient.setToken(token);
  if (getSessionMode() === "cloud") {
    cloudToken = token;
    safeSet(TOKEN_KEY, token);
  } else {
    localAccessToken = token;
    if (token) {
      markSessionReady();
      markAccessTokenReady();
    }
  }
}

/** The shared token of the local backend (sent as `X-Local-Token`). */
export function setLocalToken(token: string | null): void {
  localToken = token;
  if (token) markSessionReady();
}

export function getLocalToken(): string | null {
  return localToken;
}

/** The JWT of the local account (used for the event stream). */
export function getLocalAccessToken(): string | null {
  return localAccessToken;
}

export function getApiToken(): string | null {
  return apiClient.token;
}

export function getApiBaseUrl(): string {
  return apiClient.baseUrl;
}

/* ------------------------------------------------------------------ */
/* The local account                                                    */
/* ------------------------------------------------------------------ */

/**
 * The address of the local account of this installation.
 *
 * Every installation owns its own account, so a cleared browser storage never
 * locks the local session out.
 */
export function getLocalAccountEmail(): string {
  let id = safeGet(LOCAL_ACCOUNT_ID_KEY);
  if (!id) {
    id = Math.random().toString(36).slice(2, 8);
    safeSet(LOCAL_ACCOUNT_ID_KEY, id);
  }
  return `local-${id}@${LOCAL_ACCOUNT_DOMAIN}`;
}

/**
 * The bundled backend resolves the `X-Local-Token` header against the first
 * user of the local database.  A fresh installation has no user at all, so the
 * desktop app creates a local account on the first start.
 *
 * The account also owns the event stream: the backend accepts a JWT there
 * (an `EventSource` cannot send the `X-Local-Token` header).  The generated
 * password is kept in the local storage of the web view, so the next start
 * simply signs in again.
 */
let pendingLocalAccount: Promise<boolean> | null = null;

export async function ensureLocalAccount(): Promise<boolean> {
  if (getSessionMode() !== "local") return false;
  // The account is ready - do not talk to the backend again.
  if (localAccessToken) return true;
  if (!pendingLocalAccount) {
    pendingLocalAccount = runEnsureLocalAccount().finally(() => {
      pendingLocalAccount = null;
    });
  }
  return pendingLocalAccount;
}

async function runEnsureLocalAccount(): Promise<boolean> {
  const email = getLocalAccountEmail();
  const stored = safeGet(LOCAL_ACCOUNT_KEY);

  if (stored) {
    try {
      const result = await api.auth(apiClient).login({ email, password: stored });
      applyLocalAccessToken(result.access_token);
      return true;
    } catch {
      // The account is gone (an empty database) - create it again below.
    }
  }
  const password = stored ?? generateLocalPassword();
  try {
    const result = await api.auth(apiClient).register({
      email,
      password,
      name: "Local user",
    });
    safeSet(LOCAL_ACCOUNT_KEY, password);
    applyLocalAccessToken(result.access_token);
    return true;
  } catch {
    // The login screen stays available for a manual sign in.
    return false;
  }
}

/**
 * Signs the local account in again - the JWT of the account is only valid for
 * a limited time.
 */
async function refreshLocalAccessToken(): Promise<boolean> {
  const stored = safeGet(LOCAL_ACCOUNT_KEY);
  if (!stored) return false;
  try {
    const result = await api.auth(apiClient).login({
      email: getLocalAccountEmail(),
      password: stored,
    });
    applyLocalAccessToken(result.access_token);
    return true;
  } catch {
    return false;
  }
}

function applyLocalAccessToken(token: string): void {
  localAccessToken = token;
  if (getSessionMode() === "local") apiClient.setToken(token);
  markSessionReady();
  markAccessTokenReady();
}

function generateLocalPassword(): string {
  const random = Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2);
  return `local-${random}`;
}

/* ------------------------------------------------------------------ */
/* Submission details and the auto pilot                               */
/* ------------------------------------------------------------------ */

/**
 * One field the form of a target site asks for.
 *
 * The backend answers either with the plain field name (`"email"`) or with an
 * object that carries a ready made label
 * (`{"field": "email", "label": "E-mail address"}`).  Both are normalised
 * into this shape.
 */
export interface RequiredDetailField {
  field: string;
  label: string;
}

/** The values of the submission form that may be edited. */
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
  categories?: string[] | null;
  founded_year?: number | null;
  employee_count?: number | null;
  extra?: Record<string, unknown> | null;
}

/** The details of a target site (normalised, safe to render). */
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
  /** The names of the fields that were filled by the generator. */
  generated: string[];
  updated_at: string | null;
  /** The fields the target site asks for. */
  required: RequiredDetailField[];
  /** The fields the target site asks for and that are still empty. */
  missing: RequiredDetailField[];
  /** True when nothing is missing anymore. */
  complete: boolean;
}

/** The result of a generation run. */
export interface SubmissionGeneration {
  details: SubmissionDetails;
  /** The fields that were filled by this run. */
  generated: string[];
  /** `ai` when the assistant wrote the text, `profile` otherwise. */
  source: "ai" | "profile";
}

/** The state of the auto pilot of a project. */
export interface AutoPilotState {
  enabled: boolean;
  /** The categories the auto pilot is limited to (empty = every category). */
  categories: string[];
  /** The opportunities that wait for the operator. */
  waiting: number;
  /** The opportunities that were submitted. */
  submitted: number;
}

/** The raw answer of the backend - every part of it is optional. */
interface RawDetails {
  opportunity_id?: string;
  company_name?: unknown;
  description?: unknown;
  email?: unknown;
  phone?: unknown;
  website?: unknown;
  address?: unknown;
  city?: unknown;
  state?: unknown;
  country?: unknown;
  postal_code?: unknown;
  logo_path?: unknown;
  categories?: unknown;
  founded_year?: unknown;
  employee_count?: unknown;
  extra?: unknown;
  generated?: unknown;
  updated_at?: unknown;
  required?: unknown;
  missing?: unknown;
  complete?: unknown;
  /** The human readable label of every field. */
  labels?: unknown;
}

function asText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  return String(value);
}

function asOptionalText(value: unknown): string | null {
  const text = asText(value).trim();
  return text.length > 0 ? text : null;
}

function asNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function asStringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => asText(item).trim()).filter((item) => item.length > 0);
  }
  if (typeof value === "string" && value.trim()) {
    return value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return [];
}

function asObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

/** `email_address` -> `Email address` - the fallback label of a field. */
function fallbackLabel(field: string): string {
  const text = field.replace(/[_-]+/g, " ").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : field;
}

function normalizeFields(
  value: unknown,
  labels: Record<string, unknown> = {},
): RequiredDetailField[] {
  if (!Array.isArray(value)) return [];
  const fields: RequiredDetailField[] = [];
  for (const entry of value) {
    if (typeof entry === "string") {
      const field = entry.trim();
      if (field) fields.push({ field, label: labelOf(field, labels) });
      continue;
    }
    if (entry && typeof entry === "object") {
      const record = entry as Record<string, unknown>;
      const field = asText(record.field ?? record.name ?? record.key).trim();
      if (!field) continue;
      const label = asText(record.label ?? record.title).trim();
      fields.push({ field, label: label || labelOf(field, labels) });
    }
  }
  return fields;
}

/** The label of a field - the backend knows most of them. */
function labelOf(field: string, labels: Record<string, unknown>): string {
  const label = asText(labels[field]).trim();
  return label || fallbackLabel(field);
}

/** The generated fields may be a list of names or a map of names. */
function normalizeGenerated(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => asText(item).trim()).filter(Boolean);
  }
  if (value && typeof value === "object") {
    return Object.keys(value as Record<string, unknown>);
  }
  return [];
}

function normalizeDetails(
  raw: RawDetails | null | undefined,
  options: { requiredKnown?: boolean } = {},
): SubmissionDetails {
  const data = raw ?? {};
  const labels = asObject(data.labels);
  const missing = normalizeFields(data.missing, labels);
  // The backend tells the client which fields it asks for.  When it does
  // not, the client does not know whether the details are complete - it must
  // not claim that they are.
  const known =
    options.requiredKnown ??
    (data.required !== undefined || data.complete !== undefined);
  return {
    opportunity_id: asText(data.opportunity_id),
    company_name: asOptionalText(data.company_name),
    description: asOptionalText(data.description),
    email: asOptionalText(data.email),
    phone: asOptionalText(data.phone),
    website: asOptionalText(data.website),
    address: asOptionalText(data.address),
    city: asOptionalText(data.city),
    state: asOptionalText(data.state),
    country: asOptionalText(data.country),
    postal_code: asOptionalText(data.postal_code),
    logo_path: asOptionalText(data.logo_path),
    categories: asStringList(data.categories),
    founded_year: asNumber(data.founded_year),
    employee_count: asNumber(data.employee_count),
    extra: asObject(data.extra),
    generated: normalizeGenerated(data.generated),
    updated_at: asOptionalText(data.updated_at),
    required: normalizeFields(data.required, labels),
    missing,
    complete:
      typeof data.complete === "boolean"
        ? data.complete
        : known
          ? missing.length === 0
          : false,
  };
}

/**
 * The required fields of an opportunity.
 *
 * Some backends answer them together with the details, others keep them in
 * a separate endpoint - the client asks for them only when it has to.
 */
async function fetchRequired(
  c: ApiClient,
  id: string,
): Promise<RawDetails | null> {
  try {
    const raw = await c.get<RawDetails>(
      `/api/v1/opportunities/${id}/details/required`,
    );
    return {
      required: raw.required,
      missing: raw.missing,
      complete: raw.complete,
      labels: raw.labels,
    };
  } catch {
    return null;
  }
}

/** Adds the required fields to a details payload when they are missing. */
async function withRequired(
  c: ApiClient,
  id: string,
  raw: RawDetails,
): Promise<SubmissionDetails> {
  if (raw.required !== undefined || raw.complete !== undefined) {
    return normalizeDetails(raw);
  }
  const required = await fetchRequired(c, id);
  if (!required) return normalizeDetails(raw, { requiredKnown: false });
  return normalizeDetails({ ...raw, ...required }, { requiredKnown: true });
}

function normalizeAutoPilot(
  raw: Record<string, unknown> | null | undefined,
): AutoPilotState {
  const data = raw ?? {};
  return {
    enabled: data.enabled === true,
    categories: asStringList(data.categories),
    waiting: asNumber(data.waiting ?? data.pending) ?? 0,
    submitted: asNumber(data.submitted ?? data.approved ?? data.queued) ?? 0,
  };
}

/**
 * The submission details of one opportunity.
 *
 * The endpoints are part of the local sidecar - the desktop client never
 * sends them anywhere else.
 */
export const submissionDetails = {
  get: async (c: ApiClient, id: string): Promise<SubmissionDetails> =>
    withRequired(
      c,
      id,
      await c.get<RawDetails>(`/api/v1/opportunities/${id}/details`),
    ),
  update: async (
    c: ApiClient,
    id: string,
    body: SubmissionDetailsUpdate,
  ): Promise<SubmissionDetails> =>
    withRequired(
      c,
      id,
      await c.put<RawDetails>(`/api/v1/opportunities/${id}/details`, body),
    ),
  remove: (c: ApiClient, id: string): Promise<void> =>
    c.delete<void>(`/api/v1/opportunities/${id}/details`),
  generate: async (
    c: ApiClient,
    id: string,
  ): Promise<SubmissionGeneration> => {
    const raw = await c.post<{
      details?: RawDetails;
      generated?: unknown;
      source?: string;
    }>(`/api/v1/opportunities/${id}/details/generate`);
    const source = raw?.source === "ai" ? "ai" : "profile";
    return {
      details: await withRequired(c, id, raw?.details ?? {}),
      generated: normalizeGenerated(raw?.generated),
      source,
    };
  },
};

/** The auto pilot of a project - it submits the approved opportunities. */
export const autoPilot = {
  get: async (c: ApiClient, projectId: string): Promise<AutoPilotState> =>
    normalizeAutoPilot(
      await c.get<Record<string, unknown>>(
        `/api/v1/projects/${projectId}/autopilot`,
      ),
    ),
  update: async (
    c: ApiClient,
    projectId: string,
    body: { enabled: boolean; categories: string[] },
  ): Promise<AutoPilotState> =>
    normalizeAutoPilot(
      await c.post<Record<string, unknown>>(
        `/api/v1/projects/${projectId}/autopilot`,
        body,
      ),
    ),
};

/**
 * True when the backend does not know the endpoint yet.
 *
 * The details and the auto pilot are newer than the desktop client - an
 * older sidecar answers with 404.  The views use this to show an honest
 * "not available yet" state instead of pretending that something worked.
 */
export function isMissingEndpoint(error: unknown): boolean {
  if (error instanceof ApiError) {
    return error.status === 404 || error.status === 405 || error.status === 501;
  }
  if (!error) return false;
  const text = error instanceof Error ? error.message : String(error);
  return /\b(404|405|501)\b/.test(text) || /not\s+found/i.test(text);
}

/**
 * The transport of the desktop client.
 *
 * It is the shared API client of the web app plus the endpoints of the
 * automatic submission (the details of a target site and the auto pilot of a
 * project).  Everything runs against the local sidecar.
 */
export const api = {
  ...sharedApi,
  submissionDetails,
  autoPilot,
};

export { ApiClient, ApiError };
