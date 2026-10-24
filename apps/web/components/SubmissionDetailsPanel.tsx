"use client";

import * as React from "react";
import { api } from "@autobacklinker/api-client";
import type { SubmissionDetails, SubmissionDetailsUpdate } from "@autobacklinker/shared-types";
import {
  Alert,
  Badge,
  Button,
  Field,
  Input,
  Skeleton,
  Textarea,
  Tooltip,
  useToast,
} from "@autobacklinker/ui";
import { apiClient, errorMessage, isNotFoundError } from "@/lib/api";
import { useAction, useResource } from "@/lib/hooks";
import { formatDateTime, humanize } from "@/lib/format";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ErrorPanel } from "@/components/States";

/* ------------------------------------------------------------------ */
/* Field catalogue                                                     */
/* ------------------------------------------------------------------ */

type DetailFieldKey =
  | "company_name"
  | "description"
  | "email"
  | "phone"
  | "website"
  | "address"
  | "city"
  | "state"
  | "country"
  | "postal_code"
  | "logo_path"
  | "categories"
  | "founded_year"
  | "employee_count";

interface DetailFieldMeta {
  key: DetailFieldKey;
  label: string;
  /** What the target site needs the value for. */
  hint: string;
  kind: "input" | "textarea" | "number";
  placeholder?: string;
}

const DETAIL_FIELDS: DetailFieldMeta[] = [
  {
    key: "company_name",
    label: "Company name",
    hint: "The site publishes this name as the title of your listing.",
    kind: "input",
    placeholder: "Acme Analytics",
  },
  {
    key: "website",
    label: "Website",
    hint: "The page the backlink points to - usually your main landing page.",
    kind: "input",
    placeholder: "https://acme-analytics.example",
  },
  {
    key: "description",
    label: "Description",
    hint: "One or two sentences about your business - most directories use it as the listing text.",
    kind: "textarea",
    placeholder: "Acme Analytics turns raw events into product reports.",
  },
  {
    key: "email",
    label: "E-mail",
    hint: "The address the site uses to confirm the listing or to answer questions.",
    kind: "input",
    placeholder: "hello@acme-analytics.example",
  },
  {
    key: "phone",
    label: "Phone",
    hint: "Only needed when the site asks for a phone number.",
    kind: "input",
    placeholder: "+1 555 0100",
  },
  {
    key: "address",
    label: "Address",
    hint: "The street address of your business.",
    kind: "input",
    placeholder: "Musterstrasse 12",
  },
  { key: "city", label: "City", hint: "The city your business is located in.", kind: "input" },
  {
    key: "state",
    label: "State / region",
    hint: "The region, state or province of your business.",
    kind: "input",
  },
  {
    key: "country",
    label: "Country",
    hint: "The country your business is located in.",
    kind: "input",
  },
  {
    key: "postal_code",
    label: "Postal code",
    hint: "The postal code of your business address.",
    kind: "input",
  },
  {
    key: "logo_path",
    label: "Logo",
    hint: "Path or URL of the logo the site should show.",
    kind: "input",
    placeholder: "/uploads/logo.png",
  },
  {
    key: "categories",
    label: "Categories",
    hint: "The categories the site lists your business under.",
    kind: "input",
    placeholder: "Analytics, Reporting, SaaS",
  },
  {
    key: "founded_year",
    label: "Founded",
    hint: "The year your business was founded - sites use it for the directory filter.",
    kind: "number",
    placeholder: "2019",
  },
  {
    key: "employee_count",
    label: "Employees",
    hint: "The number of employees - some directories filter by company size.",
    kind: "number",
    placeholder: "12",
  },
];

const FIELD_META: Record<DetailFieldKey, DetailFieldMeta> = DETAIL_FIELDS.reduce(
  (acc, field) => {
    acc[field.key] = field;
    return acc;
  },
  {} as Record<DetailFieldKey, DetailFieldMeta>,
);

/** The fields that are stored as plain text. */
type TextFieldKey =
  | "company_name"
  | "description"
  | "email"
  | "phone"
  | "website"
  | "address"
  | "city"
  | "state"
  | "country"
  | "postal_code"
  | "logo_path";

const TEXT_FIELD_KEYS: TextFieldKey[] = [
  "company_name",
  "description",
  "email",
  "phone",
  "website",
  "address",
  "city",
  "state",
  "country",
  "postal_code",
  "logo_path",
];

