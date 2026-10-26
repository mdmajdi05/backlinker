import * as React from "react";
import {
  Alert,
  Badge,
  Button,
  Dialog,
  Field,
  Input,
  Select,
  useToast,
} from "@autobacklinker/ui";
import type {
  WebsiteAutomationConfig,
  WebsiteAutomationDetectResult,
} from "@autobacklinker/shared-types";
import { api, apiClient } from "../lib/api";

const VALUE_OPTIONS: Array<{ token: string; label: string }> = [
  { token: "", label: "Choose a value" },
  { token: "name", label: "Company name" },
  { token: "website", label: "Website" },
  { token: "landing_page", label: "Landing page" },
  { token: "description", label: "Description" },
  { token: "anchor", label: "Anchor text" },
  { token: "email", label: "E-mail" },
  { token: "phone", label: "Phone" },
  { token: "address", label: "Address" },
  { token: "city", label: "City" },
  { token: "state", label: "State / region" },
  { token: "country", label: "Country" },
  { token: "postal_code", label: "Postal code" },
  { token: "industry", label: "Industry" },
  { token: "niche", label: "Niche" },
  { token: "category", label: "Category" },
  { token: "region", label: "Region" },
  { token: "language", label: "Language" },
];

const SUCCESS_KINDS = [
  {
    value: "text",
    label: "The page shows this text",
    placeholder: "Thank you for your submission",
  },
  {
    value: "selector",
    label: "The page contains this element",
    placeholder: ".thank-you-message",
  },
  {
    value: "url",
    label: "The page URL contains this text",
    placeholder: "/thank-you",
  },
] as const;

type SuccessKind = (typeof SUCCESS_KINDS)[number]["value"];

interface FieldRow {
  key: string;
  token: string;
  selector: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
  websiteId: string;
  domain: string;
  formUrl: string;
  taskId: string | null;
  config: WebsiteAutomationConfig | null;
  onSaved: () => void;
}

function newKey(): string {
  return Math.random().toString(36).slice(2, 10);
}

function rowsFromConfig(config: WebsiteAutomationConfig | null): FieldRow[] {
  if (!config?.fields) return [];
  return Object.entries(config.fields).map(([selector, template]) => ({
    key: newKey(),
    selector,
    token: template.replace(/^\{\{\s*/, "").replace(/\s*\}\}$/, ""),
  }));
}

function kindFromConfig(config: WebsiteAutomationConfig | null): SuccessKind {
  if (config?.success_kind === "selector" || config?.success_kind === "url") {
    return config.success_kind;
  }
  return "text";
}

function errorText(error: unknown, fallback: string): string {
  if (error && typeof error === "object" && "message" in error) {
    return String((error as { message: unknown }).message);
  }
  return fallback;
}

