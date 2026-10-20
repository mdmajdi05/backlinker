import * as React from "react";
import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  Checkbox,
  Field,
  Input,
  Select,
  Table,
  Td,
  Th,
  useToast,
} from "@autobacklinker/ui";
import { api, apiClient } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import { ErrorBlock, LoadingBlock, NothingYet, PageHeader } from "../components/common";
import type { Adapter, Project, ProjectSettings } from "@autobacklinker/shared-types";

export function AutomationPage() {
  const toast = useToast();
  const [projectId, setProjectId] = React.useState("");
  const [saving, setSaving] = React.useState(false);

  const adapters = useAsync(() => api.adapters.list(apiClient), []);
  const projects = useAsync(
    () => api.projects.list(apiClient, { page: 1, page_size: 100 }),
    [],
  );

  const settings = useAsync(
    () =>
      projectId
        ? api.projects.settings(apiClient, projectId)
        : Promise.resolve(null),
    [projectId],
  );

  const adapterItems = adapters.data ?? [];

  async function updateSettings(patch: Partial<ProjectSettings>) {
    if (!projectId) return;
    setSaving(true);
    try {
      await api.projects.updateSettings(apiClient, projectId, patch);
      toast.push("Settings saved", "success");
      settings.reload();
    } catch (err) {
      toast.push(
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : "Could not save the settings",
        "error",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Automation"
        description="Submission adapters and the per project execution policy."
      />

      <Card>
        <CardHeader
          title="Project policy"
          description="Controls which tasks may run automatically on this device."
        />
        <CardBody>
          <div className="mb-4 w-72">
            <Field label="Project">
              <Select
                value={projectId}
                onChange={(event) => setProjectId(event.target.value)}
              >
                <option value="">Select a project…</option>
                {(projects.data?.items ?? []).map((project: Project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </Select>
            </Field>
          </div>

          {!projectId ? (
            <NothingYet
              title="No project selected"
              description="Choose a project to review and change its automation policy."
            />
          ) : settings.loading && !settings.data ? (
            <LoadingBlock rows={3} />
          ) : settings.error ? (
            <ErrorBlock message={settings.error} onRetry={settings.reload} />
          ) : settings.data ? (
            <div className="flex flex-col gap-4">
              <div className="grid gap-3 md:grid-cols-3">
                <Field
                  label="Execution environment"
                  hint="LOCAL runs the work on this machine."
                >
                  <Select
                    value={settings.data.execution_environment}
                    onChange={(event) =>
                      updateSettings({
                        execution_environment: event.target
                          .value as ProjectSettings["execution_environment"],
                      })
                    }
                  >
                    <option value="CLOUD">CLOUD</option>
                    <option value="LOCAL">LOCAL</option>
                  </Select>
                </Field>
                <Field label="Max concurrency">
                  <Input
                    type="number"
                    min={1}
                    defaultValue={settings.data.max_concurrency}
                    onBlur={(event) =>
                      updateSettings({
                        max_concurrency: Number(event.target.value),
                      })
                    }
                  />
                </Field>
                <Field label="Requests per minute">
                  <Input
                    type="number"
                    min={1}
                    defaultValue={settings.data.request_rate_per_minute}
                    onBlur={(event) =>
                      updateSettings({
                        request_rate_per_minute: Number(event.target.value),
                      })
                    }
                  />
                </Field>
              </div>

              <div className="flex flex-col gap-2">
                <label className="flex items-center gap-2 text-xs text-content">
                  <Checkbox
                    checked={settings.data.allow_browser_automation}
                    onChange={(event) =>
                      updateSettings({
                        allow_browser_automation: event.target.checked,
                      })
                    }
                  />
                  Allow browser automation (Playwright on this device)
                </label>
                <label className="flex items-center gap-2 text-xs text-content">
                  <Checkbox
                    checked={settings.data.require_approval}
                    onChange={(event) =>
                      updateSettings({ require_approval: event.target.checked })
                    }
                  />
                  Require approval before a task is queued
                </label>
                <label className="flex items-center gap-2 text-xs text-content">
                  <Checkbox
                    checked={settings.data.auto_queue_approved}
                    onChange={(event) =>
                      updateSettings({ auto_queue_approved: event.target.checked })
                    }
                  />
                  Queue approved opportunities automatically
                </label>
              </div>

              {saving ? (
                <p className="text-xs text-content-subtle">Saving…</p>
              ) : null}
            </div>
          ) : null}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Adapters"
          description={`${adapterItems.length} adapters registered by the backend`}
        />
        <CardBody className="p-0">
          {adapters.loading && !adapters.data ? (
            <div className="p-4">
              <LoadingBlock rows={3} />
            </div>
          ) : adapters.error ? (
            <div className="p-4">
              <ErrorBlock message={adapters.error} onRetry={adapters.reload} />
            </div>
          ) : adapterItems.length === 0 ? (
            <NothingYet
              title="No adapters"
              description="The backend did not report any submission adapters."
            />
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Adapter</Th>
                  <Th>Kind</Th>
                  <Th>Methods</Th>
                  <Th>Environments</Th>
                  <Th>Automatable</Th>
                  <Th>Enabled</Th>
                </tr>
              </thead>
              <tbody>
                {adapterItems.map((adapter: Adapter) => (
                  <tr key={adapter.id}>
                    <Td>
                      <p className="text-sm text-content">{adapter.name}</p>
                      <p className="text-xs text-content-subtle">
                        {adapter.key}
                      </p>
                    </Td>
                    <Td className="whitespace-nowrap text-xs">
                      {adapter.kind.replace(/_/g, " ")}
                    </Td>
                    <Td className="max-w-[220px] truncate text-xs">
                      {adapter.supported_methods.join(", ")}
                    </Td>
                    <Td>
                      <div className="flex flex-wrap gap-1">
                        {adapter.supported_environments.map((environment) => (
                          <Badge key={environment} tone="neutral">
                            {environment}
                          </Badge>
                        ))}
                      </div>
                    </Td>
                    <Td>
                      <Badge tone={adapter.automatable ? "success" : "neutral"}>
                        {adapter.automatable ? "Yes" : "No"}
                      </Badge>
                    </Td>
                    <Td>
                      <Badge tone={adapter.enabled ? "success" : "danger"}>
                        {adapter.enabled ? "Enabled" : "Disabled"}
                      </Badge>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
