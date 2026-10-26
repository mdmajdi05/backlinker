"use client";

import * as React from "react";
import { api } from "@autobacklinker/api-client";
import type { ExecutionEnvironment, Opportunity, Task, TaskType } from "@autobacklinker/shared-types";
import { TaskStatus } from "@autobacklinker/shared-types";
import {
  Badge,
  Button,
  Card,
  CardBody,
  Dialog,
  Field,
  Input,
  Pagination,
  ProgressBar,
  Select,
  StatusBadge,
  Table,
  Td,
  Th,
  Toolbar,
  Tooltip,
  useToast,
} from "@autobacklinker/ui";
import { apiClient, errorMessage } from "@/lib/api";
import { useAction, useResource } from "@/lib/hooks";
import { formatDateTime, formatNumber, fromLocalInputValue } from "@/lib/format";
import { ALL_TASK_STATUSES, ALL_TASK_TYPES, TASK_STATUS_LABELS, TASK_TYPE_LABELS } from "@/lib/constants";
import { PageHeader } from "@/components/PageHeader";
import { AsyncSection, TableSkeleton } from "@/components/States";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { OpportunityDrawer } from "@/components/OpportunityDrawer";
import { useDetailsSummaries } from "@/components/SubmissionDetailsPanel";

const PAGE_SIZE = 25;

/** Task statuses that can still be paused by a worker control request. */
const PAUSABLE = new Set<TaskStatus>([
  TaskStatus.QUEUED,
  TaskStatus.APPROVED,
  TaskStatus.NEEDS_REVIEW,
  TaskStatus.RETRY_SCHEDULED,
  TaskStatus.WAITING_FOR_APPROVAL,
]);

/** Task statuses that can be resumed after a pause or a manual hold. */
const RESUMABLE = new Set<TaskStatus>([
  TaskStatus.WAITING_FOR_USER,
  TaskStatus.WAITING_FOR_APPROVAL,
  TaskStatus.RETRY_SCHEDULED,
  TaskStatus.NEEDS_REVIEW,
  TaskStatus.FAILED,
]);

