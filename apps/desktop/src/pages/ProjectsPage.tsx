import * as React from "react";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Dialog,
  Field,
  Input,
  Pagination,
  StatusBadge,
  Table,
  Td,
  Th,
  Textarea,
} from "@autobacklinker/ui";
import { api, apiClient } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import { useToast } from "@autobacklinker/ui";
import { ErrorBlock, LoadingBlock, NothingYet, PageHeader } from "../components/common";
import { formatDate, formatNumber } from "../lib/format";
import type { Project } from "@autobacklinker/shared-types";

const PAGE_SIZE = 20;

export function ProjectsPage() {
  const toast = useToast();
  const [page, setPage] = React.useState(1);
  const [creating, setCreating] = React.useState(false);
  const [name, setName] = React.useState("");
  const [targetWebsite, setTargetWebsite] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [formError, setFormError] = React.useState<string | null>(null);

  const projects = useAsync(
    () =>
      api.projects.list(apiClient, {
        page,
        page_size: PAGE_SIZE,
      }),
    [page],
  );

  const items = projects.data?.items ?? [];

  async function createProject() {
    setSaving(true);
    setFormError(null);
    try {
      await api.projects.create(apiClient, {
        name: name.trim(),
        target_website: targetWebsite.trim(),
        description: description.trim() || undefined,
      });
      toast.push("Project created", "success");
      setCreating(false);
      setName("");
      setTargetWebsite("");
      setDescription("");
      projects.reload();
    } catch (err) {
      setFormError(
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : "Could not create the project",
      );
    } finally {
      setSaving(false);
    }
  }

  async function toggleStatus(project: Project) {
    const next = project.status === "ACTIVE" ? "PAUSED" : "ACTIVE";
    try {
      await api.projects.update(apiClient, project.id, { status: next });
      toast.push(`Project ${next === "ACTIVE" ? "resumed" : "paused"}`, "success");
      projects.reload();
    } catch (err) {
      toast.push(
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : "Could not update the project",
        "error",
      );
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Projects"
        description="Campaigns tracked by this installation."
        actions={
          <Button onClick={() => setCreating(true)}>New project</Button>
        }
      />

      {projects.loading && !projects.data ? <LoadingBlock /> : null}
      {projects.error ? (
        <ErrorBlock message={projects.error} onRetry={projects.reload} />
      ) : null}

      {!projects.loading && items.length === 0 && !projects.error ? (
        <NothingYet
          title="No projects yet"
          description="Create a project to start tracking backlink opportunities for a website."
          action={
            <Button onClick={() => setCreating(true)}>New project</Button>
          }
        />
      ) : null}

      {items.length > 0 ? (
        <Card>
          <CardHeader
            title="All projects"
            description={`${formatNumber(projects.data?.total)} projects`}
          />
          <CardBody className="p-0">
            <Table>
              <thead>
                <tr>
                  <Th>Name</Th>
                  <Th>Target</Th>
                  <Th>Status</Th>
                  <Th>Execution</Th>
                  <Th className="text-right">Approved</Th>
                  <Th className="text-right">Queued</Th>
                  <Th className="text-right">Verified</Th>
                  <Th>Updated</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {items.map((project) => (
                  <tr key={project.id}>
                    <Td>
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-content">
                          {project.name}
                        </p>
                        <p className="truncate text-xs text-content-subtle">
                          {project.description ?? "-"}
                        </p>
                      </div>
                    </Td>
                    <Td className="max-w-[220px] truncate text-xs">
                      {project.target_website}
                    </Td>
                    <Td>
                      <StatusBadge status={project.status} />
                    </Td>
                    <Td>
                      <Badge tone="neutral">
                        {project.settings?.execution_environment ?? "CLOUD"}
                      </Badge>
                    </Td>
                    <Td className="text-right text-xs">
                      {formatNumber(project.counts?.approved)}
                    </Td>
                    <Td className="text-right text-xs">
                      {formatNumber(project.counts?.queued)}
                    </Td>
                    <Td className="text-right text-xs">
                      {formatNumber(project.counts?.verified_live)}
                    </Td>
                    <Td className="whitespace-nowrap text-xs text-content-muted">
                      {formatDate(project.updated_at)}
                    </Td>
                    <Td className="text-right">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => toggleStatus(project)}
                      >
                        {project.status === "ACTIVE" ? "Pause" : "Resume"}
                      </Button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <Pagination
              page={page}
              pages={projects.data?.pages ?? 1}
              total={projects.data?.total ?? 0}
              onPageChange={setPage}
            />
          </CardBody>
        </Card>
      ) : null}

      <Dialog
        open={creating}
        onClose={() => setCreating(false)}
        title="New project"
        description="A project groups opportunities, tasks and verification for one website."
        footer={
          <>
            <Button variant="ghost" onClick={() => setCreating(false)}>
              Cancel
            </Button>
            <Button
              loading={saving}
              disabled={!name.trim() || !targetWebsite.trim()}
              onClick={createProject}
            >
              Create project
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <Field label="Name" required>
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Acme backlinks"
            />
          </Field>
          <Field
            label="Target website"
            required
            hint="The page the backlinks should point to."
          >
            <Input
              value={targetWebsite}
              onChange={(event) => setTargetWebsite(event.target.value)}
              placeholder="https://www.example.com"
            />
          </Field>
          <Field label="Description">
            <Textarea
              rows={3}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </Field>
          {formError ? (
            <p className="text-xs text-danger">{formError}</p>
          ) : null}
        </div>
      </Dialog>
    </div>
  );
}
