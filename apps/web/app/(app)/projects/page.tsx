"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api } from "@autobacklinker/api-client";
import type { Project, ProjectCounts, ProjectLogin } from "@autobacklinker/shared-types";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  Dialog,
  Pagination,
  Skeleton,
  StatusBadge,
  Table,
  Td,
  Th,
  Tooltip,
  useToast,
} from "@autobacklinker/ui";
import { apiClient, errorMessage } from "@/lib/api";
import { useAction, useResource } from "@/lib/hooks";
import { formatDateTime, formatNumber } from "@/lib/format";
import { PageHeader } from "@/components/PageHeader";
import { AsyncSection, TableSkeleton } from "@/components/States";
import { ProjectWizard } from "@/components/ProjectWizard";
import { ProjectEditDialog } from "@/components/ProjectEditDialog";
import { ConfirmDialog } from "@/components/ConfirmDialog";

const PAGE_SIZE = 20;
const VIEW_KEY = "autobacklinker.projects.view";
type ProjectView = "cards" | "list";

function readView(): ProjectView {
  try {
    return window.localStorage.getItem(VIEW_KEY) === "list" ? "list" : "cards";
  } catch {
    return "cards";
  }
}

function googleState(login: ProjectLogin | null | undefined) {
  switch (login?.status) {
    case "CONNECTED":
      return {
        label: login.email ? `Google: connected (${login.email})` : "Google: connected",
        tone: "success" as const,
      };
    case "EXPIRED":
      return { label: "Google: login expired", tone: "warning" as const };
    case "LOGIN_OPEN":
      return { label: "Google: login window open", tone: "info" as const };
    case "ERROR":
      return { label: "Google: error", tone: "danger" as const };
    default:
      return { label: "Google: not connected", tone: "neutral" as const };
  }
}

