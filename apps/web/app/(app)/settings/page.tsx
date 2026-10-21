"use client";

import * as React from "react";
import { api } from "@autobacklinker/api-client";
import {
  Card,
  CardBody,
  CardHeader,
  Field,
  Select,
  Tabs,
} from "@autobacklinker/ui";
import { apiClient } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { PageHeader } from "@/components/PageHeader";
import { AsyncSection, TableSkeleton } from "@/components/States";
import { ProfileSettingsForm } from "@/components/ProfileSettingsForm";
import { ProjectSettingsForm } from "@/components/ProjectSettingsForm";
import { StoragePanel } from "@/components/StoragePanel";
import { AutomationPanel } from "@/components/AutomationPanel";

const TABS = [
  { id: "global", label: "Global settings" },
  { id: "projects", label: "Project settings" },
  { id: "automation", label: "Automation & browser" },
  { id: "storage", label: "Database & storage" },
];

export default function SettingsPage() {
  const [tab, setTab] = React.useState("global");
  const [projectId, setProjectId] = React.useState("");

  const profiles = useResource(() => api.profiles.list(apiClient), []);
  const projects = useResource(() => api.projects.list(apiClient, { page: 1, page_size: 100 }), []);
  const projectSettings = useResource(
    () =>
      projectId
        ? api.projects.settings(apiClient, projectId)
        : Promise.resolve(null),
    [projectId],
    { enabled: Boolean(projectId) },
  );

  React.useEffect(() => {
    if (projectId) return;
    const first = projects.data?.items?.[0];
    if (first) setProjectId(first.id);
  }, [projects.data, projectId]);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Settings"
        description="Workspace defaults, per-project execution rules and the database connection."
      />

      <Card>
        <CardBody className="p-0">
          <Tabs tabs={TABS} active={tab} onChange={setTab} className="px-3" />
        </CardBody>
      </Card>

      {tab === "global" ? (
        <Card>
          <CardHeader
            title="Global settings"
            description="Business profile used for anchors, descriptions and targeting"
          />
          <CardBody>
            <AsyncSection
              loading={profiles.loading}
              error={profiles.error}
              data={profiles.data}
              onRetry={profiles.reload}
              isEmpty={(profiles.data ?? []).length === 0}
              emptyTitle="No business profile"
              emptyDescription="Create a business profile in the onboarding wizard first."
              skeleton={<TableSkeleton rows={6} columns={2} />}
            >
              {(profiles.data ?? []).length > 0 ? (
                <ProfileSettingsForm
                  profile={(profiles.data ?? [])[0]}
                  onSaved={profiles.reload}
                />
              ) : null}
            </AsyncSection>
          </CardBody>
        </Card>
      ) : null}

      {tab === "projects" ? (
        <Card>
          <CardHeader title="Project settings" description="Per-project execution rules" />
          <CardBody>
            <Field label="Project" className="max-w-sm">
              <Select value={projectId} onChange={(event) => setProjectId(event.target.value)}>
                <option value="">Select project…</option>
                {(projects.data?.items ?? []).map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </Select>
            </Field>

            <div className="mt-4">
              {!projectId ? (
                <p className="text-xs text-content-subtle">Select a project to edit its settings.</p>
              ) : projectSettings.loading && !projectSettings.data ? (
                <p className="text-xs text-content-subtle">Loading settings…</p>
              ) : projectSettings.error ? (
                <p className="text-xs text-danger">
                  {projectSettings.error instanceof Error
                    ? projectSettings.error.message
                    : "Could not load the project settings."}
                </p>
              ) : (
                <ProjectSettingsForm
                  projectId={projectId}
                  settings={projectSettings.data ?? null}
                />
              )}
            </div>
          </CardBody>
        </Card>
      ) : null}

      {tab === "automation" ? <AutomationPanel /> : null}

      {tab === "storage" ? <StoragePanel /> : null}
    </div>
  );
}
