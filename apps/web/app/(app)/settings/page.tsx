"use client";

import * as React from "react";
import Link from "next/link";
import { api } from "@autobacklinker/api-client";
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  Dialog,
  Field,
  Input,
  Select,
  Tabs,
  useToast,
} from "@autobacklinker/ui";
import { apiClient, errorMessage } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { PageHeader } from "@/components/PageHeader";
import { AsyncSection, TableSkeleton } from "@/components/States";
import { ProfileSettingsForm } from "@/components/ProfileSettingsForm";
import { StoragePanel } from "@/components/StoragePanel";

/*
 * The settings of the workspace.  Everything that belongs to a **project**
 * (execution rules, auto pilot) lives on the project page; everything that
 * belongs to a **website** lives on the website page.  This page keeps the two
 * things that are really workspace wide: the business profiles and the
 * database.
 */
const TABS = [
  { id: "profiles", label: "Business profiles" },
  { id: "storage", label: "Database & storage" },
];

const EMPTY_PROFILE = { name: "", primary_website: "" };

export default function SettingsPage() {
  const toast = useToast();
  const [tab, setTab] = React.useState("profiles");
  const [profileId, setProfileId] = React.useState("");

  const [createOpen, setCreateOpen] = React.useState(false);
  const [createForm, setCreateForm] = React.useState(EMPTY_PROFILE);
  const [createError, setCreateError] = React.useState<string | null>(null);
  const [creating, setCreating] = React.useState(false);

  const profiles = useResource(() => api.profiles.list(apiClient), []);

  const items = profiles.data ?? [];
  const selected = items.find((profile) => profile.id === profileId) ?? items[0] ?? null;

  const submitCreate = async () => {
    setCreateError(null);
    setCreating(true);
    try {
      const created = await api.profiles.create(apiClient, {
        ...EMPTY_PROFILE,
        ...createForm,
      });
      setCreateOpen(false);
      setCreateForm(EMPTY_PROFILE);
      setProfileId(created.id);
      toast.push(`${created.name} created - fill in the rest below`, "success");
      profiles.reload();
    } catch (err) {
      setCreateError(errorMessage(err));
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Settings"
        description="The business profiles every project submits with, and the local database."
      />

      <Card>
        <CardBody className="p-0">
          <Tabs tabs={TABS} active={tab} onChange={setTab} className="px-3" />
        </CardBody>
      </Card>

      {tab === "profiles" ? (
        <Card>
          <CardHeader
            title="Business profiles"
            description="One profile per company. Every project picks the profile it submits with - the values are stored once and shared, never typed twice."
            action={
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setCreateError(null);
                  setCreateForm(EMPTY_PROFILE);
                  setCreateOpen(true);
                }}
              >
                New profile
              </Button>
            }
          />
          <CardBody className="space-y-4">
            <AsyncSection
              loading={profiles.loading}
              error={profiles.error}
              data={profiles.data}
              onRetry={profiles.reload}
              isEmpty={items.length === 0}
              emptyTitle="No business profile"
              emptyDescription="Create one here - or create a project and fill in its backlink details."
              skeleton={<TableSkeleton rows={6} columns={2} />}
            >
              {items.length > 0 ? (
                <>
                  {items.length > 1 ? (
                    <Field
                      label="Profile"
                      className="max-w-sm"
                      hint="The profile that is edited below."
                    >
                      <Select
                        value={selected?.id ?? ""}
                        onChange={(event) => setProfileId(event.target.value)}
                        aria-label="The business profile to edit"
                      >
                        {items.map((profile) => (
                          <option key={profile.id} value={profile.id}>
                            {profile.name} · {profile.primary_website}
                          </option>
                        ))}
                      </Select>
                    </Field>
                  ) : null}

                  {selected ? (
                    <ProfileSettingsForm
                      key={selected.id}
                      profile={selected}
                      onSaved={profiles.reload}
                    />
                  ) : null}

                  <p className="text-xs text-content-subtle">
                    The same values can be edited from a project:{" "}
                    <span className="text-content-muted">
                      Projects → open a project → Edit → Backlink details
                    </span>
                    . Both places write the same profile, so nothing is duplicated.
                  </p>
                </>
              ) : (
                <p className="text-xs text-content-muted">
                  <Link className="underline" href="/projects">
                    Create a project
                  </Link>{" "}
                  and fill in its backlink details - the profile is created with it.
                </p>
              )}
            </AsyncSection>
          </CardBody>
        </Card>
      ) : null}

      {tab === "storage" ? <StoragePanel /> : null}

      <Dialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="New business profile"
        description="The company the backlinks are made for. The rest is filled in below after saving."
        width="md"
        footer={
          <>
            <Button variant="outline" onClick={() => setCreateOpen(false)} disabled={creating}>
              Cancel
            </Button>
            <Button
              loading={creating}
              disabled={!createForm.name.trim() || createForm.primary_website.trim().length < 3}
              onClick={() => void submitCreate()}
            >
              Create
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          {createError ? (
            <p className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-xs text-danger">
              {createError}
            </p>
          ) : null}
          <Field label="Company name" required>
            <Input
              value={createForm.name}
              onChange={(event) => setCreateForm((prev) => ({ ...prev, name: event.target.value }))}
              placeholder="Acme Analytics"
            />
          </Field>
          <Field label="Primary website" required hint="The site the backlinks point to.">
            <Input
              value={createForm.primary_website}
              onChange={(event) =>
                setCreateForm((prev) => ({ ...prev, primary_website: event.target.value }))
              }
              placeholder="https://acme.example"
            />
          </Field>
        </div>
      </Dialog>
    </div>
  );
}
