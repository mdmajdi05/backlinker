"use client";

import * as React from "react";
import { api } from "@autobacklinker/api-client";
import type { Task, TaskAttempt, TaskEvent } from "@autobacklinker/shared-types";
import {
  Alert,
  Badge,
  Button,
  Drawer,
  KeyValue,
  ProgressBar,
  StatusBadge,
  Tooltip,
  useToast,
} from "@autobacklinker/ui";
import { apiClient, errorMessage } from "@/lib/api";
import { useAction, useResource } from "@/lib/hooks";
import { formatDateTime, humanize } from "@/lib/format";
import { TASK_STATUS_LABELS, TASK_TYPE_LABELS } from "@/lib/constants";

export function TaskDrawer({
  task,
  open,
  onClose,
  onChanged,
}: {
  task: Task | null;
  open: boolean;
  onClose: () => void;
  onChanged?: () => void;
}) {
  const toast = useToast();
  const action = useAction();
  const taskId = task?.id ?? null;

  const attempts = useResource(
    () => (taskId ? api.tasks.attempts(apiClient, taskId) : Promise.resolve<TaskAttempt[]>([])),
    [taskId],
    { enabled: Boolean(taskId) },
  );
  const events = useResource(
    () => (taskId ? api.tasks.events(apiClient, taskId) : Promise.resolve<TaskEvent[]>([])),
    [taskId],
    { enabled: Boolean(taskId) },
  );

  const resume = async () => {
    if (!taskId) return;
    const outcome = await action.run(() =>
      api.queue.control(apiClient, taskId, { action: "resume" }),
    );
    if (outcome.ok) {
      toast.push("Task resumed", "success");
      onChanged?.();
    }
  };

  const cancel = async () => {
    if (!taskId) return;
    const outcome = await action.run(() => api.tasks.cancel(apiClient, taskId));
    if (outcome.ok) {
      toast.push("Task cancelled", "success");
      onChanged?.();
    }
  };

  const retry = async () => {
    if (!taskId) return;
    const outcome = await action.run(() => api.tasks.retry(apiClient, taskId));
    if (outcome.ok) {
      toast.push("Task retried", "success");
      onChanged?.();
    }
  };

  const manualIntervention = task?.status === "WAITING_FOR_USER";

  return (
    <Drawer
      open={open && Boolean(task)}
      onClose={onClose}
      title={task ? `Task ${task.id.slice(0, 8)}` : "Task"}
      width="lg"
      footer={
        task ? (
          <>
            <Button variant="outline" size="sm" onClick={retry} loading={action.pending}>
              Retry
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={cancel}
              loading={action.pending}
              disabled={task.status === "CANCELLED"}
            >
              Cancel
            </Button>
            <Button size="sm" onClick={resume} loading={action.pending}>
              Resume
            </Button>
          </>
        ) : null
      }
    >
      {task ? (
        <div className="space-y-4">
          {action.error ? (
            <Alert tone="danger" title="Action failed">
              {errorMessage(action.error)}
            </Alert>
          ) : null}

          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={task.status} />
            <Badge tone="neutral">{TASK_TYPE_LABELS[task.type] ?? task.type}</Badge>
            <Badge tone={task.execution_environment === "LOCAL" ? "warning" : "info"}>
              {task.execution_environment === "LOCAL" ? "Local agent" : "Cloud worker"}
            </Badge>
            {task.requires_human ? <Badge tone="warning">Needs human</Badge> : null}
          </div>

          {manualIntervention ? (
            <Alert tone="warning" title="Manual intervention required">
              <p>
                This task is waiting for a human. The task payload usually contains the required
                action (for example a form URL, a login, or a captcha).
              </p>
              <pre className="mt-2 max-h-48 overflow-auto rounded-md bg-surface-sunken p-2 text-[11px]">
                {JSON.stringify(task.payload ?? {}, null, 2)}
              </pre>
              <div className="mt-2">
                <Button size="sm" onClick={resume} loading={action.pending}>
                  Resume task
                </Button>
              </div>
            </Alert>
          ) : null}

          <section className="rounded-lg border border-line">
            <h3 className="border-b border-line px-3 py-2 text-xs font-semibold text-content">
              Task
            </h3>
            <div className="space-y-3 p-3">
              <ProgressBar value={task.progress} />
              <KeyValue
                items={[
                  ["Project", task.project_id ?? "—"],
                  ["Opportunity", task.opportunity_id ?? "—"],
                  ["Adapter", task.adapter_id ?? "—"],
                  ["Priority", String(task.priority)],
                  ["Attempts", `${task.attempts} / ${task.max_attempts}`],
                  ["Status", TASK_STATUS_LABELS[task.status] ?? task.status],
                  ["Scheduled", formatDateTime(task.scheduled_for)],
                  ["Started", formatDateTime(task.started_at)],
                  ["Finished", formatDateTime(task.finished_at)],
                  ["Next retry", formatDateTime(task.next_retry_at)],
                  ["Lease owner", task.lease_owner ?? "—"],
                  ["Last error", task.last_error ?? "—"],
                  ["Skip reason", task.skip_reason ?? "—"],
                ]}
              />
            </div>
          </section>

          <section className="rounded-lg border border-line">
            <h3 className="border-b border-line px-3 py-2 text-xs font-semibold text-content">
              Attempts
            </h3>
            <div className="p-3">
              {attempts.loading ? (
                <p className="text-xs text-content-subtle">Loading attempts…</p>
              ) : attempts.error ? (
                <p className="text-xs text-danger">{errorMessage(attempts.error)}</p>
              ) : (attempts.data ?? []).length === 0 ? (
                <p className="text-xs text-content-subtle">No attempts recorded yet.</p>
              ) : (
                <ol className="space-y-2">
                  {(attempts.data ?? []).map((attempt) => (
                    <li key={attempt.id} className="rounded-md border border-line p-2">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="text-xs font-medium text-content">
                          Attempt {attempt.attempt_number}
                        </span>
                        <Badge tone={attempt.outcome?.toUpperCase() === "SUCCESS" ? "success" : "neutral"}>
                          {humanize(attempt.outcome)}
                        </Badge>
                      </div>
                      <p className="mt-1 text-[11px] text-content-muted">
                        {formatDateTime(attempt.started_at)} →{" "}
                        {attempt.finished_at ? formatDateTime(attempt.finished_at) : "running"} ·{" "}
                        {attempt.worker ?? "unassigned"} · {attempt.execution_environment}
                      </p>
                      {attempt.error ? (
                        <p className="mt-1 text-[11px] text-danger">{attempt.error}</p>
                      ) : null}
                      {attempt.evidence ? (
                        <details className="mt-1">
                          <summary className="cursor-pointer text-[11px] text-content-muted">
                            Evidence
                          </summary>
                          <pre className="mt-1 max-h-40 overflow-auto rounded bg-surface-sunken p-2 text-[10px]">
                            {JSON.stringify(attempt.evidence, null, 2)}
                          </pre>
                        </details>
                      ) : null}
                    </li>
                  ))}
                </ol>
              )}
            </div>
          </section>

          <section className="rounded-lg border border-line">
            <h3 className="border-b border-line px-3 py-2 text-xs font-semibold text-content">
              Events
            </h3>
            <div className="p-3">
              {events.loading ? (
                <p className="text-xs text-content-subtle">Loading events…</p>
              ) : events.error ? (
                <p className="text-xs text-danger">{errorMessage(events.error)}</p>
              ) : (events.data ?? []).length === 0 ? (
                <p className="text-xs text-content-subtle">No events recorded yet.</p>
              ) : (
                <ol className="space-y-2">
                  {(events.data ?? []).map((event) => (
                    <li key={event.id} className="rounded-md border border-line p-2">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="text-xs font-medium text-content">
                          {humanize(event.event_type)}
                        </span>
                        <Badge
                          tone={
                            event.level === "ERROR"
                              ? "danger"
                              : event.level === "WARNING"
                                ? "warning"
                                : event.level === "SUCCESS"
                                  ? "success"
                                  : "info"
                          }
                        >
                          {event.level}
                        </Badge>
                      </div>
                      <p className="mt-1 text-[11px] text-content-muted">{event.message}</p>
                      <p className="mt-0.5 text-[11px] text-content-subtle">
                        {formatDateTime(event.created_at)}
                        {event.execution_environment ? ` · ${event.execution_environment}` : ""}
                      </p>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          </section>

          <Tooltip label="Raw task payload as returned by the backend">
            <details className="rounded-lg border border-line p-3">
              <summary className="cursor-pointer text-xs font-semibold text-content">
                Raw payload
              </summary>
              <pre className="mt-2 max-h-64 overflow-auto rounded bg-surface-sunken p-2 text-[11px]">
                {JSON.stringify(task.payload ?? {}, null, 2)}
              </pre>
            </details>
          </Tooltip>
        </div>
      ) : null}
    </Drawer>
  );
}
