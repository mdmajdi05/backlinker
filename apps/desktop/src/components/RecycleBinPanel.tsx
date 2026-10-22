import * as React from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  Dialog,
  Pagination,
  Skeleton,
  Table,
  Tabs,
  Td,
  Th,
  useToast,
} from "@autobacklinker/ui";
import type { RecycleBinItem, RecycleBinKind } from "@autobacklinker/shared-types";
import { api, apiClient, isMissingEndpoint } from "../lib/api";
import { sendNativeNotification } from "../lib/backend";
import { formatDate, formatRelative } from "../lib/format";
import { navigate, useRoute } from "../lib/router";
import { useAsync } from "../lib/useAsync";
import { ErrorBlock, NothingYet } from "./common";

const PAGE_SIZE = 25;

/** Every kind the bin can hold, in the order of the tabs. */
const KINDS: RecycleBinKind[] = ["project", "website", "profile", "opportunity"];

/** Lower-case name of a kind, used inside sentences ("the project …"). */
const KIND_NAMES: Record<string, string> = {
  project: "project",
  website: "website",
  profile: "business profile",
  opportunity: "opportunity",
};

/** The label of a kind on its own. */
const KIND_LABELS: Record<string, string> = {
  project: "Project",
  website: "Website",
  profile: "Business profile",
  opportunity: "Opportunity",
};

/** The plural label of a kind, used for the tabs. */
const KIND_TAB_LABELS: Record<string, string> = {
  project: "Projects",
  website: "Websites",
  profile: "Business profiles",
  opportunity: "Opportunities",
};

const KIND_PLURALS: Record<string, string> = {
  project: "projects",
  website: "websites",
  profile: "business profiles",
  opportunity: "opportunities",
};

function isKind(value: string): value is RecycleBinKind {
  return (KINDS as string[]).includes(value);
}

/** The selected kind travels in the `kind` query parameter of the route. */
function kindFromRoute(route: string): "" | RecycleBinKind {
  const query = route.split("?")[1] ?? "";
  const value = new URLSearchParams(query).get("kind") ?? "";
  return isKind(value) ? value : "";
}

function kindName(kind: string): string {
  return KIND_NAMES[kind] ?? kind;
}

/**
 * What "Delete forever" destroys for a kind - told plainly, never softened.
 */
function purgeImpact(kind: string): string {
  switch (kind) {
    case "project":
      return "Its opportunities, its tasks, its settings and its landing pages are deleted with it.";
    case "website":
      return "Its opportunities and the tasks of those opportunities are deleted with it.";
    case "profile":
      return "The projects keep working - they are only detached from the profile.";
    case "opportunity":
      return "Its tasks stay in the history, but they lose the link to the opportunity.";
    default:
      return "Everything that depends on it is deleted with it.";
  }
}

/** What a restore brings back - stated per kind so the message is accurate. */
function restoreMessage(item: RecycleBinItem): string {
  const label = item.title || item.id;
  switch (item.kind) {
    case "project":
    case "website":
      return `${label} restored - it is back in the normal lists with its opportunities, tasks and verification records.`;
    case "profile":
      return `${label} restored - it is back in the normal lists and re-attached to its projects.`;
    case "opportunity":
      return `${label} restored - it is back in the normal lists with its tasks.`;
    default:
      return `${label} restored - it is back in the normal lists with its history.`;
  }
}

/** What a permanent delete removed - the same impact the dialog promised. */
function purgeMessage(item: RecycleBinItem): string {
  const label = item.title || item.id;
  switch (item.kind) {
    case "project":
      return `${label} deleted forever - its opportunities, tasks, settings and landing pages are gone.`;
    case "website":
      return `${label} deleted forever - its opportunities and their tasks are gone.`;
    case "profile":
      return `${label} deleted forever - the projects keep working, they are only detached.`;
    case "opportunity":
      return `${label} deleted forever - its tasks stay in the history without the link.`;
    default:
      return `${label} deleted forever - this cannot be undone.`;
  }
}

/**
 * An honest message for a failed recycle bin action: a 404 is neither a
 * success nor hidden behind a bare "Not Found".
 */
function actionError(error: unknown, fallback: string): string {
  if (isMissingEndpoint(error)) {
    return "The backend answered 404 - the item may be gone already or this local backend does not know the recycle bin yet.";
  }
  if (error && typeof error === "object" && "message" in error) {
    return String((error as { message: unknown }).message);
  }
  return fallback;
}

interface Busy {
  key: string;
  action: "restore" | "purge";
}

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description?: React.ReactNode;
  confirmLabel: string;
  destructive?: boolean;
  pending?: boolean;
  onConfirm: () => void;
  onClose: () => void;
  children?: React.ReactNode;
}

/**
 * Confirmation dialog for the irreversible delete. The shared UI package has
 * no dedicated component - like every other desktop confirmation this is the
 * shared `Dialog` with a destructive primary action and Cancel as the safe
 * default (it takes the focus).
 */
