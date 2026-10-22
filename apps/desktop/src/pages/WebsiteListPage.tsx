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
 * Deleting a website moves it to the recycle bin - restore it there.
 */
export function WebsiteListPage() {
  const [filters, setFilters] = React.useState<WebsiteListFilters>(
    EMPTY_WEBSITE_FILTERS,
  );
  const [searchInput, setSearchInput] = React.useState("");
  const [adding, setAdding] = React.useState(false);
  const [importing, setImporting] = React.useState(false);

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

  const active =
    filters.search ||
    filters.category ||
    filters.niche ||
    filters.status ||
    filters.project_id;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Websites"
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
          description="Search by name or domain, or narrow the list down by category, niche, state and project. A website you delete waits in the recycle bin until you restore it there."
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
        projects={projects.data?.items ?? []}
        addOpen={adding}
        onAddOpenChange={setAdding}
        importOpen={importing}
        onImportOpenChange={setImporting}
      />
    </div>
  );
}
