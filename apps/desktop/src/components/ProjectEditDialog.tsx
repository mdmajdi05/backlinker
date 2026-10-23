/**
 * The dialogs of a project: editing it and deleting it.
 *
 * Both live in one file so that the projects list and the project page show
 * exactly the same wording - especially the warning of the deletion, which has
 * to tell the truth about what the backend removes and what it keeps.
 *
 * The backend knows the fields of a project (`PATCH /projects/{id}`) and the
 * landing pages of a project (`GET /projects/{id}/websites`).  Not every
 * backend writes the landing pages of an existing project - the dialog reads
 * the project back after the save and reports the fields that did not arrive
 * instead of pretending that everything was saved.
 */

import * as React from "react";
import {
  Alert,
  Badge,
  Button,
  Dialog,
  Field,
  Input,
  Select,
  Skeleton,
  Textarea,
  useToast,
} from "@autobacklinker/ui";
import { api, apiClient } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import { sendNativeNotification } from "../lib/backend";
import { formatNumber } from "../lib/format";
import type {
  BacklinkDetails,
  BacklinkDetailsUpdate,
  BusinessProfile,
  Project,
  ProjectCounts,
  TargetWebsite,
} from "@autobacklinker/shared-types";

export type ProjectStatus = "ACTIVE" | "PAUSED" | "ARCHIVED";

const LANDING_KINDS: Array<{ value: TargetWebsite["kind"]; label: string }> = [
  { value: "MAIN", label: "Main page" },
  { value: "LANDING", label: "Landing page" },
  { value: "BLOG", label: "Blog" },
  { value: "OTHER", label: "Other" },
];

/** One landing page while it is edited. */
interface LandingPageDraft {
  key: string;
  name: string;
  url: string;
  kind: TargetWebsite["kind"];
}

/** One landing page as it is sent to the backend. */
interface LandingPagePayload {
  name: string;
  url: string;
  kind: TargetWebsite["kind"];
}

/**
 * The payload of the update.
 *
 * The landing pages are newer than the shared client - they are only written
 * by a backend that knows them.  The dialog checks the answer afterwards.
 */
type ProjectUpdateBody = Partial<Project> & {
  landing_pages?: LandingPagePayload[];
};

function errorText(error: unknown, fallback: string): string {
  if (error && typeof error === "object" && "message" in error) {
    return String((error as { message: unknown }).message);
  }
  return fallback;
}

/** The URL as the backend stores it: with a scheme and without a slash. */
function normalizeUrl(value: string): string {
  const trimmed = value.trim();
  const withScheme = /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
  return withScheme.replace(/\/+$/, "").toLowerCase();
}

/** Do the two lists of landing pages describe the same pages? */
function sameLandingPages(
  wanted: LandingPagePayload[],
  current: TargetWebsite[],
): boolean {
  const wantedKeys = wanted
    .filter((page) => page.url.trim())
    .map(
      (page) =>
        `${page.name.trim() || page.url.trim()}@${normalizeUrl(page.url)}`,
    )
    .sort();
  const currentKeys = current
    .map((page) => `${page.name.trim()}@${normalizeUrl(page.url)}`)
    .sort();
  if (wantedKeys.length !== currentKeys.length) return false;
  return wantedKeys.every((key, index) => key === currentKeys[index]);
}

/**
 * Which of the sent fields did not arrive at the backend?
 *
 * An empty list means that everything was written.
 */
function rejectedFields(
  body: ProjectUpdateBody,
  project: Project,
  landingPages: TargetWebsite[],
): string[] {
  const missing: string[] = [];
  if (project.name !== body.name) missing.push("Name");
  if ((project.description ?? "") !== (body.description ?? "")) {
    missing.push("Description");
  }
  if (normalizeUrl(project.target_website) !== normalizeUrl(body.target_website ?? "")) {
    missing.push("Target website");
  }
  if (project.status !== body.status) missing.push("Status");
  if ((project.business_profile_id ?? "") !== (body.business_profile_id ?? "")) {
    missing.push("Business profile");
  }
  if (!sameLandingPages(body.landing_pages ?? [], landingPages)) {
    missing.push("Landing pages");
  }
  return missing;
}

