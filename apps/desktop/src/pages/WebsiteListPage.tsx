import * as React from "react";
import { Button, Card, CardBody, CardHeader, Field, Input, Select } from "@autobacklinker/ui";
import { useAsync } from "../lib/useAsync";
import { api, apiClient } from "../lib/api";
import { PageHeader } from "../components/common";
import {
  EMPTY_WEBSITE_FILTERS,
  WebsiteListPanel,
  type WebsiteListFilters,
} from "../components/WebsiteListPanel";
import { WEBSITE_STATUS_FILTERS } from "../lib/websites";
import type { Project } from "@autobacklinker/shared-types";

/**
 * The central website list.
 *
 * The list is the single place where the sites of every project live: it is
 * filled by hand or by a spreadsheet, the state of a site is changed here and
 * a project picks the sites it wants from the list.
 *
 * A website that is removed leaves the list - it waits in the recycle bin
 * (the "Deleted" filter) until it is restored or deleted forever.
 */
export function WebsiteListPage() {
  const [filters, setFilters] = React.useState<WebsiteListFilters>(
    EMPTY_WEBSITE_FILTERS,
  );
  const [searchInput, setSearchInput] = React.useState("");
  const [adding, setAdding] = React.useState(false);
  const [importing, setImporting] = React.useState(false);
  const [removedCount, setRemovedCount] = React.useState<number | null>(null);

  const projects = useAsync(
    () => api.projects.list(apiClient, { page: 1, page_size: 100 }),
    [],
  );

  // The search is applied with a short delay - every keystroke would send a
  // request to the local backend otherwise.
  React.useEffect(() => {
    const timer = window.setTimeout(() => {
      setFilters((previous) =>
        previous.search === searchInput
          ? previous
          : { ...previous, search: searchInput },
      );
    }, 300);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  function update(patch: Partial<WebsiteListFilters>) {
    setFilters((previous) => ({ ...previous, ...patch }));
  }

  function reset() {
    setSearchInput("");
    setFilters(EMPTY_WEBSITE_FILTERS);
  }

  /** Opens the recycle bin - the list shows the removed websites only. */
  function showRemoved(open: boolean) {
    setFilters((previous) => ({
      ...previous,
      removed: open,
      // The state filter and the recycle bin do not work together.
      status: open ? "" : previous.status,
    }));
  }

  const active =
    filters.search ||
    filters.category ||
    filters.niche ||
    filters.status ||
    filters.removed ||
    filters.project_id;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Website list"
        description="Every site where the backlinks are made - independent of the projects."
        actions={
          <>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setImporting(true)}
            >
              Import from Excel
            </Button>
            <Button size="sm" onClick={() => setAdding(true)}>
              Add website
            </Button>
          </>
        }
      />

      <Card>
        <CardHeader
          title="Filters"
          description="Search by name or domain, or narrow the list down by category, niche, state and project. A website you delete leaves the list - it waits in the recycle bin until you restore it or delete it forever."
          action={
            <div className="flex gap-2">
              {active ? (
                <Button size="sm" variant="outline" onClick={reset}>
                  Reset the filters
                </Button>
              ) : null}
            </div>
          }
        />
        <CardBody>
          <div className="flex flex-wrap items-end gap-3">
            <div className="w-64">
              <Field label="Search" hint="Name or domain of the website.">
                <Input
                  value={searchInput}
                  onChange={(event) => setSearchInput(event.target.value)}
                  placeholder="example.com"
                  aria-label="Search the website list"
                />
              </Field>
            </div>
            <div className="w-56">
              <Field label="Category">
                <Input
                  value={filters.category}
                  onChange={(event) => update({ category: event.target.value })}
                  placeholder="business_directory"
                  aria-label="Filter by category"
                />
              </Field>
            </div>
            <div className="w-56">
              <Field label="Niche">
                <Input
                  value={filters.niche}
                  onChange={(event) => update({ niche: event.target.value })}
                  placeholder="Analytics tools"
                  aria-label="Filter by niche"
                />
              </Field>
            </div>
            <div className="w-48">
              <Field label="State">
                <Select
                  value={filters.status}
                  disabled={filters.removed}
                  onChange={(event) => update({ status: event.target.value })}
                  aria-label="Filter by state"
                >
                  {WEBSITE_STATUS_FILTERS.map((entry) => (
                    <option key={entry.value} value={entry.value}>
                      {entry.label}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            <div className="w-48">
              <Field
                label="Recycle bin"
                hint="The websites that were removed from the list."
              >
                <button
                  type="button"
                  onClick={() => showRemoved(!filters.removed)}
                  aria-pressed={filters.removed}
                  aria-label={
                    filters.removed
                      ? "Close the recycle bin and show the active websites again"
                      : "Show the removed websites (the recycle bin)"
                  }
                  className={`inline-flex h-9 w-full items-center justify-between gap-2 rounded-md border px-3 text-sm font-medium transition-colors ${
                    filters.removed
                      ? "border-accent bg-accent-soft text-accent"
                      : "border-line-strong bg-surface text-content-muted hover:text-content"
                  }`}
                >
                  <span>Deleted</span>
                  <span className="rounded-full bg-surface-sunken px-1.5 py-0.5 text-[11px] text-content-muted">
                    {removedCount ?? 0}
                  </span>
                </button>
              </Field>
            </div>
            <div className="w-64">
              <Field label="Project">
                <Select
                  value={filters.project_id}
                  onChange={(event) =>
                    update({ project_id: event.target.value })
                  }
                  aria-label="Filter by project"
                >
                  <option value="">All projects</option>
                  {(projects.data?.items ?? []).map((project: Project) => (
                    <option key={project.id} value={project.id}>
                      {project.name}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
          </div>
        </CardBody>
      </Card>

      <WebsiteListPanel
        filters={filters}
        onFiltersChange={setFilters}
        onRemovedCountChange={setRemovedCount}
        projects={projects.data?.items ?? []}
        addOpen={adding}
        onAddOpenChange={setAdding}
        importOpen={importing}
        onImportOpenChange={setImporting}
      />
    </div>
  );
}
