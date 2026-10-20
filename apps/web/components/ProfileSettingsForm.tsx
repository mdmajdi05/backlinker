"use client";

import * as React from "react";
import { api } from "@autobacklinker/api-client";
import type { BusinessProfile, BusinessProfileUpsert } from "@autobacklinker/shared-types";
import {
  Button,
  Checkbox,
  Field,
  Input,
  Label,
  Textarea,
  useToast,
} from "@autobacklinker/ui";
import { apiClient, errorMessage } from "@/lib/api";
import { useAction } from "@/lib/hooks";

const splitList = (value: string): string[] =>
  value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

const splitLines = (value: string): string[] =>
  value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);

export function ProfileSettingsForm({
  profile,
  onSaved,
}: {
  profile: BusinessProfile;
  onSaved?: (profile: BusinessProfile) => void;
}) {
  const toast = useToast();
  const action = useAction();

  const [form, setForm] = React.useState({
    name: profile.name,
    primary_website: profile.primary_website,
    description: profile.description,
    industry: profile.industry,
    niche: profile.niche,
    target_countries: profile.target_countries.join(", "),
    target_regions: profile.target_regions.join(", "),
    contact_email: profile.contact_email ?? "",
    contact_phone: profile.contact_phone ?? "",
    preferred_language: profile.preferred_language,
    keywords: profile.keywords.join(", "),
    business_descriptions: profile.business_descriptions.join("\n"),
    author_bios: profile.author_bios.join("\n"),
    primary_landing_pages: profile.primary_landing_pages.join(", "),
    secondary_landing_pages: profile.secondary_landing_pages.join(", "),
    preferred_anchors: profile.preferred_anchors.join(", "),
    branded: profile.anchor_preferences?.branded ?? true,
    generic: profile.anchor_preferences?.generic ?? true,
    naked_url: profile.anchor_preferences?.naked_url ?? false,
    descriptive: profile.anchor_preferences?.descriptive ?? true,
    preferred_categories: profile.preferred_categories.join(", "),
    excluded_domains: profile.excluded_domains.join(", "),
    excluded_categories: profile.excluded_categories.join(", "),
    target_domains: profile.target_domains.join(", "),
    monthly_target: profile.monthly_target === null ? "" : String(profile.monthly_target),
    campaign_goals: profile.campaign_goals,
  });

  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const save = async () => {
    const payload: BusinessProfileUpsert = {
      name: form.name.trim(),
      primary_website: form.primary_website.trim(),
      description: form.description,
      industry: form.industry,
      niche: form.niche,
      target_countries: splitList(form.target_countries),
      target_regions: splitList(form.target_regions),
      contact_email: form.contact_email.trim() || null,
      contact_phone: form.contact_phone.trim() || null,
      preferred_language: form.preferred_language,
      keywords: splitList(form.keywords),
      business_descriptions: splitLines(form.business_descriptions),
      author_bios: splitLines(form.author_bios),
      primary_landing_pages: splitList(form.primary_landing_pages),
      secondary_landing_pages: splitList(form.secondary_landing_pages),
      preferred_anchors: splitList(form.preferred_anchors),
      anchor_preferences: {
        branded: form.branded,
        generic: form.generic,
        naked_url: form.naked_url,
        descriptive: form.descriptive,
      },
      preferred_categories: splitList(form.preferred_categories),
      excluded_domains: splitList(form.excluded_domains),
      excluded_categories: splitList(form.excluded_categories),
      target_domains: splitList(form.target_domains),
      monthly_target: form.monthly_target === "" ? null : Number.parseInt(form.monthly_target, 10),
      campaign_goals: form.campaign_goals,
    };

    const outcome = await action.run(() =>
      api.profiles.update(apiClient, profile.id, payload),
    );
    if (outcome.ok && outcome.data) {
      toast.push("Global settings saved", "success");
      onSaved?.(outcome.data);
    }
  };

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Business name" required>
          <Input value={form.name} onChange={(event) => set("name", event.target.value)} />
        </Field>
        <Field label="Primary website" required>
          <Input
            value={form.primary_website}
            onChange={(event) => set("primary_website", event.target.value)}
          />
        </Field>
        <Field label="Industry">
          <Input value={form.industry} onChange={(event) => set("industry", event.target.value)} />
        </Field>
        <Field label="Niche">
          <Input value={form.niche} onChange={(event) => set("niche", event.target.value)} />
        </Field>
        <Field label="Preferred language">
          <Input
            value={form.preferred_language}
            onChange={(event) => set("preferred_language", event.target.value)}
            placeholder="en"
          />
        </Field>
        <Field label="Contact e-mail">
          <Input
            value={form.contact_email}
            onChange={(event) => set("contact_email", event.target.value)}
          />
        </Field>
        <Field label="Contact phone">
          <Input
            value={form.contact_phone}
            onChange={(event) => set("contact_phone", event.target.value)}
          />
        </Field>
        <Field label="Monthly target">
          <Input
            type="number"
            min={0}
            value={form.monthly_target}
            onChange={(event) => set("monthly_target", event.target.value)}
          />
        </Field>
      </div>

      <Field label="Description">
        <Textarea
          rows={3}
          value={form.description}
          onChange={(event) => set("description", event.target.value)}
        />
      </Field>

      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Target countries" hint="Comma separated ISO codes">
          <Input
            value={form.target_countries}
            onChange={(event) => set("target_countries", event.target.value)}
          />
        </Field>
        <Field label="Target regions">
          <Input
            value={form.target_regions}
            onChange={(event) => set("target_regions", event.target.value)}
          />
        </Field>
        <Field label="Keywords" hint="Comma separated">
          <Input value={form.keywords} onChange={(event) => set("keywords", event.target.value)} />
        </Field>
        <Field label="Preferred categories" hint="Comma separated">
          <Input
            value={form.preferred_categories}
            onChange={(event) => set("preferred_categories", event.target.value)}
          />
        </Field>
        <Field label="Excluded domains" hint="Comma separated">
          <Input
            value={form.excluded_domains}
            onChange={(event) => set("excluded_domains", event.target.value)}
          />
        </Field>
        <Field label="Excluded categories" hint="Comma separated">
          <Input
            value={form.excluded_categories}
            onChange={(event) => set("excluded_categories", event.target.value)}
          />
        </Field>
        <Field label="Target domains" hint="Comma separated">
          <Input
            value={form.target_domains}
            onChange={(event) => set("target_domains", event.target.value)}
          />
        </Field>
        <Field label="Preferred anchors" hint="Comma separated">
          <Input
            value={form.preferred_anchors}
            onChange={(event) => set("preferred_anchors", event.target.value)}
          />
        </Field>
        <Field label="Primary landing pages" hint="Comma separated URLs">
          <Input
            value={form.primary_landing_pages}
            onChange={(event) => set("primary_landing_pages", event.target.value)}
          />
        </Field>
        <Field label="Secondary landing pages" hint="Comma separated URLs">
          <Input
            value={form.secondary_landing_pages}
            onChange={(event) => set("secondary_landing_pages", event.target.value)}
          />
        </Field>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Business descriptions" hint="One per line">
          <Textarea
            rows={3}
            value={form.business_descriptions}
            onChange={(event) => set("business_descriptions", event.target.value)}
          />
        </Field>
        <Field label="Author bios" hint="One per line">
          <Textarea
            rows={3}
            value={form.author_bios}
            onChange={(event) => set("author_bios", event.target.value)}
          />
        </Field>
      </div>

      <div className="rounded-md border border-line p-3">
        <p className="mb-2 text-xs font-semibold text-content">Anchor preferences</p>
        <div className="grid gap-2 sm:grid-cols-2">
          <Label className="flex items-center gap-2 text-content">
            <Checkbox
              checked={form.branded}
              onChange={(event) => set("branded", event.target.checked)}
            />
            Branded anchors
          </Label>
          <Label className="flex items-center gap-2 text-content">
            <Checkbox
              checked={form.generic}
              onChange={(event) => set("generic", event.target.checked)}
            />
            Generic anchors
          </Label>
          <Label className="flex items-center gap-2 text-content">
            <Checkbox
              checked={form.naked_url}
              onChange={(event) => set("naked_url", event.target.checked)}
            />
            Naked URL anchors
          </Label>
          <Label className="flex items-center gap-2 text-content">
            <Checkbox
              checked={form.descriptive}
              onChange={(event) => set("descriptive", event.target.checked)}
            />
            Descriptive anchors
          </Label>
        </div>
      </div>

      <Field label="Campaign goals">
        <Textarea
          rows={3}
          value={form.campaign_goals}
          onChange={(event) => set("campaign_goals", event.target.value)}
        />
      </Field>

      {action.error ? (
        <p className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-xs text-danger">
          {errorMessage(action.error)}
        </p>
      ) : null}

      <div className="flex justify-end border-t border-line pt-3">
        <Button onClick={save} loading={action.pending}>
          Save global settings
        </Button>
      </div>
    </div>
  );
}
