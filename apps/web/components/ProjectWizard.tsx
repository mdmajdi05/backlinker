"use client";

import * as React from "react";
import { api } from "@autobacklinker/api-client";
import type { ExecutionEnvironment, Project } from "@autobacklinker/shared-types";
import {
  Button,
  Checkbox,
  Field,
  Input,
  Label,
  Select,
  Textarea,
} from "@autobacklinker/ui";
import { apiClient, errorMessage } from "@/lib/api";
import { useAction, useResource } from "@/lib/hooks";

interface LandingPageDraft {
  name: string;
  url: string;
  kind: "MAIN" | "LANDING" | "BLOG" | "OTHER";
}

/** The facts a directory asks for.  They are stored in the business profile. */
interface DetailsDraft {
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
  categories: string;
  founded_year: string;
  employee_count: string;
  anchors: string;
}

const EMPTY_DETAILS: DetailsDraft = {
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
  categories: "",
  founded_year: "",
  employee_count: "",
  anchors: "",
};

const toList = (value: string) =>
  value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

const toNumberOrNull = (value: string) => {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : null;
};

const STEPS = ["Basics", "Backlink details", "Landing pages", "Execution"] as const;

export function ProjectWizard({
  onCreated,
  onCancel,
  defaultProfileId,
}: {
  onCreated: (project: Project) => void;
  onCancel: () => void;
  defaultProfileId?: string | null;
}) {
  const [step, setStep] = React.useState(0);
  const profiles = useResource(() => api.profiles.list(apiClient), []);

  const [name, setName] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [targetWebsite, setTargetWebsite] = React.useState("");
  const [profileId, setProfileId] = React.useState(defaultProfileId ?? "");
  const [landingPages, setLandingPages] = React.useState<LandingPageDraft[]>([]);
  const [maxConcurrency, setMaxConcurrency] = React.useState("3");
  const [requestRate, setRequestRate] = React.useState("60");
  const [maxRetries, setMaxRetries] = React.useState("3");
  const [backoffBase, setBackoffBase] = React.useState("30");
  const [environment, setEnvironment] = React.useState<ExecutionEnvironment>("CLOUD");
  const [requireApproval, setRequireApproval] = React.useState(true);
  const [autoQueueApproved, setAutoQueueApproved] = React.useState(false);
  const [allowBrowserAutomation, setAllowBrowserAutomation] = React.useState(false);
  const [formError, setFormError] = React.useState<string | null>(null);
  const [details, setDetails] = React.useState<DetailsDraft>(EMPTY_DETAILS);

  const selectedProfile = (profiles.data ?? []).find((profile) => profile.id === profileId) ?? null;
  const setDetail = (field: keyof DetailsDraft) => (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setDetails((previous) => ({ ...previous, [field]: event.target.value }));

  const action = useAction();

  const toInt = (value: string, fallback: number) => {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) ? parsed : fallback;
  };

  const submit = async () => {
    setFormError(null);
    if (!name.trim()) {
      setFormError("Project name is required.");
      setStep(0);
      return;
    }
    if (!targetWebsite.trim()) {
      setFormError("Target website is required.");
      setStep(0);
      return;
    }
    const outcome = await action.run(() =>
      api.projects.create(apiClient, {
        name: name.trim(),
        description: description.trim() || undefined,
        target_website: targetWebsite.trim(),
        business_profile_id: profileId || null,
        landing_pages: landingPages
          .filter((page) => page.url.trim())
          .map((page) => ({
            name: page.name.trim() || page.url.trim(),
            url: page.url.trim(),
            kind: page.kind,
          })),
        ...(profileId
          ? {}
          : {
              details: {
                company_name: details.company_name.trim() || undefined,
                description: details.description.trim() || undefined,
                email: details.email.trim() || undefined,
                phone: details.phone.trim() || undefined,
                website: details.website.trim() || targetWebsite.trim(),
                address: details.address.trim() || undefined,
                city: details.city.trim() || undefined,
                state: details.state.trim() || undefined,
                country: details.country.trim() || undefined,
                postal_code: details.postal_code.trim() || undefined,
                categories: toList(details.categories),
                founded_year: toNumberOrNull(details.founded_year),
                employee_count: toNumberOrNull(details.employee_count),
                anchors: toList(details.anchors),
                target_website: targetWebsite.trim(),
              },
            }),
        settings: {
          max_concurrency: toInt(maxConcurrency, 3),
          request_rate_per_minute: toInt(requestRate, 60),
          max_retries: toInt(maxRetries, 3),
          backoff_base_seconds: toInt(backoffBase, 30),
          execution_environment: environment,
          require_approval: requireApproval,
          auto_queue_approved: autoQueueApproved,
          allow_browser_automation: allowBrowserAutomation,
        },
      }),
    );
    if (outcome.ok && outcome.data) {
      onCreated(outcome.data);
    }
  };

  return (
    <div className="space-y-4">
      <ol className="flex items-center gap-2 text-xs" aria-label="Wizard steps">
        {STEPS.map((label, index) => (
          <li key={label} className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setStep(index)}
              className={`flex h-6 w-6 items-center justify-center rounded-full border text-[11px] font-semibold ${
                index === step
                  ? "border-accent bg-accent text-accent-fg"
                  : index < step
                    ? "border-accent/40 bg-accent-soft text-accent"
                    : "border-line text-content-subtle"
              }`}
              aria-current={index === step ? "step" : undefined}
            >
              {index + 1}
            </button>
            <span className={index === step ? "font-medium text-content" : "text-content-muted"}>
              {label}
            </span>
            {index < STEPS.length - 1 ? <span className="text-content-subtle">/</span> : null}
          </li>
        ))}
      </ol>

      {step === 0 ? (
        <div className="space-y-3">
          <Field label="Project name" required>
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Website Authority Growth"
            />
          </Field>
          <Field label="Description">
            <Textarea
              rows={2}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="What is this project trying to achieve?"
            />
          </Field>
          <Field label="Target website" required hint="The page that should receive the backlinks.">
            <Input
              value={targetWebsite}
              onChange={(event) => setTargetWebsite(event.target.value)}
              placeholder="https://www.example.com"
            />
          </Field>
          <Field
            label="Business profile"
            hint="Links the project to your company profile used for anchors and descriptions."
          >
            <Select value={profileId} onChange={(event) => setProfileId(event.target.value)}>
              <option value="">No profile selected</option>
              {(profiles.data ?? []).map((profile) => (
                <option key={profile.id} value={profile.id}>
                  {profile.name}
                </option>
              ))}
            </Select>
          </Field>
          {profiles.loading ? (
            <p className="text-xs text-content-subtle">Loading business profiles…</p>
          ) : null}
          {profiles.error ? (
            <p className="text-xs text-danger">{errorMessage(profiles.error)}</p>
          ) : null}
        </div>
      ) : null}

      {step === 1 ? (
        <div className="space-y-3">
          {selectedProfile ? (
            <>
              <p className="rounded-md border border-line bg-surface-sunken px-3 py-2 text-xs text-content-muted">
                These details come from the business profile{" "}
                <span className="font-medium text-content">{selectedProfile.name}</span>. They are
                stored once and shared with every project that uses this profile - edit them in{" "}
                <a className="underline" href="/settings">
                  Settings
                </a>{" "}
                so nothing is duplicated.
              </p>
              <dl className="grid gap-2 text-xs sm:grid-cols-2">
                {[
                  ["Company", selectedProfile.name],
                  ["Website", selectedProfile.primary_website],
                  ["E-mail", selectedProfile.contact_email ?? ""],
                  ["Phone", selectedProfile.contact_phone ?? ""],
                  ["Address", [selectedProfile.address, selectedProfile.city, selectedProfile.country].filter(Boolean).join(", ")],
                  ["Categories", (selectedProfile.preferred_categories ?? []).join(", ")],
                  ["Anchors", (selectedProfile.preferred_anchors ?? []).join(", ")],
                ].map(([label, value]) => (
                  <div key={label} className="rounded-md border border-line px-3 py-2">
                    <dt className="text-[11px] uppercase tracking-wide text-content-subtle">{label}</dt>
                    <dd className="text-content">{value || "—"}</dd>
                  </div>
                ))}
              </dl>
            </>
          ) : (
            <>
              <p className="text-xs text-content-muted">
                A directory asks for these facts when it publishes a backlink. They are stored once
                in a business profile for this project, so every website can reuse them - you can
                change them later at any time. Only the company name is required.
              </p>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Company name">
                  <Input value={details.company_name} onChange={setDetail("company_name")} placeholder="Acme Widgets Ltd" />
                </Field>
                <Field label="Website">
                  <Input value={details.website} onChange={setDetail("website")} placeholder="https://www.example.com" />
                </Field>
                <Field label="E-mail address">
                  <Input type="email" value={details.email} onChange={setDetail("email")} placeholder="hello@example.com" />
                </Field>
                <Field label="Phone number">
                  <Input value={details.phone} onChange={setDetail("phone")} placeholder="+1 555 0100" />
                </Field>
                <Field label="Street address" className="sm:col-span-2">
                  <Input value={details.address} onChange={setDetail("address")} placeholder="1 Main Street" />
                </Field>
                <Field label="City">
                  <Input value={details.city} onChange={setDetail("city")} placeholder="Springfield" />
                </Field>
                <Field label="State / region">
                  <Input value={details.state} onChange={setDetail("state")} placeholder="IL" />
                </Field>
                <Field label="Country">
                  <Input value={details.country} onChange={setDetail("country")} placeholder="United States" />
                </Field>
                <Field label="Postal code">
                  <Input value={details.postal_code} onChange={setDetail("postal_code")} placeholder="62701" />
                </Field>
                <Field label="Categories" hint="Comma separated, e.g. Business, Technology">
                  <Input value={details.categories} onChange={setDetail("categories")} placeholder="Business, Technology" />
                </Field>
                <Field label="Anchors" hint="Comma separated. The texts the backlinks should use.">
                  <Input value={details.anchors} onChange={setDetail("anchors")} placeholder="best widgets, acme widgets" />
                </Field>
                <Field label="Year founded">
                  <Input type="number" value={details.founded_year} onChange={setDetail("founded_year")} placeholder="2015" />
                </Field>
                <Field label="Number of employees">
                  <Input type="number" value={details.employee_count} onChange={setDetail("employee_count")} placeholder="24" />
                </Field>
                <Field label="Description" className="sm:col-span-2" hint="What the company does - the directories use it as the listing text.">
                  <Textarea rows={3} value={details.description} onChange={setDetail("description")} placeholder="We make widgets for teams." />
                </Field>
              </div>
            </>
          )}
        </div>
      ) : null}

      {step === 2 ? (
        <div className="space-y-3">
          <p className="text-xs text-content-muted">
            Landing pages are additional destination URLs of this project. They are optional.
          </p>
          {landingPages.map((page, index) => (
            <div key={index} className="grid gap-2 rounded-md border border-line p-3 sm:grid-cols-[1fr_1fr_140px_auto]">
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
                />
              </Field>
              <Field label="Kind">
                <Select
                  value={page.kind}
                  onChange={(event) =>
                    setLandingPages((prev) =>
                      prev.map((item, i) =>
                        i === index
                          ? { ...item, kind: event.target.value as LandingPageDraft["kind"] }
                          : item,
                      ),
                    )
                  }
                >
                  <option value="MAIN">Main</option>
                  <option value="LANDING">Landing</option>
                  <option value="BLOG">Blog</option>
                  <option value="OTHER">Other</option>
                </Select>
              </Field>
              <div className="flex items-end">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() =>
                    setLandingPages((prev) => prev.filter((_, i) => i !== index))
                  }
                >
                  Remove
                </Button>
              </div>
            </div>
          ))}
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() =>
              setLandingPages((prev) => [...prev, { name: "", url: "", kind: "LANDING" }])
            }
          >
            Add landing page
          </Button>
        </div>
      ) : null}

      {step === 3 ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Max concurrency">
            <Input
              type="number"
              min={1}
              value={maxConcurrency}
              onChange={(event) => setMaxConcurrency(event.target.value)}
            />
          </Field>
          <Field label="Requests per minute">
            <Input
              type="number"
              min={1}
              value={requestRate}
              onChange={(event) => setRequestRate(event.target.value)}
            />
          </Field>
          <Field label="Max retries">
            <Input
              type="number"
              min={0}
              value={maxRetries}
              onChange={(event) => setMaxRetries(event.target.value)}
            />
          </Field>
          <Field label="Backoff base (seconds)">
            <Input
              type="number"
              min={0}
              value={backoffBase}
              onChange={(event) => setBackoffBase(event.target.value)}
            />
          </Field>
          <Field label="Execution environment">
            <Select
              value={environment}
              onChange={(event) => setEnvironment(event.target.value as ExecutionEnvironment)}
            >
              <option value="CLOUD">Cloud worker</option>
              <option value="LOCAL">Local agent</option>
            </Select>
          </Field>
          <div className="space-y-2 pt-5">
            <Label className="flex items-center gap-2 text-content">
              <Checkbox
                checked={requireApproval}
                onChange={(event) => setRequireApproval(event.target.checked)}
              />
              Require approval before publishing
            </Label>
            <Label className="flex items-center gap-2 text-content">
              <Checkbox
                checked={autoQueueApproved}
                onChange={(event) => setAutoQueueApproved(event.target.checked)}
              />
              Auto-queue approved opportunities
            </Label>
            <Label className="flex items-center gap-2 text-content">
              <Checkbox
                checked={allowBrowserAutomation}
                onChange={(event) => setAllowBrowserAutomation(event.target.checked)}
              />
              Allow browser automation
            </Label>
          </div>
        </div>
      ) : null}

      {formError ? (
        <p role="alert" className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-xs text-danger">
          {formError}
        </p>
      ) : null}
      {action.error ? (
        <p role="alert" className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-xs text-danger">
          {errorMessage(action.error)}
        </p>
      ) : null}

      <div className="flex items-center justify-between gap-2 border-t border-line pt-3">
        <Button
          type="button"
          variant="ghost"
          onClick={step === 0 ? onCancel : () => setStep((s) => s - 1)}
        >
          {step === 0 ? "Cancel" : "Back"}
        </Button>
        {step < STEPS.length - 1 ? (
          <Button type="button" onClick={() => setStep((s) => s + 1)}>
            Continue
          </Button>
        ) : (
          <Button type="button" onClick={submit} loading={action.pending}>
            Create project
          </Button>
        )}
      </div>
    </div>
  );
}
