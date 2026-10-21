"use client";

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api } from "@autobacklinker/api-client";
import type { Project } from "@autobacklinker/shared-types";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  MetricTile,
  StatusBadge,
} from "@autobacklinker/ui";
import { apiClient } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { formatDateTime, formatNumber } from "@/lib/format";
import { PageHeader } from "@/components/PageHeader";
import { AsyncSection, CardSkeleton, ErrorPanel } from "@/components/States";
import { ProjectSettingsForm } from "@/components/ProjectSettingsForm";
import { AutoPilotPanel } from "@/components/AutoPilotPanel";

export default function ProjectDetailPage() {
  const params = useParams<{ id: string }>();
  const projectId = params.id;

  const project = useResource(() => api.projects.get(apiClient, projectId), [projectId]);
  const settings = useResource(
    () => api.projects.settings(apiClient, projectId),
    [projectId],
  );
  const metrics = useResource(
    () => api.dashboard.metrics(apiClient, projectId),
    [projectId],
  );

  const data: Project | null = project.data;

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
                title="Auto pilot"
                description="Automatic submission for the websites of this project"
              />
              <CardBody>
                <AutoPilotPanel projectId={projectId} projectName={data.name} />
              </CardBody>
            </Card>

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
    </div>
  );
}
