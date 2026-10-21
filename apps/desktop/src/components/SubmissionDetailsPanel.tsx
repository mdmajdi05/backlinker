import * as React from "react";
import {
  Alert,
  Badge,
  Button,
  Drawer,
  Field,
  Input,
  KeyValue,
  Textarea,
  useToast,
} from "@autobacklinker/ui";
import {
  api,
  apiClient,
  isMissingEndpoint,
  type SubmissionDetails,
  type SubmissionDetailsUpdate,
} from "../lib/api";
import { useAsync } from "../lib/useAsync";
import { ErrorBlock, LoadingBlock } from "./common";
import { sendNativeNotification } from "../lib/backend";
import { formatDate, titleCase } from "../lib/format";

/**
 * The details of a target site.
 *
 * A directory asks for a handful of values (company name, website, address,
 * ...).  The backend stores them per opportunity, reports which of them are
 * still missing and can fill the empty ones from the business profile of the
 * project.
 *
 * A task whose details are incomplete *waits* - it is never a failure.  The
 * panel therefore shows the missing fields first and offers the generator
 * before it asks the operator to type everything by hand.
 */

/** The labels of the fields the backend knows. */
const FIELD_LABELS: Record<string, string> = {
  company_name: "Company name",
  description: "Description",
  email: "E-mail address",
  phone: "Phone number",
  website: "Website",
  address: "Street address",
  city: "City",
  state: "State / region",
  country: "Country",
  postal_code: "Postal code",
  logo_path: "Logo",
  categories: "Categories",
  founded_year: "Year founded",
  employee_count: "Number of employees",
};

/**
 * The names a target site uses for the fields of the form.
 *
 * A directory calls the name of the business simply "name" and the mail
 * address "contact_email" - the backend reports the names of the site, the
 * panel edits the fields of the contract.
 */
const FIELD_ALIASES: Record<string, string> = {
  name: "company_name",
  company: "company_name",
  business_name: "company_name",
  title: "company_name",
  summary: "description",
  about: "description",
  contact_email: "email",
  mail: "email",
  contact_phone: "phone",
  telephone: "phone",
  url: "website",
  primary_website: "website",
  homepage: "website",
  street: "address",
  street_address: "address",
  town: "city",
  region: "state",
  address_region: "state",
  zip: "postal_code",
  zip_code: "postal_code",
  logo: "logo_path",
  logo_url: "logo_path",
  category: "categories",
  year_founded: "founded_year",
  employees: "employee_count",
  number_of_employees: "employee_count",
};

/** The field of the contract a name of the site addresses. */
export function resolveDetailField(field: string): string {
  const normalized = field.trim().toLowerCase().replace(/[- ]/g, "_");
  return FIELD_ALIASES[normalized] ?? normalized;
}

/** A readable label of a detail field. */
export function detailFieldLabel(field: string): string {
  return FIELD_LABELS[resolveDetailField(field)] ?? titleCase(field);
}

/** The fields that may be edited in this panel. */
const EDITABLE_FIELDS = [
  "company_name",
  "email",
  "phone",
  "website",
  "address",
  "city",
  "state",
  "country",
  "postal_code",
  "founded_year",
  "employee_count",
  "description",
  "logo_path",
  "categories",
] as const;

/** True when the field may be edited in this panel. */
export function isEditableField(field: string): boolean {
  return (EDITABLE_FIELDS as readonly string[]).includes(
    resolveDetailField(field),
  );
}

/** The form state - every value is a string while it is edited. */
interface FormState {
  company_name: string;
  description: string;
  email: string;
  phone: string;
  website: string;
  address: string;
  city: string;
  state: string;
  country: string;
  postal_code: string;
  logo_path: string;
  categories: string;
  founded_year: string;
  employee_count: string;
}

const EMPTY_FORM: FormState = {
  company_name: "",
  description: "",
  email: "",
  phone: "",
  website: "",
  address: "",
  city: "",
  state: "",
  country: "",
  postal_code: "",
  logo_path: "",
  categories: "",
  founded_year: "",
  employee_count: "",
};

