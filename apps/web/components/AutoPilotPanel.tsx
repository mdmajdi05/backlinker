"use client";

import * as React from "react";
import { api } from "@autobacklinker/api-client";
import type { AutoPilotState } from "@autobacklinker/shared-types";
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Label,
  Skeleton,
  useToast,
} from "@autobacklinker/ui";
import { apiClient, errorMessage, isNotFoundError } from "@/lib/api";
import { useAction, useResource } from "@/lib/hooks";
import { ALL_OPPORTUNITY_CATEGORIES, CATEGORY_LABELS } from "@/lib/constants";
import { formatNumber } from "@/lib/format";

/** The plain explanation every user needs to understand the switch. */
export const AUTO_PILOT_EXPLANATION =
  "When this is on, approving an opportunity queues it automatically - the worker submits in the background. You stay in control of what is approved.";

export function AutoPilotPanel({
  projectId,
  projectName,
}: {
  projectId: string;
  projectName?: string;
}) {
  const toast = useToast();
  const action = useAction();

  const state = useResource(() => api.autoPilot.get(apiClient, projectId), [projectId]);
  const [enabled, setEnabled] = React.useState(false);
  const [categories, setCategories] = React.useState<string[]>([]);

  React.useEffect(() => {
    if (!state.data) return;
    setEnabled(state.data.enabled);
    setCategories(state.data.categories);
  }, [state.data]);

  const unavailable = Boolean(state.error) && isNotFoundError(state.error);

  const save = async (next: { enabled: boolean; categories: string[] }) => {
    const outcome = await action.run(() => api.autoPilot.update(apiClient, projectId, next));
    if (outcome.ok && outcome.data) {
      setEnabled(outcome.data.enabled);
      setCategories(outcome.data.categories);
      state.reload();
      return true;
    }
    return false;
  };

  const toggle = async (next: boolean) => {
    const previous = { enabled, categories };
    setEnabled(next);
    if (await save({ enabled: next, categories })) {
      toast.push(
        next
          ? `Automatic submission is on${projectName ? ` for ${projectName}` : ""}`
          : "Automatic submission is off",
        "success",
      );
    } else {
      setEnabled(previous.enabled);
      setCategories(previous.categories);
    }
  };

  const toggleCategory = async (category: string) => {
    const previous = categories;
    const next = previous.includes(category)
      ? previous.filter((item) => item !== category)
      : [...previous, category];
    setCategories(next);
    if (!(await save({ enabled, categories: next }))) {
      setCategories(previous);
    }
  };

  if (state.loading && !state.data) {
    return (
      <div className="space-y-3" aria-busy="true" aria-live="polite">
        <span className="sr-only">Loading the automatic submission settings…</span>
        <Skeleton className="h-9 w-64" />
        <Skeleton className="h-12 w-full" />
      </div>
    );
  }

  if (state.error && !state.data) {
    if (unavailable) {
      return (
        <Alert
          tone="neutral"
          title="Automatic submission is not available yet"
          action={
            <Button variant="outline" size="sm" onClick={state.reload}>
              Try again
            </Button>
          }
        >
          The backend answered 404 for{" "}
          <code className="font-mono text-[11px]">GET /api/v1/projects/{projectId}/autopilot</code>.
          The switch stays disabled until the endpoint is available.
        </Alert>
      );
    }
    return (
      <Alert
        tone="danger"
        title="Could not load the automatic submission settings"
        action={
          <Button variant="outline" size="sm" onClick={state.reload}>
            Retry
          </Button>
        }
      >
        {errorMessage(state.error)}
      </Alert>
    );
  }

  const data: AutoPilotState | null = state.data;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Label className="flex items-center gap-2 text-content">
            <Checkbox
              checked={enabled}
              disabled={unavailable || action.pending}
              onChange={(event) => void toggle(event.target.checked)}
              aria-label="Automatic submission"
            />
            Automatic submission
          </Label>
          <p className="mt-1 max-w-xl text-xs text-content-muted">{AUTO_PILOT_EXPLANATION}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {enabled ? <Badge tone="success">On</Badge> : <Badge tone="neutral">Off</Badge>}
          {action.pending ? <Badge tone="info">Saving…</Badge> : null}
        </div>
      </div>

      {action.error ? (
        <Alert tone="danger" title="Could not save the automatic submission settings">
          {errorMessage(action.error)}
        </Alert>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-line px-3 py-2">
          <p className="text-[11px] uppercase tracking-wide text-content-muted">
            Waiting to be submitted
          </p>
          <p className="text-xl font-semibold tabular-nums text-content">
            {data ? formatNumber(data.waiting) : "—"}
          </p>
          <p className="text-xs text-content-subtle">
            Approved opportunities the worker has not submitted yet.
          </p>
        </div>
        <div className="rounded-lg border border-line px-3 py-2">
          <p className="text-[11px] uppercase tracking-wide text-content-muted">
            Submitted automatically
          </p>
          <p className="text-xl font-semibold tabular-nums text-content">
            {data ? formatNumber(data.submitted) : "—"}
          </p>
          <p className="text-xs text-content-subtle">
            Opportunities the worker submitted without a manual step.
          </p>
        </div>
      </div>

      <div className="rounded-lg border border-line p-3">
        <p className="text-xs font-semibold text-content">Category filter</p>
        <p className="mt-0.5 text-xs text-content-muted">
          Optional. Leave everything unchecked to submit every category.
        </p>
        <div className="mt-2 grid gap-1 sm:grid-cols-2 lg:grid-cols-3">
          {ALL_OPPORTUNITY_CATEGORIES.map((category) => {
            const active = categories.includes(category);
            return (
              <label
                key={category}
                className="flex items-center gap-2 text-xs text-content"
              >
                <Checkbox
                  checked={active}
                  disabled={unavailable || action.pending}
                  onChange={() => void toggleCategory(category)}
                />
                {CATEGORY_LABELS[category] ?? category}
              </label>
            );
          })}
        </div>
        {categories.length > 0 ? (
          <p className="mt-2 text-xs text-content-muted">
            Only these categories are submitted automatically:{" "}
            {categories.map((category) => CATEGORY_LABELS[category] ?? category).join(", ")}.
          </p>
        ) : null}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Summaries for list views                                           */
/* ------------------------------------------------------------------ */

export type AutoPilotSummaryState = "loading" | "ready" | "unavailable" | "error";

export interface AutoPilotSummary {
  state: AutoPilotSummaryState;
  data?: AutoPilotState;
  error?: unknown;
}

/**
 * Loads the automatic submission state of several projects - used by the
 * registry to show per row whether approving queues the submission.
 */
export function useAutoPilotStates(projectIds: string[]): {
  states: Record<string, AutoPilotSummary>;
  reload: () => void;
} {
  const [states, setStates] = React.useState<Record<string, AutoPilotSummary>>({});
  const [nonce, setNonce] = React.useState(0);
  const cache = React.useRef(new Map<string, AutoPilotState>());
  const unavailable = React.useRef<unknown>(null);

  const idsKey = Array.from(new Set(projectIds.filter(Boolean))).sort().join(",");

  React.useEffect(() => {
    const unique = idsKey ? idsKey.split(",") : [];
    if (unique.length === 0) return;
    let cancelled = false;

    setStates((prev) => {
      const next = { ...prev };
      let changed = false;
      for (const id of unique) {
        if (!next[id]) {
          next[id] = { state: "loading" };
          changed = true;
        }
      }
      return changed ? next : prev;
    });

    const run = async () => {
      for (const id of unique) {
        if (cancelled) return;
        if (cache.current.has(id)) {
          setStates((prev) => ({
            ...prev,
            [id]: { state: "ready", data: cache.current.get(id) },
          }));
          continue;
        }
        if (unavailable.current) {
          if (cancelled) return;
          setStates((prev) => ({
            ...prev,
            [id]: { state: "unavailable", error: unavailable.current },
          }));
          continue;
        }
        try {
          const data = await api.autoPilot.get(apiClient, id);
          cache.current.set(id, data);
          if (cancelled) return;
          setStates((prev) => ({ ...prev, [id]: { state: "ready", data } }));
        } catch (error) {
          if (isNotFoundError(error)) {
            unavailable.current = error;
          }
          if (cancelled) return;
          setStates((prev) => ({
            ...prev,
            [id]: { state: isNotFoundError(error) ? "unavailable" : "error", error },
          }));
        }
      }
    };

    void run();
    return () => {
      cancelled = true;
    };
  }, [idsKey, nonce]);

  const reload = React.useCallback(() => {
    cache.current.clear();
    unavailable.current = null;
    setStates({});
    setNonce((value) => value + 1);
  }, []);

  return { states, reload };
}