export default function ProjectsPage() {
  const toast = useToast();
  const router = useRouter();
  const deleteAction = useAction();
  const [page, setPage] = React.useState(1);
  // Always start with the default so the server and the first client render
  // agree; the stored preference is applied after hydration.
  const [view, setView] = React.useState<ProjectView>("cards");
  React.useEffect(() => {
    setView(readView());
  }, []);
  const chooseView = (next: ProjectView) => {
    setView(next);
    try {
      window.localStorage.setItem(VIEW_KEY, next);
    } catch {
      // The view still changes for this session.
    }
  };
  const [wizardOpen, setWizardOpen] = React.useState(false);
  const [editTarget, setEditTarget] = React.useState<Project | null>(null);
  const [deleteTarget, setDeleteTarget] = React.useState<Project | null>(null);

  const projects = useResource(
    () => api.projects.list(apiClient, { page, page_size: PAGE_SIZE }),
    [page],
  );

  const rows = projects.data?.items ?? [];

  /* The list of the backend does not carry the counters - they come from the
   * detail of every project of the page.  A counter that could not be loaded
   * stays empty, it is never made up. */
  const details = useResource(
    async () =>
      Promise.all(
        (projects.data?.items ?? []).map(async (row) => {
          try {
            const project = await api.projects.get(apiClient, row.id);
            return {
              id: row.id,
              counts: project.counts ?? null,
              login: project.login ?? null,
              failed: false,
            };
          } catch {
            return { id: row.id, counts: null, login: null, failed: true };
          }
        }),
      ),
    [projects.data],
  );

  const countsById = React.useMemo(() => {
    const map: Record<string, ProjectCounts | null> = {};
    for (const entry of details.data ?? []) map[entry.id] = entry.counts;
    return map;
  }, [details.data]);

  const failedIds = React.useMemo(
    () => (details.data ?? []).filter((entry) => entry.failed).map((entry) => entry.id),
    [details.data],
  );

  const loginById = React.useMemo(() => {
    const map: Record<string, ProjectLogin | null> = {};
    for (const entry of details.data ?? []) map[entry.id] = entry.login;
    return map;
  }, [details.data]);

  const remove = async () => {
    if (!deleteTarget) return;
    const outcome = await deleteAction.run(() => api.projects.remove(apiClient, deleteTarget.id));
    if (outcome.ok) {
      toast.push(`Project "${deleteTarget.name}" moved to the recycle bin`, "success");
      setDeleteTarget(null);
      projects.reload();
    }
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="My projects"
        description="Open a project to add its backlink websites, press Start and see the report."
        actions={
          <>
            <div
              className="flex items-center rounded-md border border-line p-0.5"
              role="group"
              aria-label="Project view"
            >
              <Button
                size="sm"
                variant={view === "cards" ? "primary" : "ghost"}
                aria-pressed={view === "cards"}
                onClick={() => chooseView("cards")}
              >
                Cards
              </Button>
              <Button
                size="sm"
                variant={view === "list" ? "primary" : "ghost"}
                aria-pressed={view === "list"}
                onClick={() => chooseView("list")}
              >
                List
              </Button>
            </div>
            <Button size="sm" onClick={() => setWizardOpen(true)}>
              New project
            </Button>
          </>
        }
      />

      <Card>
        <CardBody className="p-0">
          <AsyncSection
            loading={projects.loading}
            error={projects.error}
            data={projects.data}
            onRetry={projects.reload}
            isEmpty={rows.length === 0}
            emptyTitle="No projects yet"
            emptyDescription="A project owns its website details, its backlink websites and its report. Create the first one to start."
            emptyAction={
              <Button size="sm" onClick={() => setWizardOpen(true)}>
                Create project
              </Button>
            }
            skeleton={<TableSkeleton rows={6} columns={6} />}
          >
            {view === "cards" ? (
              <>
              <div className="grid gap-3 p-3 md:grid-cols-2 xl:grid-cols-3">
                {rows.map((project: Project) => {
                  const counts = countsById[project.id];
                  const countersLoading = details.loading && !details.data;
                  const google =
                    countersLoading && loginById[project.id] === undefined
                      ? { label: "Google: checking…", tone: "neutral" as const }
                      : failedIds.includes(project.id)
                        ? { label: "Google: unknown", tone: "neutral" as const }
                        : googleState(loginById[project.id]);
                  return (
                    <Card key={project.id} className="h-full shadow-none">
                      <CardBody className="flex h-full flex-col gap-3">
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <Link
                              href={`/projects/${project.id}`}
                              className="block truncate text-sm font-semibold text-content hover:text-accent"
                            >
                              {project.name}
                            </Link>
                            <p
                              className="truncate text-[11px] text-content-subtle"
                              title={project.target_website}
                            >
                              {project.target_website}
                            </p>
                          </div>
                          <StatusBadge status={project.status} />
                        </div>

                        <p className="line-clamp-2 min-h-[2rem] text-xs text-content-muted">
                          {project.description || "No description yet."}
                        </p>

                        <div className="flex flex-wrap items-center gap-1.5">
                          <Badge tone={google.tone}>{google.label}</Badge>
                          {loginById[project.id]?.paused_tasks ? (
                            <Badge tone="warning">
                              {loginById[project.id]?.paused_tasks} paused
                            </Badge>
                          ) : null}
                          {countersLoading ? (
                            <Skeleton className="h-4 w-16" />
                          ) : null}
                        </div>

                        <div className="grid grid-cols-4 gap-2 rounded-md border border-line px-3 py-2 text-center">
                          {[
                            ["Sites", counts?.opportunities],
                            ["Queued", counts?.queued],
                            ["Verified", counts?.verified_live],
                            ["Failed", counts?.failed],
                          ].map(([label, value]) => (
                            <div key={String(label)}>
                              <p className="text-[10px] uppercase tracking-wide text-content-subtle">
                                {label}
                              </p>
                              <p className="text-sm font-semibold tabular-nums text-content">
                                {formatNumber(value as number | undefined)}
                              </p>
                            </div>
                          ))}
                        </div>

                        <p className="text-[10px] text-content-subtle">
                          Updated {formatDateTime(project.updated_at)}
                        </p>

                        <div className="mt-auto flex flex-wrap items-center gap-2">
                          <Link
                            href={`/projects/${project.id}`}
                            aria-label={`Open the project ${project.name}`}
                            className="inline-flex h-8 items-center justify-center rounded-md bg-accent px-2.5 text-xs font-medium text-accent-fg shadow-sm transition-colors hover:bg-accent-hover"
                          >
                            Open
                          </Link>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => setEditTarget(project)}
                          >
                            Edit
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="text-danger hover:bg-danger-soft"
                            onClick={() => {
                              deleteAction.reset();
                              setDeleteTarget(project);
                            }}
                          >
                            Delete
                          </Button>
                        </div>
                      </CardBody>
                    </Card>
                  );
                })}
              </div>
              {projects.data ? (
                <Pagination
                  page={projects.data.page}
                  pages={projects.data.pages}
                  total={projects.data.total}
                  onPageChange={setPage}
                />
              ) : null}
              </>
            ) : (
              <>
            <Table>
              <thead>
                <tr>
                  <Th>Name</Th>
                  <Th>Target website</Th>
                  <Th>Status</Th>
                  <Th className="text-right">Websites</Th>
                  <Th className="text-right">Queued</Th>
                  <Th className="text-right">Verified</Th>
                  <Th className="text-right">Failed</Th>
                  <Th className="w-44">Updated</Th>
                  <Th className="w-44 text-right">Actions</Th>
                </tr>
              </thead>
              <tbody>
                {rows.map((project: Project) => {
                  const counts = countsById[project.id];
                  const countersLoading = details.loading && !details.data;
                  return (
                    <tr key={project.id}>
                      <Td>
                        <Link
                          href={`/projects/${project.id}`}
                          className="font-medium text-accent hover:underline"
                        >
                          {project.name}
                        </Link>
                        {project.description ? (
                          <p className="mt-0.5 max-w-md truncate text-xs text-content-muted">
                            {project.description}
                          </p>
                        ) : null}
                      </Td>
                      <Td className="text-xs">
                        <a
                          href={project.target_website}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-accent hover:underline"
                        >
                          {project.target_website}
                        </a>
                      </Td>
                      <Td>
                        <StatusBadge status={project.status} />
                      </Td>
                      <Td className="text-right tabular-nums">
                        <Counter value={counts?.opportunities} loading={countersLoading} />
                      </Td>
                      <Td className="text-right tabular-nums">
                        <Counter value={counts?.queued} loading={countersLoading} />
                      </Td>
                      <Td className="text-right tabular-nums">
                        <Counter value={counts?.verified_live} loading={countersLoading} />
                      </Td>
                      <Td className="text-right tabular-nums">
                        {counts && counts.failed > 0 ? (
                          <span className="font-semibold text-danger">
                            {formatNumber(counts.failed)}
                          </span>
                        ) : (
                          <Counter value={counts?.failed} loading={countersLoading} />
                        )}
                      </Td>
                      <Td className="whitespace-nowrap text-xs text-content-muted">
                        {formatDateTime(project.updated_at)}
                      </Td>
                      <Td>
                        <div className="flex items-center justify-end gap-1">
                          <Link
                            href={`/projects/${project.id}`}
                            aria-label={`Open the project ${project.name}`}
                            className="inline-flex h-8 items-center justify-center rounded-md bg-accent px-2.5 text-xs font-medium text-accent-fg shadow-sm transition-colors hover:bg-accent-hover"
                          >
                            Open
                          </Link>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => setEditTarget(project)}
                            aria-label={`Edit the project ${project.name}`}
                          >
                            Edit
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="text-danger hover:bg-danger-soft"
                            onClick={() => {
                              deleteAction.reset();
                              setDeleteTarget(project);
                            }}
                            aria-label={`Delete the project ${project.name}`}
                          >
                            Delete
                          </Button>
                        </div>
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
            {projects.data ? (
              <Pagination
                page={projects.data.page}
                pages={projects.data.pages}
                total={projects.data.total}
                onPageChange={setPage}
              />
            ) : null}
              </>
            )}
          </AsyncSection>
        </CardBody>
      </Card>

      {failedIds.length > 0 ? (
        <Alert
          tone="warning"
          title="The counters of some projects could not be loaded"
          action={
            <Button variant="outline" size="sm" onClick={details.reload}>
              Try again
            </Button>
          }
        >
          The backend did not answer for {failedIds.length} project(s) - their numbers stay
          empty instead of showing a wrong count.
        </Alert>
      ) : null}

      <Dialog
        open={wizardOpen}
        onClose={() => setWizardOpen(false)}
        title="Create project"
        description="Three steps: the project, its company details and optional landing pages."
        width="lg"
      >
        <ProjectWizard
          onCancel={() => setWizardOpen(false)}
          onCreated={(project) => {
            setWizardOpen(false);
            projects.reload();
            toast.push(`Project "${project.name}" created`, "success");
            router.push(`/projects/${project.id}`);
          }}
        />
      </Dialog>

      <ProjectEditDialog
        open={Boolean(editTarget)}
        project={editTarget}
        onClose={() => setEditTarget(null)}
        onSaved={() => {
          projects.reload();
        }}
      />

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title={`Move "${deleteTarget?.name ?? "the project"}" to the recycle bin?`}
        description="The project leaves the lists - you can restore it from the recycle bin at any time."
        confirmLabel="Move to the recycle bin"
        cancelLabel="Keep the project"
        destructive
        pending={deleteAction.pending}
        onConfirm={() => void remove()}
        onClose={() => {
          deleteAction.reset();
          setDeleteTarget(null);
        }}
      >
        <ul className="list-inside list-disc space-y-1 text-xs text-content-muted">
          <li>
            Its opportunities, tasks, attempts and verification records wait with it in the
            recycle bin.
          </li>
          <li>
            The websites stay in the website list - they are shared with the other projects.
          </li>
          <li>The business profile is not touched.</li>
          <li>
            Nothing is lost right away: restore it from the recycle bin, or use "Delete forever"
            there to remove it for good.
          </li>
        </ul>
        {deleteAction.error ? (
          <p role="alert" className="mt-2 text-xs text-danger">
            {errorMessage(deleteAction.error)}
          </p>
        ) : null}
      </ConfirmDialog>
    </div>
  );
}

/**
 * One counter of a project row.
 *
 * While the counters are loaded a skeleton is shown, when the backend could
 * not answer the cell stays empty - a wrong number would be worse.
 */
function Counter({
  value,
  loading,
}: {
  value: number | null | undefined;
  loading: boolean;
}) {
  if (loading) return <Skeleton className="ml-auto h-4 w-8" />;
  if (value === null || value === undefined) {
    return (
      <Tooltip label="The backend did not answer for this counter">
        <span className="text-content-subtle">{formatNumber(null)}</span>
      </Tooltip>
    );
  }
  return <>{formatNumber(value)}</>;
}
