"use client";

import * as React from "react";
import { api } from "@autobacklinker/api-client";
import type { Adapter } from "@autobacklinker/shared-types";
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
import { AI_PROVIDER_KEYS, probeCredentials, saveCredential } from "@/lib/integrations";
import type { IntegrationProvider } from "@/lib/integrations";
import { humanize } from "@/lib/format";
import { PageHeader } from "@/components/PageHeader";
import { AsyncSection, TableSkeleton } from "@/components/States";

interface CredentialRow {
  provider: string;
  label: string;
  apiKey: string;
  model: string;
}

const EMPTY_ROW: CredentialRow = { provider: "", label: "", apiKey: "", model: "" };

export default function IntegrationsPage() {
  const toast = useToast();
  const action = useAction();

  const adapters = useResource(() => api.adapters.list(apiClient), []);
  const [probe, setProbe] = React.useState<{
    available: boolean;
    checked: boolean;
    credentials: Array<{ id: string; provider: string; label: string; status: string }>;
    providers: IntegrationProvider[];
  }>({ available: false, checked: false, credentials: [], providers: [] });

  const [row, setRow] = React.useState<CredentialRow>(EMPTY_ROW);
  const [aiRow, setAiRow] = React.useState<CredentialRow>({ ...EMPTY_ROW, provider: "openai" });
  const [providerError, setProviderError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    void probeCredentials().then((result) => {
      if (cancelled) return;
      setProbe({
        available: result.available,
        checked: true,
        credentials: result.credentials.map((credential) => ({
          id: credential.id,
          provider: credential.provider,
          label: credential.label,
          status: credential.status,
        })),
        providers: result.providers,
      });
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const credentialProviders = React.useMemo(() => {
    const keys = new Set<string>();
    for (const adapter of adapters.data ?? []) {
      for (const field of adapter.required_user_fields ?? []) {
        keys.add(field);
      }
    }
    return Array.from(keys).sort();
  }, [adapters.data]);

  const save = async (target: CredentialRow, isAi: boolean) => {
    setProviderError(null);
    if (!target.provider.trim()) {
      setProviderError("A provider key is required.");
      return;
    }
    if (!target.apiKey.trim()) {
      setProviderError("An API key is required.");
      return;
    }
    try {
      await saveCredential({
        provider: target.provider.trim(),
        label: target.label.trim() || target.provider.trim(),
        apiKey: target.apiKey.trim(),
        model: target.model.trim() || undefined,
      });
      toast.push(
        isAi ? "AI provider configuration saved" : "Credential saved on the backend",
        "success",
      );
      setRow(EMPTY_ROW);
      const refreshed = await probeCredentials();
      setProbe((prev) => ({
        ...prev,
        available: refreshed.available,
        credentials: refreshed.credentials,
        providers: refreshed.providers,
      }));
    } catch (err) {
      setProviderError(errorMessage(err));
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

  const credentialUnavailableReason = probe.checked && !probe.available
    ? "The backend does not expose a credential storage endpoint yet, so keys cannot be saved from the browser."
    : null;

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

      {credentialUnavailableReason ? (
        <Alert tone="warning" title="Credential storage is not available">
          {credentialUnavailableReason} The backend did not answer the credential endpoint, so
          nothing is stored locally and no success is simulated.
        </Alert>
      ) : null}

      {probe.providers.length > 0 ? (
        <Card>
          <CardHeader
            title="Supported providers"
            description="What the backend can use once the credential is stored"
          />
          <CardBody className="p-0">
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
                {probe.providers.map((provider) => (
                  <tr key={provider.key}>
                    <Td className="font-medium text-content">{provider.name}</Td>
                    <Td className="text-content-muted">{provider.purpose}</Td>
                    <Td>
                      <StatusBadge status={provider.configured ? "CONFIGURED" : "MISSING"} />
                    </Td>
                    <Td>
                      <a
                        href={provider.docs}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="text-accent underline-offset-2 hover:underline"
                      >
                        Docs
                      </a>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </CardBody>
        </Card>
      ) : null}

      {probe.available ? (
        <Card>
          <CardHeader title="Stored credentials" description="Credentials known to the backend" />
          <CardBody className="p-0">
            {probe.credentials.length === 0 ? (
              <p className="px-4 py-6 text-center text-xs text-content-subtle">
                No credentials stored on the backend yet.
              </p>
            ) : (
              <Table>
                <thead>
                  <tr>
                    <Th>Provider</Th>
                    <Th>Label</Th>
                    <Th className="w-40">Status</Th>
                  </tr>
                </thead>
                <tbody>
                  {probe.credentials.map((credential) => (
                    <tr key={credential.id}>
                      <Td>{credential.provider}</Td>
                      <Td>{credential.label}</Td>
                      <Td>
                        <StatusBadge status={credential.status} />
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </CardBody>
        </Card>
      ) : null}

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

              {providerError ? <p className="text-xs text-danger">{providerError}</p> : null}

              <div className="flex justify-end">
                <Button
                  onClick={() => save(row, false)}
                  disabled={Boolean(credentialUnavailableReason)}
                  title={credentialUnavailableReason ?? "Store the credential on the backend"}
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
              <Field label="Model" hint="For example gpt-4o-mini or claude-3-5-sonnet">
                <Input
                  value={aiRow.model}
                  onChange={(event) => setAiRow((prev) => ({ ...prev, model: event.target.value }))}
                  placeholder="gpt-4o-mini"
                />
              </Field>
              <Field label="API key" required>
                <Input
                  type="password"
                  value={aiRow.apiKey}
                  onChange={(event) => setAiRow((prev) => ({ ...prev, apiKey: event.target.value }))}
                  placeholder="••••••••••••"
                  autoComplete="off"
                />
              </Field>

              <div className="flex justify-end">
                <Button
                  onClick={() => save(aiRow, true)}
                  disabled={Boolean(credentialUnavailableReason)}
                  title={credentialUnavailableReason ?? "Store the AI configuration on the backend"}
                >
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
    </div>
  );
}