function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  destructive = false,
  pending = false,
  onConfirm,
  onClose,
  children,
}: ConfirmDialogProps) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={title}
      description={description}
      width="sm"
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={pending} autoFocus>
            Cancel
          </Button>
          <Button
            variant={destructive ? "danger" : "primary"}
            onClick={onConfirm}
            loading={pending}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      {children}
    </Dialog>
  );
}

/**
 * The global recycle bin: every deleted project, website, business profile and
 * opportunity waits here until it is restored or deleted forever.
 *
 * Restoring clears the removal mark of a row, so it appears in the normal
 * lists again with everything that belongs to it. Deleting a row forever is
 * irreversible and destroys what depends on it - the confirmation names the
 * row and states the impact before anything happens.
 */
export function RecycleBinPanel() {
  const toast = useToast();
  const [route] = useRoute();
  const kind = kindFromRoute(route);

  const [page, setPage] = React.useState(1);
  const [busy, setBusy] = React.useState<Busy | null>(null);
  const [purgeTarget, setPurgeTarget] = React.useState<RecycleBinItem | null>(
    null,
  );

  /* A different tab starts at the first page. */
  React.useEffect(() => {
    setPage(1);
  }, [kind]);

  const list = useAsync(
    () =>
      api.recycleBin.list(apiClient, {
        kind: kind || undefined,
        page,
        page_size: PAGE_SIZE,
      }),
    [kind, page],
  );

  const countsResource = useAsync(() => api.recycleBin.counts(apiClient), []);

  /* The list response carries the counts too - the dedicated endpoint wins,
   * the list is the fallback so the tabs stay populated if it refuses. */
  const counts: Record<string, number> =
    countsResource.data ?? list.data?.counts ?? {};

  const total = KINDS.reduce((sum, current) => sum + (counts[current] ?? 0), 0);
  const rows = list.data?.items ?? [];
  const missingEndpoint = Boolean(list.error) && isMissingEndpoint(list.error);

  const refreshAll = React.useCallback(() => {
    list.reload();
    countsResource.reload();
  }, [list, countsResource]);

  /** Every outcome is reported by a toast and by the native notification. */
  const announce = (message: string, tone: "success" | "error") => {
    toast.push(message, tone);
    void sendNativeNotification("Auto Backlinker", message);
  };

  const selectKind = (next: string) => {
    setPage(1);
    navigate(next ? `recycle-bin?kind=${encodeURIComponent(next)}` : "recycle-bin");
  };

  /* After a removal the current page can be past the end - step back one. */
  React.useEffect(() => {
    const pages = list.data?.pages ?? 0;
    if (pages > 0 && page > pages) setPage(pages);
  }, [list.data, page]);

  const restore = async (item: RecycleBinItem) => {
    const key = `${item.kind}:${item.id}`;
    setBusy({ key, action: "restore" });
    try {
      await api.recycleBin.restore(apiClient, String(item.kind), item.id);
      announce(restoreMessage(item), "success");
      refreshAll();
    } catch (err) {
      announce(
        actionError(
          err,
          `The ${kindName(String(item.kind))} ${item.title || item.id} could not be restored`,
        ),
        "error",
      );
    } finally {
      setBusy(null);
    }
  };

  const purge = async () => {
    if (!purgeTarget) return;
    const target = purgeTarget;
    setBusy({ key: `${target.kind}:${target.id}`, action: "purge" });
    try {
      await api.recycleBin.purge(apiClient, String(target.kind), target.id);
      announce(purgeMessage(target), "success");
      setPurgeTarget(null);
      refreshAll();
    } catch (err) {
      announce(
        actionError(
          err,
          `The ${kindName(String(target.kind))} ${target.title || target.id} could not be deleted forever`,
        ),
        "error",
      );
    } finally {
      setBusy(null);
    }
  };

  const purgePending =
    purgeTarget !== null &&
    busy !== null &&
    busy.action === "purge" &&
    busy.key === `${purgeTarget.kind}:${purgeTarget.id}`;

  const tabs = [
    { id: "", label: "All", count: total },
    ...KINDS.map((value) => ({
      id: value,
      label: KIND_TAB_LABELS[value] ?? KIND_LABELS[value] ?? value,
      count: counts[value] ?? 0,
    })),
  ];

  const emptyTitle = kind
    ? `No ${KIND_PLURALS[kind] ?? kind} in the recycle bin`
    : "The recycle bin is empty";
  const emptyDescription = kind
    ? `Every deleted ${kindName(kind)} waits here until it is restored or deleted forever.`
    : "Everything you delete waits here until you restore it or delete it forever.";

  return (
    <Card>
      <Tabs tabs={tabs} active={kind} onChange={selectKind} className="px-3" />

      <CardBody className="p-0">
        {missingEndpoint ? (
          <div className="border-b border-line p-4">
            <Alert
              tone="warning"
              title="This local backend does not know the recycle bin yet"
            >
              <p>
                The endpoint <code>/api/v1/recycle-bin</code> answers with 404.
                Nothing can be restored or deleted forever until the local
                backend is updated.
              </p>
              <p className="mt-1 text-content-subtle">{list.error}</p>
            </Alert>
          </div>
        ) : null}

        {list.loading && !list.data ? (
          <div className="p-4">
            <Table>
              <thead>
                <tr>
                  <Th className="w-40">Kind</Th>
                  <Th>Item</Th>
                  <Th className="w-48">Deleted</Th>
                  <Th className="w-64 text-right">Actions</Th>
                </tr>
              </thead>
              <tbody>
                {Array.from({ length: 6 }).map((_, index) => (
                  <tr key={index}>
                    <Td>
                      <Skeleton className="h-5 w-24" />
                    </Td>
                    <Td>
                      <Skeleton className="h-4 w-64" />
                    </Td>
                    <Td>
                      <Skeleton className="h-4 w-28" />
                    </Td>
                    <Td>
                      <Skeleton className="ml-auto h-8 w-40" />
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
        ) : null}

        {list.error && !missingEndpoint ? (
          <div className="p-4">
            <ErrorBlock message={list.error} onRetry={refreshAll} />
          </div>
        ) : null}

        {!list.loading && !list.error && rows.length === 0 ? (
          <div className="p-4">
            <NothingYet title={emptyTitle} description={emptyDescription} />
          </div>
        ) : null}

        {rows.length > 0 ? (
          <>
            <Table>
              <thead>
                <tr>
                  <Th className="w-40">Kind</Th>
                  <Th>Item</Th>
                  <Th className="w-48">Deleted</Th>
                  <Th className="w-64 text-right">Actions</Th>
                </tr>
              </thead>
              <tbody>
                {rows.map((item) => {
                  const key = `${item.kind}:${item.id}`;
                  const label = item.title || item.id;
                  const isRestoring =
                    busy?.key === key && busy.action === "restore";
                  const isPurging = busy?.key === key && busy.action === "purge";
                  return (
                    <tr key={key}>
                      <Td>
                        <Badge tone="neutral">
                          {KIND_LABELS[item.kind] ?? item.kind}
                        </Badge>
                      </Td>
                      <Td>
                        <p className="font-medium text-content">{label}</p>
                        {item.subtitle ? (
                          <p
                            className="max-w-md truncate text-xs text-content-muted"
                            title={item.subtitle}
                          >
                            {item.subtitle}
                          </p>
                        ) : null}
                      </Td>
                      <Td
                        className="whitespace-nowrap text-xs text-content-muted"
                        title={formatDate(item.deleted_at)}
                      >
                        {item.deleted_at
                          ? `Deleted ${formatRelative(item.deleted_at)}`
                          : "Deletion time unknown"}
                      </Td>
                      <Td>
                        <div className="flex items-center justify-end gap-1">
                          <Button
                            size="sm"
                            variant="outline"
                            loading={isRestoring}
                            disabled={busy !== null && !isRestoring}
                            aria-label={`Restore the ${kindName(String(item.kind))} ${label}`}
                            title={`Bring the ${kindName(String(item.kind))} back into the normal lists`}
                            onClick={() => void restore(item)}
                          >
                            Restore
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            loading={isPurging}
                            disabled={busy !== null && !isPurging}
                            aria-label={`Delete the ${kindName(String(item.kind))} ${label} forever`}
                            title="Delete it forever - this cannot be undone"
                            onClick={() => setPurgeTarget(item)}
                          >
                            Delete forever
                          </Button>
                        </div>
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
            {list.data ? (
              <Pagination
                page={list.data.page}
                pages={list.data.pages}
                total={list.data.total}
                onPageChange={setPage}
              />
            ) : null}
          </>
        ) : null}
      </CardBody>

      <ConfirmDialog
        open={purgeTarget !== null}
        title={
          purgeTarget
            ? `Delete the ${kindName(String(purgeTarget.kind))} "${purgeTarget.title}" forever?`
            : "Delete this item forever?"
        }
        description="This cannot be undone."
        confirmLabel="Delete forever"
        destructive
        pending={purgePending}
        onClose={() => {
          if (!purgePending) setPurgeTarget(null);
        }}
        onConfirm={() => void purge()}
      >
        {purgeTarget ? (
          <div className="flex flex-col gap-2 text-xs text-content-muted">
            <p>
              <strong className="font-semibold text-content">
                {purgeTarget.title}
              </strong>{" "}
              is deleted forever.
              {purgeTarget.subtitle ? (
                <span className="text-content-subtle">
                  {" "}
                  ({purgeTarget.subtitle})
                </span>
              ) : null}
            </p>
            <p>{purgeImpact(String(purgeTarget.kind))}</p>
            <p className="font-medium text-danger">
              It cannot be restored after this - there is no way to undo it.
            </p>
          </div>
        ) : null}
      </ConfirmDialog>
    </Card>
  );
}
