"use client";

import * as React from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
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
import { formatDateTime, formatNumber, humanize } from "@/lib/format";
import { CATEGORY_LABELS } from "@/lib/constants";
import { PageHeader } from "@/components/PageHeader";
import { AsyncSection, TableSkeleton } from "@/components/States";
import { websiteStatusLabel } from "@/lib/websites";

const PAGE_SIZE = 20;

export default function ReportsPage() {
  /* The search parameters are read inside a Suspense boundary - Next.js
   * renders the page on the server first. */
  return (
    <React.Suspense
      fallback={
        <Card>
          <CardBody className="py-8 text-center text-sm text-content-muted">Loading…</CardBody>
        </Card>
      }
    >
      <ReportsView />
    </React.Suspense>
  );
}

function ReportsView() {
  const toast = useToast();
  const action = useAction();
  const searchParams = useSearchParams();

  /* The project of the URL preselects the scope of the report - the detail
   * page of a project links here with `/reports?project_id=<id>`. */
  const requestedProjectId = searchParams.get("project_id") ?? "";

  const [page, setPage] = React.useState(1);
  const [projectId, setProjectId] = React.useState(requestedProjectId);
  const [scope, setScope] = React.useState(requestedProjectId ? "project" : "workspace");
  const [format, setFormat] = React.useState<"xlsx" | "csv">("xlsx");

  /* The project the per website statistics are filtered by. */
  const [statsProjectId, setStatsProjectId] = React.useState(requestedProjectId);

  React.useEffect(() => {
    if (!requestedProjectId) return;
    setScope("project");
    setProjectId(requestedProjectId);
    setStatsProjectId(requestedProjectId);
  }, [requestedProjectId]);

  const projects = useResource(() => api.projects.list(apiClient, { page: 1, page_size: 100 }), []);
  const jobs = useResource(
    () => api.reports.list(apiClient, { page, page_size: PAGE_SIZE }),
    [page],
  );
  const stats = useResource(
    () => api.websites.stats(apiClient, statsProjectId || undefined),
    [statsProjectId],
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

  const statsRows = stats.data ?? [];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Reports"
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
              {requestedProjectId ? (
                <p className="text-xs text-content-subtle">
                  The scope comes from the link you opened - the report covers that project
                  only.
                </p>
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

      <Card>
        <CardHeader
          title="Per website"
          description="How many submissions succeeded per website"
          action={
            <Select
              className="w-52"
              value={statsProjectId}
              onChange={(event) => setStatsProjectId(event.target.value)}
              aria-label="Project of the statistics"
            >
              <option value="">All projects</option>
              {(projects.data?.items ?? []).map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </Select>
          }
        />
        <CardBody className="p-0">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line p-3">
            <p className="text-xs text-content-muted">
              To retry failed websites, open My projects → project → Restart failed.
            </p>
            <Link
              href="/projects"
              className="inline-flex h-8 items-center rounded-md border border-line-strong bg-surface px-2.5 text-xs font-medium text-content transition-colors hover:bg-surface-raised"
            >
              Open My projects
            </Link>
          </div>

          <AsyncSection
            loading={stats.loading}
            error={stats.error}
            data={stats.data}
            onRetry={stats.reload}
            isEmpty={statsRows.length === 0}
            emptyTitle="No website statistics yet"
            emptyDescription="As soon as submissions run, every website of the list is listed here with its counters."
            skeleton={<TableSkeleton rows={6} columns={8} />}
          >
            <Table>
              <thead>
                <tr>
                  <Th>Website</Th>
                  <Th className="w-48">Category</Th>
                  <Th className="w-36">Status</Th>
                  <Th className="w-24 text-right">Opportunities</Th>
                  <Th className="w-24 text-right">Submitted</Th>
                  <Th className="w-24 text-right">Verified</Th>
                  <Th className="w-24 text-right">Failed</Th>
                  <Th className="w-24 text-right">Pending</Th>
                  <Th className="w-40">Last attempt</Th>
                </tr>
              </thead>
              <tbody>
                {statsRows.map((row) => (
                  <tr key={`${row.domain}-${row.name}`}>
                    <Td>
                      <p className="font-medium text-content">{row.name || row.domain}</p>
                      <p className="max-w-xs truncate text-xs text-content-muted">{row.domain}</p>
                    </Td>
                    <Td>
                      <Badge tone="neutral">
                        {CATEGORY_LABELS[row.category] ?? humanize(row.category)}
                      </Badge>
                    </Td>
                    <Td className="text-xs">{websiteStatusLabel(row.status)}</Td>
                    <Td className="text-right tabular-nums">
                      {formatNumber(row.opportunities)}
                    </Td>
                    <Td className="text-right tabular-nums">{formatNumber(row.submitted)}</Td>
                    <Td className="text-right tabular-nums">{formatNumber(row.verified)}</Td>
                    <Td className="text-right tabular-nums">
                      {row.failed > 0 ? (
                        <span className="font-semibold text-danger">{formatNumber(row.failed)}</span>
                      ) : (
                        formatNumber(row.failed)
                      )}
                    </Td>
                    <Td className="text-right tabular-nums">{formatNumber(row.pending)}</Td>
                    <Td className="text-xs text-content-muted">
                      {formatDateTime(row.last_attempt_at)}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </AsyncSection>
        </CardBody>
      </Card>
    </div>
  );
}
