/**
 * The desktop client talks to the very same FastAPI backend as the web
 * client - only the base URL differs. In desktop mode the base URL points at
 * the local sidecar (127.0.0.1), in cloud mode at the remote deployment.
 */

import { ApiClient, api } from "@autobacklinker/api-client";
import { DEFAULT_BACKEND_PORT } from "./backend";

export type SessionMode = "local" | "cloud";

const BASE_URL_KEY = "autobacklinker.desktop.baseUrl";
const TOKEN_KEY = "autobacklinker.desktop.token";
const MODE_KEY = "autobacklinker.desktop.mode";
const LOCAL_ACCOUNT_KEY = "autobacklinker.desktop.localAccount";

export const LOCAL_ACCOUNT_EMAIL = "local@auto-backlinker.app";

export const DEFAULT_BASE_URL = `http://127.0.0.1:${DEFAULT_BACKEND_PORT}`;

/**
 * The bundled backend authenticates loopback clients with a shared token
 * that is sent in the `X-Local-Token` header (see apps/api/app/api/deps.py).
 * A cloud session uses the regular `Authorization: Bearer <jwt>` header.
 */
let localToken: string | null = null;

function desktopFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  const headers = new Headers(init?.headers);
  if (localToken) headers.set("X-Local-Token", localToken);
  return fetch(input, { ...init, headers });
}

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

export const apiClient = new ApiClient({
  baseUrl: safeGet(BASE_URL_KEY) ?? DEFAULT_BASE_URL,
  token: safeGet(TOKEN_KEY),
  fetchImpl: desktopFetch,
  onUnauthorized: () => {
    safeSet(TOKEN_KEY, null);
    window.dispatchEvent(new CustomEvent("autobacklinker:unauthorized"));
  },
});

export function setApiBaseUrl(url: string): void {
  const normalized = url.replace(/\/$/, "");
  apiClient.setBaseUrl(normalized);
  safeSet(BASE_URL_KEY, normalized);
}

export function setApiToken(token: string | null): void {
  apiClient.setToken(token);
  safeSet(TOKEN_KEY, token);
}

/** The shared token of the local backend (sent as `X-Local-Token`). */
export function setLocalToken(token: string | null): void {
  localToken = token;
}

export function getLocalToken(): string | null {
  return localToken;
}

/**
 * The bundled backend resolves the `X-Local-Token` header against the first
 * user of the local database. A fresh installation has no user at all, so the
 * desktop app creates a local account on the first start.
 */
export async function ensureLocalAccount(): Promise<boolean> {
  const stored = safeGet(LOCAL_ACCOUNT_KEY);
  const password = stored ?? generateLocalPassword();
  try {
    await api.auth(apiClient).register({
      email: LOCAL_ACCOUNT_EMAIL,
      password,
      name: "Local user",
    });
    safeSet(LOCAL_ACCOUNT_KEY, password);
    return true;
  } catch {
    // The account already exists (or registration is disabled) - the login
    // screen stays available for a manual sign in.
    return false;
  }
}

function generateLocalPassword(): string {
  const random = Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2);
  return `local-${random}`;
}

export function getApiToken(): string | null {
  return apiClient.token;
}

export function getApiBaseUrl(): string {
  return apiClient.baseUrl;
}

export function getSessionMode(): SessionMode {
  return safeGet(MODE_KEY) === "cloud" ? "cloud" : "local";
}

export function setSessionMode(mode: SessionMode): void {
  safeSet(MODE_KEY, mode);
}

export { api };
export { ApiClient };
