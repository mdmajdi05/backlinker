"use client";

import * as React from "react";
import { api } from "@autobacklinker/api-client";
import type { Task } from "@autobacklinker/shared-types";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  KeyValue,
  Pagination,
  ProgressBar,
  StatusBadge,
  Table,
  Td,
  Th,
  useToast,
} from "@autobacklinker/ui";
import { apiClient, errorMessage } from "@/lib/api";
import { useAction, useResource } from "@/lib/hooks";
import { formatDateTime, formatRelative } from "@/lib/format";
import { TASK_STATUS_LABELS, TASK_TYPE_LABELS } from "@/lib/constants";
import { PageHeader } from "@/components/PageHeader";
import { AsyncSection, TableSkeleton } from "@/components/States";
import { TaskDrawer } from "@/components/TaskDrawer";

const PAGE_SIZE = 25;

export default function AutomationPage() {
  const toast = useToast();
  const action = useAction();

  const [page, setPage] = React.useState(1);
  const [environment, setEnvironment] = React.useState("");
  const [detail, setDetail] = React.useState<Task | null>(null);
  const [streamState, setStreamState] = React.useState<"connecting" | "live" | "offline">(
    "connecting",
  );
  const [tick, setTick] = React.useState(0);
  const [controlBusy, setControlBusy] = React.useState<string | null>(null);

  const worker = useResource(() => api.automation.workerStatus(apiClient), [tick]);

  const control = async (mode: "pause" | "resume" | "stop") => {
    setControlBusy(mode);
    try {
      if (mode === "pause") await api.automation.pause(apiClient);
      else if (mode === "resume") await api.automation.resume(apiClient);
      else await api.automation.stop(apiClient);
      toast.push(
        mode === "pause"
          ? "All jobs are paused"
          : mode === "resume"
            ? "Jobs are running again"
            : "All jobs stopped",
        "success",
      );
      setTick((value) => value + 1);
    } catch (err) {
      toast.push(errorMessage(err), "error");
    } finally {
      setControlBusy(null);
    }
  };

  const running = useResource(
    () =>
      api.queue.list(apiClient, {
        page: 1,
        page_size: 25,
        status: "RUNNING",
        execution_environment: environment || undefined,
      }),
    [environment, tick],
  );

  const recent = useResource(
    () =>
      api.queue.list(apiClient, {
        page,
        page_size: PAGE_SIZE,
        execution_environment: environment || undefined,
      }),
    [page, environment, tick],
  );

  React.useEffect(() => {
    const unsubscribe = api.dashboard.stream(apiClient, undefined, () => {
      setStreamState("live");
      setTick((value) => value + 1);
    });
    const timer = window.setTimeout(() => {
      setStreamState((prev) => (prev === "connecting" ? "offline" : prev));
    }, 4000);
    return () => {
      unsubscribe();
      window.clearTimeout(timer);
    };
  }, []);

  const waiting = (running.data?.items ?? []).filter(
    (task) => task.status === "WAITING_FOR_USER" || task.requires_human,
  );

  const resume = async (task: Task) => {
    const outcome = await action.run(() =>
      api.queue.control(apiClient, task.id, { action: "resume" }),
    );
    if (outcome.ok) {
      toast.push("Task resumed", "success");
      running.reload();
      recent.reload();
    }
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Live Automation"
        description="Tasks currently executing on cloud workers or local agents."
        actions={
          <>
            <Badge
              tone={
                streamState === "live"
                  ? "success"
                  : streamState === "offline"
                    ? "warning"
                    : "neutral"
              }
            >
              {streamState === "live"
                ? "Stream live"
                : streamState === "offline"
                  ? "Stream offline"
                  : "Connecting"}
            </Badge>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setTick((value) => value + 1);
              }}
            >
              Refresh
            </Button>
          </>
        }
      />

      <Card>
        <CardHeader
          title="Execution control"
          description="Pause, resume or stop every job - the browser runs isolated and headless by default."
          action={
            <div className="flex items-center gap-2">
              <Badge
                tone={
                  worker.data?.execution.state === "RUNNING"
                    ? "success"
                    : worker.data?.execution.state === "PAUSED"
                      ? "warning"
                      : "danger"
                }
              >
                {worker.data?.execution.state ?? "…"}
              </Badge>
              <Button
                size="sm"
                variant="outline"
                disabled={
                  controlBusy !== null || worker.data?.execution.state === "PAUSED"
                }
                onClick={() => void control("pause")}
              >
                Pause all
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={
                  controlBusy !== null || worker.data?.execution.state === "RUNNING"
                }
                onClick={() => void control("resume")}
              >
                Resume
              </Button>
              <Button
                size="sm"
                variant="danger"
                disabled={controlBusy !== null}
                onClick={() => void control("stop")}
              >
                Stop
              </Button>
            </div>
          }
        />
        <CardBody>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <KeyValue
              items={[
                ["Running jobs", String(worker.data?.running_jobs ?? 0)],
                ["Browser jobs", String(worker.data?.running_browser_jobs ?? 0)],
                ["Parallel limit", String(worker.data?.resources.effective_limit ?? 0)],
                ["CPU", `${worker.data?.resources.resources.cpu_percent ?? 0}%`],
                [
                  "Memory free",
                  `${Math.round(worker.data?.resources.resources.memory_available_mb ?? 0)} MB`,
                ],
                [
                  "Browser",
                  worker.data?.browser.available
                    ? worker.data.browser.headless
                      ? "headless"
                      : "headed (isolated)"
                    : "not installed",
                ],
              ]}
            />
            <div className="space-y-2">
              <p className="text-xs text-content-muted">
                {worker.data?.resources.reason ??
                  "The worker lowers the number of parallel jobs when the machine is busy."}
              </p>
              <p className="text-[11px] text-content-subtle">
                {worker.data?.browser.isolation.note ??
                  "The personal browser of the operator is never opened or controlled."}
              </p>
            </div>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Running tasks"
          description="Everything the workers are processing right now"
          action={
            <select
              className="h-9 rounded-md border border-line bg-surface px-2.5 text-sm text-content"
              value={environment}
              onChange={(event) => {
                setEnvironment(event.target.value);
                setPage(1);
              }}
              aria-label="Execution environment filter"
            >
              <option value="">All environments</option>
              <option value="CLOUD">Cloud</option>
              <option value="LOCAL">Local</option>
            </select>
          }
        />
        <CardBody className="p-0">
          <AsyncSection
            loading={running.loading}
            error={running.error}
            data={running.data}
            onRetry={running.reload}
            isEmpty={(running.data?.items ?? []).length === 0}
            emptyTitle="No tasks are running"
            emptyDescription="Queued tasks start automatically unless a worker is offline."
            skeleton={<TableSkeleton rows={4} columns={6} />}
          >
            <Table>
              <thead>
                <tr>
                  <Th>Task</Th>
                  <Th className="w-28">Type</Th>
                  <Th className="w-40">Status</Th>
                  <Th className="w-24">Env</Th>
                  <Th className="w-40">Started</Th>
                  <Th className="w-24">Progress</Th>
                </tr>
              </thead>
              <tbody>
                {(running.data?.items ?? []).map((task) => (
                  <tr key={task.id} className="cursor-pointer" onClick={() => setDetail(task)}>
                    <Td className="font-medium text-content">{task.id.slice(0, 8)}</Td>
                    <Td>
                      <Badge tone="neutral">{TASK_TYPE_LABELS[task.type] ?? task.type}</Badge>
                    </Td>
                    <Td>
                      <StatusBadge status={task.status} />
                    </Td>
                    <Td>
                      <Badge tone={task.execution_environment === "LOCAL" ? "warning" : "info"}>
                        {task.execution_environment}
                      </Badge>
                    </Td>
                    <Td className="text-xs text-content-muted">{formatRelative(task.started_at)}</Td>
                    <Td>
                      <ProgressBar value={task.progress} />
                      <span className="text-[11px] text-content-subtle">
                        {Math.round(task.progress * 100)}%
                      </span>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </AsyncSection>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Manual intervention"
          description="Tasks that cannot continue without a human"
        />
        <CardBody className="p-0">
          <AsyncSection
            loading={running.loading}
            error={running.error}
            data={running.data}
            onRetry={running.reload}
            isEmpty={waiting.length === 0}
            emptyTitle="No tasks are waiting for you"
            emptyDescription="Tasks that require credentials, captchas or approvals show up here."
            skeleton={<TableSkeleton rows={3} columns={4} />}
          >
            <ul className="divide-y divide-line">
              {waiting.map((task) => (
                <li key={task.id} className="flex flex-wrap items-start justify-between gap-3 p-3">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-content">
                      Task {task.id.slice(0, 8)} · {TASK_TYPE_LABELS[task.type] ?? task.type}
                    </p>
                    <p className="mt-0.5 text-xs text-content-muted">
                      {TASK_STATUS_LABELS[task.status] ?? task.status} ·{" "}
                      {task.execution_environment} · started {formatDateTime(task.started_at)}
                    </p>
                    {task.skip_reason || task.last_error ? (
                      <p className="mt-1 text-xs text-danger">
                        {task.skip_reason ?? task.last_error}
                      </p>
                    ) : null}
                    <pre className="mt-2 max-h-40 overflow-auto rounded-md bg-surface-sunken p-2 text-[11px]">
                      {JSON.stringify(task.payload ?? {}, null, 2)}
                    </pre>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <Button variant="outline" size="sm" onClick={() => setDetail(task)}>
                      Details
                    </Button>
                    <Button size="sm" onClick={() => resume(task)} loading={action.pending}>
                      Resume
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          </AsyncSection>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Recent tasks" description="Latest queue activity" />
        <CardBody className="p-0">
          <AsyncSection
            loading={recent.loading}
            error={recent.error}
            data={recent.data}
            onRetry={recent.reload}
            isEmpty={(recent.data?.items ?? []).length === 0}
            emptyTitle="No tasks yet"
            emptyDescription="Queue tasks appear here once they are created."
            skeleton={<TableSkeleton rows={8} columns={7} />}
          >
            <Table>
              <thead>
                <tr>
                  <Th>Task</Th>
                  <Th className="w-28">Type</Th>
                  <Th className="w-44">Status</Th>
                  <Th className="w-24">Env</Th>
                  <Th className="w-24">Attempts</Th>
                  <Th className="w-36">Updated</Th>
                  <Th className="w-24">Open</Th>
                </tr>
              </thead>
              <tbody>
                {(recent.data?.items ?? []).map((task) => (
                  <tr key={task.id}>
                    <Td className="font-medium text-content">{task.id.slice(0, 8)}</Td>
                    <Td>
                      <Badge tone="neutral">{TASK_TYPE_LABELS[task.type] ?? task.type}</Badge>
                    </Td>
                    <Td>
                      <StatusBadge status={task.status} />
                    </Td>
                    <Td>
                      <Badge tone={task.execution_environment === "LOCAL" ? "warning" : "info"}>
                        {task.execution_environment}
                      </Badge>
                    </Td>
                    <Td className="tabular-nums">
                      {task.attempts}/{task.max_attempts}
                    </Td>
                    <Td className="text-xs text-content-muted">{formatRelative(task.updated_at)}</Td>
                    <Td>
                      <Button size="sm" variant="ghost" onClick={() => setDetail(task)}>
                        Inspect
                      </Button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            {recent.data ? (
              <Pagination
                page={recent.data.page}
                pages={recent.data.pages}
                total={recent.data.total}
                onPageChange={setPage}
              />
            ) : null}
          </AsyncSection>
        </CardBody>
      </Card>

      {action.error ? (
        <p className="text-xs text-danger">{errorMessage(action.error)}</p>
      ) : null}

      <TaskDrawer
        task={detail}
        open={Boolean(detail)}
        onClose={() => setDetail(null)}
        onChanged={() => {
          running.reload();
          recent.reload();
        }}
      />
    </div>
  );
}