export function AutomationSetupDialog({
  open,
  onClose,
  websiteId,
  domain,
  formUrl: initialUrl,
  taskId,
  config,
  onSaved,
}: Props) {
  const toast = useToast();
  const [adapter, setAdapter] = React.useState("playwright_form");
  const [formUrl, setFormUrl] = React.useState(initialUrl);
  const [fields, setFields] = React.useState<FieldRow[]>([]);
  const [successKind, setSuccessKind] = React.useState<SuccessKind>("text");
  const [successValue, setSuccessValue] = React.useState("");
  const [submitSelector, setSubmitSelector] = React.useState("");
  const [detected, setDetected] = React.useState<WebsiteAutomationDetectResult | null>(
    null,
  );
  const [error, setError] = React.useState<string | null>(null);
  const [confirmClear, setConfirmClear] = React.useState(false);
  const [runNow, setRunNow] = React.useState(true);
  const [detecting, setDetecting] = React.useState(false);
  const [finding, setFinding] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [clearing, setClearing] = React.useState(false);

  React.useEffect(() => {
    if (!open) return;
    setAdapter(config?.adapter === "http_form" ? "http_form" : "playwright_form");
    setFormUrl(config?.form_url || initialUrl || "");
    setFields(rowsFromConfig(config));
    setSuccessKind(kindFromConfig(config));
    setSuccessValue(config?.success_value || "");
    setSubmitSelector(config?.submit_selector || "");
    setDetected(null);
    setError(null);
    setConfirmClear(false);
    setRunNow(true);
  }, [open, config, initialUrl]);

  function updateField(key: string, patch: Partial<FieldRow>) {
    setFields((current) =>
      current.map((row) => (row.key === key ? { ...row, ...patch } : row)),
    );
  }

  async function detect() {
    setError(null);
    setDetecting(true);
    try {
      const result = await api.websites.detectAutomation(apiClient, websiteId, {
        form_url: formUrl.trim(),
      });
      setDetected(result);
      if (result.fields.length > 0) {
        setFields(
          result.fields.map((field) => ({
            key: newKey(),
            selector: field.selector,
            token: field.token,
          })),
        );
        toast.push(
          `${result.fields.length} form field(s) found - review the mapping`,
          "success",
        );
      } else {
        toast.push("No fields were found in the static HTML", "info");
      }
    } catch (err) {
      setError(errorText(err, "The form could not be inspected"));
    } finally {
      setDetecting(false);
    }
  }

  async function findForm() {
    setError(null);
    setFinding(true);
    try {
      const result = await api.websites.findAutomationForm(apiClient, websiteId, {
        form_url: formUrl.trim(),
      });
      setDetected(result);
      if (result.found && result.form_url) {
        setFormUrl(result.form_url);
        setFields(
          result.fields.map((field) => ({
            key: newKey(),
            selector: field.selector,
            token: field.token,
          })),
        );
        toast.push(
          `Submission page found: ${result.form_url} - review the mapping`,
          "success",
        );
      } else {
        toast.push(result.message || "No submission form was found", "info");
      }
    } catch (err) {
      setError(errorText(err, "The submission page could not be found"));
    } finally {
      setFinding(false);
    }
  }

  async function clearAutomation() {
    if (!confirmClear) {
      setConfirmClear(true);
      return;
    }
    setClearing(true);
    setError(null);
    try {
      await api.websites.clearAutomation(apiClient, websiteId);
      toast.push(`${domain} is back on the manual submission path`, "success");
      onSaved();
      onClose();
    } catch (err) {
      setError(errorText(err, "The automatic setup could not be removed"));
    } finally {
      setClearing(false);
    }
  }

  async function save(andRun: boolean) {
    setError(null);
    const url = formUrl.trim();
    const usable = fields.filter((row) => row.selector.trim() && row.token);
    if (!url) {
      setError("Enter the URL of the submission form.");
      return;
    }
    if (usable.length === 0) {
      setError("Add at least one field and choose the value it receives.");
      return;
    }
    if (new Set(usable.map((row) => row.selector.trim())).size !== usable.length) {
      setError("The same CSS selector is used twice.");
      return;
    }
    if (!successValue.trim()) {
      setError("Enter the success signal that appears after a successful submission.");
      return;
    }
    const mapping: Record<string, string> = {};
    usable.forEach((row) => {
      mapping[row.selector.trim()] = `{{${row.token}}}`;
    });
    setSaving(true);
    try {
      await api.websites.saveAutomation(apiClient, websiteId, {
        adapter,
        form_url: url,
        fields: mapping,
        success_kind: successKind,
        success_value: successValue.trim(),
        submit_selector: submitSelector.trim() || null,
        timeout_ms: null,
      });
      if (andRun && runNow && taskId) {
        try {
          await api.tasks.retry(apiClient, taskId);
          toast.push(
            "Automatic setup saved - the website is queued again",
            "success",
          );
        } catch (err) {
          toast.push(
            `Automatic setup saved, but the task could not be queued: ${errorText(err, "unknown error")}`,
            "error",
          );
        }
      } else if (andRun && runNow && !taskId) {
        toast.push(
          "Automatic setup saved - press Start backlinks to run it",
          "success",
        );
      } else {
        toast.push("Automatic setup saved", "success");
      }
      onSaved();
      onClose();
    } catch (err) {
      setError(errorText(err, "The automatic setup could not be saved"));
    } finally {
      setSaving(false);
    }
  }

  const successHint =
    SUCCESS_KINDS.find((item) => item.value === successKind)?.placeholder ?? "";

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={`Automatic submission - ${domain}`}
      description="The app fills this form in a real browser and only marks it submitted when your success signal really appears."
      width="xl"
      footer={
        <>
          {config ? (
            <Button
              variant={confirmClear ? "danger" : "ghost"}
              onClick={() => void clearAutomation()}
              loading={clearing}
              className="mr-auto"
            >
              {confirmClear ? "Confirm manual mode" : "Use manual mode"}
            </Button>
          ) : null}
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          {taskId && runNow ? (
            <Button variant="outline" onClick={() => void save(false)} loading={saving}>
              Save only
            </Button>
          ) : null}
          <Button onClick={() => void save(true)} loading={saving}>
            {taskId && runNow ? "Save and run now" : "Save setup"}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <Alert tone="info" title="This is a real browser submission">
          It uses the local Chromium runtime, fills the fields below, clicks submit and
          looks for your success signal. A login wall or CAPTCHA pauses the task for a
          human - it never pretends that the submission worked. Most directories still
          need the manual path; use this only when you can test the form.
        </Alert>

        <Field
          label="Submission form URL"
          hint="The page with the form, not the homepage. The fields below are filled on this page."
        >
          <Input
            value={formUrl}
            onChange={(event) => setFormUrl(event.target.value)}
            placeholder="https://directory.example/add-your-business"
            inputMode="url"
          />
        </Field>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => void findForm()}
            loading={finding}
          >
            Find submission page
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void detect()}
            loading={detecting}
            disabled={!formUrl.trim()}
          >
            Detect fields
          </Button>
          <span className="text-[11px] text-content-muted">
            The finder follows the &quot;add listing&quot; links from the homepage.
            Nothing is submitted.
          </span>
        </div>

        {detected ? (
          <Alert
            tone={
              detected.has_captcha
                ? "warning"
                : detected.fields.length > 0
                  ? "success"
                  : "warning"
            }
            title={
              detected.has_captcha
                ? "CAPTCHA detected"
                : detected.fields.length > 0
                  ? "Fields found"
                  : "No fields found"
            }
          >
            <p>{detected.message}</p>
            {detected.has_captcha ? (
              <p className="mt-1">
                The browser cannot solve a CAPTCHA. It will pause and leave the task for
                you to complete by hand.
              </p>
            ) : null}
          </Alert>
        ) : null}

        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="text-sm font-semibold text-content">Field mapping</p>
              <p className="text-[11px] text-content-muted">
                Left: the value from the project details. Right: the CSS selector of the
                form control.
              </p>
            </div>
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                setFields((current) => [
                  ...current,
                  { key: newKey(), token: "", selector: "" },
                ])
              }
            >
              Add field
            </Button>
          </div>
          {fields.length === 0 ? (
            <div className="rounded-lg border border-dashed border-line p-4 text-xs text-content-muted">
              No fields yet. Press <strong className="text-content">Detect fields</strong>{" "}
              or add the selectors by hand.
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              {fields.map((row) => (
                <div
                  key={row.key}
                  className="grid gap-2 rounded-lg border border-line bg-surface-raised/40 p-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_auto]"
                >
                  <Select
                    aria-label="Value"
                    value={row.token}
                    onChange={(event) => updateField(row.key, { token: event.target.value })}
                  >
                    {VALUE_OPTIONS.map((option) => (
                      <option key={option.token || "none"} value={option.token}>
                        {option.label}
                      </option>
                    ))}
                  </Select>
                  <Input
                    aria-label="CSS selector"
                    value={row.selector}
                    onChange={(event) =>
                      updateField(row.key, { selector: event.target.value })
                    }
                    placeholder='[name="company"]'
                    className="font-mono text-xs"
                  />
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() =>
                      setFields((current) =>
                        current.filter((item) => item.key !== row.key),
                      )
                    }
                  >
                    Remove
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field
            label="How do we know it worked?"
            hint="Required - nothing is submitted without it."
          >
            <Select
              value={successKind}
              onChange={(event) => setSuccessKind(event.target.value as SuccessKind)}
            >
              {SUCCESS_KINDS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Success signal" hint={successHint}>
            <Input
              value={successValue}
              onChange={(event) => setSuccessValue(event.target.value)}
              placeholder={successHint}
            />
          </Field>
        </div>

        <details className="rounded-lg border border-line p-3">
          <summary className="cursor-pointer text-xs font-semibold text-content">
            Advanced options
          </summary>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <Field
              label="Submit button selector"
              hint="Optional. Leave empty for a normal submit button."
            >
              <Input
                value={submitSelector}
                onChange={(event) => setSubmitSelector(event.target.value)}
                placeholder='button[type="submit"]'
                className="font-mono text-xs"
              />
            </Field>
            <Field
              label="How should the form run?"
              hint="A real browser works on JavaScript forms. The plain HTTP option is for simple forms only."
            >
              <Select
                value={adapter}
                onChange={(event) => setAdapter(event.target.value)}
              >
                <option value="playwright_form">Real browser (recommended)</option>
                <option value="http_form">Plain HTTP form</option>
              </Select>
            </Field>
          </div>
          <p className="mt-3 text-[11px] text-content-muted">
            To copy a CSS selector: right-click the field on the website, choose{" "}
            <strong className="text-content">Inspect</strong>, then{" "}
            <strong className="text-content">Copy selector</strong>. Prefer a stable
            <span className="font-mono"> id</span> or{" "}
            <span className="font-mono">name</span> attribute.
          </p>
        </details>

        {taskId ? (
          <label className="flex items-start gap-2 text-xs text-content-muted">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={runNow}
              onChange={(event) => setRunNow(event.target.checked)}
            />
            Run this website again after saving. The existing task is queued with the new
            configuration.
          </label>
        ) : (
          <p className="text-[11px] text-content-muted">
            This website has no task yet. After saving, press{" "}
            <strong className="text-content">Start backlinks</strong> to run it.
          </p>
        )}

        {error ? (
          <Alert tone="danger" title="The setup could not be saved">
            {error}
          </Alert>
        ) : null}

        <div className="flex flex-wrap items-center gap-2 text-[11px] text-content-muted">
          <Badge tone={config ? "accent" : "neutral"}>
            {config ? "Automatic setup exists" : "Manual path"}
          </Badge>
          <span>
            Saving does not submit anything. Only the queued task opens the browser.
          </span>
        </div>
      </div>
    </Dialog>
  );
}
