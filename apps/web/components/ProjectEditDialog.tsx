"use client";

import * as React from "react";
import { api } from "@autobacklinker/api-client";
import type { BacklinkDetails, BacklinkDetailsUpdate } from "@autobacklinker/shared-types";
import type { Project, TargetWebsite } from "@autobacklinker/shared-types";
import {
  Alert,
  Button,
  Dialog,
  Field,
  IconButton,
  Input,
  Select,
  Skeleton,
  Textarea,
  useToast,
} from "@autobacklinker/ui";
import { apiClient, errorMessage } from "@/lib/api";
import { useAction, useResource } from "@/lib/hooks";

/** The states a project can have - the backend stores them as plain strings. */
const STATUS_OPTIONS: Array<{ value: Project["status"]; label: string }> = [
  { value: "ACTIVE", label: "Active - the campaign runs" },
  { value: "PAUSED", label: "Paused - nothing new is queued" },
  { value: "ARCHIVED", label: "Archived - finished, kept for the reports" },
];

const KIND_OPTIONS: Array<{ value: TargetWebsite["kind"]; label: string }> = [
  { value: "MAIN", label: "Main" },
  { value: "LANDING", label: "Landing" },
  { value: "BLOG", label: "Blog" },
  { value: "OTHER", label: "Other" },
];

/** One landing page of the draft. */
interface LandingDraft {
  key: string;
  name: string;
  url: string;
  kind: TargetWebsite["kind"];
}

/**
 * The body of the PATCH request.
 *
 * `landing_pages` is not part of the project record of the backend - it is sent
 * nevertheless, because the endpoint is supposed to store it.  Whether it did
 * is checked afterwards (see `readStoredState`).
 */
interface ProjectEditBody {
  name: string;
  description: string;
  target_website: string;
  business_profile_id: string | null;
  status: Project["status"];
  landing_pages: Array<{ name: string; url: string; kind: TargetWebsite["kind"] }>;
}

/**
 * Normalizes a target website the way the backend does: the scheme is added
 * when it is missing and the trailing slash is removed.
 *
 * Returns null when the value is not a plain http(s) URL - the same rules the
 * backend applies (no credentials in the URL, no exotic schemes).
 */
