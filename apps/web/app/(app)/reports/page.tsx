"use client";

import * as React from "react";
import { api } from "@autobacklinker/api-client";
import type { ExportJob } from "@autobacklinker/shared-types";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Field,
  Pagination,
  Select,
  StatusBadge,
  Table,
  Td,
  Th,
  useToast,
} from "@autobacklinker/ui";
import { apiClient, errorMessage } from "@/lib/api";
import { useAction, useResource } from "@/lib/hooks";
import { formatDateTime, formatNumber } from "@/lib/format";
import { PageHeader } from "@/components/PageHeader";
import { AsyncSection, TableSkeleton } from "@/components/States";

const PAGE_SIZE = 20;

export default function ReportsPage() {
  const toast = useToast();
  const action = useAction();

  const [page, setPage] = React.useState(1);
  const [projectId, setProjectId] = React.useState("");
  const [scope, setScope] = React.useState("workspace");
  const [format, setFormat] = React.useState<"xlsx" | "csv">("xlsx");

  const projects = useResource(() => api.projects.list(apiClient, { page: 1, page_size: 100 }), []);
  const jobs = useResource(
    () => api.reports.list(apiClient, { page, page_size: PAGE_SIZE }),
    [page],
  );

  const generate = async () => {
    const outcome = await action.run(() =>
      api.reports.generate(apiClient, {
        project_id: scope === "project" ? projectId || undefined : undefined,
        scope,
        format,
      }),
    );
    if (outcome.ok && outcome.data) {
      toast.push(`Export job ${outcome.data.status.toLowerCase()}`, "success");
      jobs.reload();
    }
  };

  const download = async (job: ExportJob) => {
    try {
      await api.reports.download(apiClient, job.id);
      toast.push("Download started", "success");
    } catch (err) {
      toast.push(errorMessage(err), "error");
    }
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Reports & Exports"
        description="Generate spreadsheet exports of the workspace data."
        actions={
          <Button variant="outline" size="sm" onClick={jobs.reload} loading={jobs.refreshing}>
            Refresh
          </Button>
        }
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader title="Generate export" description="Create a new report job" />
          <CardBody>
            <div className="space-y-3">
              <Field label="Scope">
                <Select value={scope} onChange={(event) => setScope(event.target.value)}>
                  <option value="workspace">Whole workspace</option>
                  <option value="project">Single project</option>
                </Select>
              </Field>
              {scope === "project" ? (
                <Field label="Project" required>
                  <Select value={projectId} onChange={(event) => setProjectId(event.target.value)}>
                    <option value="">Select project…</option>
                    {(projects.data?.items ?? []).map((project) => (
                      <option key={project.id} value={project.id}>
                        {project.name}
                      </option>
                    ))}
                  </Select>
                </Field>
              ) : null}
              <Field label="Format">
                <Select
                  value={format}
                  onChange={(event) => setFormat(event.target.value as "xlsx" | "csv")}
                >
                  <option value="xlsx">Excel workbook (.xlsx)</option>
                  <option value="csv">CSV (.csv)</option>
                </Select>
              </Field>

              {action.error ? (
                <p className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-xs text-danger">
                  {errorMessage(action.error)}
                </p>
              ) : null}

              <Button
                className="w-full"
                onClick={generate}
                loading={action.pending}
                disabled={scope === "project" && !projectId}
                title={
                  scope === "project" && !projectId
                    ? "Select the project that should be exported"
                    : undefined
                }
              >
                Generate report
              </Button>
            </div>
          </CardBody>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader title="Export jobs" description="Status of generated reports" />
          <CardBody className="p-0">
            <AsyncSection
              loading={jobs.loading}
              error={jobs.error}
              data={jobs.data}
              onRetry={jobs.reload}
              isEmpty={(jobs.data?.items ?? []).length === 0}
              emptyTitle="No export jobs yet"
              emptyDescription="Generate a report to create the first export job."
              skeleton={<TableSkeleton rows={6} columns={6} />}
            >
              <Table>
                <thead>
                  <tr>
                    <Th>File</Th>
                    <Th className="w-28">Scope</Th>
                    <Th className="w-24">Format</Th>
                    <Th className="w-32">Status</Th>
                    <Th className="w-24 text-right">Rows</Th>
                    <Th className="w-40">Created</Th>
                    <Th className="w-28">Download</Th>
                  </tr>
                </thead>
                <tbody>
                  {(jobs.data?.items ?? []).map((job) => (
                    <tr key={job.id}>
                      <Td>
                        <p className="font-medium text-content">{job.file_name ?? job.id}</p>
                        {job.error ? (
                          <p className="max-w-xs truncate text-xs text-danger" title={job.error}>
                            {job.error}
                          </p>
                        ) : null}
                      </Td>
                      <Td className="text-xs">{job.scope ?? "—"}</Td>
                      <Td>
                        <Badge tone="neutral">{job.format}</Badge>
                      </Td>
                      <Td>
                        <StatusBadge status={job.status} />
                      </Td>
                      <Td className="text-right tabular-nums">{formatNumber(job.row_count)}</Td>
                      <Td className="text-xs text-content-muted">{formatDateTime(job.created_at)}</Td>
                      <Td>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={job.status !== "COMPLETED"}
                          onClick={() => download(job)}
                          title={
                            job.status !== "COMPLETED"
                              ? "The export is not finished yet"
                              : "Download the generated file"
                          }
                        >
                          Download
                        </Button>
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
              {jobs.data ? (
                <Pagination
                  page={jobs.data.page}
                  pages={jobs.data.pages}
                  total={jobs.data.total}
                  onPageChange={setPage}
                />
              ) : null}
            </AsyncSection>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
