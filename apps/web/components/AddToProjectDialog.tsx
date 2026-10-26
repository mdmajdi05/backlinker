"use client";

import * as React from "react";
import { api } from "@autobacklinker/api-client";
import type { WebsiteChooseResult } from "@autobacklinker/shared-types";
import {
  Alert,
  Badge,
  Button,
  Dialog,
  Field,
  Input,
  Label,
  Pagination,
  Select,
  Skeleton,
  Table,
  Td,
  Th,
  Tooltip,
  useToast,
} from "@autobacklinker/ui";
import { apiClient, errorMessage, isNotFoundError } from "@/lib/api";
import { useAction, useDebounced, useResource } from "@/lib/hooks";
import { humanize } from "@/lib/format";
import { ALL_OPPORTUNITY_CATEGORIES, CATEGORY_LABELS } from "@/lib/constants";
import { AsyncSection, TableSkeleton } from "@/components/States";
import { websiteStatusLabel } from "@/lib/websites";

const PAGE_SIZE = 50;

/**
 * Picks websites of the central list for one project.
 *
 * The anchor text and the target landing page come from the project and stay
 * editable - a project can link the same site with a different anchor.
 */
export function AddToProjectDialog({
  projectId,
  open,
  onClose,
  onChanged,
}: {
  projectId: string;
  open: boolean;
  onClose: () => void;
  /** Called after websites were added to the project. */
  onChanged?: () => void;
}) {
  const toast = useToast();
  const action = useAction();
  const addUrlAction = useAction();

  const newUrlId = React.useId();
  const [newUrl, setNewUrl] = React.useState("");
  const [newAddMessage, setNewAddMessage] = React.useState<string | null>(null);
  const [newAddError, setNewAddError] = React.useState<string | null>(null);
  const [page, setPage] = React.useState(1);
  const [search, setSearch] = React.useState("");
  const [category, setCategory] = React.useState("");
  const [niche, setNiche] = React.useState("");
  const [selected, setSelected] = React.useState<string[]>([]);
  const [anchorText, setAnchorText] = React.useState("");
  const [landingPage, setLandingPage] = React.useState("");
  const [result, setResult] = React.useState<WebsiteChooseResult | null>(null);

  const anchorTouched = React.useRef(false);
  const landingTouched = React.useRef(false);

  const debouncedSearch = useDebounced(search, 400);
  const debouncedNiche = useDebounced(niche, 400);

  const project = useResource(() => api.projects.get(apiClient, projectId), [projectId], {
    enabled: open,
  });
  const landingPages = useResource(
    () => api.projects.websites(apiClient, projectId, { page: 1, page_size: 100 }),
    [projectId],
    { enabled: open },
  );
  const profiles = useResource(() => api.profiles.list(apiClient), [], { enabled: open });
  const autoPilot = useResource(() => api.autoPilot.get(apiClient, projectId), [projectId], {
    enabled: open,
  });

  const websites = useResource(
    () =>
      api.websites.list(apiClient, {
        page,
        page_size: PAGE_SIZE,
        search: debouncedSearch || undefined,
        category: category || undefined,
        niche: debouncedNiche || undefined,
      }),
    [page, debouncedSearch, category, debouncedNiche],
    { enabled: open },
  );

  const rows = websites.data?.items ?? [];

  /** The landing page of the project - the main one, else the target website. */
  const defaultLandingPage = React.useMemo(() => {
    const main = (landingPages.data?.items ?? []).find((item) => item.kind === "MAIN");
    if (main) return main.url;
    const first = landingPages.data?.items?.[0];
    if (first) return first.url;
    return project.data?.target_website ?? "";
  }, [landingPages.data, project.data]);

  /** The anchor text of the project - the first preferred anchor of the profile. */
  const defaultAnchorText = React.useMemo(() => {
    const profileId = project.data?.business_profile_id;
    const profile = (profiles.data ?? []).find((item) => item.id === profileId);
    return profile?.preferred_anchors?.[0] ?? "";
  }, [project.data, profiles.data]);

  React.useEffect(() => {
    if (!open) {
      anchorTouched.current = false;
      landingTouched.current = false;
      return;
    }
    if (!anchorTouched.current && defaultAnchorText) setAnchorText(defaultAnchorText);
    if (!landingTouched.current && defaultLandingPage) setLandingPage(defaultLandingPage);
  }, [open, defaultAnchorText, defaultLandingPage]);

  React.useEffect(() => {
    setSelected([]);
    setResult(null);
  }, [projectId]);

  React.useEffect(() => {
    if (open) return;
    setNewUrl("");
    setNewAddMessage(null);
    setNewAddError(null);
  }, [open]);

  const addByUrl = async () => {
    const value = newUrl.trim();
    if (!value) return;
    setNewAddMessage(null);
    setNewAddError(null);
    const outcome = await addUrlAction.run(() =>
      api.campaign.add(apiClient, projectId, value),
    );
    if (!outcome.ok || !outcome.data) {
      setNewAddError(errorMessage(outcome.error));
      return;
    }
    const data = outcome.data;
    const message = [
      data.added ? `${data.added} added to the list and this project` : "",
      data.linked ? `${data.linked} existing site(s) linked to this project` : "",
      data.existing ? `${data.existing} already in this project` : "",
      data.invalid ? `${data.invalid} invalid` : "",
      data.deleted ? `${data.deleted} in the recycle bin` : "",
    ]
      .filter(Boolean)
      .join(" · ");
    if (data.added + data.linked === 0) {
      setNewAddError(`Nothing was added or linked. ${message}`);
      return;
    }
    setNewAddMessage(message);
    toast.push(message, data.invalid + data.deleted > 0 ? "info" : "success");
    setNewUrl("");
    websites.reload();
    onChanged?.();
  };

  const toggleOne = (id: string) => {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id],
    );
  };

  const allSelected = rows.length > 0 && rows.every((row) => selected.includes(row.id));

  const toggleAll = () => {
    if (allSelected) {
      setSelected((prev) => prev.filter((id) => !rows.some((row) => row.id === id)));
    } else {
      setSelected((prev) => Array.from(new Set([...prev, ...rows.map((row) => row.id)])));
    }
  };

  const choose = async () => {
    if (selected.length === 0) return;
    const outcome = await action.run(() =>
      api.websites.chooseForProject(apiClient, projectId, {
        website_ids: [...selected],
        anchor_text: anchorText.trim() || undefined,
        target_landing_page: landingPage.trim() || undefined,
      }),
    );
    if (outcome.ok && outcome.data) {
      setResult(outcome.data);
      toast.push(
        `${outcome.data.linked} website(s) added to the project, ${outcome.data.skipped} skipped`,
        "success",
      );
      setSelected([]);
      onChanged?.();
    }
  };

  const autoPilotUnavailable = Boolean(autoPilot.error) && isNotFoundError(autoPilot.error);

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Assign backlink websites"
      description="Pick websites from the central list, or add a new one by URL. Every website is linked to this project once."
      width="xl"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
          <Button
            loading={action.pending}
            disabled={selected.length === 0}
            onClick={() => void choose()}
            title={
              selected.length === 0
                ? "Select at least one website first"
                : "Add the selected websites to the project"
            }
          >
            Add {selected.length > 0 ? `${selected.length} ` : ""}website
            {selected.length === 1 ? "" : "s"}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {action.error ? (
          <Alert tone="danger" title="The websites could not be added">
            {errorMessage(action.error)}
          </Alert>
        ) : null}

        {result ? (
          <Alert
            tone={result.linked > 0 ? "success" : "neutral"}
            title={`${result.linked} website${result.linked === 1 ? "" : "s"} added, ${
              result.skipped
            } skipped (already in this project)`}
          >
            {result.tasks_created > 0
              ? `${result.tasks_created} task(s) were created for the queue.`
              : "No queue task was created - the auto pilot or the queue picks the websites up."}
          </Alert>
        ) : null}

        <div className="rounded-lg border border-line bg-surface-raised/40 p-3">
          <Label htmlFor={newUrlId}>Add a website that is not in the list</Label>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <Input
              id={newUrlId}
              className="min-w-64 flex-1"
              aria-describedby={`${newUrlId}-hint`}
              value={newUrl}
              onChange={(event) => setNewUrl(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  void addByUrl();
                }
              }}
              placeholder="https://example.com/add-your-business"
            />
            <Button
              variant="outline"
              loading={addUrlAction.pending}
              disabled={!newUrl.trim()}
              onClick={() => void addByUrl()}
            >
              Add and link
            </Button>
          </div>
          <p id={`${newUrlId}-hint`} className="mt-1 text-xs text-content-muted">
            Paste the exact submission page. It is added to the central list once and
            linked to this project.
          </p>
          {newAddError ? (
            <p className="mt-2 text-xs text-danger">{newAddError}</p>
          ) : null}
          {newAddMessage ? (
            <p className="mt-2 text-xs text-success">{newAddMessage}</p>
          ) : null}
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field
            label="Anchor text"
            hint="The clickable text of the link - the profile of the project suggests one."
          >
            <Input
              value={anchorText}
              onChange={(event) => {
                anchorTouched.current = true;
                setAnchorText(event.target.value);
              }}
              placeholder="Acme Analytics"
            />
          </Field>
          <Field
            label="Target landing page"
            hint="Your page that should receive the link."
          >
            <Input
              value={landingPage}
              onChange={(event) => {
                landingTouched.current = true;
                setLandingPage(event.target.value);
              }}
              placeholder="https://your-site.com/product"
            />
          </Field>
        </div>

        {landingPages.data && landingPages.data.items.length > 0 ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-content-muted">Landing pages of the project:</span>
            {landingPages.data.items.map((item) => (
              <button
                key={item.id}
                type="button"
                className="text-xs text-accent hover:underline"
                onClick={() => {
                  landingTouched.current = true;
                  setLandingPage(item.url);
                }}
              >
                {item.name}
              </button>
            ))}
          </div>
        ) : null}

        {autoPilot.loading && !autoPilot.data ? (
          <Skeleton className="h-4 w-72" />
        ) : autoPilotUnavailable ? (
          <p className="text-xs text-content-subtle">
            The backend does not expose the auto pilot endpoint for this project - it is
            unknown whether the new websites are submitted automatically.
          </p>
        ) : autoPilot.data?.enabled ? (
          <p className="text-xs text-content-muted">
            The auto pilot of this project is on - the worker submits the new websites in
            the background.
          </p>
        ) : (
          <p className="text-xs text-content-muted">
            The auto pilot of this project is off - the websites are only linked. Switch the
            auto pilot on in the project to submit them in the background.
          </p>
        )}

        <div className="flex flex-wrap items-end gap-2 border-t border-line pt-3">
          <Field label="Search" className="w-52">
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
          <Field label="Niche" className="w-40">
            <Input
              value={niche}
              onChange={(event) => {
                setNiche(event.target.value);
                setPage(1);
              }}
              placeholder="saas"
            />
          </Field>
          <span className="pb-2 text-xs text-content-muted">{selected.length} selected</span>
        </div>

        <AsyncSection
          loading={websites.loading}
          error={websites.error}
          data={websites.data}
          onRetry={websites.reload}
          isEmpty={rows.length === 0}
          emptyTitle="No websites match these filters"
          emptyDescription="No website matches these filters. Add one by URL above, or clear the filters."
          skeleton={<TableSkeleton rows={6} columns={5} />}
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
                <Th>Name</Th>
                <Th className="w-48">Domain</Th>
                <Th className="w-44">Category</Th>
                <Th className="w-32">Niche</Th>
                <Th className="w-32">Status</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
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
                  <Td className="text-xs">{row.domain}</Td>
                  <Td>
                    <Badge tone="neutral">
                      {CATEGORY_LABELS[row.category] ?? humanize(row.category)}
                    </Badge>
                  </Td>
                  <Td className="text-xs">{row.niche || "—"}</Td>
                  <Td className="text-xs">{websiteStatusLabel(row.status)}</Td>
                </tr>
              ))}
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

        {selected.length > 0 ? (
          <div className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-surface-raised px-3 py-2">
            <Tooltip label="The websites that are already linked to this project are skipped.">
              <span className="text-xs text-content-muted">
                {selected.length} website(s) will be added to the project.
              </span>
            </Tooltip>
          </div>
        ) : null}
      </div>
    </Dialog>
  );
}
