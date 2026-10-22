"use client";

import * as React from "react";
import { api, type WebsiteStatsRow } from "@autobacklinker/api-client";
import type { WebsiteImportResult, WebsiteListItem } from "@autobacklinker/shared-types";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  Checkbox,
  Dialog,
  Field,
  Input,
  Pagination,
  Select,
  Skeleton,
  Table,
  Td,
  Textarea,
  Th,
  Toolbar,
  Tooltip,
  useToast,
} from "@autobacklinker/ui";
import { apiClient, errorMessage, isNotFoundError } from "@/lib/api";
import { useAction, useDebounced, useResource } from "@/lib/hooks";
import { formatDateTime, formatNumber, humanize } from "@/lib/format";
import {
  ALL_OPPORTUNITY_CATEGORIES,
  CATEGORY_LABELS,
  SUBMISSION_METHOD_LABELS,
} from "@/lib/constants";
import { AsyncSection, TableSkeleton } from "@/components/States";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import {
  REMOVED_WEBSITE_LABEL,
  REMOVED_WEBSITE_STATUS,
  WEBSITE_STATUS_CHOICES,
  WEBSITE_STATUS_FILTERS,
  WEBSITE_STATUS_LABELS,
  isRemovedWebsite,
  readCounters,
  websiteStatusLabel,
} from "@/lib/websites";

const PAGE_SIZE = 25;

type SortKey = "name" | "domain" | "status" | "created_at" | "updated_at";

/**
 * The message of a failed recycle bin action.
 *
 * A 404 means either that the website is gone already or that the backend
 * does not know the recycle bin yet - both are told instead of a bare
 * "Not Found".
 */
function recycleBinError(error: unknown, fallback: string): string {
  if (isNotFoundError(error)) {
    return "The backend answered 404 - the website may be gone already or the backend does not know the recycle bin yet.";
  }
  return errorMessage(error) || fallback;
}

interface AddForm {
  opportunity_url: string;
  name: string;
  category: string;
  niche: string;
  notes: string;
  submission_method: string;
}

const EMPTY_ADD_FORM: AddForm = {
  opportunity_url: "",
  name: "",
  category: "BUSINESS_DIRECTORY",
  niche: "",
  notes: "",
  submission_method: "UNKNOWN",
};

/**
 * The central list of the websites.
 *
 * The list is independent of the projects: a project picks the sites it wants
 * from it.  It offers the manual entry, the Excel import, the status of every
 * row, the notes and the deletion.
 *
 * The deletion has two steps: "Delete" takes the website out of the list and
 * keeps its history (the reports stay correct), "Delete forever" destroys the
 * website together with its opportunities and its tasks.  The removed websites
 * wait in the recycle bin (the "Deleted" filter) until they are restored or
 * deleted forever.
 */
