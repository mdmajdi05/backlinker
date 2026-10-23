"use client";

import * as React from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
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
import { AddToProjectDialog } from "@/components/AddToProjectDialog";
import { WebsiteListPanel } from "@/components/WebsiteListPanel";
import { CampaignPanel } from "@/components/CampaignPanel";

/**
 * One project, one screen.
 *
 * The campaign is the primary view: add websites, press start and watch the
 * live table.  Everything that is only needed once in a while - the full
 * website fields, the auto pilot and the execution settings - lives in the
 * "Advanced" section further down, so the page stays understandable without
 * hiding a feature.
 */
export default function ProjectDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const projectId = params.id;
  const [addOpen, setAddOpen] = React.useState(false);
  /* Bumped after the website picker added rows, so the campaign shows them
     immediately instead of waiting for its next refresh. */
  const [campaignReload, setCampaignReload] = React.useState(0);

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
        skeleton={<CardSkeleton count={3} />}
      >
        {data ? (
          <>
            <CampaignPanel
              projectId={projectId}
              onChanged={project.reload}
              onPickFromList={() => setAddOpen(true)}
              onOpenReport={() => router.push(`/reports?project_id=${projectId}`)}
              reloadToken={campaignReload}
            />

            <details className="rounded-lg border border-line bg-surface">
              <summary className="cursor-pointer list-none px-4 py-3">
                <span className="text-sm font-semibold text-content">
                  Advanced: website fields, auto pilot and execution settings
                </span>
                <span className="ml-2 text-xs font-normal text-content-muted">
                  Optional - the campaign above works without it.
                </span>
              </summary>
              <div className="space-y-4 border-t border-line p-4">
                <Card>
                  <CardHeader
                    title="Auto pilot"
                    description="Queue the approved websites of this project automatically"
                  />
                  <CardBody>
                    <AutoPilotPanel projectId={projectId} projectName={data.name} />
                  </CardBody>
                </Card>

                <div className="space-y-2">
                  <h2 className="text-sm font-semibold text-content">
                    Websites of this project - every field
                  </h2>
                  <p className="text-xs text-content-muted">
                    The websites of the central list that this project works on. Use this
                    table to edit the category, the notes and the status of a site or to
                    delete it. Deleting a site moves it to the recycle bin.
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

                <Card>
                  <CardHeader
                    title="Project statistics"
                    description="The counters of the project over every website"
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
                          <dd className="text-content">
                            {formatDateTime(metrics.data.generated_at)}
                          </dd>
                        </div>
                        <div>
                          <dt className="text-content-muted">Awaiting retry</dt>
                          <dd className="text-content">
                            {formatNumber(metrics.data.awaiting_retry)}
                          </dd>
                        </div>
                        <div>
                          <dt className="text-content-muted">Requiring verification</dt>
                          <dd className="text-content">
                            {formatNumber(metrics.data.requiring_verification)}
                          </dd>
                        </div>
                        <div>
                          <dt className="text-content-muted">Published</dt>
                          <dd className="text-content">
                            {formatNumber(metrics.data.published)}
                          </dd>
                        </div>
                        <div>
                          <dt className="text-content-muted">Pending manual</dt>
                          <dd className="text-content">
                            {formatNumber(metrics.data.pending_manual)}
                          </dd>
                        </div>
                        <div>
                          <dt className="text-content-muted">Cloud workers</dt>
                          <dd className="text-content">
                            {formatNumber(metrics.data.cloud_workers)}
                          </dd>
                        </div>
                      </dl>
                    ) : (
                      <p className="text-xs text-content-subtle">No statistics available.</p>
                    )}
                  </CardBody>
                </Card>

                <p className="text-xs text-content-muted">
                  Verified links are never submitted again. Use Opportunity import to bring
                  a report back in - verified rows are skipped, failed rows are retried.
                </p>
              </div>
            </details>
          </>
        ) : null}
      </AsyncSection>

      <AddToProjectDialog
        projectId={projectId}
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onChanged={() => {
          project.reload();
          setCampaignReload((value) => value + 1);
        }}
      />
    </div>
  );
}
