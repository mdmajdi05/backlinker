"use client";

import * as React from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { api } from "@autobacklinker/api-client";
import type { Project } from "@autobacklinker/shared-types";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  MetricTile,
  Skeleton,
  StatusBadge,
} from "@autobacklinker/ui";
import { apiClient, isNotFoundError } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { formatDateTime, formatNumber } from "@/lib/format";
import { PageHeader } from "@/components/PageHeader";
import { AsyncSection, CardSkeleton, ErrorPanel } from "@/components/States";
import { ProjectSettingsForm } from "@/components/ProjectSettingsForm";
import { AutoPilotPanel } from "@/components/AutoPilotPanel";
import { AddToProjectDialog } from "@/components/AddToProjectDialog";
import { WebsiteListPanel } from "@/components/WebsiteListPanel";

export default function ProjectDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const projectId = params.id;
  const [addOpen, setAddOpen] = React.useState(false);

  const project = useResource(() => api.projects.get(apiClient, projectId), [projectId]);
  const settings = useResource(
    () => api.projects.settings(apiClient, projectId),
    [projectId],
  );
  const metrics = useResource(
    () => api.dashboard.metrics(apiClient, projectId),
    [projectId],
  );
  /* The report of the project: one row per website of the project. */
  const report = useResource(() => api.websites.stats(apiClient, projectId), [projectId]);

  const data: Project | null = project.data;

  /* The websites that failed come first - they are the ones to work on. */
  const reportRows = React.useMemo(() => {
    const rows = [...(report.data ?? [])];
    rows.sort((a, b) => {
      if (b.failed !== a.failed) return b.failed - a.failed;
      if (b.opportunities !== a.opportunities) return b.opportunities - a.opportunities;
      return (a.domain ?? "").localeCompare(b.domain ?? "");
    });
    return rows;
  }, [report.data]);

  /* The counters of the project - the sum of the rows of the report. */
  const totals = React.useMemo(() => {
    const sum = { opportunities: 0, submitted: 0, verified: 0, failed: 0, pending: 0 };
    for (const row of reportRows) {
      sum.opportunities += row.opportunities;
      sum.submitted += row.submitted;
      sum.verified += row.verified;
      sum.failed += row.failed;
      sum.pending += row.pending;
    }
    return sum;
  }, [reportRows]);

  const reportUnavailable = Boolean(report.error) && isNotFoundError(report.error);

  return (
    <div className="space-y-4">
      <PageHeader
        title={data?.name ?? "Project"}
        description={
          data ? (
            <span className="flex flex-wrap items-center gap-2">
              <StatusBadge status={data.status} />
              <a
                href={data.target_website}
                target="_blank"
                rel="noopener noreferrer"
                className="text-accent hover:underline"
              >
                {data.target_website}
              </a>
              <Badge tone="neutral">v{data.version}</Badge>
            </span>
          ) : (
            "Project details"
          )
        }
        actions={
          <>
            <Link href="/projects">
              <Button variant="outline" size="sm">
                Back to projects
              </Button>
            </Link>
            <Button variant="outline" size="sm" onClick={project.reload} loading={project.refreshing}>
              Refresh
            </Button>
          </>
        }
      />

      {project.error && !data ? (
        <ErrorPanel error={project.error} onRetry={project.reload} title="Could not load project" />
      ) : null}

      <AsyncSection
        loading={project.loading}
        error={project.error}
        data={data}
        onRetry={project.reload}
        skeleton={<CardSkeleton count={4} />}
      >
        {data ? (
          <>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <MetricTile
                label="Opportunities"
                value={formatNumber(data.counts?.opportunities)}
              />
              <MetricTile label="Approved" value={formatNumber(data.counts?.approved)} />
              <MetricTile label="Queued" value={formatNumber(data.counts?.queued)} />
              <MetricTile label="Running" value={formatNumber(data.counts?.running)} />
              <MetricTile label="Completed" value={formatNumber(data.counts?.completed)} />
              <MetricTile label="Failed" value={formatNumber(data.counts?.failed)} />
              <MetricTile label="Verified live" value={formatNumber(data.counts?.verified_live)} />
              <MetricTile label="Pending manual" value={formatNumber(data.counts?.pending_manual)} />
            </div>

            <Card>
              <CardHeader
                title="Project statistics"
                description="Live counters for this project"
              />
              <CardBody>
                {metrics.loading && !metrics.data ? (
                  <p className="text-xs text-content-subtle">Loading metrics…</p>
                ) : metrics.error ? (
                  <ErrorPanel error={metrics.error} onRetry={metrics.reload} />
                ) : metrics.data ? (
                  <dl className="grid gap-x-6 gap-y-2 text-xs sm:grid-cols-3">
                    <div>
                      <dt className="text-content-muted">Generated at</dt>
                      <dd className="text-content">{formatDateTime(metrics.data.generated_at)}</dd>
                    </div>
                    <div>
                      <dt className="text-content-muted">Awaiting retry</dt>
                      <dd className="text-content">{formatNumber(metrics.data.awaiting_retry)}</dd>
                    </div>
                    <div>
                      <dt className="text-content-muted">Requiring verification</dt>
                      <dd className="text-content">
                        {formatNumber(metrics.data.requiring_verification)}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-content-muted">Published</dt>
                      <dd className="text-content">{formatNumber(metrics.data.published)}</dd>
                    </div>
                    <div>
                      <dt className="text-content-muted">Pending manual</dt>
                      <dd className="text-content">{formatNumber(metrics.data.pending_manual)}</dd>
                    </div>
                    <div>
                      <dt className="text-content-muted">Cloud workers</dt>
                      <dd className="text-content">{formatNumber(metrics.data.cloud_workers)}</dd>
                    </div>
                  </dl>
                ) : (
                  <p className="text-xs text-content-subtle">No statistics available.</p>
                )}
              </CardBody>
            </Card>

            <Card>
              <CardHeader
                title="Report & results"
                description="What happened in this project - the totals of every website"
                action={
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => router.push(`/reports?project_id=${projectId}`)}
                  >
                    Open the full report
                  </Button>
                }
              />
              <CardBody className="space-y-4">
                {report.loading && !report.data ? (
                  <div
                    className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5"
                    aria-busy="true"
                    aria-live="polite"
                  >
                    <span className="sr-only">Loading the report…</span>
                    {Array.from({ length: 5 }).map((_, index) => (
                      <Skeleton key={index} className="h-14 w-full" />
                    ))}
                  </div>
                ) : report.error ? (
                  reportUnavailable ? (
                    <Alert
                      tone="neutral"
                      title="The per website statistics are not available yet"
                      action={
                        <Button variant="outline" size="sm" onClick={report.reload}>
                          Try again
                        </Button>
                      }
                    >
                      The backend answered 404 for{" "}
                      <code className="font-mono text-[11px]">GET /api/v1/websites/stats</code>.
                      The report of the project can not be shown until the endpoint exists - the
                      counters above stay correct.
                    </Alert>
                  ) : (
                    <ErrorPanel
                      error={report.error}
                      onRetry={report.reload}
                      title="The report could not be loaded"
                    />
                  )
                ) : (
                  <>
                    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                      <MetricTile
                        label="Opportunities"
                        value={formatNumber(totals.opportunities)}
                      />
                      <MetricTile label="Submitted" value={formatNumber(totals.submitted)} />
                      <MetricTile label="Verified" value={formatNumber(totals.verified)} />
                      <MetricTile label="Failed" value={formatNumber(totals.failed)} />
                      <MetricTile label="Pending" value={formatNumber(totals.pending)} />
                    </div>

                    <p className="text-xs text-content-muted">
                      Every website of this project is listed below with its own counters -
                      one table, always the same numbers. The full report adds the exports.
                    </p>
                  </>
                )}

                <p className="border-t border-line pt-3 text-xs text-content-muted">
                  Verified links are never submitted again. Use Opportunity import to bring a
                  report back in - verified rows are skipped, failed rows are retried.
                </p>
              </CardBody>
            </Card>

            <Card>
              <CardHeader
                title="Add from website list"
                description="Pick the websites of the central list for this project"
              />
              <CardBody>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <p className="max-w-xl text-xs text-content-muted">
                    The central list holds every website you know - added by hand or imported
                    from a spreadsheet. Choose the sites this project should work on, filter
                    them by category or niche and link them in one step. The anchor text and
                    the target landing page of the project are filled in and stay editable.
                  </p>
                  <Button size="sm" onClick={() => setAddOpen(true)}>
                    Add from website list
                  </Button>
                </div>
              </CardBody>
            </Card>

            <Card>
              <CardHeader
                title="Auto pilot"
                description="Automatic submission for the websites of this project"
              />
              <CardBody>
                <AutoPilotPanel projectId={projectId} projectName={data.name} />
              </CardBody>
            </Card>

            <div className="space-y-2">
              <h2 className="text-sm font-semibold text-content">Websites of this project</h2>
              <p className="text-xs text-content-muted">
                The websites of the central list that this project works on - with the
                counters of the submissions. Mark a site that stopped working here, it keeps
                its place in the central list.
              </p>
              <WebsiteListPanel
                projectId={projectId}
                showProjectFilter={false}
                onChanged={project.reload}
              />
            </div>

            <Card>
              <CardHeader
                title="Execution settings"
                description="Concurrency, retries, schedule and verification cadence"
              />
              <CardBody>
                {settings.loading && !settings.data ? (
                  <p className="text-xs text-content-subtle">Loading settings…</p>
                ) : settings.error ? (
                  <ErrorPanel error={settings.error} onRetry={settings.reload} />
                ) : (
                  <ProjectSettingsForm
                    projectId={projectId}
                    settings={settings.data ?? data.settings ?? null}
                  />
                )}
              </CardBody>
            </Card>
          </>
        ) : null}
      </AsyncSection>

      <AddToProjectDialog
        projectId={projectId}
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onChanged={project.reload}
      />
    </div>
  );
}