export function normalizeWebsite(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const candidate = /^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(trimmed)
    ? trimmed
    : `https://${trimmed}`;
  let parsed: URL;
  try {
    parsed = new URL(candidate);
  } catch {
    return null;
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
  if (!parsed.hostname) return null;
  if (parsed.username || parsed.password) return null;
  return candidate.replace(/\/+$/, "");
}

/** The identity of a landing page - used to compare the draft with the server. */
function landingKey(page: { name: string; url: string; kind: string }): string {
  const url = normalizeWebsite(page.url) ?? page.url.trim();
  return `${page.name.trim()}|${url}|${page.kind}`;
}

/** True when both lists hold the same landing pages (the order does not matter). */
function sameLandingPages(
  left: Array<{ name: string; url: string; kind: string }>,
  right: Array<{ name: string; url: string; kind: string }>,
): boolean {
  if (left.length !== right.length) return false;
  const a = left.map(landingKey).sort();
  const b = right.map(landingKey).sort();
  return a.every((value, index) => value === b[index]);
}

/**
 * Edit dialog of a project.
 *
 * It changes the name, the description, the target website, the business
 * profile, the status and the landing pages of a project.  Only the fields
 * that were sent are changed - the backend works the same way.
 *
 * After the save the stored state is read back.  Everything the backend did
 * not store is reported to the user instead of being claimed as saved.
 */
export function ProjectEditDialog({
  open,
  project,
  onClose,
  onSaved,
}: {
  open: boolean;
  /** The project that is edited - null closes the dialog. */
  project: Project | null;
  onClose: () => void;
  /** Called with the stored project - the list reloads it. */
  onSaved: (project: Project) => void;
}) {
  const toast = useToast();
  const action = useAction();
  const projectId = project?.id ?? "";

  const detail = useResource(
    () => api.projects.get(apiClient, projectId),
    [projectId],
    { enabled: open && Boolean(projectId) },
  );
  const landing = useResource(
    () => api.projects.websites(apiClient, projectId, { page: 1, page_size: 100 }),
    [projectId],
    { enabled: open && Boolean(projectId) },
  );
  const backlinkDetails = useResource(
    () => api.projects.details(apiClient, projectId),
    [projectId],
    { enabled: open && Boolean(projectId) },
  );

  const [name, setName] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [targetWebsite, setTargetWebsite] = React.useState("");
  const [profileId, setProfileId] = React.useState("");
  const [status, setStatus] = React.useState<Project["status"]>("ACTIVE");
  const [landingPages, setLandingPages] = React.useState<LandingDraft[]>([]);
  const [formError, setFormError] = React.useState<string | null>(null);
  /** The details a directory asks for - stored in the business profile. */
  const [details, setDetails] = React.useState<BacklinkDetailsUpdate | null>(null);
  const [detailsInfo, setDetailsInfo] = React.useState<BacklinkDetails | null>(null);
  /** The changes the backend did not store - they are shown to the user. */
  const [notices, setNotices] = React.useState<string[]>([]);
  const keyCounter = React.useRef(0);

  /* The form follows the record of the backend - never a stale list row. */
  React.useEffect(() => {
    if (!open) return;
    const source = detail.data;
    if (!source) return;
    setName(source.name);
    setDescription(source.description ?? "");
    setTargetWebsite(source.target_website);
    setProfileId(source.business_profile_id ?? "");
    setStatus(source.status);
    setFormError(null);
    setNotices([]);
  }, [open, detail.data]);

  /* The backlink details come from the business profile of the project. */
  React.useEffect(() => {
    if (!open || !backlinkDetails.settled) return;
    const source = backlinkDetails.data;
    if (!source) {
      setDetails(null);
      setDetailsInfo(null);
      return;
    }
    setDetailsInfo(source);
    setDetails({
      company_name: source.company_name,
      description: source.description,
      email: source.email,
      phone: source.phone,
      website: source.website,
      address: source.address,
      city: source.city,
      state: source.state,
      country: source.country,
      postal_code: source.postal_code,
      categories: source.categories,
      founded_year: source.founded_year ?? null,
      employee_count: source.employee_count ?? null,
      anchors: source.anchors,
    });
  }, [open, backlinkDetails.settled, backlinkDetails.data]);

  /* The landing pages come from the landing pages of the project. */
  React.useEffect(() => {
    if (!open || !landing.settled) return;
    setLandingPages(
      (landing.data?.items ?? []).map((item) => ({
        key: item.id,
        name: item.name,
        url: item.url,
        kind: item.kind,
      })),
    );
  }, [open, landing.settled, landing.data]);

  const moveLandingPage = (index: number, delta: number) => {
    setLandingPages((prev) => {
      const target = index + delta;
      if (target < 0 || target >= prev.length) return prev;
      const next = [...prev];
      const [moved] = next.splice(index, 1);
      next.splice(target, 0, moved);
      return next;
    });
  };

  const addLandingPage = () => {
    keyCounter.current += 1;
    setLandingPages((prev) => [
      ...prev,
      { key: `new-${keyCounter.current}`, name: "", url: "", kind: "LANDING" },
    ]);
  };

  /** Reads the stored state of the project back from the backend. */
  const readStoredState = async (
    id: string,
  ): Promise<{
    project: Project;
    landingPages: Array<{ name: string; url: string; kind: TargetWebsite["kind"] }>;
  } | null> => {
    try {
      const [stored, pages] = await Promise.all([
        api.projects.get(apiClient, id),
        api.projects.websites(apiClient, id, { page: 1, page_size: 100 }),
      ]);
      return {
        project: stored,
        landingPages: pages.items.map((item) => ({
          name: item.name,
          url: item.url,
          kind: item.kind,
        })),
      };
    } catch {
      return null;
    }
  };

  const save = async () => {
    setFormError(null);
    setNotices([]);

    const trimmedName = name.trim();
    if (!trimmedName) {
      setFormError("The project name is required.");
      return;
    }
    const website = normalizeWebsite(targetWebsite);
    if (!website) {
      setFormError(
        "The target website must be a valid http(s) address - for example https://www.example.com",
      );
      return;
    }

    const pages = landingPages
      .filter((page) => page.url.trim())
      .map((page) => {
        const url = normalizeWebsite(page.url) ?? page.url.trim();
        return { name: page.name.trim() || url, url, kind: page.kind };
      });

    const body: ProjectEditBody = {
      name: trimmedName,
      description: description.trim(),
      target_website: website,
      business_profile_id: profileId || null,
      status,
      landing_pages: pages,
    };

    const problems: string[] = [];

    /* The details live in the business profile - saving them is a second call. */
    if (details) {
      const stored = await action.run(() =>
        api.projects.saveDetails(apiClient, projectId, details),
      );
      if (!stored.ok) {
        problems.push("The backlink details could not be saved - the project fields were saved.");
      }
    }

    const withLanding = await action.run(() =>
      api.projects.update(apiClient, projectId, body),
    );
    /* The landing pages are only stored when the backend accepts the field. */
    const landingSent = withLanding.ok;
    if (!withLanding.ok) {
      /* Not every backend accepts the extra field - save the core fields alone. */
      const core = await action.run(() =>
        api.projects.update(apiClient, projectId, {
          name: body.name,
          description: body.description,
          target_website: body.target_website,
          business_profile_id: body.business_profile_id,
          status: body.status,
        }),
      );
      if (!core.ok) return;
      problems.push(
        "The backend rejected the landing pages in the request - only the other fields were saved.",
      );
    }

    /* Read the stored state back: nothing is claimed that was not stored. */
    const stored = await readStoredState(projectId);
    if (stored) {
      if (!body.business_profile_id && stored.project.business_profile_id) {
        problems.push(
          "The business profile was not removed - the backend keeps the previous one.",
        );
      }
      if (landingSent && !sameLandingPages(body.landing_pages, stored.landingPages)) {
        problems.push(
          "The landing pages were not stored - the backend endpoint does not support changing them yet.",
        );
      }
    }

    setNotices(problems);
    onSaved(stored?.project ?? withLanding.data ?? (project as Project));

    if (problems.length > 0) {
      toast.push("Project saved - the backend did not store everything", "info");
      return;
    }
    toast.push("Project saved", "success");
    onClose();
  };

  const loading = detail.loading && !detail.data;

  return (
    <Dialog
      open={open && Boolean(project)}
      onClose={onClose}
      title="Project details"
      description="Change what this project needs - nothing is sent until you save."
      width="lg"
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={action.pending}>
            Cancel
          </Button>
          <Button onClick={() => void save()} loading={action.pending}>
            Save changes
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {notices.length > 0 ? (
          <Alert tone="warning" title="The backend did not store everything">
            <ul className="list-inside list-disc space-y-0.5">
              {notices.map((notice) => (
                <li key={notice}>{notice}</li>
              ))}
            </ul>
          </Alert>
        ) : null}

        {detail.error && !detail.data ? (
          <Alert tone="danger" title="The project could not be loaded">
            {errorMessage(detail.error)}
          </Alert>
        ) : null}

        {loading ? (
          <div className="space-y-2" aria-busy="true">
            <span className="sr-only">Loading the project…</span>
            <Skeleton className="h-9 w-full" />
            <Skeleton className="h-9 w-full" />
            <Skeleton className="h-9 w-2/3" />
          </div>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Project name" required>
                <Input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="Website Authority Growth"
                  disabled={action.pending}
                />
              </Field>
              <Field label="Status" hint="A paused project queues nothing new.">
                <Select
                  value={status}
                  onChange={(event) => setStatus(event.target.value as Project["status"])}
                  disabled={action.pending}
                >
                  {STATUS_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>

            <Field label="Description">
              <Textarea
                rows={2}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="What is this project trying to achieve?"
                disabled={action.pending}
              />
            </Field>

            <Field
              label="Target website"
              required
              hint="The page that should receive the backlinks. The scheme is added when it is missing."
            >
              <Input
                value={targetWebsite}
                onChange={(event) => setTargetWebsite(event.target.value)}
                placeholder="https://www.example.com"
                disabled={action.pending}
              />
            </Field>

            <p className="rounded-md border border-line bg-surface-sunken px-3 py-2 text-[11px] text-content-muted">
              The company details below belong to this project only. Every website of the
              project reuses them.
            </p>
          </>
        )}

        <section className="space-y-2 border-t border-line pt-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="text-sm font-semibold text-content">Landing pages</h3>
              <p className="text-xs text-content-muted">
                The additional pages of this project a backlink may point to. Add, remove and
                reorder them.
              </p>
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={addLandingPage}
              disabled={action.pending}
            >
              Add landing page
            </Button>
          </div>

          {landing.loading && !landing.data ? (
            <div className="space-y-2" aria-busy="true">
              <span className="sr-only">Loading the landing pages…</span>
              <Skeleton className="h-16 w-full" />
            </div>
          ) : landing.error ? (
            <Alert
              tone="danger"
              title="The landing pages could not be loaded"
              action={
                <Button variant="outline" size="sm" onClick={landing.reload}>
                  Try again
                </Button>
              }
            >
              {errorMessage(landing.error)}
            </Alert>
          ) : null}

          {landingPages.map((page, index) => (
            <div
              key={page.key}
              className="grid gap-2 rounded-md border border-line p-3 sm:grid-cols-[1fr_1fr_140px_auto]"
            >
              <Field label="Name">
                <Input
                  value={page.name}
                  onChange={(event) =>
                    setLandingPages((prev) =>
                      prev.map((item, i) =>
                        i === index ? { ...item, name: event.target.value } : item,
                      ),
                    )
                  }
                  placeholder="Pricing"
                  disabled={action.pending}
                />
              </Field>
              <Field label="URL">
                <Input
                  value={page.url}
                  onChange={(event) =>
                    setLandingPages((prev) =>
                      prev.map((item, i) =>
                        i === index ? { ...item, url: event.target.value } : item,
                      ),
                    )
                  }
                  placeholder="https://www.example.com/pricing"
                  disabled={action.pending}
                />
              </Field>
              <Field label="Kind">
                <Select
                  value={page.kind}
                  onChange={(event) =>
                    setLandingPages((prev) =>
                      prev.map((item, i) =>
                        i === index
                          ? { ...item, kind: event.target.value as TargetWebsite["kind"] }
                          : item,
                      ),
                    )
                  }
                  disabled={action.pending}
                >
                  {KIND_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </Select>
              </Field>
              <div className="flex items-end gap-1">
                <IconButton
                  label={`Move ${page.name || "landing page"} up`}
                  onClick={() => moveLandingPage(index, -1)}
                  disabled={index === 0 || action.pending}
                >
                  ↑
                </IconButton>
                <IconButton
                  label={`Move ${page.name || "landing page"} down`}
                  onClick={() => moveLandingPage(index, 1)}
                  disabled={index === landingPages.length - 1 || action.pending}
                >
                  ↓
                </IconButton>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() =>
                    setLandingPages((prev) => prev.filter((_, i) => i !== index))
                  }
                  disabled={action.pending}
                >
                  Remove
                </Button>
              </div>
            </div>
          ))}

          {landingPages.length === 0 && !landing.loading ? (
            <p className="text-xs text-content-subtle">
              This project has no landing page yet - the target website above is the only
              destination.
            </p>
          ) : null}
        </section>

        <section className="space-y-2 border-t border-line pt-3">
          <div>
            <h3 className="text-sm font-semibold text-content">Company details</h3>
            <p className="text-xs text-content-muted">
              The facts a backlink website asks for when it publishes a link. They are saved
              for this project and reused by every website of the project.
            </p>
          </div>

          {backlinkDetails.loading && !backlinkDetails.data ? (
            <div className="space-y-2" aria-busy="true">
              <span className="sr-only">Loading the backlink details…</span>
              <Skeleton className="h-24 w-full" />
            </div>
          ) : backlinkDetails.error ? (
            <Alert
              tone="danger"
              title="The backlink details could not be loaded"
              action={
                <Button variant="outline" size="sm" onClick={backlinkDetails.reload}>
                  Try again
                </Button>
              }
            >
              {errorMessage(backlinkDetails.error)}
            </Alert>
          ) : details ? (
            <>
              {(detailsInfo?.notes ?? []).map((note) => (
                <p
                  key={note}
                  className="rounded-md border border-line bg-surface-sunken px-3 py-2 text-xs text-content-muted"
                >
                  {note}
                </p>
              ))}
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Company name">
                  <Input
                    value={details.company_name ?? ""}
                    onChange={(event) =>
                      setDetails({ ...details, company_name: event.target.value })
                    }
                    disabled={action.pending}
                  />
                </Field>
                <Field label="Website">
                  <Input
                    value={details.website ?? ""}
                    onChange={(event) => setDetails({ ...details, website: event.target.value })}
                    disabled={action.pending}
                  />
                </Field>
                <Field label="E-mail address">
                  <Input
                    type="email"
                    value={details.email ?? ""}
                    onChange={(event) => setDetails({ ...details, email: event.target.value })}
                    disabled={action.pending}
                  />
                </Field>
                <Field label="Phone number">
                  <Input
                    value={details.phone ?? ""}
                    onChange={(event) => setDetails({ ...details, phone: event.target.value })}
                    disabled={action.pending}
                  />
                </Field>
                <Field label="Street address" className="sm:col-span-2">
                  <Input
                    value={details.address ?? ""}
                    onChange={(event) => setDetails({ ...details, address: event.target.value })}
                    disabled={action.pending}
                  />
                </Field>
                <Field label="City">
                  <Input
                    value={details.city ?? ""}
                    onChange={(event) => setDetails({ ...details, city: event.target.value })}
                    disabled={action.pending}
                  />
                </Field>
                <Field label="State / region">
                  <Input
                    value={details.state ?? ""}
                    onChange={(event) => setDetails({ ...details, state: event.target.value })}
                    disabled={action.pending}
                  />
                </Field>
                <Field label="Country">
                  <Input
                    value={details.country ?? ""}
                    onChange={(event) => setDetails({ ...details, country: event.target.value })}
                    disabled={action.pending}
                  />
                </Field>
                <Field label="Postal code">
                  <Input
                    value={details.postal_code ?? ""}
                    onChange={(event) =>
                      setDetails({ ...details, postal_code: event.target.value })
                    }
                    disabled={action.pending}
                  />
                </Field>
                <Field label="Categories" hint="Comma separated.">
                  <Input
                    value={(details.categories ?? []).join(", ")}
                    onChange={(event) =>
                      setDetails({
                        ...details,
                        categories: event.target.value
                          .split(",")
                          .map((item) => item.trim())
                          .filter(Boolean),
                      })
                    }
                    disabled={action.pending}
                  />
                </Field>
                <Field label="Anchors" hint="Comma separated. The texts the backlinks should use.">
                  <Input
                    value={(details.anchors ?? []).join(", ")}
                    onChange={(event) =>
                      setDetails({
                        ...details,
                        anchors: event.target.value
                          .split(",")
                          .map((item) => item.trim())
                          .filter(Boolean),
                      })
                    }
                    disabled={action.pending}
                  />
                </Field>
                <Field label="Year founded">
                  <Input
                    type="number"
                    value={details.founded_year ?? ""}
                    onChange={(event) =>
                      setDetails({
                        ...details,
                        founded_year: event.target.value
                          ? Number.parseInt(event.target.value, 10)
                          : null,
                      })
                    }
                    disabled={action.pending}
                  />
                </Field>
                <Field label="Number of employees">
                  <Input
                    type="number"
                    value={details.employee_count ?? ""}
                    onChange={(event) =>
                      setDetails({
                        ...details,
                        employee_count: event.target.value
                          ? Number.parseInt(event.target.value, 10)
                          : null,
                      })
                    }
                    disabled={action.pending}
                  />
                </Field>
                <Field label="Description" className="sm:col-span-2">
                  <Textarea
                    rows={3}
                    value={details.description ?? ""}
                    onChange={(event) =>
                      setDetails({ ...details, description: event.target.value })
                    }
                    disabled={action.pending}
                  />
                </Field>
              </div>
              {(detailsInfo?.required ?? []).length > 0 ? (
                <p className="text-xs text-content-muted">
                  Completeness: {(detailsInfo?.filled ?? []).length} of{" "}
                  {(detailsInfo?.required ?? []).length} fields the websites ask for are available
                  {(detailsInfo?.missing ?? []).length > 0
                    ? ` - still missing: ${(detailsInfo?.missing ?? []).join(", ")}`
                    : ""}
                  .
                </p>
              ) : null}
            </>
          ) : null}
        </section>

        {formError ? (
          <p
            role="alert"
            className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-xs text-danger"
          >
            {formError}
          </p>
        ) : null}
        {action.error ? (
          <p
            role="alert"
            className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-xs text-danger"
          >
            {errorMessage(action.error)}
          </p>
        ) : null}
      </div>
    </Dialog>
  );
}
