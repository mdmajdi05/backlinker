"use client";

import * as React from "react";
import { api } from "@autobacklinker/api-client";
import type { Opportunity } from "@autobacklinker/shared-types";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  Dialog,
  Field,
  Input,
  Pagination,
  Select,
  Skeleton,
  StatusBadge,
  Table,
  Td,
  Th,
  Textarea,
  Toolbar,
  Tooltip,
  useToast,
} from "@autobacklinker/ui";
import { apiClient, errorMessage } from "@/lib/api";
import { useAction, useDebounced, useResource } from "@/lib/hooks";
import { formatDateTime, formatDecimal } from "@/lib/format";
import {
  ALL_OPPORTUNITY_CATEGORIES,
  ALL_OPPORTUNITY_STATUSES,
  CATEGORY_LABELS,
  OPPORTUNITY_STATUS_LABELS,
} from "@/lib/constants";
import { PageHeader } from "@/components/PageHeader";
import { AsyncSection, TableSkeleton } from "@/components/States";
import { OpportunityDrawer } from "@/components/OpportunityDrawer";
import {
  useDetailsSummaries,
  type DetailsSummary,
} from "@/components/SubmissionDetailsPanel";
import {
  useAutoPilotStates,
  type AutoPilotSummary,
} from "@/components/AutoPilotPanel";
import { ConfirmDialog } from "@/components/ConfirmDialog";

const PAGE_SIZE = 25;

type SortKey = "name" | "domain" | "score" | "status" | "created_at" | "updated_at";

type BulkAction = "approve" | "reject" | "exclude" | "delete" | "queue" | "add_to_project";

const DESTRUCTIVE: BulkAction[] = ["reject", "exclude", "delete"];