export default function QueuePage() {
  const toast = useToast();
  const action = useAction();

  const [page, setPage] = React.useState(1);
  const [projectId, setProjectId] = React.useState("");
  const [type, setType] = React.useState("");
  const [status, setStatus] = React.useState("");
  const [environment, setEnvironment] = React.useState("");
  const [order, setOrder] = React.useState<string[]>([]);
  const [cancelTarget, setCancelTarget] = React.useState<Task | null>(null);
  const [bulkOpen, setBulkOpen] = React.useState(false);
  // The task whose submission details are missing - opens the drawer.
  const [detailsTarget, setDetailsTarget] = React.useState<Task | null>(null);

  const projects = useResource(() => api.projects.list(apiClient, { page: 1, page_size: 100 }), []);
  const stats = useResource(() => api.queue.stats(apiClient), []);

  const tasks = useResource(
    () =>
      api.queue.list(apiClient, {
        page,
        page_size: PAGE_SIZE,
        project_id: projectId || undefined,
        type: type || undefined,
        status: status || undefined,
        environment: environment || undefined,
      }),
    [page, projectId, type, status, environment],
  );

  const rows = tasks.data?.items ?? [];

  // A task whose submission details are incomplete waits for the user - it is
  // not a failure and must never look like one.
  const opportunityIds = React.useMemo(
    () => rows.map((row) => row.opportunity_id).filter((id): id is string => Boolean(id)),
    [rows],
  );
  const { summaries: detailsByOpportunity, reload: reloadDetails } =
    useDetailsSummaries(opportunityIds);

  const targetOpportunity = useResource(
    () =>
      detailsTarget?.opportunity_id
        ? api.opportunities.get(apiClient, detailsTarget.opportunity_id)
        : Promise.resolve<Opportunity | null>(null),
    [detailsTarget?.opportunity_id],
    { enabled: Boolean(detailsTarget?.opportunity_id) },
  );

  React.useEffect(() => {
    setOrder([]);
  }, [page, projectId, type, status, environment]);

  const orderedRows = React.useMemo(() => {
    if (order.length === 0) return rows;
    const byId = new Map(rows.map((row) => [row.id, row]));
    const ordered = order
      .map((id) => byId.get(id))
      .filter((row): row is Task => Boolean(row));
    const rest = rows.filter((row) => !order.includes(row.id));
    return [...ordered, ...rest];
  }, [rows, order]);

  const move = async (taskId: string, direction: -1 | 1) => {
    const ids = orderedRows.map((row) => row.id);
    const index = ids.indexOf(taskId);
    const target = index + direction;
    if (index < 0 || target < 0 || target >= ids.length) return;
    const next = [...ids];
    const [moved] = next.splice(index, 1);
    next.splice(target, 0, moved);
    setOrder(next);
    const outcome = await action.run(() => api.queue.reorder(apiClient, { task_ids: next }));
    if (!outcome.ok) {
      setOrder(ids);
      toast.push("Could not reorder the queue", "error");
    } else {
      toast.push("Queue order updated", "success");
    }
  };

  const control = async (task: Task, actionName: "pause" | "resume" | "cancel" | "retry" | "requeue") => {
    const outcome = await action.run(() =>
      api.queue.control(apiClient, task.id, { action: actionName }),
    );
    if (outcome.ok) {
      toast.push(`Task ${actionName} requested`, "success");
      tasks.reload();
    }
  };

  const statEntries = Object.entries(stats.data ?? {});

  return (
    <div className="space-y-4">
      <PageHeader
        title="Task queue"
        description="Submission, verification and discovery tasks with priority ordering."
        actions={
          <>
            <Button variant="outline" size="sm" onClick={tasks.reload} loading={tasks.refreshing}>
              Refresh
            </Button>
            <Button size="sm" onClick={() => setBulkOpen(true)}>
              Create queue tasks
            </Button>
          </>
        }
      />

      <Card>
        <CardBody className="py-3">
          {stats.loading && !stats.data ? (
            <p className="text-xs text-content-subtle">Loading queue statistics…</p>
          ) : stats.error ? (
            <p className="text-xs text-danger">{errorMessage(stats.error)}</p>
          ) : statEntries.length === 0 ? (
            <p className="text-xs text-content-subtle">The backend did not report queue statistics.</p>
          ) : (
            <div className="flex flex-wrap gap-x-6 gap-y-2">
              {statEntries.map(([key, value]) => (
                <div key={key}>
                  <p className="text-[11px] uppercase tracking-wide text-content-muted">{key}</p>
                  <p className="text-lg font-semibold tabular-nums text-content">
                    {formatNumber(typeof value === "number" ? value : Number(value))}
                  </p>
                </div>
              ))}
            </div>
          )}
        </CardBody>
      </Card>

      <Card>
        <Toolbar>
          <Field label="Project" className="w-52">
            <Select
              value={projectId}
              onChange={(event) => {
                setProjectId(event.target.value);
                setPage(1);
              }}
            >
              <option value="">All projects</option>
              {(projects.data?.items ?? []).map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Type" className="w-40">
            <Select
              value={type}
              onChange={(event) => {
                setType(event.target.value);
                setPage(1);
              }}
            >
              <option value="">All types</option>
              {ALL_TASK_TYPES.map((value) => (
                <option key={value} value={value}>
                  {TASK_TYPE_LABELS[value] ?? value}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Status" className="w-48">
            <Select
              value={status}
              onChange={(event) => {
                setStatus(event.target.value);
                setPage(1);
              }}
            >
              <option value="">All statuses</option>
              {ALL_TASK_STATUSES.map((value) => (
                <option key={value} value={value}>
                  {TASK_STATUS_LABELS[value] ?? value}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Environment" className="w-40">
            <Select
              value={environment}
              onChange={(event) => {
                setEnvironment(event.target.value);
                setPage(1);
              }}
            >
              <option value="">All environments</option>
              <option value="CLOUD">Cloud</option>
              <option value="LOCAL">Local</option>
            </Select>
          </Field>
        </Toolbar>

        <CardBody className="p-0">
          <AsyncSection
            loading={tasks.loading}
            error={tasks.error}
            data={tasks.data}
            onRetry={tasks.reload}
            isEmpty={orderedRows.length === 0}
            emptyTitle="The queue is empty"
            emptyDescription="Queue tasks are created from approved opportunities or by running discovery."
            skeleton={<TableSkeleton rows={8} columns={8} />}
          >
            <Table>
              <thead>
                <tr>
                  <Th className="w-20">Order</Th>
                  <Th>Task</Th>
                  <Th className="w-24">Type</Th>
                  <Th className="w-48">Status</Th>
                  <Th className="w-24">Env</Th>
                  <Th className="w-28">Priority</Th>
                  <Th className="w-36">Scheduled</Th>
                  <Th className="w-52">Actions</Th>
                </tr>
              </thead>
              <tbody>
                {orderedRows.map((task, index) => {
                  const summary = task.opportunity_id
                    ? detailsByOpportunity[task.opportunity_id]
                    : undefined;
                  const waitingForDetails = Boolean(
                    summary?.state === "ready" &&
                      summary.details &&
                      !summary.details.complete,
                  );
                  const missingCount = summary?.details?.missing.length ?? 0;
                  return (
                    <tr key={task.id}>
                      <Td>
                        <div className="flex items-center gap-1">
                          <Tooltip label="Move up">
                            <Button
                              size="sm"
                              variant="ghost"
                              disabled={index === 0}
                              onClick={() => move(task.id, -1)}
                              aria-label="Move task up"
                            >
                              ↑
                            </Button>
                          </Tooltip>
                          <Tooltip label="Move down">
                            <Button
                              size="sm"
                              variant="ghost"
                              disabled={index === orderedRows.length - 1}
                              onClick={() => move(task.id, 1)}
                              aria-label="Move task down"
                            >
                              ↓
                            </Button>
                          </Tooltip>
                        </div>
                      </Td>
                      <Td>
                        <p className="font-medium text-content">{task.id.slice(0, 8)}</p>
                        <p className="text-xs text-content-muted">
                          Attempts {task.attempts}/{task.max_attempts}
                        </p>
                        <ProgressBar value={task.progress} className="mt-1 max-w-[160px]" />
                        {task.last_error ? (
                          <p
                            className={`mt-1 max-w-xs truncate text-xs ${
                              waitingForDetails ? "text-warning" : "text-danger"
                            }`}
                            title={task.last_error}
                          >
                            {waitingForDetails ? "Blocked: " : ""}
                            {task.last_error}
                          </p>
                        ) : null}
                      </Td>
                      <Td>
                        <Badge tone="neutral">{TASK_TYPE_LABELS[task.type] ?? task.type}</Badge>
                      </Td>
                      <Td>
                        {waitingForDetails ? (
                          <div className="space-y-1">
                            <Badge tone="warning">Waiting for details</Badge>
                            <p className="text-[11px] text-content-subtle">
                              {missingCount} detail{missingCount === 1 ? "" : "s"} missing - task
                              status:{" "}
                              {TASK_STATUS_LABELS[task.status] ?? task.status}
                            </p>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => setDetailsTarget(task)}
                            >
                              Complete details
                            </Button>
                          </div>
                        ) : (
                          <StatusBadge status={task.status} />
                        )}
                      </Td>
                      <Td>
                        <Badge tone={task.execution_environment === "LOCAL" ? "warning" : "info"}>
                          {task.execution_environment}
                        </Badge>
                      </Td>
                      <Td className="tabular-nums">{task.priority}</Td>
                      <Td className="text-xs text-content-muted">
                        {task.scheduled_for ? formatDateTime(task.scheduled_for) : "—"}
                      </Td>
                      <Td>
                        <div className="flex flex-wrap gap-1">
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={!PAUSABLE.has(task.status)}
                            onClick={() => control(task, "pause")}
                            title={
                              PAUSABLE.has(task.status)
                                ? "Pause this task"
                                : `A task in status ${task.status} cannot be paused`
                            }
                          >
                            Pause
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={!RESUMABLE.has(task.status)}
                            onClick={() => control(task, "resume")}
                            title={
                              RESUMABLE.has(task.status)
                                ? "Resume this task"
                                : `A task in status ${task.status} does not need to be resumed`
                            }
                          >
                            Resume
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={task.status === "CANCELLED"}
                            onClick={() => control(task, "retry")}
                          >
                            Retry
                          </Button>
                          <Button
                            size="sm"
                            variant="danger"
                            disabled={task.status === "CANCELLED"}
                            onClick={() => setCancelTarget(task)}
                          >
                            Cancel
                          </Button>
                        </div>
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
            {tasks.data ? (
              <Pagination
                page={tasks.data.page}
                pages={tasks.data.pages}
                total={tasks.data.total}
                onPageChange={setPage}
              />
            ) : null}
          </AsyncSection>
        </CardBody>
      </Card>

      <ConfirmDialog
        open={cancelTarget !== null}
        title="Cancel this task?"
        description={
          cancelTarget
            ? `Task ${cancelTarget.id.slice(0, 8)} will be cancelled and will not be picked up by a worker.`
            : undefined
        }
        confirmLabel="Cancel task"
        destructive
        pending={action.pending}
        onClose={() => setCancelTarget(null)}
        onConfirm={async () => {
          if (!cancelTarget) return;
          const outcome = await action.run(() =>
            api.queue.control(apiClient, cancelTarget.id, { action: "cancel" }),
          );
          if (outcome.ok) {
            toast.push("Task cancelled", "success");
            setCancelTarget(null);
            tasks.reload();
          }
        }}
      />

      <BulkQueueDialog
        open={bulkOpen}
        onClose={() => setBulkOpen(false)}
        onCreated={() => {
          setBulkOpen(false);
          tasks.reload();
        }}
      />

      <Dialog
        open={Boolean(detailsTarget) && !targetOpportunity.data}
        onClose={() => setDetailsTarget(null)}
        title="Loading the opportunity"
        width="sm"
      >
        <p className="text-xs text-content-muted">
          Fetching the opportunity of the task so you can fill in the missing details.
        </p>
      </Dialog>

      <OpportunityDrawer
        opportunity={targetOpportunity.data ?? null}
        open={Boolean(detailsTarget)}
        initialTab="details"
        onClose={() => setDetailsTarget(null)}
        onChanged={() => {
          tasks.reload();
          reloadDetails();
        }}
      />
    </div>
  );
}

function BulkQueueDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}) {
  const toast = useToast();
  const action = useAction();
  const [selectedOpportunities, setSelectedOpportunities] = React.useState<string[]>([]);
  const [selectedProjects, setSelectedProjects] = React.useState<string[]>([]);
  const [taskType, setTaskType] = React.useState<TaskType>("SUBMIT");
  const [priority, setPriority] = React.useState("10");
  const [scheduledFor, setScheduledFor] = React.useState("");
  const [environment, setEnvironment] = React.useState<ExecutionEnvironment>("CLOUD");

  const projects = useResource(() => api.projects.list(apiClient, { page: 1, page_size: 100 }), []);
  const opportunities = useResource(
    () => api.opportunities.list(apiClient, { page: 1, page_size: 50, status: "APPROVED" }),
    [],
  );

  React.useEffect(() => {
    if (!open) {
      setSelectedOpportunities([]);
      setSelectedProjects([]);
    }
  }, [open]);

  const submit = async () => {
    const outcome = await action.run(() =>
      api.queue.create(apiClient, {
        opportunity_ids: selectedOpportunities,
        project_ids: selectedProjects.length > 0 ? selectedProjects : undefined,
        type: taskType,
        priority: Number.parseInt(priority, 10) || 0,
        scheduled_for: scheduledFor ? fromLocalInputValue(scheduledFor) : null,
        execution_environment: environment,
      }),
    );
    if (outcome.ok && outcome.data) {
      toast.push(`Created ${outcome.data.created} queue task(s)`, "success");
      onCreated();
    }
  };

  const disabledReason =
    selectedOpportunities.length === 0 && selectedProjects.length === 0
      ? "Select at least one opportunity or project to queue."
      : null;

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Create queue tasks"
      description="Queue approved opportunities, or whole projects when no opportunity is selected."
      width="lg"
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={action.pending}>
            Cancel
          </Button>
          <Tooltip label={disabledReason ?? "Create the queue tasks"}>
            <span>
              <Button onClick={submit} loading={action.pending} disabled={Boolean(disabledReason)}>
                Create tasks
              </Button>
            </span>
          </Tooltip>
        </>
      }
    >
      <div className="space-y-3">
        {action.error ? (
          <p className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-xs text-danger">
            {errorMessage(action.error)}
          </p>
        ) : null}

        <Field label="Projects" required>
          <div className="max-h-40 space-y-1 overflow-y-auto rounded-md border border-line p-2">
            {(projects.data?.items ?? []).map((project) => (
              <label key={project.id} className="flex items-center gap-2 text-xs text-content">
                <input
                  type="checkbox"
                  checked={selectedProjects.includes(project.id)}
                  onChange={(event) =>
                    setSelectedProjects((prev) =>
                      event.target.checked
                        ? [...prev, project.id]
                        : prev.filter((id) => id !== project.id),
                    )
                  }
                />
                {project.name}
              </label>
            ))}
            {(projects.data?.items ?? []).length === 0 ? (
              <p className="text-xs text-content-subtle">No projects available.</p>
            ) : null}
          </div>
        </Field>

        <Field label="Approved opportunities" required>
          <div className="max-h-48 space-y-1 overflow-y-auto rounded-md border border-line p-2">
            {(opportunities.data?.items ?? []).map((opportunity) => (
              <label key={opportunity.id} className="flex items-center gap-2 text-xs text-content">
                <input
                  type="checkbox"
                  checked={selectedOpportunities.includes(opportunity.id)}
                  onChange={(event) =>
                    setSelectedOpportunities((prev) =>
                      event.target.checked
                        ? [...prev, opportunity.id]
                        : prev.filter((id) => id !== opportunity.id),
                    )
                  }
                />
                <span className="truncate">{opportunity.name}</span>
                <span className="text-content-subtle">{opportunity.domain}</span>
              </label>
            ))}
            {(opportunities.data?.items ?? []).length === 0 ? (
              <p className="text-xs text-content-subtle">
                No approved opportunities found. Approve opportunities in Review found websites
                first.
              </p>
            ) : null}
          </div>
        </Field>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Task type">
            <Select
              value={taskType}
              onChange={(event) => setTaskType(event.target.value as TaskType)}
            >
              {ALL_TASK_TYPES.map((value) => (
                <option key={value} value={value}>
                  {TASK_TYPE_LABELS[value] ?? value}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Priority">
            <Input
              type="number"
              value={priority}
              onChange={(event) => setPriority(event.target.value)}
            />
          </Field>
          <Field label="Scheduled execution" hint="Leave empty to run immediately.">
            <Input
              type="datetime-local"
              value={scheduledFor}
              onChange={(event) => setScheduledFor(event.target.value)}
            />
          </Field>
          <Field label="Execution environment">
            <Select
              value={environment}
              onChange={(event) => setEnvironment(event.target.value as ExecutionEnvironment)}
            >
              <option value="CLOUD">Cloud worker</option>
              <option value="LOCAL">Local agent</option>
            </Select>
          </Field>
        </div>

        {disabledReason ? <p className="text-xs text-content-muted">{disabledReason}</p> : null}
      </div>
    </Dialog>
  );
}