export function WebsiteListPanel({
  projectId: scopedProjectId,
  onChanged,
  showProjectFilter = true,
}: {
  /** Scopes the list to one project - the project filter is hidden then. */
  projectId?: string;
  /** Called after every change of the list. */
  onChanged?: () => void;
  showProjectFilter?: boolean;
}) {
  const toast = useToast();
  const action = useAction();

  const [page, setPage] = React.useState(1);
  const [search, setSearch] = React.useState("");
  const [category, setCategory] = React.useState("");
  const [niche, setNiche] = React.useState("");
  const [status, setStatus] = React.useState("");
  const [projectFilter, setProjectFilter] = React.useState(scopedProjectId ?? "");
  const [sort, setSort] = React.useState<SortKey>("updated_at");
  const [order, setOrder] = React.useState<"asc" | "desc">("desc");
  /** The recycle bin is open - the list shows the removed websites only. */
  const [binOpen, setBinOpen] = React.useState(false);

  const [selected, setSelected] = React.useState<string[]>([]);
  const [bulkStatus, setBulkStatus] = React.useState("");

  const [addOpen, setAddOpen] = React.useState(false);
  const [addForm, setAddForm] = React.useState<AddForm>(EMPTY_ADD_FORM);
  const [addError, setAddError] = React.useState<string | null>(null);
  const [adding, setAdding] = React.useState(false);

  const [editItem, setEditItem] = React.useState<WebsiteListItem | null>(null);
  const [editForm, setEditForm] = React.useState({
    name: "",
    category: "",
    niche: "",
    status: "",
    notes: "",
  });
  const [editError, setEditError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);

  const [deleteTarget, setDeleteTarget] = React.useState<{
    ids: string[];
    label: string;
    names: string[];
  } | null>(null);
  const [deleting, setDeleting] = React.useState(false);

  const [purgeTarget, setPurgeTarget] = React.useState<{
    ids: string[];
    label: string;
    names: string[];
  } | null>(null);
  const [purging, setPurging] = React.useState(false);

  const [restoringId, setRestoringId] = React.useState<string | null>(null);

  const [importOpen, setImportOpen] = React.useState(false);
  const [importCategory, setImportCategory] = React.useState("");
  const [importNiche, setImportNiche] = React.useState("");
  const [importStatus, setImportStatus] = React.useState("");
  const [importResult, setImportResult] = React.useState<WebsiteImportResult | null>(null);
  const [importError, setImportError] = React.useState<string | null>(null);
  const [importing, setImporting] = React.useState(false);
  const [dragActive, setDragActive] = React.useState(false);
  const fileInputRef = React.useRef<HTMLInputElement | null>(null);

  const effectiveProjectId = scopedProjectId ?? projectFilter;
  /** The recycle bin shows the removed websites - the normal list hides them. */
  const effectiveStatus = binOpen ? REMOVED_WEBSITE_STATUS : status;

  const debouncedSearch = useDebounced(search, 400);
  const debouncedNiche = useDebounced(niche, 400);

  const projects = useResource(() => api.projects.list(apiClient, { page: 1, page_size: 100 }), []);

  const websites = useResource(
    () =>
      api.websites.list(apiClient, {
        page,
        page_size: PAGE_SIZE,
        search: debouncedSearch || undefined,
        category: category || undefined,
        niche: debouncedNiche || undefined,
        status: effectiveStatus || undefined,
        project_id: effectiveProjectId || undefined,
        sort,
        order,
      }),
    [
      page,
      debouncedSearch,
      category,
      debouncedNiche,
      effectiveStatus,
      effectiveProjectId,
      sort,
      order,
    ],
  );

  const stats = useResource(
    () => api.websites.stats(apiClient, effectiveProjectId || undefined),
    [effectiveProjectId],
  );

  /** How many websites wait in the recycle bin (the badge of the chip). */
  const removed = useResource(
    () =>
      api.websites.list(apiClient, {
        page: 1,
        page_size: 1,
        status: REMOVED_WEBSITE_STATUS,
      }),
    [],
  );

  const rows = websites.data?.items ?? [];

  /**
   * The statistics of every website - the endpoint groups them by domain.
   *
   * A domain can host several websites, therefore the rows are matched by
   * domain *and* name.  When the domain alone is ambiguous the counters of
   * the list record are used - they belong to exactly one website.
   */
  const statsByWebsite = React.useMemo(() => {
    const map = new Map<string, WebsiteStatsRow>();
    const domains = new Map<string, number>();
    for (const row of stats.data ?? []) {
      if (!row.domain) continue;
      map.set(`${row.domain}|${row.name ?? ""}`, row);
      domains.set(row.domain, (domains.get(row.domain) ?? 0) + 1);
    }
    return { map, domains };
  }, [stats.data]);

  const statsFor = React.useCallback(
    (row: WebsiteListItem) => {
      const exact = statsByWebsite.map.get(`${row.domain}|${row.name ?? ""}`);
      if (exact) return exact;
      if ((statsByWebsite.domains.get(row.domain) ?? 0) <= 1) {
        const byDomain = stats.data?.find((entry) => entry.domain === row.domain);
        if (byDomain) return byDomain;
      }
      return null;
    },
    [statsByWebsite, stats.data],
  );

  const projectNames = React.useMemo(() => {
    const map = new Map<string, string>();
    for (const project of projects.data?.items ?? []) map.set(project.id, project.name);
    return map;
  }, [projects.data]);

  const knownNiches = React.useMemo(
    () =>
      Array.from(
        new Set(rows.map((row) => (row.niche ?? "").trim()).filter((value) => value.length > 0)),
      ).sort(),
    [rows],
  );

  /** The statistics endpoint did not answer - the record itself is the source. */
  const statsUnavailable = Boolean(stats.error) && isNotFoundError(stats.error);

  React.useEffect(() => {
    setSelected([]);
  }, [page, effectiveProjectId, effectiveStatus, category, debouncedSearch, debouncedNiche]);

  const refreshAll = React.useCallback(() => {
    websites.reload();
    stats.reload();
    removed.reload();
    onChanged?.();
  }, [websites, stats, removed, onChanged]);

  const toggleSort = (key: SortKey) => {
    if (sort === key) {
      setOrder((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSort(key);
      setOrder("desc");
    }
    setPage(1);
  };

  const sortIndicator = (key: SortKey) =>
    sort === key ? (order === "asc" ? " ▲" : " ▼") : "";

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

  const filtersActive = Boolean(
    search || category || niche || status || binOpen || (showProjectFilter && projectFilter),
  );

  const resetFilters = () => {
    setSearch("");
    setCategory("");
    setNiche("");
    setStatus("");
    setBinOpen(false);
    if (showProjectFilter) setProjectFilter("");
    setPage(1);
  };

  /* ---------------------------------------------------------------- */
  /* Actions                                                           */
  /* ---------------------------------------------------------------- */

  const changeStatus = async (row: WebsiteListItem, next: string) => {
    if (!next || next === row.status) return;
    const outcome = await action.run(() =>
      api.websites.update(apiClient, row.id, { status: next }),
    );
    if (outcome.ok) {
      toast.push(`${row.name} is now "${websiteStatusLabel(next)}"`, "success");
      refreshAll();
    } else {
      toast.push(errorMessage(outcome.error), "error");
    }
  };

  const applyBulkStatus = async () => {
    if (!bulkStatus || selected.length === 0) return;
    const outcome = await action.run(async () => {
      const results = await Promise.allSettled(
        selected.map((id) => api.websites.update(apiClient, id, { status: bulkStatus })),
      );
      const failed = results.filter((result) => result.status === "rejected");
      if (failed.length > 0) {
        throw new Error(
          `${failed.length} of ${results.length} websites could not be updated - ${errorMessage(
            (failed[0] as PromiseRejectedResult).reason,
          )}`,
        );
      }
      return results.length;
    });
    if (outcome.ok) {
      toast.push(`${outcome.data ?? 0} website(s) updated`, "success");
      setSelected([]);
      setBulkStatus("");
      refreshAll();
    }
  };

  const submitAdd = async () => {
    setAddError(null);
    if (!addForm.opportunity_url.trim()) {
      setAddError("The URL of the website is required.");
      return;
    }
    setAdding(true);
    try {
      await api.websites.create(apiClient, {
        opportunity_url: addForm.opportunity_url.trim(),
        name: addForm.name.trim() || undefined,
        category: addForm.category || undefined,
        niche: addForm.niche.trim() || undefined,
        notes: addForm.notes.trim() || undefined,
        submission_method: addForm.submission_method || undefined,
      });
      toast.push("Website added to the list", "success");
      setAddOpen(false);
      setAddForm(EMPTY_ADD_FORM);
      refreshAll();
    } catch (err) {
      setAddError(errorMessage(err));
    } finally {
      setAdding(false);
    }
  };

  const openEdit = (row: WebsiteListItem) => {
    setEditItem(row);
    setEditError(null);
    setEditForm({
      name: row.name ?? "",
      category: row.category ?? "",
      niche: row.niche ?? "",
      status: row.status ?? "",
      notes: row.notes ?? "",
    });
  };

  const submitEdit = async () => {
    if (!editItem) return;
    setEditError(null);
    setSaving(true);
    try {
      await api.websites.update(apiClient, editItem.id, {
        name: editForm.name.trim(),
        category: editForm.category,
        niche: editForm.niche.trim(),
        status: editForm.status,
        notes: editForm.notes.trim(),
      });
      toast.push("Website updated", "success");
      setEditItem(null);
      refreshAll();
    } catch (err) {
      setEditError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  /**
   * Takes the websites out of the list - their history stays in the database.
   *
   * The website disappears from the list and from every project that uses it,
   * but its opportunities, its tasks and its verification records stay: the
   * old reports remain truthful and the website can be restored.
   */
  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      const results = await Promise.allSettled(
        deleteTarget.ids.map((id) => api.websites.remove(apiClient, id)),
      );
      const failed = results.filter((result) => result.status === "rejected");
      if (failed.length > 0) {
        throw new Error(
          `${failed.length} of ${results.length} websites could not be removed - ${errorMessage(
            (failed[0] as PromiseRejectedResult).reason,
          )}`,
        );
      }
      toast.push(
        deleteTarget.ids.length === 1
          ? `${deleteTarget.label} removed from the list - restore it with the "Deleted" filter`
          : `${deleteTarget.ids.length} websites removed from the list - restore them with the "Deleted" filter`,
        "success",
      );
      setDeleteTarget(null);
      setSelected([]);
      refreshAll();
    } catch (err) {
      toast.push(errorMessage(err), "error");
    } finally {
      setDeleting(false);
    }
  };

  /**
   * Deletes the websites forever - the website, its opportunities and its
   * tasks are gone.  This cannot be undone.
   */
  const confirmPurge = async () => {
    if (!purgeTarget) return;
    setPurging(true);
    try {
      const results = await Promise.allSettled(
        purgeTarget.ids.map((id) => api.websites.purge(apiClient, id)),
      );
      const failed = results.filter((result) => result.status === "rejected");
      if (failed.length > 0) {
        throw new Error(
          `${failed.length} of ${results.length} websites could not be deleted forever - ${recycleBinError(
            (failed[0] as PromiseRejectedResult).reason,
            "the backend refused the request",
          )}`,
        );
      }
      toast.push(
        purgeTarget.ids.length === 1
          ? `${purgeTarget.label} deleted forever - its opportunities and tasks are gone`
          : `${purgeTarget.ids.length} websites deleted forever - their opportunities and tasks are gone`,
        "success",
      );
      setPurgeTarget(null);
      setSelected([]);
      refreshAll();
    } catch (err) {
      toast.push(recycleBinError(err, "The websites could not be deleted forever"), "error");
    } finally {
      setPurging(false);
    }
  };

  /** Brings one removed website back into the list. */
  const restoreOne = async (row: WebsiteListItem) => {
    setRestoringId(row.id);
    try {
      await api.websites.restore(apiClient, row.id);
      toast.push(`${row.name} restored - it is back in the list with its history`, "success");
      refreshAll();
    } catch (err) {
      toast.push(recycleBinError(err, "The website could not be restored"), "error");
    } finally {
      setRestoringId(null);
    }
  };

  /** Brings the selected websites back into the list. */
  const restoreSelected = async () => {
    if (selected.length === 0) return;
    const ids = [...selected];
    const outcome = await action.run(async () => {
      const results = await Promise.allSettled(
        ids.map((id) => api.websites.restore(apiClient, id)),
      );
      const failed = results.filter((result) => result.status === "rejected");
      if (failed.length > 0) {
        throw new Error(
          `${failed.length} of ${results.length} websites could not be restored - ${recycleBinError(
            (failed[0] as PromiseRejectedResult).reason,
            "the backend refused the request",
          )}`,
        );
      }
      return results.length;
    });
    if (outcome.ok) {
      toast.push(
        `${outcome.data ?? 0} website(s) restored - they are back in the list with their history`,
        "success",
      );
      setSelected([]);
      refreshAll();
    } else {
      toast.push(recycleBinError(outcome.error, "The websites could not be restored"), "error");
    }
  };

  const runImport = async (file: File) => {
    setImportError(null);
    setImportResult(null);
    setImporting(true);
    try {
      const fields: Record<string, string> = {};
      if (importCategory) fields.category = importCategory;
      if (importNiche) fields.niche = importNiche;
      if (importStatus) fields.status = importStatus;
      const result = await api.websites.importFile(apiClient, file, fields);
      setImportResult(result);
      toast.push(
        `${result.created} created, ${result.updated} updated, ${result.invalid} invalid`,
        "success",
      );
      refreshAll();
    } catch (err) {
      setImportError(errorMessage(err));
    } finally {
      setImporting(false);
    }
  };

  /* ---------------------------------------------------------------- */
  /* Render                                                            */
  /* ---------------------------------------------------------------- */

  return (
    <Card>
      <Toolbar>
        <Field label="Search" className="w-56">
          <Input
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(1);
            }}
            placeholder="Name, domain or notes"
          />
        </Field>
        <Field label="Category" className="w-48">
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
        <Field label="Niche" className="w-44">
          <Input
            value={niche}
            onChange={(event) => {
              setNiche(event.target.value);
              setPage(1);
            }}
            placeholder="e.g. saas"
            list="website-niches"
          />
        </Field>
        <datalist id="website-niches">
          {knownNiches.map((value) => (
            <option key={value} value={value} />
          ))}
        </datalist>
        <Field label="Status" className="w-44">
          <Select
            value={binOpen ? REMOVED_WEBSITE_STATUS : status}
            disabled={binOpen}
            aria-label="Filter the websites by their status"
            onChange={(event) => {
              setStatus(event.target.value);
              setPage(1);
            }}
          >
            <option value="">All statuses</option>
            {binOpen ? (
              <option value={REMOVED_WEBSITE_STATUS}>{REMOVED_WEBSITE_LABEL}</option>
            ) : null}
            {WEBSITE_STATUS_FILTERS.map((value) => (
              <option key={value} value={value}>
                {WEBSITE_STATUS_LABELS[value] ?? value}
              </option>
            ))}
          </Select>
        </Field>
        <div className="flex flex-col gap-1">
          <span className="text-xs font-medium text-content-muted">Recycle bin</span>
          <button
            type="button"
            onClick={() => {
              setBinOpen((previous) => !previous);
              setPage(1);
            }}
            aria-pressed={binOpen}
            aria-label={
              binOpen
                ? "Close the recycle bin and show the active websites again"
                : "Show the removed websites (the recycle bin)"
            }
            className={`inline-flex h-9 items-center gap-2 rounded-md border px-3 text-sm font-medium transition-colors ${
              binOpen
                ? "border-accent bg-accent-soft text-accent"
                : "border-line-strong bg-surface text-content-muted hover:text-content"
            }`}
          >
            <span>Deleted</span>
            <span className="rounded-full bg-surface-sunken px-1.5 py-0.5 text-[11px] text-content-muted">
              {removed.data?.total ?? 0}
            </span>
          </button>
        </div>
        {showProjectFilter ? (
          <Field label="Project" className="w-52">
            <Select
              value={projectFilter}
              onChange={(event) => {
                setProjectFilter(event.target.value);
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
        ) : null}
        {filtersActive ? (
          <Button variant="ghost" size="sm" onClick={resetFilters}>
            Reset filters
          </Button>
        ) : null}
        <div className="ml-auto flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setImportResult(null);
              setImportError(null);
              setImportOpen(true);
            }}
          >
            Import from Excel
          </Button>
          <Button
            size="sm"
            onClick={() => {
              setAddError(null);
              setAddForm(EMPTY_ADD_FORM);
              setAddOpen(true);
            }}
          >
            Add website
          </Button>
        </div>
      </Toolbar>

      <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
        <span className="text-xs text-content-muted">{selected.length} selected</span>
        {binOpen ? (
          <>
            <Button
              size="sm"
              disabled={selected.length === 0}
              onClick={() => void restoreSelected()}
              loading={action.pending}
              title={
                selected.length === 0
                  ? "Select at least one website first"
                  : "Bring the selected websites back into the list"
              }
            >
              Restore selected
            </Button>
            <Button
              size="sm"
              variant="danger"
              disabled={selected.length === 0}
              onClick={() =>
                setPurgeTarget({
                  ids: [...selected],
                  label: `${selected.length} websites`,
                  names: selected
                    .map((id) => rows.find((row) => row.id === id)?.name ?? id)
                    .slice(0, 5),
                })
              }
              title={
                selected.length === 0
                  ? "Select at least one website first"
                  : "Delete the selected websites forever - this cannot be undone"
              }
            >
              Delete forever
            </Button>
          </>
        ) : (
          <>
            <Select
              className="w-48"
              value={bulkStatus}
              onChange={(event) => setBulkStatus(event.target.value)}
              aria-label="Status for the selected websites"
              disabled={selected.length === 0}
            >
              <option value="">Set status…</option>
              {WEBSITE_STATUS_CHOICES.map((value) => (
                <option key={value} value={value}>
                  {WEBSITE_STATUS_LABELS[value] ?? value}
                </option>
              ))}
            </Select>
            <Button
              size="sm"
              variant="outline"
              disabled={selected.length === 0 || !bulkStatus}
              onClick={() => void applyBulkStatus()}
              loading={action.pending}
              title={
                selected.length === 0
                  ? "Select at least one website first"
                  : !bulkStatus
                    ? "Choose the status the selected websites should get"
                    : undefined
              }
            >
              Apply status
            </Button>
            <Button
              size="sm"
              variant="danger"
              disabled={selected.length === 0}
              onClick={() =>
                setDeleteTarget({
                  ids: [...selected],
                  label: `${selected.length} websites`,
                  names: selected
                    .map((id) => rows.find((row) => row.id === id)?.name ?? id)
                    .slice(0, 5),
                })
              }
              title={
                selected.length === 0
                  ? "Select at least one website first"
                  : "Remove the selected websites from the list"
              }
            >
              Delete selected
            </Button>
          </>
        )}
      </div>

      {action.error ? (
        <div className="px-3 pt-3">
          <Alert tone="danger" title="The action failed">
            {errorMessage(action.error)}
          </Alert>
        </div>
      ) : null}

      {stats.error ? (
        <div className="px-3 pt-3">
          <Alert
            tone={statsUnavailable ? "neutral" : "danger"}
            title={
              statsUnavailable
                ? "The statistics endpoint is not available yet"
                : "The statistics could not be loaded"
            }
            action={
              <Button variant="outline" size="sm" onClick={stats.reload}>
                Try again
              </Button>
            }
          >
            {statsUnavailable ? (
              <>
                The backend answered 404 for{" "}
                <code className="font-mono text-[11px]">GET /api/v1/websites/stats</code>. The
                counters of the list record itself are shown instead.
              </>
            ) : (
              errorMessage(stats.error)
            )}
          </Alert>
        </div>
      ) : null}

      <CardBody className="p-0">
        <AsyncSection
          loading={websites.loading}
          error={websites.error}
          data={websites.data}
          onRetry={websites.reload}
          isEmpty={rows.length === 0}
          emptyTitle={
            binOpen ? "The recycle bin is empty" : "No websites match these filters"
          }
          emptyDescription={
            binOpen
              ? "Every website that was removed from the list waits here until it is restored or deleted forever."
              : "Add a website by hand, import a spreadsheet or adjust the filters."
          }
          skeleton={<TableSkeleton rows={8} columns={10} />}
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
                  <button
                    type="button"
                    onClick={() => toggleSort("name")}
                    className="font-semibold uppercase"
                  >
                    Name{sortIndicator("name")}
                  </button>
                </Th>
                <Th className="w-44">
                  <button
                    type="button"
                    onClick={() => toggleSort("domain")}
                    className="font-semibold uppercase"
                  >
                    Domain{sortIndicator("domain")}
                  </button>
                </Th>
                <Th className="w-32">Category</Th>
                <Th className="w-24">Niche</Th>
                <Th className="w-44">
                  <button
                    type="button"
                    onClick={() => toggleSort("status")}
                    className="font-semibold uppercase"
                  >
                    Status{sortIndicator("status")}
                  </button>
                </Th>
                <Th className="w-20">Projects</Th>
                <Th className="w-16 text-right">Submitted</Th>
                <Th className="w-16 text-right">Verified</Th>
                <Th className="w-16 text-right">Failed</Th>
                <Th className="w-16 text-right">Pending</Th>
                <Th className="w-44">Notes</Th>
                <Th className={binOpen ? "w-44" : "w-28"}>Actions</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const counters = readCounters(statsFor(row) ?? row.stats);
                const projectIds = row.project_ids ?? [];
                const projectLabel =
                  projectIds.length === 0
                    ? "Not linked to a project"
                    : projectIds
                        .map((id) => projectNames.get(id) ?? id)
                        .join(", ");
                const removedRow = isRemovedWebsite(row.status);
                return (
                  <tr key={row.id} className={removedRow ? "opacity-60" : undefined}>
                    <Td>
                      <input
                        type="checkbox"
                        aria-label={`Select ${row.name}`}
                        checked={selected.includes(row.id)}
                        onChange={() => toggleOne(row.id)}
                      />
                    </Td>
                    <Td>
                      <p className="font-medium text-content">{row.name}</p>
                      <p className="max-w-xs truncate text-xs text-content-muted">
                        {row.opportunity_url}
                      </p>
                    </Td>
                    <Td className="text-xs">
                      <p className="max-w-[10rem] truncate">{row.domain}</p>
                    </Td>
                    <Td>
                      <Badge tone="neutral">
                        {CATEGORY_LABELS[row.category] ?? humanize(row.category)}
                      </Badge>
                    </Td>
                    <Td className="text-xs">{row.niche || "—"}</Td>
                    <Td>
                      {removedRow ? (
                        <Badge tone="neutral">{REMOVED_WEBSITE_LABEL}</Badge>
                      ) : (
                        <Select
                          className="h-8 w-40 text-xs"
                          value={row.status}
                          onChange={(event) => void changeStatus(row, event.target.value)}
                          aria-label={`Status of ${row.name}`}
                        >
                          {!WEBSITE_STATUS_CHOICES.includes(
                            row.status as (typeof WEBSITE_STATUS_CHOICES)[number],
                          ) ? (
                            <option value={row.status}>
                              {WEBSITE_STATUS_LABELS[row.status] ?? row.status}
                            </option>
                          ) : null}
                          {WEBSITE_STATUS_CHOICES.map((value) => (
                            <option key={value} value={value}>
                              {WEBSITE_STATUS_LABELS[value] ?? value}
                            </option>
                          ))}
                        </Select>
                      )}
                    </Td>
                    <Td>
                      <Tooltip label={projectLabel}>
                        <span>
                          <Badge tone={projectIds.length > 0 ? "info" : "neutral"}>
                            {formatNumber(projectIds.length)}
                          </Badge>
                        </span>
                      </Tooltip>
                    </Td>
                    <Td className="text-right tabular-nums">
                      {stats.loading && !stats.data ? (
                        <Skeleton className="ml-auto h-4 w-8" />
                      ) : (
                        (counters?.submitted ?? "—")
                      )}
                    </Td>
                    <Td className="text-right tabular-nums">
                      {stats.loading && !stats.data ? (
                        <Skeleton className="ml-auto h-4 w-8" />
                      ) : (
                        (counters?.verified ?? "—")
                      )}
                    </Td>
                    <Td className="text-right tabular-nums">
                      {stats.loading && !stats.data ? (
                        <Skeleton className="ml-auto h-4 w-8" />
                      ) : (
                        (counters?.failed ?? "—")
                      )}
                    </Td>
                    <Td className="text-right tabular-nums">
                      {stats.loading && !stats.data ? (
                        <Skeleton className="ml-auto h-4 w-8" />
                      ) : (
                        (counters?.pending ?? "—")
                      )}
                    </Td>
                    <Td>
                      <button
                        type="button"
                        onClick={() => openEdit(row)}
                        className="max-w-full truncate text-left text-xs text-content-muted hover:text-content hover:underline"
                        title={row.notes ?? "Add a note"}
                      >
                        {row.notes || "Add a note"}
                      </button>
                    </Td>
                    <Td>
                      <div className="flex items-center gap-1">
                        {removedRow ? (
                          <>
                            <Button
                              size="sm"
                              variant="outline"
                              loading={restoringId === row.id}
                              onClick={() => void restoreOne(row)}
                              title={`Bring ${row.name} back into the list`}
                            >
                              Restore
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() =>
                                setPurgeTarget({
                                  ids: [row.id],
                                  label: row.name,
                                  names: [row.name],
                                })
                              }
                              title={`Delete ${row.name} forever - this cannot be undone`}
                            >
                              Delete forever
                            </Button>
                          </>
                        ) : (
                          <>
                            <Button size="sm" variant="ghost" onClick={() => openEdit(row)}>
                              Edit
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() =>
                                setDeleteTarget({
                                  ids: [row.id],
                                  label: row.name,
                                  names: [row.name],
                                })
                              }
                              title={`Remove ${row.name} from the list`}
                            >
                              Delete
                            </Button>
                          </>
                        )}
                      </div>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
          {websites.data ? (
            <Pagination
              page={websites.data.page}
              pages={websites.data.pages}
              total={websites.data.total}
              onPageChange={setPage}
            />
          ) : null}
        </AsyncSection>
      </CardBody>

      {/* ---------------------------------------------------------------- */}
      {/* Add website                                                       */}
      {/* ---------------------------------------------------------------- */}
      <Dialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        title="Add a website"
        description="The site where the backlink should be placed. It lives in the central list until a project picks it."
        width="lg"
        footer={
          <>
            <Button variant="outline" onClick={() => setAddOpen(false)} disabled={adding}>
              Cancel
            </Button>
            <Button loading={adding} onClick={() => void submitAdd()}>
              Add to the list
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
            label="Website URL"
            required
            hint="The page that accepts the listing - for example https://example.com/add-your-business"
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
                onChange={(event) =>
                  setAddForm((prev) => ({ ...prev, category: event.target.value }))
                }
              >
                {ALL_OPPORTUNITY_CATEGORIES.map((value) => (
                  <option key={value} value={value}>
                    {CATEGORY_LABELS[value] ?? value}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Niche" hint="Free text - used to filter the list and to pick sites for a project">
              <Input
                value={addForm.niche}
                onChange={(event) => setAddForm((prev) => ({ ...prev, niche: event.target.value }))}
                placeholder="saas"
              />
            </Field>
            <Field label="Submission method" hint="How the backlink is placed on this site">
              <Select
                value={addForm.submission_method}
                onChange={(event) =>
                  setAddForm((prev) => ({ ...prev, submission_method: event.target.value }))
                }
              >
                {Object.keys(SUBMISSION_METHOD_LABELS).map((value) => (
                  <option key={value} value={value}>
                    {SUBMISSION_METHOD_LABELS[value] ?? value}
                  </option>
                ))}
              </Select>
            </Field>
          </div>

          <Field label="Notes" hint="Free text - why this site is worth it, what happened to it">
            <Textarea
              rows={3}
              value={addForm.notes}
              onChange={(event) => setAddForm((prev) => ({ ...prev, notes: event.target.value }))}
              placeholder="Accepts listings without a captcha."
            />
          </Field>
        </div>
      </Dialog>

      {/* ---------------------------------------------------------------- */}
      {/* Edit website                                                      */}
      {/* ---------------------------------------------------------------- */}
      <Dialog
        open={editItem !== null}
        onClose={() => setEditItem(null)}
        title={editItem ? `Edit ${editItem.name}` : "Edit website"}
        description="Change the name, the classification, the status or the notes of the website."
        width="md"
        footer={
          <>
            <Button variant="outline" onClick={() => setEditItem(null)} disabled={saving}>
              Cancel
            </Button>
            <Button loading={saving} onClick={() => void submitEdit()}>
              Save
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          {editError ? (
            <p className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-xs text-danger">
              {editError}
            </p>
          ) : null}

          <Field label="Name">
            <Input
              value={editForm.name}
              onChange={(event) =>
                setEditForm((prev) => ({ ...prev, name: event.target.value }))
              }
            />
          </Field>

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Category">
              <Select
                value={editForm.category}
                onChange={(event) =>
                  setEditForm((prev) => ({ ...prev, category: event.target.value }))
                }
              >
                <option value="">No category</option>
                {ALL_OPPORTUNITY_CATEGORIES.map((value) => (
                  <option key={value} value={value}>
                    {CATEGORY_LABELS[value] ?? value}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Niche">
              <Input
                value={editForm.niche}
                onChange={(event) =>
                  setEditForm((prev) => ({ ...prev, niche: event.target.value }))
                }
              />
            </Field>
          </div>

          <Field
            label="Status"
            hint="Mark a site that stopped working as &quot;not working&quot;. A website that leaves the list is removed with the delete action."
          >
            <Select
              value={editForm.status}
              onChange={(event) =>
                setEditForm((prev) => ({ ...prev, status: event.target.value }))
              }
            >
              {WEBSITE_STATUS_FILTERS.map((value) => (
                <option key={value} value={value}>
                  {WEBSITE_STATUS_LABELS[value] ?? value}
                </option>
              ))}
            </Select>
          </Field>

          <Field label="Notes">
            <Textarea
              rows={4}
              value={editForm.notes}
              onChange={(event) =>
                setEditForm((prev) => ({ ...prev, notes: event.target.value }))
              }
              placeholder="Why this site is worth it, what happened to it"
            />
          </Field>
        </div>
      </Dialog>

      {/* ---------------------------------------------------------------- */}
      {/* Import                                                            */}
      {/* ---------------------------------------------------------------- */}
      <Dialog
        open={importOpen}
        onClose={() => setImportOpen(false)}
        title="Import websites"
        description="Upload a CSV or XLSX file with the websites. The rows are added to the central list."
        width="lg"
        footer={
          <Button variant="outline" onClick={() => setImportOpen(false)}>
            Close
          </Button>
        }
      >
        <div className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Category" hint="Applied to every row that has no category.">
              <Select
                value={importCategory}
                onChange={(event) => setImportCategory(event.target.value)}
              >
                <option value="">Keep the value of the file</option>
                {ALL_OPPORTUNITY_CATEGORIES.map((value) => (
                  <option key={value} value={value}>
                    {CATEGORY_LABELS[value] ?? value}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Niche" hint="Applied to every row that has no niche.">
              <Input
                value={importNiche}
                onChange={(event) => setImportNiche(event.target.value)}
                placeholder="saas"
              />
            </Field>
            <Field label="Status" hint="The state the imported rows get.">
              <Select value={importStatus} onChange={(event) => setImportStatus(event.target.value)}>
                <option value="">Keep the value of the file</option>
                {WEBSITE_STATUS_FILTERS.map((value) => (
                  <option key={value} value={value}>
                    {WEBSITE_STATUS_LABELS[value] ?? value}
                  </option>
                ))}
              </Select>
            </Field>
          </div>

          <div
            onDragOver={(event) => {
              event.preventDefault();
              setDragActive(true);
            }}
            onDragLeave={() => setDragActive(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragActive(false);
              const file = event.dataTransfer.files?.[0];
              if (file) void runImport(file);
            }}
            className={`flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed p-6 text-center transition-colors ${
              dragActive ? "border-accent bg-accent-soft" : "border-line bg-surface-raised"
            }`}
          >
            <p className="text-sm text-content">Drop a file here or choose one</p>
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,.xlsx,.xls"
              className="sr-only"
              id="website-import-file"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void runImport(file);
                event.target.value = "";
              }}
            />
            <Button
              type="button"
              variant="outline"
              loading={importing}
              onClick={() => fileInputRef.current?.click()}
            >
              Choose file
            </Button>
            <p className="text-xs text-content-subtle">
              The first column should hold the URL of the website.
            </p>
          </div>

          {importError ? (
            <Alert tone="danger" title="The import failed">
              {importError}
            </Alert>
          ) : null}

          {importResult ? (
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="success">{importResult.created} created</Badge>
                <Badge tone="info">{importResult.updated} updated</Badge>
                <Badge tone="neutral">{importResult.skipped} skipped</Badge>
                <Badge tone={importResult.invalid > 0 ? "danger" : "neutral"}>
                  {importResult.invalid} invalid
                </Badge>
              </div>

              {importResult.rows.length === 0 ? (
                <p className="text-xs text-content-subtle">
                  The backend did not report any row of the file.
                </p>
              ) : (
                <Table>
                  <thead>
                    <tr>
                      <Th className="w-20">Row</Th>
                      <Th className="w-28">Action</Th>
                      <Th className="w-48">Domain</Th>
                      <Th>Reason</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {importResult.rows.map((row) => {
                      const action = (row.action ?? "").toUpperCase();
                      return (
                        <tr key={`${row.row}-${row.domain}-${row.action}`}>
                          <Td className="tabular-nums">{row.row}</Td>
                          <Td>
                            <Badge
                              tone={
                                action === "INVALID"
                                  ? "danger"
                                  : action === "CREATED"
                                    ? "success"
                                    : action === "UPDATED"
                                      ? "info"
                                      : "neutral"
                              }
                            >
                              {action}
                            </Badge>
                          </Td>
                          <Td className="text-xs">{row.domain || "—"}</Td>
                          <Td className="text-xs text-content-muted">{row.reason || "—"}</Td>
                        </tr>
                      );
                    })}
                  </tbody>
                </Table>
              )}
            </div>
          ) : null}
        </div>
      </Dialog>

      {/* ---------------------------------------------------------------- */}
      {/* Delete - the website leaves the list, its history stays             */}
      {/* ---------------------------------------------------------------- */}
      <Dialog
        open={deleteTarget !== null}
        onClose={() => setDeleteTarget(null)}
        title={
          deleteTarget && deleteTarget.ids.length > 1
            ? `Remove ${deleteTarget.ids.length} websites from the list?`
            : deleteTarget
              ? `Remove "${deleteTarget.label}" from the list?`
              : "Remove the website from the list?"
        }
        description="The website leaves the central list and every project that uses it."
        width="md"
        footer={
          <>
            <Button variant="outline" onClick={() => setDeleteTarget(null)} disabled={deleting}>
              Cancel
            </Button>
            <Button
              variant="danger"
              disabled={deleting}
              onClick={() => {
                setPurgeTarget(deleteTarget);
                setDeleteTarget(null);
              }}
              title="Delete the website together with its history - this cannot be undone"
            >
              Delete forever
            </Button>
            <Button loading={deleting} onClick={() => void confirmDelete()}>
              Move to the recycle bin
            </Button>
          </>
        }
      >
        <ul className="space-y-1.5 text-xs text-content-muted">
          <li>
            • The website is removed from the list and from every project that uses it.
          </li>
          <li>
            • Its opportunities, its tasks and its verification records are{" "}
            <strong className="font-semibold text-content">kept</strong> - the old reports stay
            correct.
          </li>
          <li>
            • You can bring it back at any time with the{" "}
            <strong className="font-semibold text-content">Deleted</strong> filter (the recycle
            bin).
          </li>
        </ul>
        <p className="mt-3 text-xs text-content-muted">
          Do you want it to be gone for good? Then use{" "}
          <strong className="font-semibold text-content">Delete forever</strong>: the website, its
          opportunities, its tasks and its verification records are destroyed and nothing can bring
          them back.
        </p>
        <p className="mt-2 text-xs text-content-subtle">
          A website that only stopped working is better marked as &quot;not working&quot; than
          removed - the list keeps it and the project picks it again when it works.
        </p>
      </Dialog>

      {/* ---------------------------------------------------------------- */}
      {/* Delete forever - the website and its history are destroyed         */}
      {/* ---------------------------------------------------------------- */}
      <ConfirmDialog
        open={purgeTarget !== null}
        title={
          purgeTarget && purgeTarget.ids.length > 1
            ? `Delete ${purgeTarget.ids.length} websites forever?`
            : purgeTarget
              ? `Delete "${purgeTarget.label}" forever?`
              : "Delete the website forever?"
        }
        description="This cannot be undone."
        confirmLabel="Delete forever"
        destructive
        pending={purging}
        onClose={() => setPurgeTarget(null)}
        onConfirm={() => void confirmPurge()}
      >
        <p className="text-xs text-content-muted">
          {purgeTarget && purgeTarget.ids.length === 1 ? (
            <>
              <strong className="font-semibold text-content">{purgeTarget.label}</strong> is
              deleted forever. Its opportunities, its tasks and its verification records go with it
              and the old reports lose this website. There is no way to undo this.
            </>
          ) : (
            <>
              These {purgeTarget?.ids.length ?? 0} websites are deleted forever. Their
              opportunities, their tasks and their verification records go with them and the old
              reports lose them. There is no way to undo this.
            </>
          )}
        </p>
        {purgeTarget && purgeTarget.names.length > 0 ? (
          <ul className="mt-2 space-y-0.5 text-xs text-content-subtle">
            {purgeTarget.names.map((name) => (
              <li key={name}>• {name}</li>
            ))}
          </ul>
        ) : null}
      </ConfirmDialog>
    </Card>
  );
}