/** Maps the field names used by the backend onto the fields of the form. */
const ALIAS_TO_FIELD: Record<string, DetailFieldKey> = {
  name: "company_name",
  company_name: "company_name",
  company: "company_name",
  business_name: "company_name",
  title: "company_name",
  organisation: "company_name",
  organization: "company_name",
  website: "website",
  website_url: "website",
  primary_website: "website",
  homepage: "website",
  url: "website",
  description: "description",
  summary: "description",
  about: "description",
  email: "email",
  contact_email: "email",
  e_mail: "email",
  mail: "email",
  phone: "phone",
  contact_phone: "phone",
  telephone: "phone",
  phone_number: "phone",
  address: "address",
  street: "address",
  street_address: "address",
  address_line1: "address",
  address1: "address",
  city: "city",
  town: "city",
  locality: "city",
  state: "state",
  region: "state",
  province: "state",
  address_region: "state",
  country: "country",
  country_code: "country",
  postal_code: "postal_code",
  postcode: "postal_code",
  zip: "postal_code",
  zip_code: "postal_code",
  postal: "postal_code",
  logo: "logo_path",
  logo_path: "logo_path",
  logo_url: "logo_path",
  categories: "categories",
  category: "categories",
  business_categories: "categories",
  founded_year: "founded_year",
  founded: "founded_year",
  year_founded: "founded_year",
  established: "founded_year",
  employee_count: "employee_count",
  employees: "employee_count",
  employee_number: "employee_count",
  number_of_employees: "employee_count",
  company_size: "employee_count",
  staff_count: "employee_count",
};

/** Site specific fields without a dedicated input in the form. */
const EXTRA_FIELD_LABELS: Record<string, string> = {
  author_bio: "Author bio",
  pitch: "Pitch",
  topic: "Topic",
  comment: "Comment",
  answer: "Answer",
  image_url: "Image URL",
  document_url: "Document URL",
  broken_url: "Broken URL",
  mention_url: "Mention URL",
  anchor_text: "Anchor text",
  tags: "Tags",
  social_profiles: "Social profiles",
};

type DetailsForm = Record<DetailFieldKey, string>;

const EMPTY_FORM: DetailsForm = DETAIL_FIELDS.reduce((acc, field) => {
  acc[field.key] = "";
  return acc;
}, {} as DetailsForm);

const splitList = (value: string): string[] =>
  value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

const normalizeName = (value: string): string =>
  value.trim().toLowerCase().replace(/[\s-]+/g, "_");

const fieldValue = (details: SubmissionDetails, key: DetailFieldKey): string => {
  const value = details[key];
  if (value === null || value === undefined) return "";
  return Array.isArray(value) ? value.join(", ") : String(value);
};

const toForm = (details: SubmissionDetails): DetailsForm =>
  DETAIL_FIELDS.reduce((acc, field) => {
    acc[field.key] = fieldValue(details, field.key);
    return acc;
  }, {} as DetailsForm);

const toNumber = (value: string): number | null => {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
};

/** A missing field as the backend reported it, resolved for the UI. */
interface MissingEntry {
  /** The raw name the backend uses. */
  name: string;
  label: string;
  /** The field of the form, when the name maps onto one. */
  field: DetailFieldKey | null;
  /** The value lives in the site specific extra data. */
  extra: boolean;
}

function resolveMissing(name: string): MissingEntry {
  const key = normalizeName(name);
  const field = ALIAS_TO_FIELD[key];
  if (field) {
    return { name, label: FIELD_META[field].label, field, extra: false };
  }
  if (EXTRA_FIELD_LABELS[key]) {
    return { name, label: EXTRA_FIELD_LABELS[key], field: null, extra: true };
  }
  return { name, label: humanize(name), field: null, extra: false };
}

/* ------------------------------------------------------------------ */
/* Panel                                                               */
/* ------------------------------------------------------------------ */

