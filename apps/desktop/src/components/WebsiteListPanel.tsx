import * as React from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Checkbox,
  Dialog,
  Field,
  Input,
  Pagination,
  Select,
  Table,
  Td,
  Th,
  Textarea,
  useToast,
} from "@autobacklinker/ui";
import { isMissingEndpoint } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import { ErrorBlock, LoadingBlock, NothingYet } from "./common";
import { formatDate, formatNumber, truncate } from "../lib/format";
import {
  NativeUnavailableError,
  pickFile,
  readFileBytes,
  sendNativeNotification,
} from "../lib/backend";
import {
  REMOVED_WEBSITE_LABEL,
  REMOVED_WEBSITE_STATUS,
  WEBSITE_STATUS_FILTERS,
  createWebsite,
  fetchWebsiteStats,
  fetchWebsites,
  importWebsites,
  isRemovedWebsite,
  purgeWebsite,
  removeWebsite,
  restoreWebsite,
  updateWebsite,
  websiteStatusLabel,
  websiteStatusOptions,
  type WebsiteImportInput,
} from "../lib/websites";
import type { Project } from "@autobacklinker/shared-types";
import type { WebsiteStatsRow } from "@autobacklinker/api-client";

/**
 * The central website list.
 *
 * The panel owns the table, the selection and the dialogs (add, import,
 * delete).  The page around it owns the filters - they are shown above the
 * table and the panel reloads itself whenever they change.
 *
 * The deletion has two steps: "Delete" takes the website out of the list and
 * keeps its history (the reports stay correct), "Delete forever" destroys the
 * website together with its opportunities and its tasks.  The removed websites
 * wait in the recycle bin (the "Deleted" filter) until they are restored or
 * deleted forever.
 */

const PAGE_SIZE = 25;

const SPREADSHEET_FILTERS = [
  { name: "Excel", extensions: ["xlsx", "xls"] },
  { name: "CSV", extensions: ["csv"] },
];

export interface WebsiteListFilters {
  search: string;
  category: string;
  niche: string;
  status: string;
  project_id: string;
  /** The recycle bin is open - the list shows the removed websites only. */
  removed: boolean;
}

export const EMPTY_WEBSITE_FILTERS: WebsiteListFilters = {
  search: "",
  category: "",
  niche: "",
  status: "",
  project_id: "",
  removed: false,
};

function errorText(error: unknown, fallback: string): string {
  if (error && typeof error === "object" && "message" in error) {
    return String((error as { message: unknown }).message);
  }
  return fallback;
}

/**
 * The message of a failed recycle bin action.
 *
 * A 404 means either that the website is gone already or that the local
 * backend does not know the recycle bin yet - both are told instead of a bare
 * "Not Found".
 */
function recycleBinError(error: unknown, fallback: string): string {
  if (isMissingEndpoint(error)) {
    return "The backend answered 404 - the website may be gone already or the local backend does not know the recycle bin yet.";
  }
  return errorText(error, fallback);
}

/** The name of a file with its content type. */
function fileType(name: string): string {
  if (name.toLowerCase().endsWith(".csv")) return "text/csv";
  return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
}

/**
 * Opens the native picker of the desktop build and reads the file.
 *
 * The browser preview (the plain `npm run dev`) has no native picker - there
 * the file is chosen with the file input of the browser.
 */
async function pickSpreadsheet(): Promise<File | null> {
  try {
    const path = await pickFile(SPREADSHEET_FILTERS);
    if (!path) return null;
    const bytes = await readFileBytes(path);
    const name = path.split(/[\\/]/).pop() ?? path;
    const blob = new Blob([bytes.slice().buffer], { type: fileType(name) });
    return new File([blob], name, { type: blob.type });
  } catch (err) {
    if (err instanceof NativeUnavailableError) return pickWithBrowserInput();
    throw err;
  }
}

/** The file input of the browser - the fallback of the native picker. */
function pickWithBrowserInput(): Promise<File | null> {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".xlsx,.xls,.csv";
    input.onchange = () => resolve(input.files?.[0] ?? null);
    input.oncancel = () => resolve(null);
    input.click();
  });
}

/* ------------------------------------------------------------------ */
/* The table                                                           */
/* ------------------------------------------------------------------ */

