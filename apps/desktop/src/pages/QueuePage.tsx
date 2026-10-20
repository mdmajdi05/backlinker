import * as React from "react";
import {
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
import { formatDate, formatNumber, truncate } from "../lib/format";
import { ExecutionEnvironment, type Task } from "@autobacklinker/shared-types";

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

export function QueuePage() {
  const toast = useToast();
  const [page, setPage] = React.useState(1);
  const [status, setStatus] = React.useState("");
  const [environment, setEnvironment] = React.useState("");
  const [busyId, setBusyId] = React.useState<string | null>(null);

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

  const items = tasks.data?.items ?? [];

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
                  return (
                    <tr key={task.id}>
                      <Td className="whitespace-nowrap text-xs font-medium">
                        {task.type}
                      </Td>
                      <Td>
                        <StatusBadge status={task.status} />
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
                      <Td className="max-w-[220px] truncate text-xs text-danger">
                        {task.last_error ?? "-"}
                      </Td>
                      <Td className="whitespace-nowrap text-right">
                        {isLocal ? (
                          <div className="flex justify-end gap-1">
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
                          </div>
                        ) : (
                          <span className="text-[11px] text-content-subtle">
                            {truncate(task.idempotency_key, 12)}
                          </span>
                        )}
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
    </div>
  );
}