function toForm(details: SubmissionDetails): FormState {
  return {
    company_name: details.company_name ?? "",
    description: details.description ?? "",
    email: details.email ?? "",
    phone: details.phone ?? "",
    website: details.website ?? "",
    address: details.address ?? "",
    city: details.city ?? "",
    state: details.state ?? "",
    country: details.country ?? "",
    postal_code: details.postal_code ?? "",
    logo_path: details.logo_path ?? "",
    categories: details.categories.join(", "),
    founded_year:
      details.founded_year === null ? "" : String(details.founded_year),
    employee_count:
      details.employee_count === null ? "" : String(details.employee_count),
  };
}

function toPayload(form: FormState): SubmissionDetailsUpdate {
  const text = (value: string) => value.trim();
  const number = (value: string) => {
    const parsed = Number.parseInt(value.trim(), 10);
    return Number.isFinite(parsed) ? parsed : null;
  };
  return {
    company_name: text(form.company_name) || null,
    description: text(form.description) || null,
    email: text(form.email) || null,
    phone: text(form.phone) || null,
    website: text(form.website) || null,
    address: text(form.address) || null,
    city: text(form.city) || null,
    state: text(form.state) || null,
    country: text(form.country) || null,
    postal_code: text(form.postal_code) || null,
    logo_path: text(form.logo_path) || null,
    categories: form.categories
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
    founded_year: number(form.founded_year),
    employee_count: number(form.employee_count),
  };
}

function sameForm(left: FormState, right: FormState): boolean {
  return (Object.keys(left) as (keyof FormState)[]).every(
    (key) => left[key] === right[key],
  );
}

/**
 * Applies the generated values to the form.
 *
 * The values the generator filled always win, the values the operator typed
 * are kept - only the fields that are still empty take the generated value.
 */
function mergeGenerated(
  current: FormState,
  generated: SubmissionDetails,
  generatedFields: string[],
): FormState {
  const server = toForm(generated);
  const names = generatedFields.map(resolveDetailField);
  const next: FormState = { ...current };
  (Object.keys(next) as (keyof FormState)[]).forEach((key) => {
    if (names.includes(key)) {
      next[key] = server[key];
      return;
    }
    if (!current[key] && server[key]) next[key] = server[key];
  });
  return next;
}

function errorText(error: unknown, fallback: string): string {
  if (error && typeof error === "object" && "message" in error) {
    return String((error as { message: unknown }).message);
  }
  return fallback;
}

/* ------------------------------------------------------------------ */
/* The state of many opportunities                                     */
/* ------------------------------------------------------------------ */

export interface SubmissionDetailsState {
  complete: boolean;
  missing: string[];
}

export interface SubmissionDetailsStates {
  /** The state per opportunity id. */
  states: Record<string, SubmissionDetailsState>;
  loading: boolean;
  /**
   * `null` while the answer is unknown, `false` when the backend does not
   * provide the details at all (an older sidecar).
   */
  supported: boolean | null;
  error: string | null;
  reload: () => void;
}

/**
 * Loads the details state of many opportunities.
 *
 * The registry and the queue show the state of every row - the details are
 * fetched per opportunity, because the backend answers per opportunity.
 */
