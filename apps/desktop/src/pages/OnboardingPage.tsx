import * as React from "react";
import {
  Alert,
  Button,
  Card,
  CardBody,
  Checkbox,
  Field,
  Input,
  Label,
  Select,
  Textarea,
  useToast,
} from "@autobacklinker/ui";
import { OpportunityCategory } from "@autobacklinker/shared-types";
import { api, apiClient } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import { PageHeader } from "../components/common";
import { formatNumber, titleCase } from "../lib/format";
import { navigate } from "../lib/router";
import { sendNativeNotification } from "../lib/backend";
import type { BusinessProfile, ProjectCreate } from "@autobacklinker/shared-types";

const STEPS = ["Business profile", "SEO configuration", "First project"] as const;

const CATEGORIES = Object.values(OpportunityCategory);

function errorText(error: unknown, fallback: string): string {
  if (error && typeof error === "object" && "message" in error) {
    return String((error as { message: unknown }).message);
  }
  return fallback;
}

function splitList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function OnboardingPage() {
  const toast = useToast();
  const [step, setStep] = React.useState(0);
  const [profileId, setProfileId] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  const existing = useAsync(() => api.profiles.list(apiClient), []);

  const [profile, setProfile] = React.useState({
    name: "",
    primary_website: "",
    description: "",
    industry: "",
    niche: "",
    target_countries: "",
    contact_email: "",
    preferred_language: "en",
  });

  const [seo, setSeo] = React.useState({
    keywords: "",
    preferred_anchors: "",
    preferred_categories: "",
    excluded_domains: "",
    primary_landing_pages: "",
    monthly_target: "",
    campaign_goals: "",
    branded: true,
    generic: true,
    naked_url: false,
    descriptive: true,
  });

  const [project, setProject] = React.useState({
    name: "",
    description: "",
    target_website: "",
    max_concurrency: "3",
    request_rate_per_minute: "60",
    max_retries: "3",
    require_approval: true,
  });

  function profilePayload() {
    return {
      name: profile.name.trim(),
      primary_website: profile.primary_website.trim(),
      description: profile.description.trim(),
      industry: profile.industry.trim(),
      niche: profile.niche.trim(),
      target_countries: splitList(profile.target_countries),
      contact_email: profile.contact_email.trim() || null,
      preferred_language: profile.preferred_language.trim() || "en",
    };
  }

  function seoPayload() {
    return {
      ...profilePayload(),
      keywords: splitList(seo.keywords),
      preferred_anchors: splitList(seo.preferred_anchors),
      preferred_categories: splitList(seo.preferred_categories),
      excluded_domains: splitList(seo.excluded_domains),
      primary_landing_pages: splitList(seo.primary_landing_pages),
      monthly_target:
        seo.monthly_target === ""
          ? null
          : Number.parseInt(seo.monthly_target, 10) || null,
      campaign_goals: seo.campaign_goals,
      anchor_preferences: {
        branded: seo.branded,
        generic: seo.generic,
        naked_url: seo.naked_url,
        descriptive: seo.descriptive,
      },
    };
  }

  async function createProfile() {
    setError(null);
    if (!profile.name.trim()) {
      setError("The business name is required.");
      return;
    }
    if (!profile.primary_website.trim()) {
      setError("The primary website is required.");
      return;
    }
    setBusy(true);
    try {
      const created = await api.profiles.create(apiClient, profilePayload());
      setProfileId(created.id);
      toast.push("Business profile created", "success");
      void sendNativeNotification(
        "Auto Backlinker",
        `The business profile ${profile.name.trim()} was created.`,
      );
      setStep(1);
    } catch (err) {
      setError(errorText(err, "Could not create the business profile"));
    } finally {
      setBusy(false);
    }
  }

  async function saveSeo() {
    setError(null);
    if (!profileId) {
      setError("The business profile was not created yet.");
      return;
    }
    setBusy(true);
    try {
      await api.profiles.update(apiClient, profileId, seoPayload());
      toast.push("SEO configuration saved", "success");
      void sendNativeNotification(
        "Auto Backlinker",
        "The SEO configuration was saved.",
      );
      setStep(2);
    } catch (err) {
      setError(errorText(err, "Could not save the SEO configuration"));
    } finally {
      setBusy(false);
    }
  }

  async function skipSeo() {
    setError(null);
    if (profileId) {
      setStep(2);
      return;
    }
    if (!profile.name.trim() || !profile.primary_website.trim()) {
      setError("A business profile is required before a project can be created.");
      return;
    }
    setBusy(true);
    try {
      const created = await api.profiles.create(apiClient, profilePayload());
      setProfileId(created.id);
      setStep(2);
    } catch (err) {
      setError(errorText(err, "Could not create the business profile"));
    } finally {
      setBusy(false);
    }
  }

  async function createProject() {
    setError(null);
    if (!project.name.trim()) {
      setError("The project name is required.");
      return;
    }
    const target = project.target_website.trim() || profile.primary_website.trim();
    if (!target) {
      setError("The target website is required.");
      return;
    }

    const payload: ProjectCreate = {
      name: project.name.trim(),
      description: project.description.trim() || undefined,
      target_website: target,
      business_profile_id: profileId,
      landing_pages: splitList(seo.primary_landing_pages).map((url) => ({
        name: url,
        url,
        kind: "LANDING" as const,
      })),
      settings: {
        max_concurrency: Number.parseInt(project.max_concurrency, 10) || 3,
        request_rate_per_minute:
          Number.parseInt(project.request_rate_per_minute, 10) || 60,
        max_retries: Number.parseInt(project.max_retries, 10) || 3,
        require_approval: project.require_approval,
        execution_environment: "LOCAL",
      },
    };

    setBusy(true);
    try {
      const created = await api.projects.create(apiClient, payload);
      toast.push("Project created - the workspace is ready", "success");
      void sendNativeNotification(
        "Auto Backlinker",
        `The project ${project.name.trim()} was created.`,
      );
      navigate(`projects/${created.id}`);
    } catch (err) {
      setError(errorText(err, "Could not create the project"));
    } finally {
      setBusy(false);
    }
  }

  const existingProfiles: BusinessProfile[] = existing.data ?? [];

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4">
      <PageHeader
        title="Setup"
        description="Three short steps until this installation is ready to work."
      />

      <Card>
        <CardBody>
          <ol className="mb-5 flex flex-wrap items-center gap-2 text-xs">
            {STEPS.map((label, index) => (
              <li key={label} className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => index <= step && setStep(index)}
                  disabled={index > step}
                  aria-current={index === step ? "step" : undefined}
                  className={
                    index === step
                      ? "flex h-6 w-6 items-center justify-center rounded-full border border-accent bg-accent text-[11px] font-semibold text-accent-fg"
                      : "flex h-6 w-6 items-center justify-center rounded-full border border-accent/40 bg-accent-soft text-[11px] font-semibold text-accent disabled:opacity-50"
                  }
                >
                  {index + 1}
                </button>
                <span
                  className={
                    index === step
                      ? "font-medium text-content"
                      : "text-content-muted"
                  }
                >
                  {label}
                </span>
                {index < STEPS.length - 1 ? (
                  <span className="text-content-subtle">/</span>
                ) : null}
              </li>
            ))}
          </ol>

          {existingProfiles.length > 0 ? (
            <div className="mb-4">
              <Alert tone="info" title="A business profile already exists">
                This installation already contains{" "}
                {formatNumber(existingProfiles.length)} profile(s). Creating
                another one may duplicate business data.
              </Alert>
            </div>
          ) : null}

          {error ? (
            <p className="mb-3 rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-xs text-danger">
              {error}
            </p>
          ) : null}

          {/*
            The actions sit above the form: the toasts of the desktop client
            are shown in the lower right corner and would otherwise cover the
            button of the step.
          */}
          <div className="mb-4 flex items-center justify-between gap-2 border-b border-line pb-3">
            <Button
              type="button"
              variant="ghost"
              onClick={() =>
                step === 0 ? navigate("overview") : setStep((s) => s - 1)
              }
            >
              {step === 0 ? "Skip for now" : "Back"}
            </Button>
            {step === 0 ? (
              <Button type="button" loading={busy} onClick={createProfile}>
                Continue
              </Button>
            ) : step === 1 ? (
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  loading={busy}
                  onClick={skipSeo}
                >
                  Skip SEO config
                </Button>
                <Button type="button" loading={busy} onClick={saveSeo}>
                  Continue
                </Button>
              </div>
            ) : (
              <Button type="button" loading={busy} onClick={createProject}>
                Create project and finish
              </Button>
            )}
          </div>

          {step === 0 ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Business name" required>
                <Input
                  value={profile.name}
                  onChange={(event) =>
                    setProfile((prev) => ({ ...prev, name: event.target.value }))
                  }
                  placeholder="Acme Ltd."
                />
              </Field>
              <Field label="Primary website" required>
                <Input
                  value={profile.primary_website}
                  onChange={(event) =>
                    setProfile((prev) => ({
                      ...prev,
                      primary_website: event.target.value,
                    }))
                  }
                  placeholder="https://www.acme.com"
                />
              </Field>
              <Field label="Industry">
                <Input
                  value={profile.industry}
                  onChange={(event) =>
                    setProfile((prev) => ({
                      ...prev,
                      industry: event.target.value,
                    }))
                  }
                />
              </Field>
              <Field label="Niche">
                <Input
                  value={profile.niche}
                  onChange={(event) =>
                    setProfile((prev) => ({ ...prev, niche: event.target.value }))
                  }
                />
              </Field>
              <Field label="Target countries" hint="Comma separated ISO codes">
                <Input
                  value={profile.target_countries}
                  onChange={(event) =>
                    setProfile((prev) => ({
                      ...prev,
                      target_countries: event.target.value,
                    }))
                  }
                  placeholder="US, GB, DE"
                />
              </Field>
              <Field label="Contact e-mail">
                <Input
                  value={profile.contact_email}
                  onChange={(event) =>
                    setProfile((prev) => ({
                      ...prev,
                      contact_email: event.target.value,
                    }))
                  }
                />
              </Field>
              <Field label="Preferred language">
                <Input
                  value={profile.preferred_language}
                  onChange={(event) =>
                    setProfile((prev) => ({
                      ...prev,
                      preferred_language: event.target.value,
                    }))
                  }
                />
              </Field>
              <Field label="Description" className="sm:col-span-2">
                <Textarea
                  rows={3}
                  value={profile.description}
                  onChange={(event) =>
                    setProfile((prev) => ({
                      ...prev,
                      description: event.target.value,
                    }))
                  }
                  placeholder="What does the business do?"
                />
              </Field>
            </div>
          ) : null}

          {step === 1 ? (
            <div className="flex flex-col gap-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Keywords" hint="Comma separated">
                  <Input
                    value={seo.keywords}
                    onChange={(event) =>
                      setSeo((prev) => ({ ...prev, keywords: event.target.value }))
                    }
                    placeholder="project management, team collaboration"
                  />
                </Field>
                <Field label="Preferred anchors" hint="Comma separated">
                  <Input
                    value={seo.preferred_anchors}
                    onChange={(event) =>
                      setSeo((prev) => ({
                        ...prev,
                        preferred_anchors: event.target.value,
                      }))
                    }
                    placeholder="Acme, acme project management"
                  />
                </Field>
                <Field label="Preferred category">
                  <Select
                    value={seo.preferred_categories}
                    onChange={(event) =>
                      setSeo((prev) => ({
                        ...prev,
                        preferred_categories: event.target.value,
                      }))
                    }
                  >
                    <option value="">No preference</option>
                    {CATEGORIES.map((value) => (
                      <option key={value} value={value}>
                        {titleCase(value)}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Excluded domains" hint="Comma separated">
                  <Input
                    value={seo.excluded_domains}
                    onChange={(event) =>
                      setSeo((prev) => ({
                        ...prev,
                        excluded_domains: event.target.value,
                      }))
                    }
                  />
                </Field>
                <Field label="Primary landing pages" hint="Comma separated URLs">
                  <Input
                    value={seo.primary_landing_pages}
                    onChange={(event) =>
                      setSeo((prev) => ({
                        ...prev,
                        primary_landing_pages: event.target.value,
                      }))
                    }
                    placeholder="https://www.acme.com/pricing"
                  />
                </Field>
                <Field label="Monthly backlink target">
                  <Input
                    type="number"
                    min={0}
                    value={seo.monthly_target}
                    onChange={(event) =>
                      setSeo((prev) => ({
                        ...prev,
                        monthly_target: event.target.value,
                      }))
                    }
                  />
                </Field>
              </div>

              <div className="rounded-md border border-line p-3">
                <p className="mb-2 text-xs font-semibold text-content">
                  Anchor preferences
                </p>
                <div className="grid gap-2 sm:grid-cols-2">
                  <Label className="flex items-center gap-2 text-content">
                    <Checkbox
                      checked={seo.branded}
                      onChange={(event) =>
                        setSeo((prev) => ({ ...prev, branded: event.target.checked }))
                      }
                    />
                    Branded
                  </Label>
                  <Label className="flex items-center gap-2 text-content">
                    <Checkbox
                      checked={seo.generic}
                      onChange={(event) =>
                        setSeo((prev) => ({ ...prev, generic: event.target.checked }))
                      }
                    />
                    Generic
                  </Label>
                  <Label className="flex items-center gap-2 text-content">
                    <Checkbox
                      checked={seo.naked_url}
                      onChange={(event) =>
                        setSeo((prev) => ({
                          ...prev,
                          naked_url: event.target.checked,
                        }))
                      }
                    />
                    Naked URL
                  </Label>
                  <Label className="flex items-center gap-2 text-content">
                    <Checkbox
                      checked={seo.descriptive}
                      onChange={(event) =>
                        setSeo((prev) => ({
                          ...prev,
                          descriptive: event.target.checked,
                        }))
                      }
                    />
                    Descriptive
                  </Label>
                </div>
              </div>

              <Field label="Campaign goals">
                <Textarea
                  rows={3}
                  value={seo.campaign_goals}
                  onChange={(event) =>
                    setSeo((prev) => ({
                      ...prev,
                      campaign_goals: event.target.value,
                    }))
                  }
                  placeholder="Reach 50 verified backlinks in 3 months…"
                />
              </Field>
            </div>
          ) : null}

          {step === 2 ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Project name" required>
                <Input
                  value={project.name}
                  onChange={(event) =>
                    setProject((prev) => ({ ...prev, name: event.target.value }))
                  }
                  placeholder="Website authority growth"
                />
              </Field>
              <Field
                label="Target website"
                required
                hint={
                  profile.primary_website
                    ? `Defaults to ${profile.primary_website}`
                    : undefined
                }
              >
                <Input
                  value={project.target_website}
                  onChange={(event) =>
                    setProject((prev) => ({
                      ...prev,
                      target_website: event.target.value,
                    }))
                  }
                  placeholder={profile.primary_website || "https://www.acme.com"}
                />
              </Field>
              <Field label="Description" className="sm:col-span-2">
                <Textarea
                  rows={2}
                  value={project.description}
                  onChange={(event) =>
                    setProject((prev) => ({
                      ...prev,
                      description: event.target.value,
                    }))
                  }
                />
              </Field>
              <Field label="Max concurrency">
                <Input
                  type="number"
                  min={1}
                  value={project.max_concurrency}
                  onChange={(event) =>
                    setProject((prev) => ({
                      ...prev,
                      max_concurrency: event.target.value,
                    }))
                  }
                />
              </Field>
              <Field label="Requests per minute">
                <Input
                  type="number"
                  min={1}
                  value={project.request_rate_per_minute}
                  onChange={(event) =>
                    setProject((prev) => ({
                      ...prev,
                      request_rate_per_minute: event.target.value,
                    }))
                  }
                />
              </Field>
              <Field label="Max retries">
                <Input
                  type="number"
                  min={0}
                  value={project.max_retries}
                  onChange={(event) =>
                    setProject((prev) => ({
                      ...prev,
                      max_retries: event.target.value,
                    }))
                  }
                />
              </Field>
              <div className="flex items-end pb-1">
                <Label className="flex items-center gap-2 text-content">
                  <Checkbox
                    checked={project.require_approval}
                    onChange={(event) =>
                      setProject((prev) => ({
                        ...prev,
                        require_approval: event.target.checked,
                      }))
                    }
                  />
                  Require approval before publishing
                </Label>
              </div>
            </div>
          ) : null}
        </CardBody>
      </Card>
    </div>
  );
}
