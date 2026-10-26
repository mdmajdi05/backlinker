"use client";

import * as React from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { api } from "@autobacklinker/api-client";
import type { BacklinkDetails, Project } from "@autobacklinker/shared-types";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  MetricTile,
  StatusBadge,
} from "@autobacklinker/ui";
import { apiClient, errorMessage } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { formatDateTime, formatNumber, humanize } from "@/lib/format";
import { PageHeader } from "@/components/PageHeader";
import { AsyncSection, CardSkeleton, ErrorPanel } from "@/components/States";
import { AutoPilotPanel } from "@/components/AutoPilotPanel";
import { AddToProjectDialog } from "@/components/AddToProjectDialog";
import { WebsiteListPanel } from "@/components/WebsiteListPanel";
import { CampaignPanel } from "@/components/CampaignPanel";
import { GoogleLoginCard } from "@/components/GoogleLoginCard";
import { ProjectEditDialog } from "@/components/ProjectEditDialog";

/**
 * One project, one screen.
 *
 * The campaign is the primary view: add websites, press start and watch the
 * live table.  Everything that is only needed once in a while - the full
 * website fields, the auto pilot and the statistics - lives in the "More
 * tools" section further down, so the page stays understandable without
 * hiding a feature.
 */
export default function ProjectDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const projectId = params.id;
  const [addOpen, setAddOpen] = React.useState(false);
  const [editOpen, setEditOpen] = React.useState(false);
  /* Bumped after the website picker added rows, so the campaign shows them
     immediately instead of waiting for its next refresh. */
  const [campaignReload, setCampaignReload] = React.useState(0);

  const project = useResource(() => api.projects.get(apiClient, projectId), [projectId]);
  const details = useResource(
    () => api.projects.details(apiClient, projectId),
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
            <Button
              size="sm"
              disabled={!data}
              onClick={() => setAddOpen(true)}
            >
              Add backlink websites
            </Button>
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
            <GoogleLoginCard
              projectId={projectId}
              login={data.login}
              onChanged={() => {
                project.reload();
                setCampaignReload((value) => value + 1);
              }}
            />

            <Card>
              <CardHeader
                title="1. Project details"
                description="This project keeps its own company details. Every website below reuses them - nothing is asked twice."
                action={
                  <Button size="sm" variant="outline" onClick={() => setEditOpen(true)}>
                    Edit details
                  </Button>
                }
              />
              <CardBody className="space-y-3">
                {details.error ? (
                  <Alert tone="warning" title="The project details could not be loaded">
                    {errorMessage(details.error)}
                  </Alert>
                ) : null}
                {details.data ? (
                  <>
                    <dl className="grid gap-3 text-xs sm:grid-cols-2 lg:grid-cols-4">
                      {[
                        ["Company", details.data.company_name],
                        ["Website", details.data.website || data.target_website],
                        ["E-mail", details.data.email],
                        ["Phone", details.data.phone],
                        ["City", details.data.city],
                        ["State / region", details.data.state],
                        ["Country", details.data.country],
                        ["Anchors", details.data.anchors.join(", ")],
                      ].map(([label, value]) => (
                        <div key={label} className="rounded-md border border-line px-3 py-2">
                          <dt className="text-[10px] uppercase tracking-wider text-content-subtle">
                            {label}
                          </dt>
                          <dd className="truncate text-content" title={value || "Not filled"}>
                            {value || <span className="text-warning">Not filled</span>}
                          </dd>
                        </div>
                      ))}
                    </dl>
                    {details.data.required.length > 0 ? (
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="text-[11px] text-content-muted">
                          {details.data.filled.length} of {details.data.required.length} values
                          the selected websites ask for are ready.
                        </p>
                        {details.data.missing.length > 0 ? (
                          <p className="text-[11px] text-warning">
                            Missing: {details.data.missing.map(humanize).join(", ")}
                          </p>
                        ) : (
                          <p className="text-[11px] text-success">
                            Every required value is ready.
                          </p>
                        )}
                      </div>
                    ) : (
                      <p className="text-[11px] text-content-muted">
                        Use Add backlink websites above and this card shows exactly which
                        details they ask for.
                      </p>
                    )}
                    {details.data.notes.map((note) => (
                      <p key={note} className="text-[11px] text-content-subtle">
                        {note}
                      </p>
                    ))}
                  </>
                ) : (
                  <p className="text-xs text-content-subtle">Loading project details…</p>
                )}
              </CardBody>
            </Card>

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
                  More tools (optional): auto pilot, website fields and statistics
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
                  Verified links are never submitted again. Use{" "}
                  <span className="font-medium text-content">Import old report</span> to bring
                  a report back in - verified rows are skipped, failed rows are retried.
                </p>
              </div>
            </details>
          </>
        ) : null}
      </AsyncSection>

      <ProjectEditDialog
        open={editOpen}
        project={data}
        onClose={() => setEditOpen(false)}
        onSaved={() => {
          project.reload();
          details.reload();
        }}
      />

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
