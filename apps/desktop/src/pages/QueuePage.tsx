import * as React from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  MetricTile,
  Pagination,
  ProgressBar,
  Select,
  StatusBadge,
  Table,
  Td,
  Th,
  useToast,
} from "@autobacklinker/ui";
import { api, apiClient } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import { ErrorBlock, LoadingBlock, NothingYet, PageHeader } from "../components/common";
import {
  SubmissionDetailsPanel,
  useSubmissionDetailsStates,
} from "../components/SubmissionDetailsPanel";
import { formatDate, formatNumber, truncate } from "../lib/format";
import { ExecutionEnvironment, TaskStatus, type Task } from "@autobacklinker/shared-types";

const PAGE_SIZE = 25;

const STATUS_FILTERS = [
  "",
  "QUEUED",
  "RUNNING",
  "RETRY_SCHEDULED",
  "WAITING_FOR_USER",
  "WAITING_FOR_APPROVAL",
  "SUBMITTED",
  "PUBLISHED_UNVERIFIED",
  "VERIFIED_LIVE",
  "FAILED",
  "SKIPPED",
  "CANCELLED",
];

/**
 * The statuses of a task that already reached the target site.  A task in
 * one of them is never "waiting for details" - the submission happened.
 */
const SUBMITTED_STATUSES = new Set<string>([
  TaskStatus.SUBMITTED,
  TaskStatus.PUBLISHED_UNVERIFIED,
  TaskStatus.VERIFIED_LIVE,
  TaskStatus.SKIPPED,
  TaskStatus.CANCELLED,
  TaskStatus.COMPLETED,
]);

