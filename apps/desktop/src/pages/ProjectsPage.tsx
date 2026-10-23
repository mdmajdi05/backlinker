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
import {
  ProjectDeleteDialog,
  ProjectEditDialog,
} from "../components/ProjectEditDialog";
import { sendNativeNotification } from "../lib/backend";
import { formatDate, formatNumber } from "../lib/format";
import type {
  BacklinkDetailsUpdate,
  Project,
  ProjectCounts,
} from "@autobacklinker/shared-types";

const PAGE_SIZE = 20;

function errorText(error: unknown, fallback: string): string {
  if (error && typeof error === "object" && "message" in error) {
    return String((error as { message: unknown }).message);
  }
  return fallback;
}

export function ProjectsPage() {
  const toast = useToast();
  const [page, setPage] = React.useState(1);
  const [creating, setCreating] = React.useState(false);
  const [name, setName] = React.useState("");
  const [targetWebsite, setTargetWebsite] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [formError, setFormError] = React.useState<string | null>(null);
  // The facts a directory asks for - stored for this project only.
  const [bDetails, setBDetails] = React.useState<BacklinkDetailsUpdate>({});
  const [categoriesText, setCategoriesText] = React.useState("");
  const [anchorsText, setAnchorsText] = React.useState("");

  // The project that is edited or deleted at the moment.
  const [editing, setEditing] = React.useState<Project | null>(null);
  const [deleting, setDeleting] = React.useState<Project | null>(null);
  const [deletingBusy, setDeletingBusy] = React.useState(false);
  const [deleteError, setDeleteError] = React.useState<string | null>(null);

  const projects = useAsync(
    () =>
      api.projects.list(apiClient, {
        page,
        page_size: PAGE_SIZE,
      }),
    [page],
  );

  const items = projects.data?.items ?? [];
  const itemIds = items.map((project) => project.id).join(",");

  // The list of the backend only knows the projects themselves - the counters
  // and the execution environment come from the detail of every project of the
  // page.  A project that does not answer keeps an empty counter: the view
  // shows a dash instead of a number it does not have.
  const [details, setDetails] = React.useState<
    Record<string, { counts?: ProjectCounts; environment?: string }>
  >({});
  const [detailsNonce, setDetailsNonce] = React.useState(0);

  React.useEffect(() => {
    if (!itemIds) {
      setDetails({});
      return;
    }
    let cancelled = false;
    const ids = itemIds.split(",");
    void Promise.all(
      ids.map(async (id) => {
        try {
          const detail = await api.projects.get(apiClient, id);
          return [
            id,
            {
              counts: detail.counts,
              environment: detail.settings?.execution_environment,
            },
          ] as const;
        } catch {
          return [id, {}] as const;
        }
      }),
    ).then((entries) => {
      if (cancelled) return;
      setDetails(Object.fromEntries(entries));
    });
    return () => {
      cancelled = true;
    };
  }, [itemIds, detailsNonce]);

  async function createProject() {
    setSaving(true);
    setFormError(null);

    /* Only the values that were really typed are sent - empty fields would
       overwrite nothing, but they would make the request noisy. */
    const cleaned: BacklinkDetailsUpdate = {};
    const text = (value: string | null | undefined) => (value ?? "").trim();
    for (const key of [
      "company_name",
      "description",
      "email",
      "phone",
      "website",
      "address",
      "city",
      "state",
      "country",
      "postal_code",
    ] as const) {
      const value = text(bDetails[key] as string | null | undefined);
      if (value) cleaned[key] = value;
    }
    if (bDetails.founded_year) cleaned.founded_year = bDetails.founded_year;
    if (bDetails.employee_count) cleaned.employee_count = bDetails.employee_count;
    const categories = categoriesText
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    if (categories.length) cleaned.categories = categories;
    const anchors = anchorsText
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    if (anchors.length) cleaned.anchors = anchors;

    try {
      await api.projects.create(apiClient, {
        name: name.trim(),
        target_website: targetWebsite.trim(),
        description: description.trim() || undefined,
        ...(Object.keys(cleaned).length
          ? { details: { ...cleaned, target_website: targetWebsite.trim() } }
          : {}),
      });
      toast.push("Project created", "success");
      setCreating(false);
      setName("");
      setTargetWebsite("");
      setDescription("");
      setBDetails({});
      setCategoriesText("");
      setAnchorsText("");
      projects.reload();
      setDetailsNonce((value) => value + 1);
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
      setDetailsNonce((value) => value + 1);
    } catch (err) {
      toast.push(
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : "Could not update the project",
        "error",
      );
    }
  }

  async function deleteProject() {
    if (!deleting) return;
    setDeletingBusy(true);
    setDeleteError(null);
    try {
      await api.projects.remove(apiClient, deleting.id);
      toast.push(`Project "${deleting.name}" deleted`, "success");
      void sendNativeNotification(
        "Auto Backlinker",
        `The project ${deleting.name} was deleted. The websites stay in the website list.`,
      );
      setDeleting(null);
      // The last row of the last page is gone - go one page back.
      if (items.length === 1 && page > 1) {
        setPage(page - 1);
      } else {
        projects.reload();
      }
      setDetailsNonce((value) => value + 1);
    } catch (err) {
      setDeleteError(errorText(err, "Could not delete the project"));
    } finally {
      setDeletingBusy(false);
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
          description="Create a project to start tracking backlink opportunities for a website. Every project has its own report - and it can be edited or deleted at any time."
          action={
            <Button onClick={() => setCreating(true)}>Create project</Button>
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
                  <Th className="text-right">Opportunities</Th>
                  <Th className="text-right">Queued</Th>
                  <Th className="text-right">Verified</Th>
                  <Th className="text-right">Failed</Th>
                  <Th>Updated</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {items.map((project) => {
                  const detail = details[project.id];
                  const counts = detail?.counts;
                  return (
                  <tr key={project.id}>
                    <Td className="max-w-[240px]">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-content">
                          {project.name}
                        </p>
                        <p className="truncate text-xs text-content-subtle">
                          {project.description ?? "-"}
                        </p>
                      </div>
                    </Td>
                    <Td className="max-w-[180px] truncate text-xs">
                      {project.target_website}
                    </Td>
                    <Td>
                      <StatusBadge status={project.status} />
                    </Td>
                    <Td>
                      <Badge tone="neutral">
                        {detail?.environment ?? "-"}
                      </Badge>
                    </Td>
                    <Td className="text-right text-xs tabular-nums">
                      {formatNumber(counts?.opportunities)}
                    </Td>
                    <Td className="text-right text-xs tabular-nums">
                      {formatNumber(counts?.queued)}
                    </Td>
                    <Td className="text-right text-xs tabular-nums text-success">
                      {formatNumber(counts?.verified_live)}
                    </Td>
                    <Td className="text-right text-xs tabular-nums text-danger">
                      {formatNumber(counts?.failed)}
                    </Td>
                    <Td className="whitespace-nowrap text-xs text-content-muted">
                      {formatDate(project.updated_at)}
                    </Td>
                    <Td className="text-right">
                      <div className="flex items-center justify-end gap-1 whitespace-nowrap">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => setEditing(project)}
                        >
                          Edit
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => toggleStatus(project)}
                        >
                          {project.status === "ACTIVE" ? "Pause" : "Resume"}
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          className="text-danger"
                          onClick={() => {
                            setDeleteError(null);
                            setDeleting(project);
                          }}
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
        description="A project keeps its own details, backlink websites and report for one website."
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

          <div className="rounded-md border border-line p-3">
            <div className="mb-2">
              <p className="text-xs font-semibold text-content">
                Company details (optional)
              </p>
              <p className="text-[11px] text-content-subtle">
                A directory asks for these facts when it publishes a backlink.
                They are stored for this project only, so
                every website reuses them - you can change them later in the
                project.
              </p>
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              <Field label="Company name">
                <Input
                  className="h-8 text-xs"
                  value={bDetails.company_name ?? ""}
                  onChange={(event) =>
                    setBDetails({ ...bDetails, company_name: event.target.value })
                  }
                  placeholder="Acme Widgets Ltd"
                />
              </Field>
              <Field label="Website">
                <Input
                  className="h-8 text-xs"
                  value={bDetails.website ?? ""}
                  onChange={(event) =>
                    setBDetails({ ...bDetails, website: event.target.value })
                  }
                  placeholder="https://www.example.com"
                />
              </Field>
              <Field label="E-mail address">
                <Input
                  className="h-8 text-xs"
                  type="email"
                  value={bDetails.email ?? ""}
                  onChange={(event) =>
                    setBDetails({ ...bDetails, email: event.target.value })
                  }
                  placeholder="hello@example.com"
                />
              </Field>
              <Field label="Phone number">
                <Input
                  className="h-8 text-xs"
                  value={bDetails.phone ?? ""}
                  onChange={(event) =>
                    setBDetails({ ...bDetails, phone: event.target.value })
                  }
                />
              </Field>
              <div className="sm:col-span-2">
                <Field label="Street address">
                  <Input
                    className="h-8 text-xs"
                    value={bDetails.address ?? ""}
                    onChange={(event) =>
                      setBDetails({ ...bDetails, address: event.target.value })
                    }
                  />
                </Field>
              </div>
              <Field label="City">
                <Input
                  className="h-8 text-xs"
                  value={bDetails.city ?? ""}
                  onChange={(event) =>
                    setBDetails({ ...bDetails, city: event.target.value })
                  }
                />
              </Field>
              <Field label="State / region">
                <Input
                  className="h-8 text-xs"
                  value={bDetails.state ?? ""}
                  onChange={(event) =>
                    setBDetails({ ...bDetails, state: event.target.value })
                  }
                />
              </Field>
              <Field label="Country">
                <Input
                  className="h-8 text-xs"
                  value={bDetails.country ?? ""}
                  onChange={(event) =>
                    setBDetails({ ...bDetails, country: event.target.value })
                  }
                />
              </Field>
              <Field label="Postal code">
                <Input
                  className="h-8 text-xs"
                  value={bDetails.postal_code ?? ""}
                  onChange={(event) =>
                    setBDetails({ ...bDetails, postal_code: event.target.value })
                  }
                />
              </Field>
              <Field label="Categories" hint="Comma separated.">
                <Input
                  className="h-8 text-xs"
                  value={categoriesText}
                  onChange={(event) => setCategoriesText(event.target.value)}
                  placeholder="Business, Technology"
                />
              </Field>
              <Field
                label="Anchors"
                hint="Comma separated. The texts the backlinks should use."
              >
                <Input
                  className="h-8 text-xs"
                  value={anchorsText}
                  onChange={(event) => setAnchorsText(event.target.value)}
                  placeholder="best widgets, acme widgets"
                />
              </Field>
              <Field label="Year founded">
                <Input
                  className="h-8 text-xs"
                  type="number"
                  value={bDetails.founded_year ?? ""}
                  onChange={(event) =>
                    setBDetails({
                      ...bDetails,
                      founded_year: event.target.value
                        ? Number.parseInt(event.target.value, 10)
                        : null,
                    })
                  }
                />
              </Field>
              <Field label="Number of employees">
                <Input
                  className="h-8 text-xs"
                  type="number"
                  value={bDetails.employee_count ?? ""}
                  onChange={(event) =>
                    setBDetails({
                      ...bDetails,
                      employee_count: event.target.value
                        ? Number.parseInt(event.target.value, 10)
                        : null,
                    })
                  }
                />
              </Field>
              <div className="sm:col-span-2">
                <Field label="Submission description">
                  <Textarea
                    rows={2}
                    value={bDetails.description ?? ""}
                    onChange={(event) =>
                      setBDetails({ ...bDetails, description: event.target.value })
                    }
                    placeholder="What the company does - the directories use it as the listing text."
                  />
                </Field>
              </div>
            </div>
          </div>

          {formError ? (
            <p className="text-xs text-danger">{formError}</p>
          ) : null}
        </div>
      </Dialog>

      <ProjectEditDialog
        open={Boolean(editing)}
        project={editing}
        onClose={() => setEditing(null)}
        onSaved={() => {
          projects.reload();
          setDetailsNonce((value) => value + 1);
        }}
      />

      <ProjectDeleteDialog
        open={Boolean(deleting)}
        project={deleting}
        counts={deleting ? details[deleting.id]?.counts ?? null : null}
        busy={deletingBusy}
        error={deleteError}
        onCancel={() => {
          if (deletingBusy) return;
          setDeleting(null);
          setDeleteError(null);
        }}
        onConfirm={() => void deleteProject()}
      />
    </div>
  );
}
