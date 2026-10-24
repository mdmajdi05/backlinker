"use client";

import * as React from "react";
import { api } from "@autobacklinker/api-client";
import type { Adapter, IntegrationCredential } from "@autobacklinker/shared-types";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Field,
  Input,
  Select,
  StatusBadge,
  Table,
  Td,
  Th,
  useToast,
} from "@autobacklinker/ui";
import { apiClient, errorMessage } from "@/lib/api";
import { useAction, useResource } from "@/lib/hooks";
import {
  AI_PROVIDER_KEYS,
  deleteCredential,
  isKeylessAiProvider,
  loadCredentials,
  loadProviders,
  saveCredential,
} from "@/lib/integrations";
import type { IntegrationProvider } from "@/lib/integrations";
import { humanize } from "@/lib/format";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { AsyncSection, TableSkeleton } from "@/components/States";

interface CredentialRow {
  provider: string;
  label: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

const EMPTY_ROW: CredentialRow = {
  provider: "",
  label: "",
  apiKey: "",
  model: "",
  baseUrl: "",
};

export default function IntegrationsPage() {
  const toast = useToast();
  const action = useAction();

  const adapters = useResource(() => api.adapters.list(apiClient), []);
  const credentials = useResource(() => loadCredentials(), []);
  const providers = useResource(() => loadProviders(), []);

  const [row, setRow] = React.useState<CredentialRow>(EMPTY_ROW);
  const [aiRow, setAiRow] = React.useState<CredentialRow>({ ...EMPTY_ROW, provider: "openai" });
  const [credentialError, setCredentialError] = React.useState<string | null>(null);
  const [aiError, setAiError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState<"credential" | "ai" | null>(null);
  const [deleteTarget, setDeleteTarget] = React.useState<IntegrationCredential | null>(null);

  const credentialProviders = React.useMemo(() => {
    const keys = new Set<string>();
    for (const adapter of adapters.data ?? []) {
      for (const field of adapter.required_user_fields ?? []) {
        keys.add(field);
      }
    }
    return Array.from(keys).sort();
  }, [adapters.data]);

  const refreshCredentials = () => {
    credentials.reload();
    providers.reload();
  };

  const keylessAi = isKeylessAiProvider(aiRow.provider);

  const save = async (target: CredentialRow, isAi: boolean) => {
    const setError = isAi ? setAiError : setCredentialError;
    setError(null);
    if (!target.provider.trim()) {
      setError("A provider key is required.");
      return;
    }
    const keyless = isKeylessAiProvider(target.provider);
    if (keyless && !target.model.trim()) {
      setError("A model is required for local AI providers (no API key is needed).");
      return;
    }
    if (!keyless && !target.apiKey.trim()) {
      setError("An API key is required.");
      return;
    }
    setSaving(isAi ? "ai" : "credential");
    try {
      await saveCredential({
        provider: target.provider.trim(),
        label: target.label.trim() || target.provider.trim(),
        // Local providers are saved with an empty secret; the model is what
        // makes the credential usable.
        apiKey: target.apiKey.trim(),
        model: target.model.trim() || undefined,
        baseUrl: target.baseUrl.trim() || undefined,
      });
      toast.push(isAi ? "AI configuration saved" : "Credential saved", "success");
      if (isAi) {
        setAiRow((prev) => ({ ...prev, apiKey: "", model: "", baseUrl: "" }));
      } else {
        setRow(EMPTY_ROW);
      }
      refreshCredentials();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(null);
    }
  };

  const remove = async () => {
    if (!deleteTarget) return;
    const outcome = await action.run(() => deleteCredential(deleteTarget.id));
    if (outcome.ok) {
      toast.push(`Credential for ${deleteTarget.provider} deleted`, "success");
      setDeleteTarget(null);
      refreshCredentials();
    } else {
      toast.push(errorMessage(outcome.error), "error");
    }
  };

  const toggleAdapter = async (adapter: Adapter) => {
    const outcome = await action.run(() =>
      api.adapters.update(apiClient, adapter.id, { enabled: !adapter.enabled }),
    );
    if (outcome.ok && outcome.data) {
      toast.push(
        `${adapter.name} ${outcome.data.enabled ? "enabled" : "disabled"}`,
        "success",
      );
      adapters.reload();
    }
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Integrations"
        description="Submission adapters, credential providers and AI configuration."
        actions={
          <Button variant="outline" size="sm" onClick={adapters.reload} loading={adapters.refreshing}>
            Refresh
          </Button>
        }
      />

      <Card>
        <CardHeader
          title="Supported providers"
          description="What the platform can use once the credential is stored"
          action={
            providers.error ? (
              <Button
                variant="outline"
                size="sm"
                onClick={providers.reload}
                loading={providers.refreshing}
              >
                Retry
              </Button>
            ) : null
          }
        />
        <CardBody className="p-0">
          {providers.error ? (
            <div className="p-4">
              <Alert tone="danger" title="Could not load supported providers">
                {errorMessage(providers.error)}
              </Alert>
            </div>
          ) : providers.loading ? (
            <TableSkeleton rows={4} columns={4} />
          ) : (providers.data ?? []).length === 0 ? (
            <p className="px-4 py-6 text-center text-xs text-content-subtle">
              No providers reported.
            </p>
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Provider</Th>
                  <Th>Purpose</Th>
                  <Th>Status</Th>
                  <Th>Documentation</Th>
                </tr>
              </thead>
              <tbody>
                {(providers.data ?? []).map((provider: IntegrationProvider) => (
                  <tr key={provider.key}>
                    <Td className="font-medium text-content">{provider.name}</Td>
                    <Td className="text-content-muted">{provider.purpose}</Td>
                    <Td>
                      <StatusBadge status={provider.configured ? "CONFIGURED" : "MISSING"} />
                    </Td>
                    <Td>
                      {provider.docs ? (
                        <a
                          href={provider.docs}
                          target="_blank"
                          rel="noreferrer noopener"
                          className="text-accent underline-offset-2 hover:underline"
                        >
                          Docs
                        </a>
                      ) : (
                        <span className="text-content-subtle">—</span>
                      )}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Stored credentials"
          description="Credentials saved for this workspace"
          action={
            credentials.error ? (
              <Button
                variant="outline"
                size="sm"
                onClick={credentials.reload}
                loading={credentials.refreshing}
              >
                Retry
              </Button>
            ) : null
          }
        />
        <CardBody className="p-0">
          {credentials.error ? (
            <div className="p-4">
              <Alert tone="danger" title="Could not load stored credentials">
                {errorMessage(credentials.error)}
              </Alert>
            </div>
          ) : credentials.loading ? (
            <TableSkeleton rows={3} columns={4} />
          ) : (credentials.data ?? []).length === 0 ? (
            <p className="px-4 py-6 text-center text-xs text-content-subtle">
              No credentials saved yet.
            </p>
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Provider</Th>
                  <Th>Label</Th>
                  <Th className="w-40">Status</Th>
                  <Th className="w-24">Actions</Th>
                </tr>
              </thead>
              <tbody>
                {(credentials.data ?? []).map((credential) => (
                  <tr key={credential.id}>
                    <Td>{credential.provider}</Td>
                    <Td>{credential.label}</Td>
                    <Td>
                      <StatusBadge status={credential.status} />
                    </Td>
                    <Td>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setDeleteTarget(credential)}
                      >
                        Delete
                      </Button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </CardBody>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="Credential providers"
            description="API keys for discovery providers and submission adapters"
          />
          <CardBody>
            <div className="space-y-3">
              <Field label="Provider" required>
                <Input
                  value={row.provider}
                  onChange={(event) => setRow((prev) => ({ ...prev, provider: event.target.value }))}
                  placeholder="dataforseo"
                  list="credential-providers"
                />
                <datalist id="credential-providers">
                  {credentialProviders.map((provider) => (
                    <option key={provider} value={provider} />
                  ))}
                </datalist>
              </Field>
              <Field label="Label">
                <Input
                  value={row.label}
                  onChange={(event) => setRow((prev) => ({ ...prev, label: event.target.value }))}
                  placeholder="Production key"
                />
              </Field>
              <Field label="API key" required>
                <Input
                  type="password"
                  value={row.apiKey}
                  onChange={(event) => setRow((prev) => ({ ...prev, apiKey: event.target.value }))}
                  placeholder="••••••••••••"
                  autoComplete="off"
                />
              </Field>

              {credentialError ? <p className="text-xs text-danger">{credentialError}</p> : null}

              <div className="flex justify-end">
                <Button
                  onClick={() => save(row, false)}
                  loading={saving === "credential"}
                >
                  Save credential
                </Button>
              </div>
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="AI provider"
            description="Model used for scoring, anchors and content generation"
          />
          <CardBody>
            <div className="space-y-3">
              <Field label="Provider" required>
                <Select
                  value={aiRow.provider}
                  onChange={(event) => setAiRow((prev) => ({ ...prev, provider: event.target.value }))}
                >
                  {AI_PROVIDER_KEYS.map((provider) => (
                    <option key={provider} value={provider}>
                      {humanize(provider)}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field
                label="Model"
                required={keylessAi}
                hint={
                  keylessAi
                    ? "Required for local providers, for example llama3.1"
                    : "For example gpt-4o-mini or claude-3-5-sonnet"
                }
              >
                <Input
                  value={aiRow.model}
                  onChange={(event) => setAiRow((prev) => ({ ...prev, model: event.target.value }))}
                  placeholder={keylessAi ? "llama3.1" : "gpt-4o-mini"}
                />
              </Field>
              {keylessAi ? (
                <Field
                  label="Base URL"
                  hint="Optional. Leave empty for the default: Ollama uses :11434, LM Studio and local servers use :1234/v1."
                >
                  <Input
                    value={aiRow.baseUrl}
                    onChange={(event) =>
                      setAiRow((prev) => ({ ...prev, baseUrl: event.target.value }))
                    }
                    placeholder="http://localhost:11434/v1"
                  />
                </Field>
              ) : null}
              <Field
                label="API key"
                required={!keylessAi}
                hint={
                  keylessAi
                    ? "Not required: Ollama, LM Studio and local servers run without a key."
                    : undefined
                }
              >
                <Input
                  type="password"
                  value={aiRow.apiKey}
                  onChange={(event) => setAiRow((prev) => ({ ...prev, apiKey: event.target.value }))}
                  placeholder={keylessAi ? "No key needed" : "••••••••••••"}
                  autoComplete="off"
                />
              </Field>

              {aiError ? <p className="text-xs text-danger">{aiError}</p> : null}

              <div className="flex justify-end">
                <Button onClick={() => save(aiRow, true)} loading={saving === "ai"}>
                  Save AI configuration
                </Button>
              </div>
              <p className="text-[11px] text-content-subtle">
                The backend reports which AI features are available through the adapter list below.
              </p>
            </div>
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader
          title="Submission adapters"
          description="How the platform submits backlinks on each site type"
        />
        <CardBody className="p-0">
          <AsyncSection
            loading={adapters.loading}
            error={adapters.error}
            data={adapters.data}
            onRetry={adapters.reload}
            isEmpty={(adapters.data ?? []).length === 0}
            emptyTitle="No adapters registered"
            emptyDescription="The backend did not report any submission adapters."
            skeleton={<TableSkeleton rows={6} columns={6} />}
          >
            <Table>
              <thead>
                <tr>
                  <Th>Adapter</Th>
                  <Th className="w-36">Kind</Th>
                  <Th className="w-28">Registration</Th>
                  <Th className="w-28">Approval</Th>
                  <Th className="w-28">Automation</Th>
                  <Th>Requirements</Th>
                  <Th className="w-28">Enabled</Th>
                </tr>
              </thead>
              <tbody>
                {(adapters.data ?? []).map((adapter) => (
                  <tr key={adapter.id}>
                    <Td>
                      <p className="font-medium text-content">{adapter.name}</p>
                      <p className="text-xs text-content-muted">{adapter.key}</p>
                      {adapter.description ? (
                        <p className="mt-0.5 max-w-sm text-xs text-content-subtle">
                          {adapter.description}
                        </p>
                      ) : null}
                    </Td>
                    <Td>
                      <Badge tone="neutral">{humanize(adapter.kind)}</Badge>
                    </Td>
                    <Td className="text-xs">
                      {adapter.registration_required ? "Required" : "Not required"}
                    </Td>
                    <Td className="text-xs">
                      {adapter.manual_approval_required ? "Manual" : "Automatic"}
                    </Td>
                    <Td className="text-xs">
                      {adapter.automatable ? "Automatable" : "Manual only"}
                    </Td>
                    <Td className="text-xs text-content-muted">
                      {adapter.required_user_fields?.length
                        ? adapter.required_user_fields.join(", ")
                        : "—"}
                    </Td>
                    <Td>
                      <Button
                        size="sm"
                        variant={adapter.enabled ? "outline" : "primary"}
                        onClick={() => toggleAdapter(adapter)}
                        loading={action.pending}
                      >
                        {adapter.enabled ? "Disable" : "Enable"}
                      </Button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </AsyncSection>
        </CardBody>
      </Card>

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete this credential?"
        description={
          deleteTarget
            ? `The stored ${deleteTarget.provider} credential "${deleteTarget.label}" will be removed.`
            : undefined
        }
        confirmLabel="Delete credential"
        destructive
        pending={action.pending}
        onClose={() => setDeleteTarget(null)}
        onConfirm={remove}
      />
    </div>
  );
}
