"use client";

import * as React from "react";
import { api } from "@autobacklinker/api-client";
import type { ActivityEvent } from "@autobacklinker/shared-types";
import {
  Badge,
  Button,
  Card,
  CardBody,
  Field,
  Input,
  Pagination,
  Select,
  Table,
  Td,
  Th,
  Toolbar,
  useToast,
} from "@autobacklinker/ui";
import { apiClient } from "@/lib/api";
import { useDebounced, useResource } from "@/lib/hooks";
import { downloadTextFile, formatDateTime, toCsv } from "@/lib/format";
import { humanize } from "@/lib/format";
import { PageHeader } from "@/components/PageHeader";
import { AsyncSection, TableSkeleton } from "@/components/States";

const PAGE_SIZE = 25;
const LEVELS = ["INFO", "WARNING", "ERROR", "SUCCESS"];

export default function ActivityPage() {
  const toast = useToast();
  const [page, setPage] = React.useState(1);
  const [level, setLevel] = React.useState("");
  const [eventType, setEventType] = React.useState("");
  const [projectId, setProjectId] = React.useState("");
  const [from, setFrom] = React.useState("");
  const [to, setTo] = React.useState("");

  const projects = useResource(() => api.projects.list(apiClient, { page: 1, page_size: 100 }), []);

  const debouncedType = useDebounced(eventType, 400);

  const activity = useResource(
    () =>
      api.activity.list(apiClient, {
        page,
        page_size: PAGE_SIZE,
        level: level || undefined,
        event_type: debouncedType || undefined,
        project_id: projectId || undefined,
        from: from ? new Date(from).toISOString() : undefined,
        to: to ? new Date(to).toISOString() : undefined,
      }),
    [page, level, debouncedType, projectId, from, to],
  );

  const rows = activity.data?.items ?? [];

  const exportCsv = () => {
    if (rows.length === 0) {
      toast.push("There is nothing to export on this page", "error");
      return;
    }
    const header = [
      "Timestamp",
      "Level",
      "Event type",
      "Project",
      "Website",
      "Task",
      "Opportunity",
      "Environment",
      "Message",
    ];
    const body = rows.map((event: ActivityEvent) => [
      event.created_at,
      event.level,
      event.event_type,
      event.project_name ?? event.project_id ?? "",
      event.website ?? "",
      event.task_id ?? "",
      event.opportunity_id ?? "",
      event.execution_environment ?? "",
      event.message,
    ]);
    downloadTextFile(
      `activity-page-${activity.data?.page ?? page}.csv`,
      toCsv([header, ...body]),
    );
    toast.push(`Exported ${rows.length} rows`, "success");
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Activity"
        description="Every event recorded by the backend, filterable and exportable."
        actions={
          <>
            <Button variant="outline" size="sm" onClick={activity.reload} loading={activity.refreshing}>
              Refresh
            </Button>
            <Button size="sm" onClick={exportCsv} disabled={rows.length === 0}>
              Export page as CSV
            </Button>
          </>
        }
      />

      <Card>
        <Toolbar>
          <Field label="Level" className="w-36">
            <Select
              value={level}
              onChange={(event) => {
                setLevel(event.target.value);
                setPage(1);
              }}
            >
              <option value="">All levels</option>
              {LEVELS.map((value) => (
                <option key={value} value={value}>
                  {humanize(value)}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Event type" className="w-48">
            <Input
              value={eventType}
              onChange={(event) => {
                setEventType(event.target.value);
                setPage(1);
              }}
              placeholder="task.completed"
            />
          </Field>
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
          <Field label="From" className="w-44">
            <Input
              type="datetime-local"
              value={from}
              onChange={(event) => {
                setFrom(event.target.value);
                setPage(1);
              }}
            />
          </Field>
          <Field label="To" className="w-44">
            <Input
              type="datetime-local"
              value={to}
              onChange={(event) => {
                setTo(event.target.value);
                setPage(1);
              }}
            />
          </Field>
          {(level || eventType || projectId || from || to) && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setLevel("");
                setEventType("");
                setProjectId("");
                setFrom("");
                setTo("");
                setPage(1);
              }}
            >
              Reset filters
            </Button>
          )}
        </Toolbar>

        <CardBody className="p-0">
          <AsyncSection
            loading={activity.loading}
            error={activity.error}
            data={activity.data}
            onRetry={activity.reload}
            isEmpty={rows.length === 0}
            emptyTitle="No activity matches these filters"
            emptyDescription="Change the filters or widen the time range."
            skeleton={<TableSkeleton rows={10} columns={7} />}
          >
            <Table>
              <thead>
                <tr>
                  <Th className="w-44">Timestamp</Th>
                  <Th className="w-24">Level</Th>
                  <Th className="w-48">Event</Th>
                  <Th className="w-40">Project</Th>
                  <Th className="w-44">Website</Th>
                  <Th className="w-24">Env</Th>
                  <Th>Message</Th>
                </tr>
              </thead>
              <tbody>
                {rows.map((event) => (
                  <tr key={event.id}>
                    <Td className="whitespace-nowrap text-xs text-content-muted">
                      {formatDateTime(event.created_at)}
                    </Td>
                    <Td>
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
                    </Td>
                    <Td className="text-xs">{event.event_type}</Td>
                    <Td className="text-xs">{event.project_name ?? event.project_id ?? "—"}</Td>
                    <Td className="truncate text-xs">{event.website ?? "—"}</Td>
                    <Td className="text-xs">{event.execution_environment ?? "—"}</Td>
                    <Td className="text-xs">{event.message}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            {activity.data ? (
              <Pagination
                page={activity.data.page}
                pages={activity.data.pages}
                total={activity.data.total}
                onPageChange={setPage}
              />
            ) : null}
          </AsyncSection>
        </CardBody>
      </Card>
    </div>
  );
}
