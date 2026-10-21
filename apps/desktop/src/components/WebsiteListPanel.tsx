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
  WEBSITE_STATUS_FILTERS,
  createWebsite,
  fetchWebsiteStats,
  fetchWebsites,
  importWebsites,
  removeWebsite,
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
}

export const EMPTY_WEBSITE_FILTERS: WebsiteListFilters = {
  search: "",
  category: "",
  niche: "",
  status: "",
  project_id: "",
};

function errorText(error: unknown, fallback: string): string {
  if (error && typeof error === "object" && "message" in error) {
    return String((error as { message: unknown }).message);
  }
  return fallback;
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
  projects,
  addOpen,
  onAddOpenChange,
  importOpen,
  onImportOpenChange,
}: {
  filters: WebsiteListFilters;
  onFiltersChange: (filters: WebsiteListFilters) => void;
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

  const filterKey = `${filters.search}|${filters.category}|${filters.niche}|${filters.status}|${filters.project_id}`;

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
        status: filters.status,
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

  const knownNiches = React.useMemo(() => {
    const values = new Set<string>();
    items.forEach((item) => {
      if (item.niche) values.add(item.niche);
    });
    return Array.from(values).sort();
  }, [items]);

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

  async function confirmDelete() {
    if (!deleteTarget || deleteTarget.length === 0) return;
    setBusy(true);
    let removed = 0;
    let failed = 0;
    for (const id of deleteTarget) {
      try {
        await removeWebsite(id);
        removed += 1;
      } catch {
        failed += 1;
      }
    }
    setBusy(false);
    setDeleteTarget(null);
    if (failed === 0) {
      toast.push(
        `${removed} website${removed === 1 ? "" : "s"} removed from the list`,
        "success",
      );
      void sendNativeNotification(
        "Auto Backlinker",
        `${removed} website${removed === 1 ? " was" : "s were"} removed from the website list. The history is kept.`,
      );
    } else {
      toast.push(
        `${removed} removed, ${failed} could not be removed`,
        "error",
      );
    }
    setSelected([]);
    websites.reload();
  }

  const missingEndpoint = Boolean(websites.error) && isMissingEndpoint(websites.error);

  return (
    <Card>
      <CardHeader
        title="Websites"
        description={`${formatNumber(websites.data?.total)} websites in the list`}
        action={
          <div className="flex flex-wrap items-center gap-2">
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
            <NothingYet
              title="No websites yet"
              description="Add a website by hand or import a spreadsheet - the list is the single place where the sites of your projects live."
              action={
                <Button size="sm" onClick={() => onAddOpenChange(true)}>
                  Add a website
                </Button>
              }
            />
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
                  return (
                    <tr key={item.id}>
                      <Td>
                        <Checkbox
                          aria-label={`Select ${item.name || item.domain}`}
                          checked={selected.includes(item.id)}
                          onChange={() => toggle(item.id)}
                        />
                      </Td>
                      <Td>
                        <div className="min-w-0">
                          <p className="truncate text-sm text-content">
                            {item.name || item.domain || "—"}
                          </p>
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
                        <Select
                          aria-label={`State of ${item.name || item.domain}`}
                          value={item.status}
                          disabled={savingId === item.id}
                          onChange={(event) =>
                            void changeStatus(
                              item.id,
                              event.target.value,
                              item.name || item.domain,
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
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => setDeleteTarget([item.id])}
                        >
                          Delete
                        </Button>
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
            ?.map((id) => items.find((item) => item.id === id)?.name ?? id)
            .join(", ") ?? ""
        }
        busy={busy}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => void confirmDelete()}
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
            <datalist id="website-categories">
              {categories.map((value) => (
                <option key={value} value={value} />
              ))}
            </datalist>
          </Field>
          <Field label="Niche" hint="The topic the site covers.">
            <Input
              value={niche}
              onChange={(event) => setNiche(event.target.value)}
              placeholder="Analytics tools"
            />
          </Field>
        </div>
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
            <datalist id="import-categories">
              {categories.map((value) => (
                <option key={value} value={value} />
              ))}
            </datalist>
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

function DeleteWebsitesDialog({
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
        count === 1 ? "Remove the website from the list?" : "Remove the websites?"
      }
      description={
        names ? truncate(names, 120) : `${count} websites leave the list.`
      }
      width="sm"
      footer={
        <>
          <Button variant="outline" onClick={onCancel} disabled={busy}>
            Keep them
          </Button>
          <Button variant="danger" loading={busy} onClick={onConfirm}>
            Remove from the list
          </Button>
        </>
      }
    >
      <p className="text-xs text-content-muted">
        The site leaves the central list. The submissions, the tasks and the
        verification records of this site are kept - the history stays intact and
        the reports still show the old numbers.
      </p>
    </Dialog>
  );
}