export function ProjectEditDialog({
  open,
  project,
  onClose,
  onSaved,
}: {
  open: boolean;
  project: Project | null;
  onClose: () => void;
  /** Called after the backend accepted the change. */
  onSaved?: (project?: Project) => void;
}) {
  const toast = useToast();
  const [name, setName] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [targetWebsite, setTargetWebsite] = React.useState("");
  const [profileId, setProfileId] = React.useState("");
  const [status, setStatus] = React.useState<ProjectStatus>("ACTIVE");
  const [drafts, setDrafts] = React.useState<LandingPageDraft[]>([]);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [notAccepted, setNotAccepted] = React.useState<string[]>([]);
  /** The facts a directory asks for - stored in the business profile. */
  const [details, setDetails] = React.useState<BacklinkDetailsUpdate | null>(null);
  const [detailsInfo, setDetailsInfo] = React.useState<BacklinkDetails | null>(null);
  const counter = React.useRef(0);

  const profiles = useAsync(
    async () => (open ? api.profiles.list(apiClient) : ([] as BusinessProfile[])),
    [open],
  );

  const landingPages = useAsync(
    async () => {
      if (!open || !project) return [] as TargetWebsite[];
      const page = await api.projects.websites(apiClient, project.id, {
        page: 1,
        page_size: 100,
      });
      return page?.items ?? [];
    },
    [open, project?.id],
  );

  const backlink = useAsync(
    async () => {
      if (!open || !project) return null;
      return api.projects.details(apiClient, project.id);
    },
    [open, project?.id],
  );

  // The form starts with the values of the project.  It is only reset when a
  // different project is opened - a reload of the list must not throw away
  // what the operator is typing.
  React.useEffect(() => {
    if (!open || !project) return;
    setName(project.name ?? "");
    setDescription(project.description ?? "");
    setTargetWebsite(project.target_website ?? "");
    setProfileId(project.business_profile_id ?? "");
    setStatus((project.status ?? "ACTIVE") as ProjectStatus);
    setError(null);
    setNotAccepted([]);
    setDrafts([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, project?.id]);

  // The backlink details come from the business profile of the project.
  React.useEffect(() => {
    if (!open) return;
    const source = backlink.data ?? null;
    setDetailsInfo(source);
    setDetails(
      source
        ? {
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
          }
        : null,
    );
  }, [open, backlink.data]);

  // The landing pages come from the backend.
  React.useEffect(() => {
    if (!open) return;
    setDrafts(
      (landingPages.data ?? []).map((page) => ({
        key: page.id,
        name: page.name,
        url: page.url,
        kind: page.kind,
      })),
    );
  }, [open, landingPages.data]);

  function updateDraft(key: string, patch: Partial<LandingPageDraft>) {
    setDrafts((previous) =>
      previous.map((draft) =>
        draft.key === key ? { ...draft, ...patch } : draft,
      ),
    );
  }

  function moveDraft(index: number, offset: number) {
    setDrafts((previous) => {
      const target = index + offset;
      if (target < 0 || target >= previous.length) return previous;
      const next = [...previous];
      const [item] = next.splice(index, 1);
      next.splice(target, 0, item);
      return next;
    });
  }

  function addDraft() {
    counter.current += 1;
    setDrafts((previous) => [
      ...previous,
      {
        key: `new-${counter.current}`,
        name: "",
        url: "",
        kind: "LANDING",
      },
    ]);
  }

  async function save() {
    if (!project) return;
    setSaving(true);
    setError(null);
    setNotAccepted([]);

    const body: ProjectUpdateBody = {
      name: name.trim(),
      description: description.trim(),
      target_website: targetWebsite.trim(),
      business_profile_id: profileId.trim() || null,
      status,
      landing_pages: drafts
        .filter((draft) => draft.url.trim())
        .map((draft) => ({
          name: draft.name.trim() || draft.url.trim(),
          url: draft.url.trim(),
          kind: draft.kind,
        })),
    };

    /* The details live in the business profile - they are a second call. */
    if (details) {
      try {
        await api.projects.saveDetails(apiClient, project.id, details);
      } catch (err) {
        setError(
          `The backlink details were not saved: ${errorText(
            err,
            "the backend did not answer",
          )}`,
        );
        setSaving(false);
        return;
      }
    }

    try {
      await api.projects.update(apiClient, project.id, body);
    } catch (err) {
      setError(errorText(err, "Could not save the project"));
      setSaving(false);
      return;
    }

    // The backend may accept only a part of the payload - read the project
    // back and say what did not arrive.  A silent success would be a lie.
    let fresh: Project;
    let freshLanding: TargetWebsite[] = [];
    try {
      const [project_, landing_] = await Promise.all([
        api.projects.get(apiClient, project.id),
        api.projects.websites(apiClient, project.id, {
          page: 1,
          page_size: 100,
        }),
      ]);
      fresh = project_;
      freshLanding = landing_?.items ?? [];
    } catch (err) {
      // The save worked - only the check of the answer failed.
      onSaved?.();
      toast.push("Project saved", "success");
      void sendNativeNotification(
        "Auto Backlinker",
        `The project ${body.name} was saved.`,
      );
      setError(
        `The project was saved, but it could not be read back: ${errorText(
          err,
          "the backend did not answer",
        )}`,
      );
      setSaving(false);
      return;
    }

    const missing = rejectedFields(body, fresh, freshLanding);
    onSaved?.(fresh);

    if (missing.length === 0) {
      toast.push(`Project "${body.name}" saved`, "success");
      void sendNativeNotification(
        "Auto Backlinker",
        `The project ${body.name} was saved.`,
      );
      onClose();
    } else {
      setNotAccepted(missing);
      setDrafts(
        freshLanding.map((page) => ({
          key: page.id,
          name: page.name,
          url: page.url,
          kind: page.kind,
        })),
      );
      toast.push(
        `Project saved - not accepted by the backend: ${missing.join(", ")}`,
        "error",
      );
    }
    setSaving(false);
  }

  const canSave = Boolean(name.trim() && targetWebsite.trim()) && !saving;

  return (
    <Dialog
      open={open && Boolean(project)}
      onClose={() => {
        if (!saving) onClose();
      }}
      title={project ? `Edit the project "${project.name}"` : "Edit the project"}
      description="The name, the target, the business profile, the state and the landing pages of the project."
      width="lg"
      footer={
        <>
          <Button
            variant="ghost"
            onClick={onClose}
            disabled={saving}
          >
            Cancel
          </Button>
          <Button loading={saving} disabled={!canSave} onClick={() => void save()}>
            Save the project
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        {error ? (
          <Alert tone="danger" title="The project was not saved">
            {error}
          </Alert>
        ) : null}

        {notAccepted.length > 0 ? (
          <Alert
            tone="warning"
            title="The backend did not accept every change"
          >
            <p>
              {notAccepted.join(", ")} could not be written. This backend
              changes only the fields of a project - it ignores the empty
              values and does not know the landing pages of a project that
              already exists. The values below are the ones the backend
              stored.
            </p>
          </Alert>
        ) : null}

        <Field label="Name" required>
          <Input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Acme backlinks"
          />
        </Field>

        <Field label="Description">
          <Textarea
            rows={3}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="What should this project achieve?"
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

        <div className="grid gap-3 sm:grid-cols-2">
          <Field
            label="Business profile"
            hint="Optional. Leave it empty to keep this project's own details."
          >
            {profiles.loading && !profiles.data ? (
              <Skeleton className="h-9 w-full" />
            ) : (
              <Select
                value={profileId}
                onChange={(event) => setProfileId(event.target.value)}
                aria-label="The business profile of the project"
              >
                <option value="">No profile</option>
                {(profiles.data ?? []).map((profile) => (
                  <option key={profile.id} value={profile.id}>
                    {profile.name} · {profile.primary_website}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        </div>

        {profiles.error ? (
          <p className="text-xs text-danger">
            The business profiles could not be loaded: {profiles.error}
          </p>
        ) : null}

        <div className="rounded-md border border-line p-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <div>
              <p className="text-xs font-semibold text-content">Landing pages</p>
              <p className="text-[11px] text-content-subtle">
                The pages of your own site a backlink may point to. The first
                one is the main page.
              </p>
            </div>
            <Button size="sm" variant="outline" onClick={addDraft}>
              Add a page
            </Button>
          </div>

          {landingPages.loading && !landingPages.data ? (
            <div className="flex flex-col gap-2">
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
            </div>
          ) : null}

          {landingPages.error ? (
            <Alert
              tone="warning"
              title="The landing pages could not be loaded"
            >
              {landingPages.error}
            </Alert>
          ) : null}

          {!landingPages.loading && drafts.length === 0 ? (
            <p className="py-2 text-xs text-content-subtle">
              This project has no landing page yet. Add the page the backlinks
              should point to.
            </p>
          ) : null}

          {drafts.length > 0 ? (
            <ul className="flex flex-col gap-2">
              {drafts.map((draft, index) => {
                const label = draft.name.trim() || draft.url.trim() || "page";
                return (
                  <li
                    key={draft.key}
                    className="flex flex-wrap items-end gap-2 rounded-md border border-line p-2"
                  >
                    <div className="min-w-[160px] flex-1">
                      <label
                        className="mb-1 block text-[11px] font-medium text-content-muted"
                        htmlFor={`landing-name-${draft.key}`}
                      >
                        Name
                      </label>
                      <Input
                        id={`landing-name-${draft.key}`}
                        className="h-8 text-xs"
                        value={draft.name}
                        placeholder="Product page"
                        onChange={(event) =>
                          updateDraft(draft.key, { name: event.target.value })
                        }
                      />
                    </div>
                    <div className="min-w-[220px] flex-[2]">
                      <label
                        className="mb-1 block text-[11px] font-medium text-content-muted"
                        htmlFor={`landing-url-${draft.key}`}
                      >
                        URL
                      </label>
                      <Input
                        id={`landing-url-${draft.key}`}
                        className="h-8 text-xs"
                        value={draft.url}
                        placeholder="https://example.com/product"
                        onChange={(event) =>
                          updateDraft(draft.key, { url: event.target.value })
                        }
                      />
                    </div>
                    <div className="w-36">
                      <label
                        className="mb-1 block text-[11px] font-medium text-content-muted"
                        htmlFor={`landing-kind-${draft.key}`}
                      >
                        Kind
                      </label>
                      <Select
                        id={`landing-kind-${draft.key}`}
                        className="h-8 text-xs"
                        value={draft.kind}
                        onChange={(event) =>
                          updateDraft(draft.key, {
                            kind: event.target.value as TargetWebsite["kind"],
                          })
                        }
                      >
                        {LANDING_KINDS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </Select>
                    </div>
                    <div className="flex items-center gap-1 pb-0.5">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={index === 0}
                        aria-label={`Move ${label} up`}
                        title="Move up"
                        onClick={() => moveDraft(index, -1)}
                      >
                        ↑
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={index === drafts.length - 1}
                        aria-label={`Move ${label} down`}
                        title="Move down"
                        onClick={() => moveDraft(index, 1)}
                      >
                        ↓
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        aria-label={`Remove ${label}`}
                        title="Remove"
                        className="text-danger"
                        onClick={() =>
                          setDrafts((previous) =>
                            previous.filter((item) => item.key !== draft.key),
                          )
                        }
                      >
                        Remove
                      </Button>
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : null}
        </div>

        <div className="rounded-md border border-line p-3">
          <div className="mb-2">
            <p className="text-xs font-semibold text-content">Company details</p>
            <p className="text-[11px] text-content-subtle">
              The facts a directory asks for. They are stored once in the
              business profile, so every website of this project reuses them.
            </p>
          </div>

          {backlink.loading && !backlink.data ? (
            <div className="flex flex-col gap-2">
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
            </div>
          ) : null}

          {backlink.error ? (
            <Alert tone="warning" title="The backlink details could not be loaded">
              {backlink.error}
            </Alert>
          ) : null}

          {details ? (
            <>
              {(detailsInfo?.notes ?? []).map((note) => (
                <p
                  key={note}
                  className="mb-2 rounded-md border border-line px-2 py-1.5 text-[11px] text-content-muted"
                >
                  {note}
                </p>
              ))}
              <div className="grid gap-2 sm:grid-cols-2">
                <Field label="Company name">
                  <Input
                    className="h-8 text-xs"
                    value={details.company_name ?? ""}
                    onChange={(event) =>
                      setDetails({ ...details, company_name: event.target.value })
                    }
                  />
                </Field>
                <Field label="Website">
                  <Input
                    className="h-8 text-xs"
                    value={details.website ?? ""}
                    onChange={(event) =>
                      setDetails({ ...details, website: event.target.value })
                    }
                  />
                </Field>
                <Field label="E-mail address">
                  <Input
                    className="h-8 text-xs"
                    type="email"
                    value={details.email ?? ""}
                    onChange={(event) =>
                      setDetails({ ...details, email: event.target.value })
                    }
                  />
                </Field>
                <Field label="Phone number">
                  <Input
                    className="h-8 text-xs"
                    value={details.phone ?? ""}
                    onChange={(event) =>
                      setDetails({ ...details, phone: event.target.value })
                    }
                  />
                </Field>
                <div className="sm:col-span-2">
                  <Field label="Street address">
                    <Input
                      className="h-8 text-xs"
                      value={details.address ?? ""}
                      onChange={(event) =>
                        setDetails({ ...details, address: event.target.value })
                      }
                    />
                  </Field>
                </div>
                <Field label="City">
                  <Input
                    className="h-8 text-xs"
                    value={details.city ?? ""}
                    onChange={(event) =>
                      setDetails({ ...details, city: event.target.value })
                    }
                  />
                </Field>
                <Field label="State / region">
                  <Input
                    className="h-8 text-xs"
                    value={details.state ?? ""}
                    onChange={(event) =>
                      setDetails({ ...details, state: event.target.value })
                    }
                  />
                </Field>
                <Field label="Country">
                  <Input
                    className="h-8 text-xs"
                    value={details.country ?? ""}
                    onChange={(event) =>
                      setDetails({ ...details, country: event.target.value })
                    }
                  />
                </Field>
                <Field label="Postal code">
                  <Input
                    className="h-8 text-xs"
                    value={details.postal_code ?? ""}
                    onChange={(event) =>
                      setDetails({ ...details, postal_code: event.target.value })
                    }
                  />
                </Field>
                <Field label="Categories" hint="Comma separated.">
                  <Input
                    className="h-8 text-xs"
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
                  />
                </Field>
                <Field label="Anchors" hint="Comma separated. The texts the backlinks should use.">
                  <Input
                    className="h-8 text-xs"
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
                  />
                </Field>
                <Field label="Year founded">
                  <Input
                    className="h-8 text-xs"
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
                  />
                </Field>
                <Field label="Number of employees">
                  <Input
                    className="h-8 text-xs"
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
                  />
                </Field>
                <div className="sm:col-span-2">
                  <Field label="Description">
                    <Textarea
                      rows={3}
                      value={details.description ?? ""}
                      onChange={(event) =>
                        setDetails({ ...details, description: event.target.value })
                      }
                    />
                  </Field>
                </div>
              </div>
              {(detailsInfo?.required ?? []).length > 0 ? (
                <p className="mt-2 text-[11px] text-content-muted">
                  Completeness: {(detailsInfo?.filled ?? []).length} of{" "}
                  {(detailsInfo?.required ?? []).length} fields the websites ask
                  for are available
                  {(detailsInfo?.missing ?? []).length > 0
                    ? ` - still missing: ${(detailsInfo?.missing ?? []).join(", ")}`
                    : ""}
                  .
                </p>
              ) : null}
            </>
          ) : null}
        </div>

        {project ? (
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-content-subtle">
            <Badge tone="neutral">v{project.version}</Badge>
            <span>
              The project keeps its history - the reports of the past stay in
              the database.
            </span>
          </div>
        ) : null}
      </div>
    </Dialog>
  );
}

/**
 * The confirmation of the deletion of a project.
 *
 * The dialog tells what the backend really removes: the work of the project
 * disappears, the shared websites and the business profile stay.
 */
export function ProjectDeleteDialog({
  open,
  project,
  counts,
  busy,
  error,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  project: Project | null;
  /** The counters of the project - they are only shown when they are known. */
  counts?: ProjectCounts | null;
  busy?: boolean;
  error?: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <Dialog
      open={open && Boolean(project)}
      onClose={() => {
        if (!busy) onCancel();
      }}
      title={project ? `Delete the project "${project.name}"?` : "Delete the project"}
      description="The project goes to the recycle bin - you can restore it there."
      width="md"
      footer={
        <>
          <Button
            variant="outline"
            onClick={onCancel}
            disabled={busy}
            autoFocus
          >
            Keep the project
          </Button>
          <Button
            variant="danger"
            loading={busy}
            onClick={onConfirm}
          >
            Move to the recycle bin
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        {error ? (
          <Alert tone="danger" title="The project was not deleted">
            {error}
          </Alert>
        ) : null}

        {counts ? (
          <p className="text-xs text-content-muted">
            {formatNumber(counts.opportunities)} opportunit
            {counts.opportunities === 1 ? "y" : "ies"},{" "}
            {formatNumber(counts.queued)} task
            {counts.queued === 1 ? "" : "s"} in the queue and{" "}
            {formatNumber(counts.verified_live)} verified link
            {counts.verified_live === 1 ? "" : "s"} disappear with it.
          </p>
        ) : null}

        <ul className="flex flex-col gap-2 text-xs text-content-muted">
          <li className="flex gap-2">
            <span aria-hidden className="text-danger">
              ✕
            </span>
            <span>
              The project disappears from the lists; its opportunities, tasks,
              attempts and verification records wait with it in the recycle bin.
            </span>
          </li>
          <li className="flex gap-2">
            <span aria-hidden className="text-success">
              ✓
            </span>
            <span>
              The websites stay in the website list - they are shared with the
              other projects and are not deleted.
            </span>
          </li>
          <li className="flex gap-2">
            <span aria-hidden className="text-success">
              ✓
            </span>
            <span>
              The business profile is not touched - it stays as it is and can
              still be used by other projects.
            </span>
          </li>
          <li className="flex gap-2">
            <span aria-hidden className="text-warning">
              !
            </span>
            <span>
              Nothing is lost right away. Restore it from the recycle bin, or use
              "Delete forever" there to remove it (and everything above) for good.
            </span>
          </li>
        </ul>
      </div>
    </Dialog>
  );
}
