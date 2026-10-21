import * as React from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Dialog,
  Field,
  Input,
  Select,
  StatusBadge,
  Table,
  Td,
  Th,
  useToast,
} from "@autobacklinker/ui";
import { api, apiClient } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import { ErrorBlock, LoadingBlock, NothingYet, PageHeader } from "../components/common";
import { formatDate, titleCase } from "../lib/format";
import { sendNativeNotification } from "../lib/backend";
import type { Adapter, IntegrationCredentialSummary } from "@autobacklinker/shared-types";

function errorText(error: unknown, fallback: string): string {
  if (error && typeof error === "object" && "message" in error) {
    return String((error as { message: unknown }).message);
  }
  return fallback;
}

function statusOf(error: unknown): number | null {
  if (error && typeof error === "object" && "status" in error) {
    const value = (error as { status: unknown }).status;
    return typeof value === "number" ? value : null;
  }
  return null;
}

export function IntegrationsPage() {
  const toast = useToast();
  const [provider, setProvider] = React.useState("");
  const [label, setLabel] = React.useState("");
  const [secret, setSecret] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [formError, setFormError] = React.useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = React.useState<IntegrationCredentialSummary | null>(
    null,
  );
  const [deleting, setDeleting] = React.useState(false);

  const providers = useAsync(() => api.integrations.providers(apiClient), []);
  const credentials = useAsync(() => api.integrations.credentials(apiClient), []);
  const adapters = useAsync(() => api.adapters.list(apiClient), []);

  const providerItems = providers.data ?? [];
  const credentialItems = credentials.data ?? [];
  const adapterItems = adapters.data ?? [];

  // The endpoint does not exist on older backends - then no credential can be
  // stored and nothing is simulated.
  const storageMissing =
    statusOf(credentials.error) === 404 || statusOf(credentials.error) === 405;

  async function save() {
    setFormError(null);
    if (!provider) {
      setFormError("Select a provider.");
      return;
    }
    if (!secret.trim()) {
      setFormError("A secret is required.");
      return;
    }

    setSaving(true);
    try {
      await api.integrations.saveCredential(apiClient, {
        provider,
        label: label.trim() || provider,
        secret: secret.trim(),
      });
      toast.push("Credential stored on the local backend", "success");
      void sendNativeNotification(
        "Auto Backlinker",
        `The credential for ${provider} was stored.`,
      );
      // The secret is never read back - it is dropped from the form.
      setSecret("");
      setLabel("");
      credentials.reload();
      providers.reload();
    } catch (err) {
      setFormError(errorText(err, "Could not store the credential"));
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await api.integrations.deleteCredential(apiClient, pendingDelete.id);
      toast.push("Credential deleted", "success");
      void sendNativeNotification(
        "Auto Backlinker",
        `The credential for ${pendingDelete.provider} was deleted.`,
      );
      setPendingDelete(null);
      credentials.reload();
      providers.reload();
    } catch (err) {
      toast.push(errorText(err, "Could not delete the credential"), "error");
    } finally {
      setDeleting(false);
    }
  }

  async function toggleAdapter(adapter: Adapter) {
    try {
      const updated = await api.adapters.update(apiClient, adapter.id, {
        enabled: !adapter.enabled,
      });
      toast.push(
        `${adapter.name} ${updated.enabled ? "enabled" : "disabled"}`,
        "success",
      );
      adapters.reload();
    } catch (err) {
      toast.push(errorText(err, "Could not update the adapter"), "error");
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Integrations"
        description="Provider credentials and the submission adapters of this installation."
        actions={
          <Button
            size="sm"
            variant="outline"
            loading={credentials.loading}
            onClick={credentials.reload}
          >
            Refresh
          </Button>
        }
      />

      {storageMissing ? (
        <Alert tone="warning" title="Credential storage is not available">
          The backend does not answer the credential endpoint, so no key can be
          stored on this machine. Nothing is simulated and no key is kept in the
          desktop app.
        </Alert>
      ) : null}

      <Card>
        <CardHeader
          title="Supported providers"
          description="What the local backend can use once the credential is stored"
        />
        <CardBody className="p-0">
          {providers.loading && !providers.data ? (
            <div className="p-4">
              <LoadingBlock rows={4} />
            </div>
          ) : providers.error ? (
            <div className="p-4">
              <ErrorBlock
                message={providers.error}
                onRetry={providers.reload}
              />
            </div>
          ) : providerItems.length === 0 ? (
            <NothingYet
              title="No providers known"
              description="The backend did not report any integration provider."
            />
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Provider</Th>
                  <Th>Purpose</Th>
                  <Th>Status</Th>
                  <Th>Key</Th>
                </tr>
              </thead>
              <tbody>
                {providerItems.map((item) => (
                  <tr key={item.key}>
                    <Td>
                      <p className="text-sm font-medium text-content">
                        {item.name}
                      </p>
                      <p className="text-xs text-content-subtle">{item.key}</p>
                    </Td>
                    <Td className="text-xs text-content-muted">
                      {item.purpose}
                    </Td>
                    <Td>
                      <StatusBadge
                        status={item.configured ? "CONFIGURED" : "MISSING"}
                      />
                    </Td>
                    <Td className="text-xs text-content-muted">
                      {item.configured ? "stored" : "not stored"}
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
            title="Credential"
            description="Secrets are encrypted by the backend and never sent back"
          />
          <CardBody>
            <div className="flex flex-col gap-3">
              <Field label="Provider" required>
                <Select
                  value={provider}
                  onChange={(event) => setProvider(event.target.value)}
                >
                  <option value="">Select provider…</option>
                  {providerItems.map((item) => (
                    <option key={item.key} value={item.key}>
                      {item.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Label" hint="Lets you store several keys of one provider">
                <Input
                  value={label}
                  onChange={(event) => setLabel(event.target.value)}
                  placeholder="Production key"
                />
              </Field>
              <Field label="Secret" required>
                <Input
                  type="password"
                  value={secret}
                  autoComplete="off"
                  onChange={(event) => setSecret(event.target.value)}
                  placeholder="••••••••••••"
                />
              </Field>

              {formError ? (
                <p className="text-xs text-danger">{formError}</p>
              ) : null}

              <div className="flex justify-end">
                <Button
                  loading={saving}
                  disabled={storageMissing || !provider || !secret.trim()}
                  onClick={save}
                >
                  Save credential
                </Button>
              </div>
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="Stored credentials"
            description="Only the masked hint is known to the client"
          />
          <CardBody className="p-0">
            {credentials.loading && !credentials.data ? (
              <div className="p-4">
                <LoadingBlock rows={3} />
              </div>
            ) : credentials.error ? (
              <div className="p-4">
                <ErrorBlock
                  message={credentials.error}
                  onRetry={credentials.reload}
                />
              </div>
            ) : credentialItems.length === 0 ? (
              <NothingYet
                title="No credentials stored"
                description="Save a provider key to use it for discovery or AI assistance."
              />
            ) : (
              <Table>
                <thead>
                  <tr>
                    <Th>Provider</Th>
                    <Th>Label</Th>
                    <Th>Hint</Th>
                    <Th>Status</Th>
                    <Th>Updated</Th>
                    <Th />
                  </tr>
                </thead>
                <tbody>
                  {credentialItems.map((credential) => (
                    <tr key={credential.id}>
                      <Td className="text-xs">{credential.provider}</Td>
                      <Td className="text-xs">{credential.label}</Td>
                      <Td className="font-mono text-xs text-content-muted">
                        {credential.masked_hint || "—"}
                      </Td>
                      <Td>
                        <StatusBadge status={credential.status} />
                      </Td>
                      <Td className="whitespace-nowrap text-xs text-content-muted">
                        {formatDate(credential.updated_at)}
                      </Td>
                      <Td className="text-right">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => setPendingDelete(credential)}
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
      </div>

      <Card>
        <CardHeader
          title="Submission adapters"
          description="How the platform submits backlinks on each site type"
        />
        <CardBody className="p-0">
          {adapters.loading && !adapters.data ? (
            <div className="p-4">
              <LoadingBlock rows={4} />
            </div>
          ) : adapters.error ? (
            <div className="p-4">
              <ErrorBlock message={adapters.error} onRetry={adapters.reload} />
            </div>
          ) : adapterItems.length === 0 ? (
            <NothingYet
              title="No adapters registered"
              description="The backend did not report any submission adapters."
            />
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Adapter</Th>
                  <Th>Kind</Th>
                  <Th>Registration</Th>
                  <Th>Approval</Th>
                  <Th>Automation</Th>
                  <Th>Requirements</Th>
                  <Th>Enabled</Th>
                </tr>
              </thead>
              <tbody>
                {adapterItems.map((adapter: Adapter) => (
                  <tr key={adapter.id}>
                    <Td>
                      <p className="text-sm font-medium text-content">
                        {adapter.name}
                      </p>
                      <p className="text-xs text-content-subtle">
                        {adapter.key}
                      </p>
                    </Td>
                    <Td>
                      <Badge tone="neutral">{titleCase(adapter.kind)}</Badge>
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
                    <Td className="max-w-[180px] truncate text-xs text-content-muted">
                      {adapter.required_user_fields?.length
                        ? adapter.required_user_fields.join(", ")
                        : "—"}
                    </Td>
                    <Td>
                      <Button
                        size="sm"
                        variant={adapter.enabled ? "outline" : "primary"}
                        onClick={() => void toggleAdapter(adapter)}
                      >
                        {adapter.enabled ? "Disable" : "Enable"}
                      </Button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </CardBody>
      </Card>

      <Dialog
        open={pendingDelete !== null}
        onClose={() => setPendingDelete(null)}
        title="Delete credential"
        description="The encrypted secret is removed from the local backend. This cannot be undone."
        footer={
          <>
            <Button variant="ghost" onClick={() => setPendingDelete(null)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              loading={deleting}
              onClick={remove}
            >
              Delete credential
            </Button>
          </>
        }
      >
        <p className="text-xs text-content-muted">
          {pendingDelete
            ? `${pendingDelete.provider} · ${pendingDelete.label}`
            : ""}
        </p>
      </Dialog>
    </div>
  );
}
