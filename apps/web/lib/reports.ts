/** The report helpers the web client needs but the shared client does not have yet. */

import type { ApiClient } from "@autobacklinker/api-client";

export interface RetryFailedOptions {
  /** Only the submissions of this domain are retried. */
  domain?: string;
  /** Only the submissions of this project are retried. */
  project_id?: string;
}

export interface RetryFailedResult {
  /**
   * The number of submissions the backend queued.  It is `null` when the
   * answer of the backend does not contain a count - the UI then says so
   * instead of inventing a number.
   */
  retried: number | null;
  /** The raw answer of the backend. */
  raw: unknown;
}

/** The keys the backend may use for the number of retried submissions. */
const COUNT_KEYS = [
  "retried",
  "retried_count",
  "queued",
  "queued_count",
  "count",
  "tasks_created",
  "affected",
];

/** Reads the number of retried submissions out of the answer of the backend. */
function countOf(payload: unknown): number | null {
  if (!payload || typeof payload !== "object") return null;
  const raw = payload as Record<string, unknown>;
  for (const key of COUNT_KEYS) {
    const value = raw[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
  }
  return null;
}

/**
 * Retries the failed submissions of an export job.
 *
 * The shared client does not expose this endpoint yet, therefore the call
 * lives here.  When the backend answers 404 the caller shows the disabled
 * state with the reason - it never reports a success that did not happen.
 */
export async function retryFailed(
  client: ApiClient,
  exportId: string,
  options: RetryFailedOptions = {},
): Promise<RetryFailedResult> {
  const payload = await client.post<unknown>(`/api/v1/reports/${exportId}/retry-failed`, {
    ...(options.domain ? { domain: options.domain } : {}),
    ...(options.project_id ? { project_id: options.project_id } : {}),
  });
  return { retried: countOf(payload), raw: payload };
}
