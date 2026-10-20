"use client";

import * as React from "react";
import { api } from "@autobacklinker/api-client";
import type { StorageMigrationPreview, StorageStatus } from "@autobacklinker/shared-types";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Field,
  Input,
  KeyValue,
  Table,
  Td,
  Th,
  useToast,
} from "@autobacklinker/ui";
import { apiClient, errorMessage } from "@/lib/api";
import { useAction, useResource } from "@/lib/hooks";
import { formatDateTime, formatNumber, humanize } from "@/lib/format";
import { STORAGE_MODE_LABELS } from "@/lib/constants";
import { ConfirmDialog } from "@/components/ConfirmDialog";

export function StoragePanel() {
  const toast = useToast();
  const action = useAction();

  const status = useResource(() => api.storage.status(apiClient), []);
  const history = useResource(() => api.storage.history(apiClient), []);
  const migration = useResource(() => api.storage.previewMigration(apiClient), []);

  const [databaseUrl, setDatabaseUrl] = React.useState("");
  const [label, setLabel] = React.useState("");
  const [testResult, setTestResult] = React.useState<{
    ok: boolean;
    message: string;
    dialect: string;
  } | null>(null);
  const [confirm, setConfirm] = React.useState<null | "migrate" | "disconnect" | "restore">(null);
  const [restorePath, setRestorePath] = React.useState("");

  const data: StorageStatus | null = status.data;

  const refreshAll = () => {
    status.reload();
    history.reload();
    migration.reload();
  };

  const test = async () => {
    const outcome = await action.run(() =>
      api.storage.test(apiClient, { database_url: databaseUrl.trim(), label: label.trim() || undefined }),
    );
    if (outcome.ok && outcome.data) {
      setTestResult(outcome.data);
      toast.push(
        outcome.data.ok ? "Connection test succeeded" : "Connection test failed",
        outcome.data.ok ? "success" : "error",
      );
    }
  };

  const connect = async () => {
    const outcome = await action.run(() =>
      api.storage.connect(apiClient, { database_url: databaseUrl.trim(), label: label.trim() || undefined }),
    );
    if (outcome.ok && outcome.data) {
      toast.push(
        `Connected in ${STORAGE_MODE_LABELS[outcome.data.mode] ?? outcome.data.mode} mode`,
        "success",
      );
      setDatabaseUrl("");
      refreshAll();
    }
  };

  const backup = async () => {
    const outcome = await action.run(() => api.storage.backup(apiClient));
    if (outcome.ok && outcome.data) {
      toast.push(`Backup created at ${outcome.data.path}`, "success");
      history.reload();
      status.reload();
    }
  };

  const restore = async () => {
    const outcome = await action.run(() =>
      api.storage.restore(apiClient, { path: restorePath.trim() || undefined }),
    );
    if (outcome.ok && outcome.data) {
      toast.push(
        outcome.data.restored ? "Backup restored" : "Restore did not complete",
        outcome.data.restored ? "success" : "error",
      );
      setConfirm(null);
      refreshAll();
    }
  };

  const migrate = async () => {
    const outcome = await action.run(() => api.storage.migrate(apiClient));
    if (outcome.ok) {
      toast.push("Migration finished", "success");
      setConfirm(null);
      refreshAll();
    }
  };

  const disconnect = async () => {
    const outcome = await action.run(() => api.storage.disconnect(apiClient));
    if (outcome.ok) {
      toast.push("Cloud connection closed", "success");
      setConfirm(null);
      refreshAll();
    }
  };

  const preview: StorageMigrationPreview | null = migration.data;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title="Database & storage"
          description="Where the workspace data lives and how it is synchronised"
          action={
            <Button variant="outline" size="sm" onClick={refreshAll} loading={status.refreshing}>
              Refresh
            </Button>
          }
        />
        <CardBody>
          {status.error && !data ? (
            <Alert tone="danger" title="Could not read the storage status">
              {errorMessage(status.error)}
            </Alert>
          ) : null}

          <div className="grid gap-4 lg:grid-cols-2">
            <div>
              <p className="mb-2 text-xs font-semibold text-content">Current connection</p>
              <KeyValue
                items={[
                  [
                    "Mode",
                    data ? (
                      <Badge tone={data.mode === "CLOUD" ? "accent" : data.mode === "HYBRID" ? "success" : "info"}>
                        {STORAGE_MODE_LABELS[data.mode] ?? data.mode}
                      </Badge>
                    ) : (
                      "—"
                    ),
                  ],
                  ["Database type", data?.database_type ?? "—"],
                  ["Database URL", data?.database_url_masked || "—"],
                  [
                    "Connection",
                    data ? (
                      <Badge tone={data.connected ? "success" : "danger"}>
                        {data.connected ? "Connected" : "Not connected"}
                      </Badge>
                    ) : (
                      "—"
                    ),
                  ],
                  [
                    "Cloud",
                    data ? (
                      <Badge tone={data.cloud_connected ? "success" : "neutral"}>
                        {data.cloud_connected ? "Linked" : "Not linked"}
                      </Badge>
                    ) : (
                      "—"
                    ),
                  ],
                  ["Schema version", data?.schema_version ?? "—"],
                  ["Last backup", formatDateTime(data?.last_backup_at)],
                  ["Pending sync changes", formatNumber(data?.pending_sync_changes)],
                  ["Conflicts", formatNumber(data?.conflicts)],
                ]}
              />
            </div>

            <div className="space-y-3">
              <Field
                label="Database URL"
                hint="PostgreSQL connection string, for example postgresql://user:pass@host/db"
              >
                <Input
                  type="password"
                  value={databaseUrl}
                  onChange={(event) => setDatabaseUrl(event.target.value)}
                  placeholder="postgresql://…"
                  autoComplete="off"
                />
              </Field>
              <Field label="Label" hint="Optional name for this connection">
                <Input
                  value={label}
                  onChange={(event) => setLabel(event.target.value)}
                  placeholder="Cloud production"
                />
              </Field>

              <div className="flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  onClick={test}
                  loading={action.pending}
                  disabled={!databaseUrl.trim()}
                  title={!databaseUrl.trim() ? "Enter a database URL first" : undefined}
                >
                  Test connection
                </Button>
                <Button
                  onClick={connect}
                  loading={action.pending}
                  disabled={!databaseUrl.trim()}
                  title={!databaseUrl.trim() ? "Enter a database URL first" : undefined}
                >
                  Connect cloud
                </Button>
                <Button variant="outline" onClick={backup} loading={action.pending}>
                  Create backup
                </Button>
                <Button
                  variant="outline"
                  onClick={() => setConfirm("restore")}
                  title="Restores the latest backup known to the backend"
                >
                  Restore backup
                </Button>
                <Button
                  variant="danger"
                  onClick={() => setConfirm("disconnect")}
                  disabled={!data?.cloud_connected}
                  title={
                    !data?.cloud_connected
                      ? "No cloud database is connected"
                      : "Close the cloud connection"
                  }
                >
                  Disconnect
                </Button>
              </div>

              {testResult ? (
                <Alert tone={testResult.ok ? "success" : "danger"} title="Connection test">
                  <p>{testResult.message}</p>
                  <p className="mt-1 text-[11px]">Dialect: {testResult.dialect || "—"}</p>
                </Alert>
              ) : null}

              {action.error ? (
                <Alert tone="danger" title="Storage action failed">
                  {errorMessage(action.error)}
                </Alert>
              ) : null}
            </div>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Migrate local data"
          description="Copy the local workspace into the connected cloud database"
          action={
            <Button
              variant="outline"
              size="sm"
              onClick={migration.reload}
              loading={migration.refreshing}
            >
              Refresh preview
            </Button>
          }
        />
        <CardBody>
          {migration.loading && !preview ? (
            <p className="text-xs text-content-subtle">Loading migration preview…</p>
          ) : migration.error ? (
            <Alert tone="danger" title="Could not build the migration preview">
              {errorMessage(migration.error)}
            </Alert>
          ) : preview ? (
            <div className="space-y-3">
              <div className="grid gap-x-6 gap-y-2 text-xs sm:grid-cols-3">
                <div>
                  <p className="text-content-muted">Projects</p>
                  <p className="text-content">{formatNumber(preview.projects)}</p>
                </div>
                <div>
                  <p className="text-content-muted">Opportunities</p>
                  <p className="text-content">{formatNumber(preview.opportunities)}</p>
                </div>
                <div>
                  <p className="text-content-muted">Tasks</p>
                  <p className="text-content">{formatNumber(preview.tasks)}</p>
                </div>
                <div>
                  <p className="text-content-muted">Backlink records</p>
                  <p className="text-content">{formatNumber(preview.backlink_records)}</p>
                </div>
                <div>
                  <p className="text-content-muted">Profiles</p>
                  <p className="text-content">{formatNumber(preview.profiles)}</p>
                </div>
                <div>
                  <p className="text-content-muted">Duplicates</p>
                  <p className="text-content">{formatNumber(preview.duplicates)}</p>
                </div>
                <div>
                  <p className="text-content-muted">Conflicts</p>
                  <p className="text-content">{formatNumber(preview.conflicts)}</p>
                </div>
                <div>
                  <p className="text-content-muted">Compatible</p>
                  <p className="text-content">
                    {preview.compatible ? "Yes" : "No"}
                  </p>
                </div>
              </div>

              {preview.notes.length > 0 ? (
                <ul className="list-inside list-disc space-y-0.5 text-xs text-content-muted">
                  {preview.notes.map((note, index) => (
                    <li key={`${note}-${index}`}>{note}</li>
                  ))}
                </ul>
              ) : null}

              <Button
                onClick={() => setConfirm("migrate")}
                disabled={!preview.compatible}
                title={
                  !preview.compatible
                    ? "The backend reports that this migration is not compatible"
                    : "Run the migration"
                }
              >
                Run migration
              </Button>
            </div>
          ) : (
            <p className="text-xs text-content-subtle">No migration preview available.</p>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Storage history" description="Backups and connection events" />
        <CardBody className="p-0">
          {history.loading && !history.data ? (
            <p className="px-4 py-4 text-xs text-content-subtle">Loading history…</p>
          ) : history.error ? (
            <div className="p-4">
              <Alert tone="danger" title="Could not load the storage history">
                {errorMessage(history.error)}
              </Alert>
            </div>
          ) : (history.data ?? []).length === 0 ? (
            <p className="px-4 py-6 text-center text-xs text-content-subtle">
              The backend did not report any storage history.
            </p>
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Event</Th>
                  <Th>Detail</Th>
                  <Th className="w-44">When</Th>
                </tr>
              </thead>
              <tbody>
                {(history.data ?? []).map((entry, index) => {
                  const record = entry as Record<string, unknown>;
                  const when =
                    (record.created_at as string) ??
                    (record.timestamp as string) ??
                    (record.at as string) ??
                    null;
                  return (
                    <tr key={index}>
                      <Td className="text-xs">
                        {humanize(
                          (record.action as string) ??
                            (record.event as string) ??
                            (record.type as string) ??
                            "event",
                        )}
                      </Td>
                      <Td className="text-xs text-content-muted">
                        {Object.entries(record)
                          .filter(
                            ([key]) =>
                              key !== "created_at" && key !== "timestamp" && key !== "at" &&
                              key !== "action" && key !== "event" && key !== "type",
                          )
                          .map(([key, value]) => `${key}: ${String(value)}`)
                          .join(" · ") || "—"}
                      </Td>
                      <Td className="text-xs text-content-muted">{formatDateTime(when)}</Td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
          )}
        </CardBody>
      </Card>

      <ConfirmDialog
        open={confirm === "migrate"}
        title="Run the migration?"
        description="Local workspace data will be copied into the connected cloud database."
        confirmLabel="Run migration"
        destructive
        pending={action.pending}
        onClose={() => setConfirm(null)}
        onConfirm={migrate}
      />

      <ConfirmDialog
        open={confirm === "disconnect"}
        title="Disconnect the cloud database?"
        description="The workspace falls back to the local database. Synced changes stay in the local storage."
        confirmLabel="Disconnect"
        destructive
        pending={action.pending}
        onClose={() => setConfirm(null)}
        onConfirm={disconnect}
      />

      <ConfirmDialog
        open={confirm === "restore"}
        title="Restore from a backup?"
        description="The current local database is replaced by the selected backup."
        confirmLabel="Restore"
        destructive
        pending={action.pending}
        onClose={() => setConfirm(null)}
        onConfirm={restore}
      >
        <Field label="Backup path" hint="Leave empty to restore the latest backup.">
          <Input
            value={restorePath}
            onChange={(event) => setRestorePath(event.target.value)}
            placeholder="/path/to/backup.sqlite"
          />
        </Field>
      </ConfirmDialog>
    </div>
  );
}