export function WebsiteListPanel({
  filters,
  onFiltersChange,
  onRemovedCountChange,
  projects,
  addOpen,
  onAddOpenChange,
  importOpen,
  onImportOpenChange,
}: {
  filters: WebsiteListFilters;
  onFiltersChange: (filters: WebsiteListFilters) => void;
  /** Reports how many websites wait in the recycle bin (the badge of the chip). */
  onRemovedCountChange?: (count: number) => void;
  projects: Project[];
  /** The "add a website" dialog is opened by the page. */
  addOpen: boolean;
  onAddOpenChange: (open: boolean) => void;
  /** The "import from a spreadsheet" dialog is opened by the page. */
  importOpen: boolean;
  onImportOpenChange: (open: boolean) => void;
}) {
  const toast = useToast();
  const [page, setPage] = React.useState(1);
  const [selected, setSelected] = React.useState<string[]>([]);
  const [bulkStatus, setBulkStatus] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [savingId, setSavingId] = React.useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = React.useState<string[] | null>(null);
  const [purgeTarget, setPurgeTarget] = React.useState<string[] | null>(null);
  const [restoringId, setRestoringId] = React.useState<string | null>(null);

  const filterKey = `${filters.search}|${filters.category}|${filters.niche}|${filters.status}|${filters.project_id}|${filters.removed}`;

  // A new filter always starts at the first page.
  React.useEffect(() => {
    setPage(1);
    setSelected([]);
  }, [filterKey]);

  const websites = useAsync(
    () =>
      fetchWebsites({
        page,
        page_size: PAGE_SIZE,
        search: filters.search,
        category: filters.category,
        niche: filters.niche,
        // The recycle bin shows the removed websites - the normal list hides them.
        status: filters.removed ? REMOVED_WEBSITE_STATUS : filters.status,
        project_id: filters.project_id,
      }),
    [page, filterKey],
  );

  // The counters of the websites.  The endpoint is newer than the list - when
  // it is missing the list answers with its own counters.
  const stats = useAsync(
    () => fetchWebsiteStats(filters.project_id || undefined),
    [filters.project_id],
  );

  // How many websites wait in the recycle bin.
  const removedList = useAsync(
    () => fetchWebsites({ page: 1, page_size: 1, status: REMOVED_WEBSITE_STATUS }),
    [],
  );

  React.useEffect(() => {
    if (!removedList.data) return;
    onRemovedCountChange?.(removedList.data.total);
  }, [removedList.data, onRemovedCountChange]);

  const items = websites.data?.items ?? [];

  const statsByDomain = React.useMemo(() => {
    const map = new Map<string, WebsiteStatsRow>();
    (stats.data ?? []).forEach((row) => {
      if (row.domain) map.set(row.domain.toLowerCase(), row);
    });
    return map;
  }, [stats.data]);

  const projectNames = React.useMemo(() => {
    const map = new Map<string, string>();
    projects.forEach((project) => map.set(project.id, project.name));
    return map;
  }, [projects]);

  const knownCategories = React.useMemo(() => {
    const values = new Set<string>();
    items.forEach((item) => {
      if (item.category) values.add(item.category);
    });
    (stats.data ?? []).forEach((row) => {
      if (row.category) values.add(row.category);
    });
    return Array.from(values).sort();
  }, [items, stats.data]);

  function toggle(id: string) {
    setSelected((previous) =>
      previous.includes(id)
        ? previous.filter((item) => item !== id)
        : [...previous, id],
    );
  }

  async function changeStatus(id: string, status: string, name: string) {
    setSavingId(id);
    try {
      await updateWebsite(id, { status });
      toast.push(`${name} is now "${websiteStatusLabel(status)}"`, "success");
      websites.reload();
    } catch (err) {
      toast.push(
        errorText(err, "Could not change the state of the website"),
        "error",
      );
      websites.reload();
    } finally {
      setSavingId(null);
    }
  }

  async function applyBulkStatus() {
    if (!bulkStatus || selected.length === 0) return;
    setBusy(true);
    let changed = 0;
    let failed = 0;
    for (const id of selected) {
      try {
        await updateWebsite(id, { status: bulkStatus });
        changed += 1;
      } catch {
        failed += 1;
      }
    }
    setBusy(false);
    if (failed === 0) {
      toast.push(
        `${changed} website${changed === 1 ? "" : "s"} set to "${websiteStatusLabel(bulkStatus)}"`,
        "success",
      );
    } else {
      toast.push(
        `${changed} website${changed === 1 ? "" : "s"} changed, ${failed} failed`,
        "error",
      );
    }
    setSelected([]);
    setBulkStatus("");
    websites.reload();
  }

  /**
   * Takes the websites out of the list - their history stays in the database.
   *
   * The website disappears from the list and from every project that uses it,
   * but its opportunities, its tasks and its verification records stay: the
   * old reports remain truthful and the website can be restored.
   */
  async function confirmDelete() {
    if (!deleteTarget || deleteTarget.length === 0) return;
    setBusy(true);
    let removedCount = 0;
    let failed = 0;
    let lastError: unknown = null;
    for (const id of deleteTarget) {
      try {
        await removeWebsite(id);
        removedCount += 1;
      } catch (err) {
        failed += 1;
        lastError = err;
      }
    }
    setBusy(false);
    setDeleteTarget(null);
    if (failed === 0) {
      toast.push(
        `${removedCount} website${removedCount === 1 ? "" : "s"} removed from the list - restore ${removedCount === 1 ? "it" : "them"} with the "Deleted" filter`,
        "success",
      );
      void sendNativeNotification(
        "Auto Backlinker",
        `${removedCount} website${removedCount === 1 ? " was" : "s were"} removed from the website list. The history is kept and the website can be restored.`,
      );
    } else {
      toast.push(
        `${removedCount} removed, ${failed} could not be removed - ${errorText(
          lastError,
          "the backend refused the request",
        )}`,
        "error",
      );
    }
    setSelected([]);
    websites.reload();
    removedList.reload();
  }

  /**
   * Deletes the websites forever - the website, its opportunities and its
   * tasks are gone.  This cannot be undone.
   */
  async function confirmPurge() {
    if (!purgeTarget || purgeTarget.length === 0) return;
    setBusy(true);
    let purged = 0;
    let failed = 0;
    let lastError: unknown = null;
    for (const id of purgeTarget) {
      try {
        await purgeWebsite(id);
        purged += 1;
      } catch (err) {
        failed += 1;
        lastError = err;
      }
    }
    setBusy(false);
    setPurgeTarget(null);
    if (failed === 0) {
      toast.push(
        `${purged} website${purged === 1 ? "" : "s"} deleted forever - the opportunities and the tasks are gone`,
        "success",
      );
      void sendNativeNotification(
        "Auto Backlinker",
        `${purged} website${purged === 1 ? " was" : "s were"} deleted forever. The opportunities and the tasks went with ${purged === 1 ? "it" : "them"}.`,
      );
    } else {
      toast.push(
        `${purged} deleted forever, ${failed} could not be deleted - ${recycleBinError(
          lastError,
          "the backend refused the request",
        )}`,
        "error",
      );
    }
    setSelected([]);
    websites.reload();
    removedList.reload();
  }

  /** Brings one removed website back into the list. */
  async function restoreOne(id: string, name: string) {
    setRestoringId(id);
    try {
      await restoreWebsite(id);
      toast.push(
        `${name} restored - it is back in the list with its history`,
        "success",
      );
      websites.reload();
      removedList.reload();
    } catch (err) {
      toast.push(
        recycleBinError(err, "Could not restore the website"),
        "error",
      );
    } finally {
      setRestoringId(null);
    }
  }

  /** Brings the selected websites back into the list. */
  async function restoreSelected() {
    if (selected.length === 0) return;
    const ids = [...selected];
    setBusy(true);
    let restored = 0;
    let failed = 0;
    let lastError: unknown = null;
    for (const id of ids) {
      try {
        await restoreWebsite(id);
        restored += 1;
      } catch (err) {
        failed += 1;
        lastError = err;
      }
    }
    setBusy(false);
    if (failed === 0) {
      toast.push(
        `${restored} website${restored === 1 ? "" : "s"} restored - ${restored === 1 ? "it is" : "they are"} back in the list with ${restored === 1 ? "its" : "their"} history`,
        "success",
      );
    } else {
      toast.push(
        `${restored} restored, ${failed} could not be restored - ${recycleBinError(
          lastError,
          "the backend refused the request",
        )}`,
        "error",
      );
    }
    setSelected([]);
    websites.reload();
    removedList.reload();
  }

  const missingEndpoint = Boolean(websites.error) && isMissingEndpoint(websites.error);

  return (
    <Card>
      <CardHeader
        title={filters.removed ? "Recycle bin" : "Websites"}
        description={
          filters.removed
            ? `${formatNumber(websites.data?.total)} removed websites - restore them or delete them forever`
            : `${formatNumber(websites.data?.total)} websites in the list`
        }
        action={
          <div className="flex flex-wrap items-center gap-2">
            {filters.removed ? (
              <>
                <Button
                  size="sm"
                  disabled={selected.length === 0 || busy}
                  loading={busy}
                  onClick={() => void restoreSelected()}
                  title={
                    selected.length === 0
                      ? "Select at least one website first"
                      : "Bring the selected websites back into the list"
                  }
                >
                  Restore {selected.length > 0 ? selected.length : ""}
                </Button>
                <Button
                  size="sm"
                  variant="danger"
                  disabled={selected.length === 0 || busy}
                  onClick={() => setPurgeTarget(selected)}
                  title="Delete the selected websites forever - this cannot be undone"
                >
                  Delete forever {selected.length > 0 ? selected.length : ""}
                </Button>
              </>
            ) : (
              <>
                <Select
                  aria-label="State for the selected websites"
                  value={bulkStatus}
                  disabled={selected.length === 0 || busy}
                  onChange={(event) => setBulkStatus(event.target.value)}
                  className="h-8 w-40 text-xs"
                >
                  <option value="">Set the state…</option>
                  {websiteStatusOptions("").map((value) => (
                    <option key={value} value={value}>
                      {websiteStatusLabel(value)}
                    </option>
                  ))}
                </Select>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!bulkStatus || selected.length === 0 || busy}
                  loading={busy}
                  onClick={applyBulkStatus}
                >
                  Apply to {selected.length}
                </Button>
                <Button
                  size="sm"
                  variant="danger"
                  disabled={selected.length === 0 || busy}
                  onClick={() => setDeleteTarget(selected)}
                >
                  Delete {selected.length > 0 ? selected.length : ""}
                </Button>
              </>
            )}
          </div>
        }
      />
      <CardBody className="p-0">
        {missingEndpoint ? (
          <div className="border-b border-line p-4">
            <Alert
              tone="warning"
              title="The local backend does not know the central website list yet"
            >
              <p>
                The endpoint <code>/api/v1/websites</code> answers with 404. The
                list, the import and the state changes need a newer backend -
                until then nothing can be added here.
              </p>
              <p className="mt-1 text-content-subtle">{websites.error}</p>
            </Alert>
          </div>
        ) : null}

        {websites.loading && !websites.data ? (
          <div className="p-4">
            <LoadingBlock rows={6} />
          </div>
        ) : null}

        {websites.error && !missingEndpoint ? (
          <div className="p-4">
            <ErrorBlock message={websites.error} onRetry={websites.reload} />
          </div>
        ) : null}

        {!websites.loading && items.length === 0 && !websites.error ? (
          <div className="p-4">
            {filters.removed ? (
              <NothingYet
                title="The recycle bin is empty"
                description="Every website that was removed from the list waits here until it is restored or deleted forever."
              />
            ) : (
              <NothingYet
                title="No websites yet"
                description="Add a website by hand or import a spreadsheet - the list is the single place where the sites of your projects live."
                action={
                  <Button size="sm" onClick={() => onAddOpenChange(true)}>
                    Add a website
                  </Button>
                }
              />
            )}
          </div>
        ) : null}

        {items.length > 0 ? (
          <>
            <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-2 text-xs text-content-muted">
              <span>
                {selected.length} selected of {formatNumber(websites.data?.total)}
              </span>
              {stats.error ? (
                <span className="text-content-subtle">
                  The counters of the websites are not reported by this backend -
                  the list shows its own numbers.
                </span>
              ) : null}
            </div>
            <Table>
              <thead>
                <tr>
                  <Th className="w-8">
                    <Checkbox
                      aria-label="Select all websites"
                      checked={
                        items.length > 0 && selected.length === items.length
                      }
                      onChange={(event) =>
                        setSelected(
                          event.target.checked
                            ? items.map((item) => item.id)
                            : [],
                        )
                      }
                    />
                  </Th>
                  <Th>Website</Th>
                  <Th>Category</Th>
                  <Th>Niche</Th>
                  <Th>State</Th>
                  <Th>Projects</Th>
                  <Th className="text-right">Submitted</Th>
                  <Th className="text-right">Verified</Th>
                  <Th className="text-right">Failed</Th>
                  <Th className="text-right">Pending</Th>
                  <Th>Last attempt</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const row = statsByDomain.get(item.domain.toLowerCase());
                  const counters = row
                    ? {
                        submitted: row.submitted,
                        verified: row.verified,
                        failed: row.failed,
                        pending: row.pending,
                      }
                    : {
                        submitted: item.stats.submitted,
                        verified: item.stats.verified,
                        failed: item.stats.failed,
                        pending: item.stats.pending,
                      };
                  const names = item.project_ids
                    .map((id) => projectNames.get(id) ?? id)
                    .join(", ");
                  const label = item.name || item.domain || "—";
                  const removedRow = isRemovedWebsite(item.status);
                  return (
                    <tr key={item.id} className={removedRow ? "opacity-60" : undefined}>
                      <Td>
                        <Checkbox
                          aria-label={`Select ${label}`}
                          checked={selected.includes(item.id)}
                          onChange={() => toggle(item.id)}
                        />
                      </Td>
                      <Td>
                        <div className="min-w-0">
                          <p className="truncate text-sm text-content">{label}</p>
                          <p className="truncate text-xs text-content-subtle">
                            {item.domain || "—"}
                          </p>
                        </div>
                      </Td>
                      <Td className="whitespace-nowrap text-xs">
                        {truncate(item.category.replace(/_/g, " "), 24)}
                      </Td>
                      <Td className="whitespace-nowrap text-xs">
                        {truncate(item.niche, 24)}
                      </Td>
                      <Td>
                        {removedRow ? (
                          <Badge tone="neutral">{REMOVED_WEBSITE_LABEL}</Badge>
                        ) : (
                          <Select
                            aria-label={`State of ${label}`}
                            value={item.status}
                            disabled={savingId === item.id}
                            onChange={(event) =>
                              void changeStatus(
                                item.id,
                                event.target.value,
                                label,
                              )
                            }
                            className="h-8 w-40 text-xs"
                          >
                            {websiteStatusOptions(item.status).map((value) => (
                              <option key={value} value={value}>
                                {websiteStatusLabel(value)}
                              </option>
                            ))}
                          </Select>
                        )}
                      </Td>
                      <Td className="whitespace-nowrap text-xs">
                        {item.project_count > 0 ? (
                          <span title={names}>
                            <Badge tone="accent">{item.project_count}</Badge>
                          </span>
                        ) : (
                          <span className="text-content-subtle">—</span>
                        )}
                      </Td>
                      <Td className="text-right text-xs tabular-nums">
                        {formatNumber(counters.submitted)}
                      </Td>
                      <Td className="text-right text-xs tabular-nums text-success">
                        {formatNumber(counters.verified)}
                      </Td>
                      <Td className="text-right text-xs tabular-nums text-danger">
                        {formatNumber(counters.failed)}
                      </Td>
                      <Td className="text-right text-xs tabular-nums text-content-muted">
                        {formatNumber(counters.pending)}
                      </Td>
                      <Td className="whitespace-nowrap text-xs text-content-muted">
                        {formatDate(
                          row?.last_attempt_at ?? item.stats.last_attempt_at,
                        )}
                      </Td>
                      <Td className="whitespace-nowrap text-right">
                        {removedRow ? (
                          <div className="flex items-center justify-end gap-1">
                            <Button
                              size="sm"
                              variant="outline"
                              loading={restoringId === item.id}
                              onClick={() => void restoreOne(item.id, label)}
                              title={`Bring ${label} back into the list`}
                            >
                              Restore
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => setPurgeTarget([item.id])}
                              title={`Delete ${label} forever - this cannot be undone`}
                            >
                              Delete forever
                            </Button>
                          </div>
                        ) : (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => setDeleteTarget([item.id])}
                            title={`Remove ${label} from the list`}
                          >
                            Delete
                          </Button>
                        )}
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
            <Pagination
              page={page}
              pages={websites.data?.pages ?? 1}
              total={websites.data?.total ?? 0}
              onPageChange={setPage}
            />
          </>
        ) : null}
      </CardBody>

      <AddWebsiteDialog
        open={addOpen}
        onClose={() => onAddOpenChange(false)}
        categories={knownCategories}
        onAdded={() => {
          onAddOpenChange(false);
          websites.reload();
        }}
      />

      <ImportWebsitesDialog
        open={importOpen}
        onClose={() => onImportOpenChange(false)}
        categories={knownCategories}
        onImported={() => {
          websites.reload();
        }}
      />

      <DeleteWebsitesDialog
        ids={deleteTarget}
        names={
          deleteTarget
            ?.map((id) => {
              const item = items.find((entry) => entry.id === id);
              return item ? item.name || item.domain || id : id;
            })
            .join(", ") ?? ""
        }
        busy={busy}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => void confirmDelete()}
        onDeleteForever={() => {
          setPurgeTarget(deleteTarget);
          setDeleteTarget(null);
        }}
      />

      <PurgeWebsitesDialog
        ids={purgeTarget}
        names={
          purgeTarget
            ?.map((id) => {
              const item = items.find((entry) => entry.id === id);
              return item ? item.name || item.domain || id : id;
            })
            .join(", ") ?? ""
        }
        busy={busy}
        onCancel={() => setPurgeTarget(null)}
        onConfirm={() => void confirmPurge()}
      />
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/* The dialogs                                                         */
/* ------------------------------------------------------------------ */

