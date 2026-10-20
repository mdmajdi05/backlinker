import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  KeyValue,
  StatusBadge,
  Table,
  Td,
  Th,
} from "@autobacklinker/ui";
import { api, apiClient } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import { ErrorBlock, LoadingBlock, NothingYet, PageHeader } from "../components/common";
import { formatDate, formatRelative } from "../lib/format";
import { useBackend } from "../lib/backendState";
import { openPath } from "../lib/backend";
import type { Device } from "@autobacklinker/shared-types";

export function DevicesPage() {
  const { agent, refreshAgent, status } = useBackend();
  const devices = useAsync(() => api.devices.list(apiClient), []);

  const items = devices.data ?? [];

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Devices"
        description="Registered devices and the local automation agent of this machine."
      />

      <Card>
        <CardHeader
          title="Local agent"
          description="The agent claims LOCAL tasks and executes them on this device."
          action={
            <Button size="sm" variant="outline" onClick={refreshAgent}>
              Refresh
            </Button>
          }
        />
        <CardBody>
          {status ? (
            <KeyValue
              items={[
                [
                  "Agent configuration",
                  agent?.registered ? (
                    <span className="text-success">registered</span>
                  ) : (
                    <span className="text-content-muted">not registered</span>
                  ),
                ],
                ["Device id", agent?.deviceId ?? "-"],
                ["Configuration file", agent?.configPath ?? "-"],
                ["Log file", agent?.logPath ?? "-"],
                [
                  "Last heartbeat",
                  agent?.lastSeen ? formatRelative(agent.lastSeen) : "-",
                ],
                ["Backend", status.baseUrl],
              ]}
            />
          ) : (
            <p className="text-xs text-content-muted">
              The agent status is only available in the desktop build.
            </p>
          )}
          <p className="mt-3 text-xs text-content-subtle">
            Register the agent with{" "}
            <code className="rounded bg-surface-sunken px-1 py-0.5">
              python -m agent --register --server-url &lt;backend-url&gt;
            </code>{" "}
            inside <code className="rounded bg-surface-sunken px-1 py-0.5">apps/local-agent</code>.
          </p>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Registered devices"
          description={`${items.length} devices known to the backend`}
        />
        <CardBody className="p-0">
          {devices.loading && !devices.data ? (
            <div className="p-4">
              <LoadingBlock rows={3} />
            </div>
          ) : devices.error ? (
            <div className="p-4">
              <ErrorBlock message={devices.error} onRetry={devices.reload} />
            </div>
          ) : items.length === 0 ? (
            <NothingYet
              title="No devices"
              description="No device has registered with this backend yet."
            />
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Name</Th>
                  <Th>Platform</Th>
                  <Th>Status</Th>
                  <Th>Capabilities</Th>
                  <Th>Version</Th>
                  <Th>Last seen</Th>
                  <Th>Created</Th>
                </tr>
              </thead>
              <tbody>
                {items.map((device: Device) => (
                  <tr key={device.id}>
                    <Td className="text-sm">{device.name}</Td>
                    <Td className="text-xs">{device.platform}</Td>
                    <Td>
                      <StatusBadge status={device.status} />
                    </Td>
                    <Td>
                      <div className="flex flex-wrap gap-1">
                        {device.capabilities.map((capability) => (
                          <Badge key={capability} tone="neutral">
                            {capability}
                          </Badge>
                        ))}
                      </div>
                    </Td>
                    <Td className="text-xs">{device.version ?? "-"}</Td>
                    <Td className="whitespace-nowrap text-xs text-content-muted">
                      {formatDate(device.last_seen_at)}
                    </Td>
                    <Td className="whitespace-nowrap text-xs text-content-muted">
                      {formatDate(device.created_at)}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </CardBody>
      </Card>

      {agent?.logPath ? (
        <Card>
          <CardHeader title="Agent log" />
          <CardBody>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                void openPath(agent.logPath).catch(() => undefined);
              }}
            >
              Open log file
            </Button>
          </CardBody>
        </Card>
      ) : null}
    </div>
  );
}
