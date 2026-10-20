"use client";

import * as React from "react";

export interface ResourceState<T> {
  data: T | null;
  error: unknown;
  loading: boolean;
  /** True while a background refresh runs on top of already loaded data. */
  refreshing: boolean;
  /** True once the first load attempt finished (successfully or not). */
  settled: boolean;
  reload: () => void;
  setData: React.Dispatch<React.SetStateAction<T | null>>;
}

/**
 * Small data-fetching helper: runs the loader on mount / when the deps change
 * and exposes an explicit `reload` for retry buttons.
 */
export function useResource<T>(
  loader: () => Promise<T>,
  deps: React.DependencyList,
  options?: { enabled?: boolean },
): ResourceState<T> {
  const enabled = options?.enabled ?? true;
  const [data, setData] = React.useState<T | null>(null);
  const [error, setError] = React.useState<unknown>(null);
  const [loading, setLoading] = React.useState(enabled);
  const [refreshing, setRefreshing] = React.useState(false);
  const [settled, setSettled] = React.useState(false);
  const [nonce, setNonce] = React.useState(0);
  const loaderRef = React.useRef(loader);
  loaderRef.current = loader;

  React.useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading((prev) => (data === null ? true : prev));
    setRefreshing(true);
    loaderRef
      .current()
      .then((result) => {
        if (cancelled) return;
        setData(result);
        setError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err);
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
        setRefreshing(false);
        setSettled(true);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, enabled, nonce]);

  const reload = React.useCallback(() => setNonce((n) => n + 1), []);

  return { data, error, loading, refreshing, settled, reload, setData };
}

/** Debounces a rapidly changing value (search inputs). */
export function useDebounced<T>(value: T, delay = 350): T {
  const [debounced, setDebounced] = React.useState(value);
  React.useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

/** Outcome of an async action. `ok` is true only when the call succeeded. */
export interface ActionResult<T> {
  ok: boolean;
  data?: T;
  error?: unknown;
}

/**
 * Tracks an async action (button handlers) with pending + error state.
 * The result object distinguishes "succeeded" from "failed" even for
 * endpoints that return no payload.
 */
export function useAction(): {
  pending: boolean;
  error: unknown;
  run: <T>(fn: () => Promise<T>) => Promise<ActionResult<T>>;
  reset: () => void;
} {
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<unknown>(null);

  const run = React.useCallback(async <T,>(fn: () => Promise<T>): Promise<ActionResult<T>> => {
    setPending(true);
    setError(null);
    try {
      const data = await fn();
      return { ok: true, data };
    } catch (err) {
      setError(err);
      return { ok: false, error: err };
    } finally {
      setPending(false);
    }
  }, []);

  const reset = React.useCallback(() => setError(null), []);

  return { pending, error, run, reset };
}
