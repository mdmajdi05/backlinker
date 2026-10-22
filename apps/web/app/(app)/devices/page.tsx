"use client";

import * as React from "react";
import { api } from "@autobacklinker/api-client";
import type { Device } from "@autobacklinker/shared-types";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  StatusBadge,
  Table,
  Td,
  Th,
  useToast,
} from "@autobacklinker/ui";
import { apiClient, errorMessage } from "@/lib/api";
import { useAction, useResource } from "@/lib/hooks";
import { formatDateTime, formatRelative } from "@/lib/format";
import { PageHeader } from "@/components/PageHeader";
import { AsyncSection, TableSkeleton } from "@/components/States";
import { ConfirmDialog } from "@/components/ConfirmDialog";

export default function DevicesPage() {
  const toast = useToast();
  const action = useAction();
  const [revokeTarget, setRevokeTarget] = React.useState<Device | null>(null);

  const devices = useResource(() => api.devices.list(apiClient), []);

  const revoke = async () => {
    if (!revokeTarget) return;
    const outcome = await action.run(() => api.devices.revoke(apiClient, revokeTarget.id));
    if (outcome.ok) {
      toast.push(`Device ${revokeTarget.name} revoked`, "success");
      setRevokeTarget(null);
      devices.reload();
    }
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Devices"
        description="Local agents and browsers that are allowed to execute tasks."
        actions={
          <Button variant="outline" size="sm" onClick={devices.reload} loading={devices.refreshing}>
            Refresh
          </Button>
        }
      />

      <Card>
        <CardHeader title="Registered devices" description="Agents with access to this workspace" />
        <CardBody className="p-0">
          <AsyncSection
            loading={devices.loading}
            error={devices.error}
            data={devices.data}
            onRetry={devices.reload}
            isEmpty={(devices.data ?? []).length === 0}
            emptyTitle="No devices registered"
            emptyDescription="Local agents and desktop clients appear here once they register with the backend."
            skeleton={<TableSkeleton rows={5} columns={5} />}
          >
            <Table>
              <thead>
                <tr>
                  <Th>Device</Th>
                  <Th className="w-36">Platform</Th>
                  <Th className="w-32">Status</Th>
                  <Th className="w-44">Last seen</Th>
                  <Th>Capabilities</Th>
                  <Th className="w-28">Revoke</Th>
                </tr>
              </thead>
              <tbody>
                {(devices.data ?? []).map((device) => (
                  <tr key={device.id}>
                    <Td>
                      <p className="font-medium text-content">{device.name}</p>
                      <p className="text-xs text-content-muted">{device.id}</p>
                      {device.version ? (
                        <p className="text-xs text-content-subtle">v{device.version}</p>
                      ) : null}
                    </Td>
                    <Td className="text-xs">{device.platform}</Td>
                    <Td>
                      <StatusBadge status={device.status} />
                    </Td>
                    <Td className="text-xs text-content-muted">
                      {device.last_seen_at ? (
                        <span title={formatDateTime(device.last_seen_at)}>
                          {formatRelative(device.last_seen_at)}
                        </span>
                      ) : (
                        "—"
                      )}
                    </Td>
                    <Td>
                      <div className="flex flex-wrap gap-1">
                        {(device.capabilities ?? []).length === 0 ? (
                          <span className="text-xs text-content-subtle">None reported</span>
                        ) : (
                          device.capabilities.map((capability) => (
                            <Badge key={capability} tone="neutral">
                              {capability}
                            </Badge>
                          ))
                        )}
                      </div>
                    </Td>
                    <Td>
                      <Button
                        size="sm"
                        variant="danger"
                        disabled={device.status === "DISABLED"}
                        onClick={() => setRevokeTarget(device)}
                        title={
                          device.status === "DISABLED"
                            ? "This device is already revoked"
                            : "Revoke this device"
                        }
                      >
                        Revoke
                      </Button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </AsyncSection>
        </CardBody>
      </Card>

      {action.error ? (
        <p className="text-xs text-danger">{errorMessage(action.error)}</p>
      ) : null}

      <ConfirmDialog
        open={revokeTarget !== null}
        title="Revoke this device?"
        description={
          revokeTarget
            ? `${revokeTarget.name} will no longer be able to execute tasks for this workspace.`
            : undefined
        }
        confirmLabel="Revoke device"
        destructive
        pending={action.pending}
        onClose={() => setRevokeTarget(null)}
        onConfirm={revoke}
      />
    </div>
  );
}
