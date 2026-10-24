"use client";

import * as React from "react";
import { api } from "@autobacklinker/api-client";
import type { StorageStatus } from "@autobacklinker/shared-types";
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
import { formatDateTime, humanize } from "@/lib/format";
import { STORAGE_MODE_LABELS } from "@/lib/constants";
import { ConfirmDialog } from "@/components/ConfirmDialog";

export function StoragePanel() {
  const toast = useToast();
  const action = useAction();

  const status = useResource(() => api.storage.status(apiClient), []);
  const history = useResource(() => api.storage.history(apiClient), []);

  const [confirm, setConfirm] = React.useState<null | "restore">(null);
  const [restorePath, setRestorePath] = React.useState("");

  const data: StorageStatus | null = status.data;

  const refreshAll = () => {
    status.reload();
    history.reload();
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

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title="Database & storage"
          description="Where the workspace data lives."
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
                  ["Schema version", data?.schema_version ?? "—"],
                  ["Last backup", formatDateTime(data?.last_backup_at)],
                ]}
              />
            </div>

            <div className="space-y-3">
              <p className="text-xs text-content-muted">
                Backups are written next to the local database. Restoring replaces the
                current local database with the selected backup.
              </p>

              <div className="flex flex-wrap gap-2">
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
              </div>

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
        <CardHeader title="Storage history" description="Backups and storage events" />
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