export function useSubmissionDetailsStates(
  ids: string[],
): SubmissionDetailsStates {
  const key = ids.join("|");
  const [states, setStates] = React.useState<
    Record<string, SubmissionDetailsState>
  >({});
  const [loading, setLoading] = React.useState(false);
  const [supported, setSupported] = React.useState<boolean | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [nonce, setNonce] = React.useState(0);

  React.useEffect(() => {
    let cancelled = false;
    const list = key ? key.split("|") : [];
    if (list.length === 0) {
      setStates({});
      setSupported(null);
      setError(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    (async () => {
      type Answer =
        | { id: string; details: SubmissionDetails; error?: undefined }
        | { id: string; details?: undefined; error: unknown };
      const answers: Answer[] = await Promise.all(
        list.map(async (id): Promise<Answer> => {
          try {
            const details = await api.submissionDetails.get(apiClient, id);
            return { id, details };
          } catch (err) {
            return { id, error: err };
          }
        }),
      );
      if (cancelled) return;
      const next: Record<string, SubmissionDetailsState> = {};
      const failures = answers.filter(
        (answer): answer is { id: string; details?: undefined; error: unknown } =>
          answer.error !== undefined,
      );
      for (const answer of answers) {
        if (!answer.details) continue;
        next[answer.id] = {
          complete: answer.details.complete,
          missing: answer.details.missing.map((entry) => entry.field),
        };
      }
      setStates(next);
      setSupported(
        failures.length === 0
          ? true
          : failures.every((failure) => isMissingEndpoint(failure.error))
            ? false
            : true,
      );
      const failure = failures.find(
        (item) => !isMissingEndpoint(item.error),
      );
      setError(
        failure
          ? errorText(failure.error, "Could not load the submission details")
          : null,
      );
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [key, nonce]);

  const reload = React.useCallback(
    () => setNonce((value) => value + 1),
    [],
  );

  return { states, loading, supported, error, reload };
}

/* ------------------------------------------------------------------ */
/* The panel                                                           */
/* ------------------------------------------------------------------ */

export function SubmissionDetailsPanel({
  opportunityId,
  opportunityName,
  onClose,
  onChanged,
}: {
  opportunityId: string;
  opportunityName?: string;
  onClose: () => void;
  /** Called after the details were saved, cleared or generated. */
  onChanged?: () => void;
}) {
  const toast = useToast();
  const [rawError, setRawError] = React.useState<unknown>(null);
  const [snapshot, setSnapshot] = React.useState<SubmissionDetails | null>(null);
  const [form, setForm] = React.useState<FormState>(EMPTY_FORM);
  const [baseline, setBaseline] = React.useState<FormState>(EMPTY_FORM);
  const [saving, setSaving] = React.useState(false);
  const [generating, setGenerating] = React.useState(false);
  const [clearing, setClearing] = React.useState(false);
  const [confirmClear, setConfirmClear] = React.useState(false);
  const [actionError, setActionError] = React.useState<string | null>(null);

  const details = useAsync(async () => {
    try {
      return await api.submissionDetails.get(apiClient, opportunityId);
    } catch (err) {
      // The raw error is kept - the view needs the status code to tell a
      // missing endpoint from a backend that is not reachable.
      setRawError(err);
      throw err;
    }
  }, [opportunityId]);

  React.useEffect(() => {
    if (!details.data) return;
    const next = toForm(details.data);
    setForm(next);
    setBaseline(next);
    setSnapshot(details.data);
    setActionError(null);
  }, [details.data]);

  const data = snapshot;
  const unsupported =
    Boolean(details.error) && isMissingEndpoint(rawError ?? details.error);
  const dirty = !sameForm(form, baseline);
  const busy = saving || generating || clearing;

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((previous) => ({ ...previous, [key]: value }));
  }

  function focusField(field: string) {
    const element = document.getElementById(`detail-${resolveDetailField(field)}`);
    if (!element) return;
    element.focus();
    element.scrollIntoView({ block: "center" });
  }

  async function save() {
    setSaving(true);
    setActionError(null);
    try {
      const saved = await api.submissionDetails.update(
        apiClient,
        opportunityId,
        toPayload(form),
      );
      const next = toForm(saved);
      setForm(next);
      setBaseline(next);
      setSnapshot(saved);
      toast.push("Submission details saved", "success");
      onChanged?.();
    } catch (err) {
      setActionError(errorText(err, "Could not save the submission details"));
    } finally {
      setSaving(false);
    }
  }

  async function generate() {
    setGenerating(true);
    setActionError(null);
    try {
      const result = await api.submissionDetails.generate(
        apiClient,
        opportunityId,
      );
      setForm((current) =>
        mergeGenerated(current, result.details, result.generated),
      );
      setBaseline(toForm(result.details));
      setSnapshot(result.details);
      const names = result.generated.map(detailFieldLabel);
      const message = names.length
        ? `${names.join(", ")} were filled from your business profile`
        : "The empty details were filled from your business profile";
      toast.push(message, "success");
      void sendNativeNotification(
        "Auto Backlinker",
        `${message}${opportunityName ? ` (${opportunityName})` : ""}.`,
      );
      onChanged?.();
    } catch (err) {
      setActionError(
        errorText(err, "Could not generate the submission details"),
      );
    } finally {
      setGenerating(false);
    }
  }

  async function clearDetails() {
    setClearing(true);
    setActionError(null);
    try {
      await api.submissionDetails.remove(apiClient, opportunityId);
      setConfirmClear(false);
      setForm(EMPTY_FORM);
      setBaseline(EMPTY_FORM);
      setSnapshot(null);
      toast.push("Submission details cleared", "success");
      details.reload();
      onChanged?.();
    } catch (err) {
      setActionError(
        errorText(err, "Could not clear the submission details"),
      );
    } finally {
      setClearing(false);
    }
  }

  const missing = data?.missing ?? [];
  const required = data?.required ?? [];

  return (
    <Drawer
      open
      onClose={onClose}
      title={`Submission details${opportunityName ? ` · ${opportunityName}` : ""}`}
      width="lg"
      footer={
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
        </div>
      }
    >
      {details.loading && !data ? <LoadingBlock rows={5} /> : null}

      {details.error ? (
        unsupported ? (
          <Alert
            tone="warning"
            title="The backend does not provide submission details yet"
          >
            The local backend of this installation is older than the automatic
            submission. The details are read and written by the backend - the
            desktop client can not fill them on its own. Update the backend and
            reload this view.
          </Alert>
        ) : (
          <ErrorBlock message={details.error} onRetry={details.reload} />
        )
      ) : null}

      {data ? (
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={data.complete ? "success" : "warning"}>
              {data.complete
                ? "Complete"
                : missing.length > 0
                  ? `${missing.length} missing`
                  : "Unknown"}
            </Badge>
            <Badge tone="neutral">{required.length} required</Badge>
            {data.generated.length > 0 ? (
              <Badge tone="accent">
                Generated: {data.generated.map(detailFieldLabel).join(", ")}
              </Badge>
            ) : null}
            <span className="text-xs text-content-subtle">
              Updated {formatDate(data.updated_at)}
            </span>
          </div>

          {missing.length > 0 ? (
            <Alert
              tone="warning"
              title={`${missing.length} detail${
                missing.length === 1 ? " is" : "s are"
              } still missing`}
            >
              <p>
                The submission waits for these values - it is not an error and
                the task is not lost.
              </p>
              <ul className="mt-1.5 flex flex-wrap gap-1.5">
                {missing.map((entry) => {
                  const editable = isEditableField(entry.field);
                  return (
                    <li key={entry.field}>
                      <button
                        type="button"
                        disabled={!editable}
                        onClick={() => focusField(entry.field)}
                        className={
                          editable
                            ? "rounded-full transition-opacity hover:opacity-80"
                            : "cursor-default"
                        }
                        title={
                          editable
                            ? `Fill "${entry.label}" below`
                            : "This field is filled by the backend"
                        }
                      >
                        <Badge tone="warning">
                          {entry.label || detailFieldLabel(entry.field)}
                        </Badge>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </Alert>
          ) : data.complete ? (
            <Alert tone="success" title="Every required detail is filled">
              The submission can run without asking for anything.
            </Alert>
          ) : (
            <Alert tone="info" title="The details are not complete">
              The backend does not report which values this site asks for, so
              the client can not tell you what is missing. Fill the form below
              with the values of your business.
            </Alert>
          )}

          {required.length > 0 ? (
            <p className="text-xs text-content-subtle">
              The site asks for:{" "}
              {required
                .map((entry) => entry.label || detailFieldLabel(entry.field))
                .join(", ")}
              .
            </p>
          ) : null}

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Company name">
              <Input
                id="detail-company_name"
                value={form.company_name}
                onChange={(event) => update("company_name", event.target.value)}
                placeholder="The name of the business"
              />
            </Field>
            <Field label="E-mail address">
              <Input
                id="detail-email"
                type="email"
                value={form.email}
                onChange={(event) => update("email", event.target.value)}
                placeholder="contact@example.com"
              />
            </Field>
            <Field label="Phone number">
              <Input
                id="detail-phone"
                type="tel"
                value={form.phone}
                onChange={(event) => update("phone", event.target.value)}
                placeholder="+49 30 123456"
              />
            </Field>
            <Field label="Website">
              <Input
                id="detail-website"
                type="url"
                value={form.website}
                onChange={(event) => update("website", event.target.value)}
                placeholder="https://example.com"
              />
            </Field>
            <Field label="Street address">
              <Input
                id="detail-address"
                value={form.address}
                onChange={(event) => update("address", event.target.value)}
                placeholder="Street and number"
              />
            </Field>
            <Field label="City">
              <Input
                id="detail-city"
                value={form.city}
                onChange={(event) => update("city", event.target.value)}
              />
            </Field>
            <Field label="State / region">
              <Input
                id="detail-state"
                value={form.state}
                onChange={(event) => update("state", event.target.value)}
              />
            </Field>
            <Field label="Postal code">
              <Input
                id="detail-postal_code"
                value={form.postal_code}
                onChange={(event) =>
                  update("postal_code", event.target.value)
                }
              />
            </Field>
            <Field label="Country">
              <Input
                id="detail-country"
                value={form.country}
                onChange={(event) => update("country", event.target.value)}
              />
            </Field>
            <Field label="Year founded">
              <Input
                id="detail-founded_year"
                type="number"
                value={form.founded_year}
                onChange={(event) =>
                  update("founded_year", event.target.value)
                }
                placeholder="2012"
              />
            </Field>
            <Field label="Number of employees">
              <Input
                id="detail-employee_count"
                type="number"
                value={form.employee_count}
                onChange={(event) =>
                  update("employee_count", event.target.value)
                }
                placeholder="25"
              />
            </Field>
            <Field
              label="Categories"
              hint="Comma separated, for example: business directory, local citation."
            >
              <Input
                id="detail-categories"
                value={form.categories}
                onChange={(event) => update("categories", event.target.value)}
                placeholder="business directory, local citation"
              />
            </Field>
            <Field
              label="Logo"
              hint="A file on this machine or a local URL."
            >
              <Input
                id="detail-logo_path"
                value={form.logo_path}
                onChange={(event) => update("logo_path", event.target.value)}
                placeholder="/Users/me/logo.png"
              />
            </Field>
            <Field
              label="Description"
              className="sm:col-span-2"
              hint="The text the directory publishes about the business."
            >
              <Textarea
                id="detail-description"
                rows={4}
                value={form.description}
                onChange={(event) => update("description", event.target.value)}
                placeholder="What the business does, in two or three sentences."
              />
            </Field>
          </div>

          {Object.keys(data.extra).length > 0 ? (
            <div>
              <p className="mb-2 text-xs font-semibold text-content">
                Additional details of the site
              </p>
              <KeyValue
                items={Object.entries(data.extra).map(([key, value]) => [
                  titleCase(key),
                  typeof value === "string" || typeof value === "number"
                    ? String(value)
                    : JSON.stringify(value),
                ])}
              />
            </div>
          ) : null}

          {actionError ? (
            <Alert tone="danger" title="The action failed">
              {actionError}
            </Alert>
          ) : null}

          <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line pt-3">
            <p className="mr-auto text-[11px] text-content-subtle">
              {dirty
                ? "There are unsaved changes."
                : "Everything is saved."}
            </p>
            {confirmClear ? (
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setConfirmClear(false)}
                >
                  Keep the details
                </Button>
                <Button
                  size="sm"
                  variant="danger"
                  loading={clearing}
                  onClick={() => void clearDetails()}
                >
                  Clear them
                </Button>
              </div>
            ) : (
              <Button
                size="sm"
                variant="outline"
                disabled={busy || unsupported}
                onClick={() => setConfirmClear(true)}
              >
                Clear the details
              </Button>
            )}
            <Button
              variant="outline"
              loading={generating}
              disabled={busy || unsupported}
              onClick={() => void generate()}
            >
              Generate from my details
            </Button>
            <Button
              loading={saving}
              disabled={busy || unsupported || !dirty}
              onClick={() => void save()}
            >
              Save details
            </Button>
          </div>
        </div>
      ) : null}
    </Drawer>
  );
}
