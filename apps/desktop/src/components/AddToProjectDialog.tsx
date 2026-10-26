import * as React from "react";
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Dialog,
  Field,
  Input,
  Label,
  Table,
  Td,
  Th,
  useToast,
} from "@autobacklinker/ui";
import { useAsync } from "../lib/useAsync";
import { api, apiClient, isMissingEndpoint } from "../lib/api";
import { sendNativeNotification } from "../lib/backend";
import { truncate } from "../lib/format";
import {
  chooseWebsitesForProject,
  fetchWebsites,
  websiteStatusLabel,
} from "../lib/websites";
import type { WebsiteListItem } from "@autobacklinker/shared-types";

/**
 * Adds websites of the central list to a project.
 *
 * The list is the only source of the sites - the operator picks the ones the
 * project should work on.  The anchor text and the target landing page are
 * filled with the values of the project, they can be changed before the
 * websites are added.
 */

/** The states a site should not be submitted to any more. */
const INACTIVE_STATES = ["NOT_WORKING", "DELETED", "REJECTED", "EXCLUDED"];

function errorText(error: unknown, fallback: string): string {
  if (error && typeof error === "object" && "message" in error) {
    return String((error as { message: unknown }).message);
  }
  return fallback;
}

export function AddToProjectDialog({
  projectId,
  projectName,
  open,
  onClose,
  onAdded,
  defaultAnchorText = "",
  defaultTargetLandingPage = "",
}: {
  projectId: string;
  projectName?: string;
  open: boolean;
  onClose: () => void;
  onAdded?: () => void;
  /** The anchor text of the project - it can be changed. */
  defaultAnchorText?: string;
  /** The landing page of the project - it can be changed. */
  defaultTargetLandingPage?: string;
}) {
  const toast = useToast();
  const [search, setSearch] = React.useState("");
  const [category, setCategory] = React.useState("");
  const [niche, setNiche] = React.useState("");
  const [selected, setSelected] = React.useState<string[]>([]);
  const [anchorText, setAnchorText] = React.useState(defaultAnchorText);
  const [landingPage, setLandingPage] = React.useState(
    defaultTargetLandingPage,
  );
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [result, setResult] = React.useState<{
    linked: number;
    skipped: number;
    tasks_created: number;
  } | null>(null);
  const newUrlId = React.useId();
  const [newUrl, setNewUrl] = React.useState("");
  const [newMessage, setNewMessage] = React.useState<string | null>(null);
  const [newError, setNewError] = React.useState<string | null>(null);
  const [addingUrl, setAddingUrl] = React.useState(false);

  React.useEffect(() => {
    if (!open) {
      setNewUrl("");
      setNewMessage(null);
      setNewError(null);
      return;
    }
    setSelected([]);
    setError(null);
    setResult(null);
    setNewMessage(null);
    setNewError(null);
    setAddingUrl(false);
    setAnchorText(defaultAnchorText);
    setLandingPage(defaultTargetLandingPage);
  }, [open, defaultAnchorText, defaultTargetLandingPage]);

  const websites = useAsync(async () => {
    if (!open) {
      return {
        items: [] as WebsiteListItem[],
        total: 0,
        page: 1,
        page_size: 100,
        pages: 1,
      };
    }
    return fetchWebsites({
      page: 1,
      page_size: 100,
      search,
      category,
      niche,
    });
  }, [open, search, category, niche]);

  const items = websites.data?.items ?? [];

  function toggle(id: string) {
    setSelected((previous) =>
      previous.includes(id)
        ? previous.filter((item) => item !== id)
        : [...previous, id],
    );
  }

  async function addByUrl() {
    const value = newUrl.trim();
    if (!value) return;
    setAddingUrl(true);
    setNewError(null);
    setNewMessage(null);
    try {
      const data = await api.campaign.add(apiClient, projectId, value);
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
        setNewError(`Nothing was added or linked. ${message}`);
        return;
      }
      setNewMessage(message);
      setNewUrl("");
      toast.push(message, data.invalid + data.deleted > 0 ? "info" : "success");
      websites.reload();
      onAdded?.();
    } catch (err) {
      setNewError(errorText(err, "Could not add the website"));
    } finally {
      setAddingUrl(false);
    }
  }

  async function add() {
    if (selected.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      const outcome = await chooseWebsitesForProject(projectId, {
        website_ids: selected,
        anchor_text: anchorText,
        target_landing_page: landingPage,
      });
      setResult(outcome);
      const message = `${outcome.linked} website${
        outcome.linked === 1 ? "" : "s"
      } added to the project`;
      toast.push(message, "success");
      void sendNativeNotification(
        "Auto Backlinker",
        `${message}${outcome.tasks_created ? `, ${outcome.tasks_created} task(s) queued` : ""}.`,
      );
      onAdded?.();
    } catch (err) {
      setError(errorText(err, "Could not add the websites to the project"));
    } finally {
      setBusy(false);
    }
  }

  const missingEndpoint =
    Boolean(websites.error) && isMissingEndpoint(websites.error);

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Assign backlink websites"
      description={
        projectName
          ? `Pick websites from the central list or add a new one by URL. The chosen sites join the project ${projectName}.`
          : "Pick websites from the central list or add a new one by URL. The chosen sites join the project."
      }
      width="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Close
          </Button>
          <Button
            loading={busy}
            disabled={selected.length === 0}
            onClick={() => void add()}
          >
            Add {selected.length > 0 ? selected.length : ""} website
            {selected.length === 1 ? "" : "s"}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
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
              loading={addingUrl}
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
          {newError ? (
            <p className="mt-2 text-xs text-danger">{newError}</p>
          ) : null}
          {newMessage ? (
            <p className="mt-2 text-xs text-success">{newMessage}</p>
          ) : null}
        </div>

        <div className="flex flex-wrap items-end gap-3">
          <div className="w-56">
            <Field label="Search">
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Name or domain"
                aria-label="Search the website list"
              />
            </Field>
          </div>
          <div className="w-48">
            <Field label="Category">
              <Input
                value={category}
                onChange={(event) => setCategory(event.target.value)}
                placeholder="business_directory"
                aria-label="Filter by category"
              />
            </Field>
          </div>
          <div className="w-48">
            <Field label="Niche">
              <Input
                value={niche}
                onChange={(event) => setNiche(event.target.value)}
                placeholder="Analytics tools"
                aria-label="Filter by niche"
              />
            </Field>
          </div>
        </div>

        {missingEndpoint ? (
          <Alert
            tone="warning"
            title="The local backend does not know the website list yet"
          >
            The endpoint <code>/api/v1/websites</code> answers with 404 - there
            is nothing to pick from. A newer backend is needed.
          </Alert>
        ) : null}

        {websites.error && !missingEndpoint ? (
          <Alert tone="danger" title="The website list could not be loaded">
            {websites.error}
          </Alert>
        ) : null}

        <div className="max-h-[320px] overflow-y-auto rounded-md border border-line">
          {websites.loading && !websites.data ? (
            <p className="p-4 text-xs text-content-subtle">
              Loading the website list…
            </p>
          ) : items.length === 0 ? (
            <p className="p-4 text-xs text-content-subtle">
              No website matches the filter. Add one by URL above, or clear the
              filters.
            </p>
          ) : (
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
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const inactive = INACTIVE_STATES.includes(item.status);
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
                        {truncate(item.category.replace(/_/g, " "), 22)}
                      </Td>
                      <Td className="whitespace-nowrap text-xs">
                        {truncate(item.niche, 22)}
                      </Td>
                      <Td>
                        <Badge tone={inactive ? "warning" : "neutral"}>
                          {websiteStatusLabel(item.status)}
                        </Badge>
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
          )}
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field
            label="Anchor text"
            hint="The text of the backlink - it is filled with the value of the project."
          >
            <Input
              value={anchorText}
              onChange={(event) => setAnchorText(event.target.value)}
              placeholder="Acme Analytics"
            />
          </Field>
          <Field
            label="Target landing page"
            hint="The page of your own site the backlink points to."
          >
            <Input
              value={landingPage}
              onChange={(event) => setLandingPage(event.target.value)}
              placeholder="https://example.com/product"
            />
          </Field>
        </div>

        {result ? (
          <Alert tone="success" title="The websites were added">
            <p>
              {result.linked} website{result.linked === 1 ? "" : "s"} joined the
              project
              {result.skipped > 0
                ? `, ${result.skipped} were skipped (they are already in the project)`
                : ""}
              {result.tasks_created > 0
                ? `, ${result.tasks_created} task(s) were queued`
                : ""}
              .
            </p>
          </Alert>
        ) : null}

        {error ? (
          <Alert tone="danger" title="The websites were not added">
            {error}
          </Alert>
        ) : null}
      </div>
    </Dialog>
  );
}