export function SubmissionDetailsPanel({
  opportunityId,
  onChanged,
}: {
  opportunityId: string;
  onChanged?: () => void;
}) {
  const toast = useToast();
  const saveAction = useAction();
  const generateAction = useAction();
  const resetAction = useAction();

  const details = useResource(
    () => api.submissionDetails.get(apiClient, opportunityId),
    [opportunityId],
  );

  const [form, setForm] = React.useState<DetailsForm>(EMPTY_FORM);
  /** The values the backend knows - the diff against them is what is saved. */
  const [initialForm, setInitialForm] = React.useState<DetailsForm>(EMPTY_FORM);
  const [initialExtra, setInitialExtra] = React.useState<Record<string, unknown>>({});
  const [extraValues, setExtraValues] = React.useState<Record<string, string>>({});
  const [generatedFields, setGeneratedFields] = React.useState<string[]>([]);
  /** The state the backend reported after a generation run. */
  const [generatedState, setGeneratedState] = React.useState<{
    missing: string[];
    complete: boolean;
    updatedAt: string | null;
  } | null>(null);
  const [resetOpen, setResetOpen] = React.useState(false);

  React.useEffect(() => {
    if (!details.data) return;
    setForm(toForm(details.data));
    setInitialForm(toForm(details.data));
    setInitialExtra(details.data.extra);
    setExtraValues(
      Object.fromEntries(
        Object.entries(details.data.extra)
          .filter(([, value]) => typeof value === "string" || typeof value === "number")
          .map(([key, value]) => [key, String(value)]),
      ),
    );
    setGeneratedState(null);
  }, [details.data]);

  const data = details.data;

  const missing = React.useMemo<MissingEntry[]>(() => {
    if (!data) return [];
    const names = generatedState ? generatedState.missing : data.missing;
    return names.map(resolveMissing);
  }, [data, generatedState]);

  const missingFields = React.useMemo(
    () => new Set(missing.filter((entry) => entry.field).map((entry) => entry.field as DetailFieldKey)),
    [missing],
  );

  const generatedKeys = React.useMemo(() => {
    const keys = new Set<DetailFieldKey>();
    // The fields the backend marked as generated (the map of the payload) and
    // the ones of the last generation run.
    const names = [...Object.keys(data?.generated ?? {}), ...generatedFields];
    for (const name of names) {
      const key = ALIAS_TO_FIELD[normalizeName(name)];
      if (key) keys.add(key);
    }
    return keys;
  }, [data, generatedFields]);

  const extraFields = React.useMemo(() => {
    const known = new Set(Object.keys(EXTRA_FIELD_LABELS));
    const names = new Set<string>();
    for (const entry of missing) {
      if (entry.extra) names.add(normalizeName(entry.name));
    }
    for (const key of Object.keys(extraValues)) {
      if (known.has(key)) names.add(key);
    }
    return Array.from(names).sort();
  }, [missing, extraValues]);

  const update = (key: DetailFieldKey, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  /**
   * Only the changed values are sent: the backend applies the fields of the
   * request and forgets the "generated" marker of a value that is edited by
   * hand - a value the assistant produced must keep its marker.
   */
  const changes = React.useMemo<SubmissionDetailsUpdate>(() => {
    const body: SubmissionDetailsUpdate = {};
    for (const key of TEXT_FIELD_KEYS) {
      const value = form[key].trim();
      if (value === (initialForm[key] ?? "").trim()) continue;
      body[key] = value || null;
    }
    if (form.categories.trim() !== initialForm.categories.trim()) {
      body.categories = splitList(form.categories);
    }
    if (form.founded_year.trim() !== initialForm.founded_year.trim()) {
      body.founded_year = toNumber(form.founded_year);
    }
    if (form.employee_count.trim() !== initialForm.employee_count.trim()) {
      body.employee_count = toNumber(form.employee_count);
    }
    const extra: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(extraValues)) {
      const before = initialExtra[key];
      if (String(before ?? "") === value) continue;
      extra[key] = value;
    }
    if (Object.keys(extra).length > 0) {
      body.extra = extra;
    }
    return body;
  }, [form, initialForm, extraValues, initialExtra]);

  const hasChanges = Object.keys(changes).length > 0;

  const save = async () => {
    if (!hasChanges) {
      toast.push("Nothing changed", "info");
      return;
    }
    const outcome = await saveAction.run(() =>
      api.submissionDetails.update(apiClient, opportunityId, changes),
    );
    if (outcome.ok && outcome.data) {
      toast.push("Submission details saved", "success");
      details.setData(outcome.data);
      onChanged?.();
    }
  };

  const generate = async () => {
    const outcome = await generateAction.run(() => api.submissionDetails.generate(apiClient, opportunityId));
    if (!outcome.ok || !outcome.data) return;
    const result = outcome.data;
    const generated = result.details;

    setForm((prev) => {
      const next = { ...prev };
      for (const field of DETAIL_FIELDS) {
        if (next[field.key].trim()) continue;
        const value = fieldValue(generated, field.key);
        if (value.trim()) next[field.key] = value;
      }
      return next;
    });
    setExtraValues((prev) => {
      const next = { ...prev };
      for (const [key, value] of Object.entries(generated.extra)) {
        if (next[key]) continue;
        if (typeof value === "string" || typeof value === "number") next[key] = String(value);
      }
      return next;
    });
    // The backend stored the generated values - the snapshot follows them so
    // that a later save only sends the values that were edited by hand.
    setInitialForm(toForm(generated));
    setInitialExtra(generated.extra);
    setGeneratedFields(result.generated);
    setGeneratedState({
      missing: generated.missing,
      complete: generated.complete,
      updatedAt: generated.updated_at,
    });
    if (result.generated.length > 0) {
      toast.push(
        `Generated ${result.generated.length} field(s) from your ${
          result.source === "profile" ? "business profile" : "business profile (AI)"
        } - the backend stored them`,
        "success",
      );
    } else {
      toast.push("The backend did not generate any new values", "info");
    }
  };

  const reset = async () => {
    const outcome = await resetAction.run(() => api.submissionDetails.remove(apiClient, opportunityId));
    if (outcome.ok) {
      toast.push("Submission details cleared", "success");
      setResetOpen(false);
      setGeneratedFields([]);
      details.reload();
      onChanged?.();
    }
  };

  if (details.loading && !data) {
    return (
      <div className="space-y-3" aria-busy="true" aria-live="polite">
        <span className="sr-only">Loading the submission details…</span>
        <Skeleton className="h-4 w-48" />
        <div className="grid gap-3 sm:grid-cols-2">
          {Array.from({ length: 6 }, (_, index) => (
            <Skeleton key={index} className="h-9 w-full" />
          ))}
        </div>
      </div>
    );
  }

  if (details.error && !data) {
    if (isNotFoundError(details.error)) {
      return (
        <Alert
          tone="neutral"
          title="These submission details could not be loaded"
          action={
            <Button variant="outline" size="sm" onClick={details.reload}>
              Try again
            </Button>
          }
        >
          The backend answered 404 for{" "}
          <code className="font-mono text-[11px]">
            GET /api/v1/opportunities/{opportunityId}/details
          </code>
          . The website may have been removed, or it may not belong to this account. Its
          details can not be shown or edited.
        </Alert>
      );
    }
    return (
      <ErrorPanel
        error={details.error}
        onRetry={details.reload}
        title="Could not load the submission details"
      />
    );
  }

  if (!data) {
    return (
      <Alert tone="neutral" title="No submission details">
        The backend did not return any details for this opportunity.
      </Alert>
    );
  }

  const complete = generatedState ? generatedState.complete : data.complete && missing.length === 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-content">Submission details</h3>
          <p className="text-xs text-content-muted">
            Everything this site asks for before it accepts your listing.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {complete ? (
            <Badge tone="success">Complete</Badge>
          ) : (
            <Badge tone="warning">
              {missing.length} detail{missing.length === 1 ? "" : "s"} missing
            </Badge>
          )}
          <span className="text-[11px] text-content-subtle">
            Updated {formatDateTime(generatedState ? generatedState.updatedAt : data.updated_at)}
          </span>
        </div>
      </div>

      {missing.length > 0 ? (
        <Alert tone="warning" title={`${missing.length} detail(s) are still missing`}>
          <p className="mb-1">
            The submission waits for these values - a task with missing details stays in
            &quot;waiting for details&quot; instead of failing.
          </p>
          <ul className="mt-1 list-inside list-disc space-y-0.5">
            {missing.map((entry) => (
              <li key={entry.name}>
                <span className="font-medium text-content">{entry.label}</span>
                {entry.field ? (
                  <span className="text-content-subtle">
                    {" "}
                    - {FIELD_META[entry.field].hint}
                  </span>
                ) : entry.extra ? (
                  <span className="text-content-subtle">
                    {" "}
                    - the site asks for this value in addition to the standard fields.
                  </span>
                ) : (
                  <span className="text-content-subtle">
                    {" "}
                    - the backend expects this value as site specific data ({entry.name}).
                  </span>
                )}
              </li>
            ))}
          </ul>
        </Alert>
      ) : (
        <Alert tone="success" title="All required details are filled in">
          Every value the website asks for is ready. If this site has no automated
          adapter, submit the form by hand and then mark it submitted.
        </Alert>
      )}

      {saveAction.error ? (
        <Alert tone="danger" title="Could not save the details">
          {errorMessage(saveAction.error)}
        </Alert>
      ) : null}
      {generateAction.error ? (
        <Alert tone="danger" title="Could not generate the details">
          {errorMessage(generateAction.error)}
        </Alert>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2">
        {DETAIL_FIELDS.map((field) => {
          const isMissing = missingFields.has(field.key);
          const isGenerated = generatedKeys.has(field.key);
          const label = (
            <span className="flex flex-wrap items-center gap-1.5">
              {field.label}
              {isMissing ? <Badge tone="warning">missing</Badge> : null}
              {isGenerated ? <Badge tone="info">generated</Badge> : null}
            </span>
          );
          const shared = {
            value: form[field.key],
            onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
              update(field.key, event.target.value),
            className: isMissing ? "border-warning" : undefined,
          };
          return (
            <Field
              key={field.key}
              label={label}
              hint={field.hint}
              className={field.kind === "textarea" ? "sm:col-span-2" : undefined}
            >
              {field.kind === "textarea" ? (
                <Textarea rows={3} placeholder={field.placeholder} {...shared} />
              ) : field.kind === "number" ? (
                <Input type="number" placeholder={field.placeholder} {...shared} />
              ) : (
                <Input placeholder={field.placeholder} {...shared} />
              )}
            </Field>
          );
        })}
      </div>

      {extraFields.length > 0 ? (
        <section className="rounded-lg border border-line">
          <h4 className="border-b border-line px-3 py-2 text-xs font-semibold text-content">
            Site specific values
          </h4>
          <div className="grid gap-3 p-3 sm:grid-cols-2">
            {extraFields.map((key) => (
              <Field
                key={key}
                label={EXTRA_FIELD_LABELS[key] ?? humanize(key)}
                hint="This site asks for a value that has no dedicated field."
              >
                <Input
                  value={extraValues[key] ?? ""}
                  onChange={(event) => {
                    const value = event.target.value;
                    setExtraValues((prev) => ({ ...prev, [key]: value }));
                  }}
                />
              </Field>
            ))}
          </div>
        </section>
      ) : null}

      {Object.keys(data.extra).length > 0 ? (
        <details className="rounded-lg border border-line">
          <summary className="cursor-pointer px-3 py-2 text-xs font-semibold text-content">
            Raw site specific data
          </summary>
          <pre className="overflow-x-auto border-t border-line px-3 py-2 text-[11px] text-content-muted">
            {JSON.stringify(data.extra, null, 2)}
          </pre>
        </details>
      ) : null}

      <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line pt-3">
        <Tooltip label="Fills the empty fields from your business profile">
          <Button
            variant="outline"
            size="sm"
            onClick={generate}
            loading={generateAction.pending}
          >
            Generate from my details
          </Button>
        </Tooltip>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setResetOpen(true)}
          disabled={resetAction.pending}
        >
          Clear details
        </Button>
        <Button size="sm" onClick={save} loading={saveAction.pending} disabled={!hasChanges}>
          Save details
        </Button>
      </div>

      <ConfirmDialog
        open={resetOpen}
        title="Clear the submission details?"
        description="All values of this opportunity are removed. The site asks for them again the next time you submit."
        confirmLabel="Clear details"
        destructive
        pending={resetAction.pending}
        onClose={() => setResetOpen(false)}
        onConfirm={() => void reset()}
      >
        {resetAction.error ? (
          <p className="text-xs text-danger">{errorMessage(resetAction.error)}</p>
        ) : null}
      </ConfirmDialog>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Summaries for list views                                           */
/* ------------------------------------------------------------------ */

export type DetailsSummaryState = "loading" | "ready" | "unavailable" | "error";

export interface DetailsSummary {
  state: DetailsSummaryState;
  details?: SubmissionDetails;
  error?: unknown;
}

/**
 * Loads the submission details of many opportunities at once - used by the
 * registry and the queue to show whether a row waits for details.
 *
 * The endpoint is optional: when the backend answers 404 the hook stops
 * requesting and reports the rows as unavailable instead of pretending that
 * the details are complete.
 */
export function useDetailsSummaries(ids: string[]): {
  summaries: Record<string, DetailsSummary>;
  reload: () => void;
} {
  const [summaries, setSummaries] = React.useState<Record<string, DetailsSummary>>({});
  const [nonce, setNonce] = React.useState(0);
  const cache = React.useRef(new Map<string, SubmissionDetails>());
  const unavailable = React.useRef<unknown>(null);

  const idsKey = Array.from(new Set(ids.filter(Boolean))).sort().join(",");

  React.useEffect(() => {
    const unique = idsKey ? idsKey.split(",") : [];
    if (unique.length === 0) return;
    let cancelled = false;

    setSummaries((prev) => {
      const next = { ...prev };
      let changed = false;
      for (const id of unique) {
        if (!next[id]) {
          next[id] = { state: "loading" };
          changed = true;
        }
      }
      return changed ? next : prev;
    });

    /** Loads one opportunity - returns false when the endpoint is missing. */
    const load = async (id: string): Promise<boolean> => {
      try {
        const details = await api.submissionDetails.get(apiClient, id);
        cache.current.set(id, details);
        if (cancelled) return true;
        setSummaries((prev) => ({ ...prev, [id]: { state: "ready", details } }));
        return true;
      } catch (error) {
        if (cancelled) return false;
        const missing = isNotFoundError(error);
        // A 404 means the endpoint does not exist (yet) - stop hammering the
        // backend and report the rows as unavailable instead of pretending
        // that the details are complete.
        if (missing) unavailable.current = error;
        setSummaries((prev) => ({
          ...prev,
          [id]: { state: missing ? "unavailable" : "error", error },
        }));
        return !missing;
      }
    };

    const run = async () => {
      const pending = unique.filter((id) => !cache.current.has(id));
      // The first request runs alone: when the endpoint does not exist only
      // one request fails instead of one per row.
      const probe = pending.shift();
      if (probe !== undefined) {
        const ok = await load(probe);
        if (!ok) {
          if (cancelled) return;
          for (const id of pending) {
            setSummaries((prev) => ({
              ...prev,
              [id]: { state: "unavailable", error: unavailable.current },
            }));
          }
          return;
        }
      }
      const worker = async () => {
        while (pending.length > 0) {
          const id = pending.shift();
          if (!id) return;
          if (unavailable.current) {
            if (cancelled) return;
            setSummaries((prev) => ({
              ...prev,
              [id]: { state: "unavailable", error: unavailable.current },
            }));
            continue;
          }
          await load(id);
        }
      };
      const workers = Array.from({ length: Math.min(6, pending.length) }, worker);
      await Promise.all(workers);
    };

    void run();
    return () => {
      cancelled = true;
    };
  }, [idsKey, nonce]);

  const reload = React.useCallback(() => {
    cache.current.clear();
    unavailable.current = null;
    setSummaries({});
    setNonce((value) => value + 1);
  }, []);

  return { summaries, reload };
}

/**
 * Compact indicator whether the submission details of one opportunity are
 * complete - used in the drawer and in the list views.
 */
export function DetailsStateBadge({
  opportunityId,
  className,
}: {
  opportunityId: string;
  className?: string;
}) {
  const { summaries } = useDetailsSummaries([opportunityId]);
  const summary = summaries[opportunityId];

  if (!summary || summary.state === "loading") {
    return <Skeleton className={className ?? "h-4 w-24"} />;
  }

  if (summary.state === "ready" && summary.details) {
    const missing = summary.details.missing.length;
    if (!missing && summary.details.complete) {
      return (
        <Badge tone="success" className={className}>
          Details complete
        </Badge>
      );
    }
    return (
      <Badge tone="warning" className={className}>
        {missing || "?"} detail{missing === 1 ? "" : "s"} missing
      </Badge>
    );
  }

  if (summary.state === "unavailable") {
    return (
      <Tooltip label="The backend returned 404 for this opportunity's details; it may have been removed.">
        <span>
          <Badge tone="neutral" className={className}>
            Details unavailable
          </Badge>
        </span>
      </Tooltip>
    );
  }

  return (
    <Tooltip label="The details state could not be loaded.">
      <span>
        <Badge tone="neutral" className={className}>
          Details unknown
        </Badge>
      </span>
    </Tooltip>
  );
}
