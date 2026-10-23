"use client";

import * as React from "react";
import { api } from "@autobacklinker/api-client";
import type { Project } from "@autobacklinker/shared-types";
import { Button, Field, Input, Select, Textarea } from "@autobacklinker/ui";
import { apiClient, errorMessage } from "@/lib/api";
import { useAction } from "@/lib/hooks";

interface LandingPageDraft {
  name: string;
  url: string;
  kind: "MAIN" | "LANDING" | "BLOG" | "OTHER";
}

/** The facts the backlink websites ask for.  They belong to this project. */
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

const STEPS = ["Project", "Company details", "Landing pages"] as const;

/**
 * Three plain steps: the project, the company facts every website needs and
 * optional landing pages.  Every project gets its own details - there is no
 * shared profile to think about.
 */
export function ProjectWizard({
  onCreated,
  onCancel,
}: {
  onCreated: (project: Project) => void;
  onCancel: () => void;
}) {
  const [step, setStep] = React.useState(0);
  const [name, setName] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [targetWebsite, setTargetWebsite] = React.useState("");
  const [landingPages, setLandingPages] = React.useState<LandingPageDraft[]>([]);
  const [formError, setFormError] = React.useState<string | null>(null);
  const [details, setDetails] = React.useState<DetailsDraft>(EMPTY_DETAILS);

  const setDetail =
    (field: keyof DetailsDraft) =>
    (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setDetails((previous) => ({ ...previous, [field]: event.target.value }));

  const action = useAction();

  const submit = async () => {
    setFormError(null);
    if (!name.trim()) {
      setFormError("Give the project a name.");
      setStep(0);
      return;
    }
    if (!targetWebsite.trim()) {
      setFormError("The target website is required.");
      setStep(0);
      return;
    }
    const outcome = await action.run(() =>
      api.projects.create(apiClient, {
        name: name.trim(),
        description: description.trim() || undefined,
        target_website: targetWebsite.trim(),
        business_profile_id: null,
        landing_pages: landingPages
          .filter((page) => page.url.trim())
          .map((page) => ({
            name: page.name.trim() || page.url.trim(),
            url: page.url.trim(),
            kind: page.kind,
          })),
        details: {
          company_name: details.company_name.trim() || name.trim(),
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
        settings: {
          max_concurrency: 3,
          request_rate_per_minute: 60,
          max_retries: 3,
          backoff_base_seconds: 30,
          execution_environment: "CLOUD",
          require_approval: false,
          auto_queue_approved: false,
          allow_browser_automation: true,
        },
      }),
    );
    if (outcome.ok && outcome.data) {
      onCreated(outcome.data);
    }
  };

  return (
    <div className="space-y-4">
      <ol className="flex flex-wrap items-center gap-2 text-xs" aria-label="Wizard steps">
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
          <p className="text-xs text-content-muted">
            A project is one website you want backlinks for. Its details, its websites and its
            report stay together on one page.
          </p>
          <Field label="Project name" required>
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Acme - Shopify app"
            />
          </Field>
          <Field
            label="Target website"
            required
            hint="The page that should receive the backlinks."
          >
            <Input
              value={targetWebsite}
              onChange={(event) => setTargetWebsite(event.target.value)}
              placeholder="https://www.example.com"
            />
          </Field>
          <Field label="What is this project about? (optional)">
            <Textarea
              rows={2}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="e.g. Backlinks for the product page of our Shopify app"
            />
          </Field>
        </div>
      ) : null}

      {step === 1 ? (
        <div className="space-y-3">
          <p className="text-xs text-content-muted">
            Websites ask for these facts when they publish a backlink. They are saved for this
            project only and you can change them anytime on the project page. You can start with
            the company name and fill the rest later.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Company name" hint="Defaults to the project name.">
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
            <Field label="Anchors" hint="Comma separated. The clickable texts of the links.">
              <Input value={details.anchors} onChange={setDetail("anchors")} placeholder="best widgets, acme widgets" />
            </Field>
            <Field label="Year founded">
              <Input type="number" value={details.founded_year} onChange={setDetail("founded_year")} placeholder="2015" />
            </Field>
            <Field label="Number of employees">
              <Input type="number" value={details.employee_count} onChange={setDetail("employee_count")} placeholder="24" />
            </Field>
            <Field
              label="Description"
              className="sm:col-span-2"
              hint="What the company does - the websites use it as the listing text."
            >
              <Textarea rows={3} value={details.description} onChange={setDetail("description")} placeholder="We make widgets for teams." />
            </Field>
          </div>
        </div>
      ) : null}

      {step === 2 ? (
        <div className="space-y-3">
          <p className="text-xs text-content-muted">
            Optional. Add other pages of your website a backlink may point to. The target website
            above is used when this list is empty.
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
          <Button type="button" onClick={() => void submit()} loading={action.pending}>
            Create project
          </Button>
        )}
      </div>
    </div>
  );
}
