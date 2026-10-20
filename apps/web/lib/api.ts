"use client";

import { ApiClient } from "@autobacklinker/api-client";

/** Key used to persist the JWT in localStorage. */
export const TOKEN_STORAGE_KEY = "abk.token";

/**
 * Base URL of the FastAPI backend. Override with NEXT_PUBLIC_API_BASE_URL
 * (e.g. http://127.0.0.1:8000) when the backend does not run on :8000.
 */
export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"
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