function AddWebsiteDialog({
  open,
  onClose,
  categories,
  onAdded,
}: {
  open: boolean;
  onClose: () => void;
  categories: string[];
  onAdded: () => void;
}) {
  const toast = useToast();
  const [url, setUrl] = React.useState("");
  const [name, setName] = React.useState("");
  const [category, setCategory] = React.useState("");
  const [niche, setNiche] = React.useState("");
  const [method, setMethod] = React.useState("BROWSER_FORM");
  const [notes, setNotes] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) return;
    setUrl("");
    setName("");
    setCategory("");
    setNiche("");
    setMethod("BROWSER_FORM");
    setNotes("");
    setError(null);
  }, [open]);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const created = await createWebsite({
        opportunity_url: url,
        name,
        category,
        niche,
        notes,
        submission_method: method,
      });
      const label = created.name || created.domain || url;
      toast.push(`${label} was added to the website list`, "success");
      void sendNativeNotification(
        "Auto Backlinker",
        `${label} was added to the website list.`,
      );
      onAdded();
    } catch (err) {
      setError(errorText(err, "Could not add the website"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Add a website"
      description="The site joins the central list - a project picks it from there."
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button
            loading={saving}
            disabled={!url.trim()}
            onClick={() => void save()}
          >
            Add to the list
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <Field
          label="Opportunity URL"
          required
          hint="The page of the site where a listing can be published."
        >
          <Input
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://example.com/submit"
          />
        </Field>
        <Field label="Name" hint="Leave empty to use the name of the site.">
          <Input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Example directory"
          />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Category" hint="For example business_directory.">
            <Input
              list="website-categories"
              value={category}
              onChange={(event) => setCategory(event.target.value)}
              placeholder="business_directory"
            />
          </Field>
          <Field label="Niche" hint="The topic the site covers.">
            <Input
              value={niche}
              onChange={(event) => setNiche(event.target.value)}
              placeholder="Analytics tools"
            />
          </Field>
        </div>
        <datalist id="website-categories">
          {categories.map((value) => (
            <option key={value} value={value} />
          ))}
        </datalist>
        <Field label="Submission method">
          <Select
            value={method}
            onChange={(event) => setMethod(event.target.value)}
          >
            <option value="BROWSER_FORM">Browser form</option>
            <option value="API">API</option>
            <option value="INTEGRATION">Integration</option>
            <option value="EMAIL_OUTREACH">E-mail outreach</option>
            <option value="MANUAL">Manual</option>
          </Select>
        </Field>
        <Field label="Notes">
          <Textarea
            rows={3}
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            placeholder="Login needed, no listing without a review…"
          />
        </Field>
        {error ? (
          <Alert tone="danger" title="The website was not added">
            {error}
          </Alert>
        ) : null}
      </div>
    </Dialog>
  );
}

function ImportWebsitesDialog({
  open,
  onClose,
  categories,
  onImported,
}: {
  open: boolean;
  onClose: () => void;
  categories: string[];
  onImported: () => void;
}) {
  const toast = useToast();
  const [category, setCategory] = React.useState("");
  const [niche, setNiche] = React.useState("");
  const [status, setStatus] = React.useState("");
  const [file, setFile] = React.useState<File | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [result, setResult] = React.useState<
    Awaited<ReturnType<typeof importWebsites>> | null
  >(null);

  React.useEffect(() => {
    if (!open) return;
    setCategory("");
    setNiche("");
    setStatus("");
    setFile(null);
    setError(null);
    setResult(null);
  }, [open]);

  async function choose() {
    setBusy(true);
    setError(null);
    try {
      const picked = await pickSpreadsheet();
      if (!picked) {
        setBusy(false);
        return;
      }
      setFile(picked);
      setResult(null);
    } catch (err) {
      setError(errorText(err, "Could not read the selected file"));
    } finally {
      setBusy(false);
    }
  }

  async function run() {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const outcome = await importWebsites(file, { category, niche, status });
      setResult(outcome);
      const summary = `${outcome.created} created, ${outcome.updated} updated, ${outcome.invalid} invalid`;
      toast.push(`Import finished: ${summary}`, "success");
      void sendNativeNotification(
        "Auto Backlinker",
        `The website import finished: ${summary}.`,
      );
      onImported();
    } catch (err) {
      setError(errorText(err, "Could not import the file"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Import websites from a spreadsheet"
      description="The file is read by your own backend on this machine."
      width="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Close
          </Button>
          <Button
            loading={busy}
            disabled={!file}
            onClick={() => void run()}
          >
            Import the file
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Category" hint="Applies to every row.">
            <Input
              list="import-categories"
              value={category}
              onChange={(event) => setCategory(event.target.value)}
              placeholder="business_directory"
            />
          </Field>
          <Field label="Niche" hint="Applies to every row.">
            <Input
              value={niche}
              onChange={(event) => setNiche(event.target.value)}
              placeholder="Analytics tools"
            />
          </Field>
          <Field label="State" hint="Applies to every row.">
            <Select
              value={status}
              onChange={(event) => setStatus(event.target.value)}
            >
              <option value="">Keep the state of the file</option>
              {WEBSITE_STATUS_FILTERS.filter((entry) => entry.value).map(
                (entry) => (
                  <option key={entry.value} value={entry.value}>
                    {entry.label}
                  </option>
                ),
              )}
            </Select>
          </Field>
        </div>
        <datalist id="import-categories">
          {categories.map((value) => (
            <option key={value} value={value} />
          ))}
        </datalist>

        <div className="flex flex-wrap items-center gap-3">
          <Button variant="outline" loading={busy} onClick={() => void choose()}>
            Choose file…
          </Button>
          {file ? (
            <span className="text-xs text-content-muted">{file.name}</span>
          ) : (
            <span className="text-xs text-content-subtle">
              No file chosen yet.
            </span>
          )}
        </div>

        {error ? (
          <Alert tone="danger" title="The import failed">
            {error}
          </Alert>
        ) : null}

        {result ? (
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap gap-2">
              <Badge tone="success">created {result.created}</Badge>
              <Badge tone="accent">updated {result.updated}</Badge>
              <Badge tone="neutral">skipped {result.skipped}</Badge>
              <Badge tone="danger">invalid {result.invalid}</Badge>
            </div>
            {result.rows.length > 0 ? (
              <Table>
                <thead>
                  <tr>
                    <Th>Row</Th>
                    <Th>Action</Th>
                    <Th>Reason</Th>
                    <Th>Domain</Th>
                  </tr>
                </thead>
                <tbody>
                  {result.rows.slice(0, 100).map((row, index) => (
                    <tr key={`${row.row}-${index}`}>
                      <Td className="text-xs">{row.row}</Td>
                      <Td>
                        <Badge
                          tone={
                            row.action.toUpperCase() === "CREATE"
                              ? "success"
                              : row.action.toUpperCase() === "UPDATE"
                                ? "accent"
                                : row.action.toUpperCase() === "INVALID"
                                  ? "danger"
                                  : "neutral"
                          }
                        >
                          {row.action || "—"}
                        </Badge>
                      </Td>
                      <Td className="max-w-[260px] truncate text-xs">
                        {row.reason || "—"}
                      </Td>
                      <Td className="max-w-[200px] truncate text-xs">
                        {row.domain || "—"}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            ) : (
              <p className="text-xs text-content-subtle">
                The backend did not report the single rows of the import.
              </p>
            )}
          </div>
        ) : null}
      </div>
    </Dialog>
  );
}

/**
 * The first step of the deletion: the website leaves the list, its history
 * stays.  The dialog offers the destructive alternative ("Delete forever")
 * as well - it opens the second confirmation.
 */
function DeleteWebsitesDialog({
  ids,
  names,
  busy,
  onCancel,
  onConfirm,
  onDeleteForever,
}: {
  ids: string[] | null;
  names: string;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
  onDeleteForever: () => void;
}) {
  const count = ids?.length ?? 0;
  return (
    <Dialog
      open={count > 0}
      onClose={onCancel}
      title={
        count === 1
          ? "Remove the website from the list?"
          : `Remove ${count} websites from the list?`
      }
      description={
        names ? truncate(names, 120) : `${count} websites leave the list.`
      }
      width="md"
      footer={
        <>
          <Button variant="outline" onClick={onCancel} disabled={busy}>
            Keep them
          </Button>
          <Button
            variant="danger"
            disabled={busy}
            onClick={onDeleteForever}
            title="Delete the website together with its history - this cannot be undone"
          >
            Delete forever
          </Button>
          <Button loading={busy} onClick={onConfirm}>
            Move to the recycle bin
          </Button>
        </>
      }
    >
      <ul className="space-y-1.5 text-xs text-content-muted">
        <li>
          • The website is removed from the list and from every project that uses
          it.
        </li>
        <li>
          • Its opportunities, its tasks and its verification records are{" "}
          <strong className="font-semibold text-content">kept</strong> - the old
          reports stay correct.
        </li>
        <li>
          • You can bring it back at any time with the{" "}
          <strong className="font-semibold text-content">Deleted</strong> filter
          (the recycle bin).
        </li>
      </ul>
      <p className="mt-3 text-xs text-content-muted">
        Do you want it to be gone for good? Then use{" "}
        <strong className="font-semibold text-content">Delete forever</strong>: the
        website, its opportunities, its tasks and its verification records are
        destroyed and nothing can bring them back.
      </p>
    </Dialog>
  );
}

/**
 * The second step of the deletion: the website and its history are destroyed.
 * This cannot be undone.
 */
function PurgeWebsitesDialog({
  ids,
  names,
  busy,
  onCancel,
  onConfirm,
}: {
  ids: string[] | null;
  names: string;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const count = ids?.length ?? 0;
  return (
    <Dialog
      open={count > 0}
      onClose={onCancel}
      title={
        count === 1 ? "Delete the website forever?" : `Delete ${count} websites forever?`
      }
      description="This cannot be undone."
      width="sm"
      footer={
        <>
          <Button variant="outline" onClick={onCancel} disabled={busy}>
            Keep them
          </Button>
          <Button variant="danger" loading={busy} onClick={onConfirm}>
            Delete forever
          </Button>
        </>
      }
    >
      <p className="text-xs text-content-muted">
        {count === 1 ? (
          <>
            <strong className="font-semibold text-content">{names}</strong> is
            deleted forever. Its opportunities, its tasks and its verification
            records go with it and the old reports lose this website. There is no
            way to undo this.
          </>
        ) : (
          <>
            These {count} websites are deleted forever. Their opportunities,
            their tasks and their verification records go with them and the old
            reports lose them. There is no way to undo this.
          </>
        )}
      </p>
      {names ? (
        <p className="mt-2 text-xs text-content-subtle">{truncate(names, 120)}</p>
      ) : null}
    </Dialog>
  );
}