export function QueuePage() {
  const toast = useToast();
  const [page, setPage] = React.useState(1);
  const [status, setStatus] = React.useState("");
  const [environment, setEnvironment] = React.useState("");
  const [busyId, setBusyId] = React.useState<string | null>(null);
  const [detailsFor, setDetailsFor] = React.useState<{
    task: Task;
    name: string | null;
  } | null>(null);

  const stats = useAsync(() => api.queue.stats(apiClient), []);

  const tasks = useAsync(
    () =>
      api.queue.list(apiClient, {
        page,
        page_size: PAGE_SIZE,
        status: status || undefined,
        execution_environment: environment || undefined,
      }),
    [page, status, environment],
  );

  const items = React.useMemo(() => tasks.data?.items ?? [], [tasks.data]);

  // The details of the opportunities of the tasks - a task whose details are
  // incomplete waits for the operator instead of failing.
  const detailStates = useSubmissionDetailsStates(
    items
      .map((task) => task.opportunity_id)
      .filter((id): id is string => Boolean(id)),
  );

  function waitsForDetails(task: Task): boolean {
    if (!task.opportunity_id) return false;
    if (SUBMITTED_STATUSES.has(task.status)) return false;
    const details = detailStates.states[task.opportunity_id];
    return Boolean(details && !details.complete);
  }

  async function openDetails(task: Task) {
    if (!task.opportunity_id) return;
    setDetailsFor({ task, name: null });
    try {
      const opportunity = await api.opportunities.get(
        apiClient,
        task.opportunity_id,
      );
      setDetailsFor((current) =>
        current && current.task.id === task.id
          ? { ...current, name: opportunity.name }
          : current,
      );
    } catch {
      // The name is only a decoration - the panel works without it.
    }
  }

  async function control(task: Task, action: "pause" | "resume" | "cancel") {
    setBusyId(task.id);
    try {
      await api.queue.control(apiClient, task.id, {
        action,
        reason: `Requested from the desktop app`,
      });
      toast.push(`Task ${action}d`, "success");
      tasks.reload();
      stats.reload();
    } catch (err) {
      toast.push(
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : "Could not update the task",
        "error",
      );
    } finally {
      setBusyId(null);
    }
  }

  const statEntries = Object.entries(stats.data ?? {}).filter(
    ([key]) => key !== "TOTAL",
  );

  const waitingForDetails = items.filter((task) => waitsForDetails(task)).length;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Queue"
        description="Tasks, leases and the controls for locally executed work."
      />

      {stats.error ? (
        <ErrorBlock message={stats.error} onRetry={stats.reload} />
      ) : null}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <MetricTile
          label="Queued"
          value={formatNumber(stats.data?.QUEUED)}
          tone="info"
        />
        <MetricTile
          label="Running"
          value={formatNumber(stats.data?.RUNNING)}
          tone="accent"
        />
        <MetricTile
          label="Waiting"
          value={formatNumber(stats.data?.WAITING_FOR_USER)}
          tone="warning"
        />
        <MetricTile
          label="Failed"
          value={formatNumber(stats.data?.FAILED)}
          tone="danger"
        />
      </div>

      {waitingForDetails > 0 ? (
        <Alert
          tone="warning"
          title={`${waitingForDetails} task${
            waitingForDetails === 1 ? " waits" : "s wait"
          } in this view for the missing details`}
        >
          <p>
            A submission that asks for a value that is still empty waits for
            you. It is not a failure - fill the details and it continues.
          </p>
        </Alert>
      ) : null}

      <Card>
        <CardHeader title="Filters" />
        <CardBody>
          <div className="flex flex-wrap items-end gap-3">
            <div className="w-52">
              <label className="mb-1 block text-xs font-medium text-content-muted">
                Status
              </label>
              <Select
                value={status}
                onChange={(event) => {
                  setStatus(event.target.value);
                  setPage(1);
                }}
              >
                {STATUS_FILTERS.map((value) => (
                  <option key={value} value={value}>
                    {value ? value.replace(/_/g, " ") : "All statuses"}
                  </option>
                ))}
              </Select>
            </div>
            <div className="w-48">
              <label className="mb-1 block text-xs font-medium text-content-muted">
                Execution environment
              </label>
              <Select
                value={environment}
                onChange={(event) => {
                  setEnvironment(event.target.value);
                  setPage(1);
                }}
              >
                <option value="">All environments</option>
                <option value={ExecutionEnvironment.LOCAL}>Local</option>
                <option value={ExecutionEnvironment.CLOUD}>Cloud</option>
              </Select>
            </div>
            {statEntries.length > 0 ? (
              <div className="flex flex-wrap items-center gap-1.5 pb-1.5">
                {statEntries.map(([key, value]) => (
                  <Badge key={key} tone="neutral">
                    {key.replace(/_/g, " ")} · {formatNumber(value)}
                  </Badge>
                ))}
              </div>
            ) : null}
          </div>
        </CardBody>
      </Card>

      {tasks.loading && !tasks.data ? <LoadingBlock /> : null}
      {tasks.error ? (
        <ErrorBlock message={tasks.error} onRetry={tasks.reload} />
      ) : null}

      {!tasks.loading && items.length === 0 && !tasks.error ? (
        <NothingYet
          title="The queue is empty"
          description="No task matches the current filter."
        />
      ) : null}

      {items.length > 0 ? (
        <Card>
          <CardBody className="p-0">
            <Table>
              <thead>
                <tr>
                  <Th>Type</Th>
                  <Th>Status</Th>
                  <Th>Environment</Th>
                  <Th>Priority</Th>
                  <Th>Progress</Th>
                  <Th>Attempts</Th>
                  <Th>Scheduled</Th>
                  <Th>Last error</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {items.map((task: Task) => {
                  const isLocal =
                    task.execution_environment === ExecutionEnvironment.LOCAL;
                  const waiting = waitsForDetails(task);
                  const missing = task.opportunity_id
                    ? detailStates.states[task.opportunity_id]?.missing ?? []
                    : [];
                  return (
                    <tr key={task.id}>
                      <Td className="whitespace-nowrap text-xs font-medium">
                        {task.type}
                      </Td>
                      <Td>
                        {waiting ? (
                          <div className="flex flex-col gap-1">
                            <Badge tone="warning">
                              Waiting for details
                            </Badge>
                            <span className="text-[11px] text-content-subtle">
                              {task.status.replace(/_/g, " ")}
                            </span>
                          </div>
                        ) : (
                          <StatusBadge status={task.status} />
                        )}
                      </Td>
                      <Td>
                        <Badge tone={isLocal ? "accent" : "neutral"}>
                          {task.execution_environment}
                        </Badge>
                      </Td>
                      <Td className="text-right text-xs">{task.priority}</Td>
                      <Td className="w-32">
                        <ProgressBar value={task.progress ?? 0} />
                      </Td>
                      <Td className="text-xs">
                        {task.attempts}/{task.max_attempts}
                      </Td>
                      <Td className="whitespace-nowrap text-xs text-content-muted">
                        {formatDate(task.scheduled_for)}
                      </Td>
                      <Td
                        className={
                          waiting
                            ? "max-w-[220px] truncate text-xs text-content-muted"
                            : "max-w-[220px] truncate text-xs text-danger"
                        }
                        title={
                          waiting
                            ? `Missing: ${missing.join(", ") || "details"}`
                            : undefined
                        }
                      >
                        {waiting
                          ? `Missing: ${missing.join(", ") || "details"}`
                          : (task.last_error ?? "-")}
                      </Td>
                      <Td className="whitespace-nowrap text-right">
                        <div className="flex justify-end gap-1">
                          {task.opportunity_id ? (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => void openDetails(task)}
                            >
                              Details
                            </Button>
                          ) : null}
                          {isLocal ? (
                            <>
                              {task.status === "QUEUED" ||
                              task.status === "RETRY_SCHEDULED" ? (
                                <Button
                                  size="sm"
                                  variant="outline"
                                  disabled={busyId === task.id}
                                  onClick={() => control(task, "pause")}
                                >
                                  Pause
                                </Button>
                              ) : null}
                              {task.status === "DISCOVERED" ? (
                                <Button
                                  size="sm"
                                  variant="outline"
                                  disabled={busyId === task.id}
                                  onClick={() => control(task, "resume")}
                                >
                                  Resume
                                </Button>
                              ) : null}
                              <Button
                                size="sm"
                                variant="danger"
                                disabled={busyId === task.id}
                                onClick={() => control(task, "cancel")}
                              >
                                Cancel
                              </Button>
                            </>
                          ) : (
                            <span className="text-[11px] text-content-subtle">
                              {truncate(task.idempotency_key, 12)}
                            </span>
                          )}
                        </div>
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
            <Pagination
              page={page}
              pages={tasks.data?.pages ?? 1}
              total={tasks.data?.total ?? 0}
              onPageChange={setPage}
            />
          </CardBody>
        </Card>
      ) : null}

      {detailsFor?.task.opportunity_id ? (
        <SubmissionDetailsPanel
          opportunityId={detailsFor.task.opportunity_id}
          opportunityName={detailsFor.name ?? undefined}
          onClose={() => setDetailsFor(null)}
          onChanged={detailStates.reload}
        />
      ) : null}
    </div>
  );
}