export default function RegistryPage() {
  const toast = useToast();
  const action = useAction();

  const [page, setPage] = React.useState(1);
  const [projectId, setProjectId] = React.useState("");
  const [status, setStatus] = React.useState("");
  const [category, setCategory] = React.useState("");
  const [domain, setDomain] = React.useState("");
  const [minScore, setMinScore] = React.useState("");
  const [search, setSearch] = React.useState("");
  const [sort, setSort] = React.useState<SortKey>("updated_at");
  const [order, setOrder] = React.useState<"asc" | "desc">("desc");

  const [selected, setSelected] = React.useState<string[]>([]);
  const [detail, setDetail] = React.useState<Opportunity | null>(null);
  const [confirmAction, setConfirmAction] = React.useState<BulkAction | null>(null);
  const [bulkProjectId, setBulkProjectId] = React.useState("");

  // Manual entry: the website on which the backlink should be placed.
  const [addOpen, setAddOpen] = React.useState(false);
  const [addForm, setAddForm] = React.useState({
    opportunity_url: "",
    name: "",
    category: "BUSINESS_DIRECTORY",
    project_id: "",
    anchor_text: "",
    description: "",
    target_landing_page: "",
  });
  const [addError, setAddError] = React.useState<string | null>(null);
  const [adding, setAdding] = React.useState(false);

  const resetAddForm = () =>
    setAddForm({
      opportunity_url: "",
      name: "",
      category: "BUSINESS_DIRECTORY",
      project_id: projectId || (projects.data?.items?.[0]?.id ?? ""),
      anchor_text: "",
      description: "",
      target_landing_page: "",
    });

  const submitManualWebsite = async () => {
    setAddError(null);
    if (!addForm.opportunity_url.trim()) {
      setAddError("The URL of the website is required.");
      return;
    }
    if (!addForm.project_id) {
      setAddError("Choose the project this website belongs to.");
      return;
    }
    setAdding(true);
    try {
      await apiClient.post("/api/v1/opportunities", {
        opportunity_url: addForm.opportunity_url.trim(),
        name: addForm.name.trim() || undefined,
        category: addForm.category,
        project_id: addForm.project_id,
        anchor_text: addForm.anchor_text.trim() || undefined,
        description: addForm.description.trim() || undefined,
        target_landing_page: addForm.target_landing_page.trim() || undefined,
      });
      toast.push("Website added to the registry", "success");
      setAddOpen(false);
      resetAddForm();
      opportunities.reload();
    } catch (err) {
      setAddError(errorMessage(err));
    } finally {
      setAdding(false);
    }
  };

  const debouncedSearch = useDebounced(search, 400);
  const debouncedDomain = useDebounced(domain, 400);

  const projects = useResource(() => api.projects.list(apiClient, { page: 1, page_size: 100 }), []);

  const opportunities = useResource(
    () =>
      api.opportunities.list(apiClient, {
        page,
        page_size: PAGE_SIZE,
        project_id: projectId || undefined,
        status: status || undefined,
        category: category || undefined,
        domain: debouncedDomain || undefined,
        min_score: minScore || undefined,
        search: debouncedSearch || undefined,
        sort,
        order,
      }),
    [page, projectId, status, category, debouncedDomain, minScore, debouncedSearch, sort, order],
  );

  const rows = opportunities.data?.items ?? [];

  // The submission details and the automatic submission state decide whether a
  // row can be submitted without asking the user for more information.
  const detailIds = React.useMemo(() => rows.map((row) => row.id), [rows]);
  const projectIds = React.useMemo(
    // The selected project is always part of the list - an opportunity can
    // belong to several projects and the filter may point to a project that is
    // not the primary one of the visible rows.
    () => Array.from(new Set([...rows.map((row) => row.project_id), projectId].filter(Boolean))),
    [rows, projectId],
  );
  const { summaries: detailsByOpportunity } = useDetailsSummaries(detailIds);
  const { states: autoPilotByProject } = useAutoPilotStates(projectIds);

  /** The project whose automatic submission state is relevant for a row. */
  const rowProjectId = React.useCallback(
    (row: Opportunity) => {
      if (projectId && (row.project_id === projectId || row.project_ids?.includes(projectId))) {
        return projectId;
      }
      return row.project_id;
    },
    [projectId],
  );

  const selectedProject = React.useMemo(
    () => (projects.data?.items ?? []).find((project) => project.id === projectId) ?? null,
    [projects.data, projectId],
  );
  const selectedAutoPilot = projectId ? autoPilotByProject[projectId] : undefined;

  React.useEffect(() => {
    setSelected([]);
  }, [page, projectId, status, category, debouncedDomain, minScore, debouncedSearch]);

  const toggleSort = (key: SortKey) => {
    if (sort === key) {
      setOrder((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSort(key);
      setOrder("desc");
    }
    setPage(1);
  };

  const sortIndicator = (key: SortKey) => (sort === key ? (order === "asc" ? " ▲" : " ▼") : "");

  const allSelected = rows.length > 0 && rows.every((row) => selected.includes(row.id));

  const toggleAll = () => {
    if (allSelected) {
      setSelected((prev) => prev.filter((id) => !rows.some((row) => row.id === id)));
    } else {
      setSelected((prev) => Array.from(new Set([...prev, ...rows.map((row) => row.id)])));
    }
  };

  const toggleOne = (id: string) => {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id],
    );
  };

  const runBulk = async (bulkAction: BulkAction) => {
    if (selected.length === 0) return;
    const outcome = await action.run(() =>
      api.opportunities.bulk(apiClient, {
        opportunity_ids: selected,
        action: bulkAction,
        project_id: bulkAction === "add_to_project" ? bulkProjectId || undefined : undefined,
      }),
    );
    if (outcome.ok && outcome.data) {
      const { affected, queued = 0, skipped = 0 } = outcome.data;
      if (bulkAction === "queue") {
        // Only report success when a submission was really created - a run
        // where every website was already queued is not a success.
        if (queued === 0) {
          toast.push(
            skipped > 0
              ? `Nothing queued: ${skipped} website${skipped === 1 ? " was" : "s were"} already queued, excluded or in a paused project`
              : "Nothing was queued",
            "info",
          );
        } else if (skipped > 0) {
          toast.push(
            `${queued} website${queued === 1 ? "" : "s"} queued, ${skipped} skipped (already queued or not eligible)`,
            "success",
          );
        } else {
          toast.push(
            `${queued} website${queued === 1 ? "" : "s"} added to the queue`,
            "success",
          );
        }
      } else {
        toast.push(`${affected} website${affected === 1 ? "" : "s"} updated`, "success");
      }
      setSelected([]);
      setConfirmAction(null);
      opportunities.reload();
    }
  };

  const bulkDisabledReason =
    selected.length === 0
      ? "Select at least one website first."
      : confirmAction === "add_to_project" && !bulkProjectId
        ? "Choose the target project for this bulk action."
        : null;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Review websites"
        description="Every website you can get a backlink from - its state, score and submission readiness."
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="primary"
              size="sm"
              onClick={() => {
                resetAddForm();
                setAddError(null);
                setAddOpen(true);
              }}
            >
              Add website
            </Button>
            <Button variant="outline" size="sm" onClick={opportunities.reload} loading={opportunities.refreshing}>
              Refresh
            </Button>
          </div>
        }
      />

      {selectedAutoPilot?.state === "ready" && selectedAutoPilot.data?.enabled ? (
        <Alert tone="accent" title="Automatic submission is on">
          Approving a website of{" "}
          <span className="font-semibold text-content">
            {selectedProject?.name ?? "this project"}
          </span>{" "}
          queues it automatically - the worker submits it in the background. You stay in control
          of what is approved.
        </Alert>
      ) : null}

      {selectedAutoPilot?.state === "ready" && !selectedAutoPilot.data?.enabled ? (
        <Alert tone="neutral" title="Automatic submission is off">
          Approving a website of{" "}
          <span className="font-semibold text-content">
            {selectedProject?.name ?? "this project"}
          </span>{" "}
          only queues it - the worker submits it in the background once the details are
          complete. Switch the auto pilot on in the project to submit without the manual step.
        </Alert>
      ) : null}

      {selectedAutoPilot?.state === "unavailable" ? (
        <Alert tone="neutral" title="The automatic submission state could not be loaded">
          The backend answered 404 for the auto pilot endpoint of this project. The project may
          have been removed, or it may not belong to this account, so the registry can not show
          whether approving queues the submission.
        </Alert>
      ) : null}

      <Card>
        <Toolbar>
          <Field label="Search" className="w-56">
            <Input
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setPage(1);
              }}
              placeholder="Name, URL or notes"
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
          <Field label="Status" className="w-44">
            <Select
              value={status}
              onChange={(event) => {
                setStatus(event.target.value);
                setPage(1);
              }}
            >
              <option value="">All statuses</option>
              {ALL_OPPORTUNITY_STATUSES.map((value) => (
                <option key={value} value={value}>
                  {OPPORTUNITY_STATUS_LABELS[value] ?? value}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Category" className="w-52">
            <Select
              value={category}
              onChange={(event) => {
                setCategory(event.target.value);
                setPage(1);
              }}
            >
              <option value="">All categories</option>
              {ALL_OPPORTUNITY_CATEGORIES.map((value) => (
                <option key={value} value={value}>
                  {CATEGORY_LABELS[value] ?? value}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Domain" className="w-44">
            <Input
              value={domain}
              onChange={(event) => {
                setDomain(event.target.value);
                setPage(1);
              }}
              placeholder="example.com"
            />
          </Field>
          <Field label="Min score" className="w-28">
            <Input
              type="number"
              min={0}
              step="0.1"
              value={minScore}
              onChange={(event) => {
                setMinScore(event.target.value);
                setPage(1);
              }}
              placeholder="0"
            />
          </Field>
          {(projectId || status || category || domain || minScore || search) && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setProjectId("");
                setStatus("");
                setCategory("");
                setDomain("");
                setMinScore("");
                setSearch("");
                setPage(1);
              }}
            >
              Reset filters
            </Button>
          )}
        </Toolbar>

        <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
          <span className="text-xs text-content-muted">
            {selected.length} selected
          </span>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={selected.length === 0}
              onClick={() => setConfirmAction("approve")}
            >
              Approve
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={selected.length === 0}
              onClick={() => setConfirmAction("reject")}
            >
              Reject
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={selected.length === 0}
              onClick={() => setConfirmAction("exclude")}
            >
              Exclude
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={selected.length === 0}
              onClick={() => setConfirmAction("queue")}
            >
              Add to queue
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={selected.length === 0}
              onClick={() => setConfirmAction("add_to_project")}
            >
              Add to project
            </Button>
            <Button
              size="sm"
              variant="danger"
              disabled={selected.length === 0}
              onClick={() => setConfirmAction("delete")}
            >
              Delete
            </Button>
          </div>
          {confirmAction === "add_to_project" ? (
            <Select
              className="w-56"
              value={bulkProjectId}
              onChange={(event) => setBulkProjectId(event.target.value)}
              aria-label="Target project"
            >
              <option value="">Select target project…</option>
              {(projects.data?.items ?? []).map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </Select>
          ) : null}
        </div>

        <CardBody className="p-0">
          <AsyncSection
            loading={opportunities.loading}
            error={opportunities.error}
            data={opportunities.data}
            onRetry={opportunities.reload}
            isEmpty={rows.length === 0}
            emptyTitle="No websites match these filters"
            emptyDescription="Adjust the filters or run a discovery to populate the registry."
            skeleton={<TableSkeleton rows={8} columns={9} />}
          >
            <Table>
              <thead>
                <tr>
                  <Th className="w-10">
                    <input
                      type="checkbox"
                      aria-label="Select all websites on this page"
                      checked={allSelected}
                      onChange={toggleAll}
                    />
                  </Th>
                  <Th>
                    <button type="button" onClick={() => toggleSort("name")} className="font-semibold uppercase">
                      Name{sortIndicator("name")}
                    </button>
                  </Th>
                  <Th>
                    <button type="button" onClick={() => toggleSort("domain")} className="font-semibold uppercase">
                      Domain{sortIndicator("domain")}
                    </button>
                  </Th>
                  <Th>Category</Th>
                  <Th>
                    <button type="button" onClick={() => toggleSort("score")} className="font-semibold uppercase">
                      Score{sortIndicator("score")}
                    </button>
                  </Th>
                  <Th>
                    <button type="button" onClick={() => toggleSort("status")} className="font-semibold uppercase">
                      Status{sortIndicator("status")}
                    </button>
                  </Th>
                  <Th className="w-32">Details</Th>
                  <Th className="w-28">Auto-submit</Th>
                  <Th>
                    <button type="button" onClick={() => toggleSort("updated_at")} className="font-semibold uppercase">
                      Updated{sortIndicator("updated_at")}
                    </button>
                  </Th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={row.id}
                    className="cursor-pointer"
                    onClick={() => setDetail(row)}
                  >
                    <Td onClick={(event) => event.stopPropagation()}>
                      <input
                        type="checkbox"
                        aria-label={`Select ${row.name}`}
                        checked={selected.includes(row.id)}
                        onChange={() => toggleOne(row.id)}
                      />
                    </Td>
                    <Td>
                      <p className="font-medium text-content">{row.name}</p>
                      <p className="max-w-xs truncate text-xs text-content-muted">{row.opportunity_url}</p>
                    </Td>
                    <Td className="text-xs">{row.domain}</Td>
                    <Td>
                      <Badge tone="neutral">
                        {CATEGORY_LABELS[row.category] ?? row.category}
                      </Badge>
                    </Td>
                    <Td className="tabular-nums">{formatDecimal(row.score, 1)}</Td>
                    <Td>
                      <StatusBadge status={row.status} />
                    </Td>
                    <Td>
                      <DetailsCell summary={detailsByOpportunity[row.id]} />
                    </Td>
                    <Td>
                      <AutoSubmitCell summary={autoPilotByProject[rowProjectId(row)]} />
                    </Td>
                    <Td className="text-xs text-content-muted">{formatDateTime(row.updated_at)}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            {opportunities.data ? (
              <Pagination
                page={opportunities.data.page}
                pages={opportunities.data.pages}
                total={opportunities.data.total}
                onPageChange={setPage}
              />
            ) : null}
          </AsyncSection>
        </CardBody>
      </Card>

      <OpportunityDrawer
        opportunity={detail}
        open={Boolean(detail)}
        onClose={() => setDetail(null)}
        onChanged={opportunities.reload}
      />

      <Dialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        title="Add a website"
        description="The page on which the backlink should be placed - for example a directory form."
        width="lg"
        footer={
          <>
            <Button variant="outline" onClick={() => setAddOpen(false)}>
              Cancel
            </Button>
            <Button loading={adding} onClick={() => void submitManualWebsite()}>
              Add website
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          {addError ? (
            <p className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-xs text-danger">
              {addError}
            </p>
          ) : null}

          <Field
            label="Submission URL"
            required
            hint="The exact page that accepts the listing - for example https://example.com/add-your-business"
          >
            <Input
              value={addForm.opportunity_url}
              onChange={(event) =>
                setAddForm((prev) => ({ ...prev, opportunity_url: event.target.value }))
              }
              placeholder="https://example.com/add-your-business"
            />
          </Field>

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Name" hint="Shown in the list">
              <Input
                value={addForm.name}
                onChange={(event) => setAddForm((prev) => ({ ...prev, name: event.target.value }))}
                placeholder="Example directory"
              />
            </Field>
            <Field label="Category" required>
              <Select
                value={addForm.category}
                onChange={(event) => setAddForm((prev) => ({ ...prev, category: event.target.value }))}
              >
                {ALL_OPPORTUNITY_CATEGORIES.map((value) => (
                  <option key={value} value={value}>
                    {CATEGORY_LABELS[value] ?? value}
                  </option>
                ))}
              </Select>
            </Field>
          </div>

          <Field label="Project" required hint="The project this website belongs to">
            <Select
              value={addForm.project_id}
              onChange={(event) => setAddForm((prev) => ({ ...prev, project_id: event.target.value }))}
            >
              <option value="">Choose a project</option>
              {(projects.data?.items ?? []).map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </Select>
          </Field>

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Anchor text" hint="The clickable text of the link">
              <Input
                value={addForm.anchor_text}
                onChange={(event) =>
                  setAddForm((prev) => ({ ...prev, anchor_text: event.target.value }))
                }
                placeholder="Acme Analytics"
              />
            </Field>
            <Field label="Target landing page" hint="Your page that should receive the link">
              <Input
                value={addForm.target_landing_page}
                onChange={(event) =>
                  setAddForm((prev) => ({ ...prev, target_landing_page: event.target.value }))
                }
                placeholder="https://your-site.com/product"
              />
            </Field>
          </div>

          <Field label="Description" hint="Used for the submission form and the outreach draft">
            <Textarea
              rows={3}
              value={addForm.description}
              onChange={(event) =>
                setAddForm((prev) => ({ ...prev, description: event.target.value }))
              }
              placeholder="One or two sentences about your business."
            />
          </Field>
        </div>
      </Dialog>

      <ConfirmDialog
        open={confirmAction !== null}
        title={
          confirmAction === "delete"
            ? "Delete websites?"
            : confirmAction === "approve"
              ? "Approve websites?"
              : confirmAction === "reject"
                ? "Reject websites?"
                : confirmAction === "exclude"
                  ? "Exclude websites?"
                  : confirmAction === "queue"
                    ? "Add websites to the queue?"
                    : "Add websites to a project?"
        }
        description={
          confirmAction
            ? `${selected.length} website(s) will be processed by the backend.`
            : undefined
        }
        confirmLabel={
          confirmAction === "delete"
            ? "Delete permanently"
            : confirmAction === "approve"
              ? "Approve"
              : confirmAction === "reject"
                ? "Reject"
                : confirmAction === "exclude"
                  ? "Exclude"
                  : confirmAction === "queue"
                    ? "Add to queue"
                    : "Add to project"
        }
        destructive={confirmAction !== null && DESTRUCTIVE.includes(confirmAction)}
        pending={action.pending}
        onClose={() => setConfirmAction(null)}
        onConfirm={() => confirmAction && runBulk(confirmAction)}
      >
        {action.error ? (
          <p className="text-xs text-danger">{errorMessage(action.error)}</p>
        ) : null}
        {bulkDisabledReason ? (
          <Tooltip label={bulkDisabledReason}>
            <span className="text-xs text-danger">{bulkDisabledReason}</span>
          </Tooltip>
        ) : null}
      </ConfirmDialog>
    </div>
  );
}

/** Shows whether the submission details of a row are complete. */
function DetailsCell({ summary }: { summary?: DetailsSummary }) {
  if (!summary || summary.state === "loading") {
    return <Skeleton className="h-4 w-20" />;
  }
  if (summary.state === "ready" && summary.details) {
    const missing = summary.details.missing.length;
    if (!missing && summary.details.complete) {
      return <Badge tone="success">Complete</Badge>;
    }
    return (
      <Tooltip label="The site asks for values that are still missing - open the row to fill them in.">
        <span>
          <Badge tone="warning">
            {missing} missing
          </Badge>
        </span>
      </Tooltip>
    );
  }
  if (summary.state === "unavailable") {
    return (
      <Tooltip label="The backend returned 404 for this opportunity's details; it may have been removed.">
        <span>
          <Badge tone="neutral">details unavailable</Badge>
        </span>
      </Tooltip>
    );
  }
  return (
    <Tooltip label="The details state could not be loaded.">
      <span>
        <Badge tone="neutral">unknown</Badge>
      </span>
    </Tooltip>
  );
}

/** Shows whether approving an opportunity queues the submission. */
function AutoSubmitCell({ summary }: { summary?: AutoPilotSummary }) {
  if (!summary || summary.state === "loading") {
    return <Skeleton className="h-4 w-16" />;
  }
  if (summary.state === "ready" && summary.data) {
    return summary.data.enabled ? (
      <Badge tone="success">On</Badge>
    ) : (
      <Badge tone="neutral">Off</Badge>
    );
  }
  if (summary.state === "unavailable") {
    return (
      <Tooltip label="The backend returned 404 for this project's auto pilot endpoint; the project may have been removed.">
        <span>
          <Badge tone="neutral">state unavailable</Badge>
        </span>
      </Tooltip>
    );
  }
  return (
    <Tooltip label="The automatic submission state could not be loaded.">
      <span>
        <Badge tone="neutral">unknown</Badge>
      </span>
    </Tooltip>
  );
}
