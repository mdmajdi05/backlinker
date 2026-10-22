"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@autobacklinker/api-client";
import type { RecycleBinItem, RecycleBinKind } from "@autobacklinker/shared-types";
import {
  Badge,
  Button,
  Card,
  CardBody,
  Pagination,
  Table,
  Tabs,
  Td,
  Th,
  useToast,
} from "@autobacklinker/ui";
import { apiClient, errorMessage, isNotFoundError } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { formatDateTime, formatRelative } from "@/lib/format";
import { AsyncSection, TableSkeleton } from "@/components/States";
import { ConfirmDialog } from "@/components/ConfirmDialog";

const PAGE_SIZE = 25;

/** Every kind the bin can hold, in the order of the tabs. */
const KINDS: RecycleBinKind[] = ["project", "website", "profile", "opportunity"];

const KIND_LABELS: Record<string, string> = {
  project: "Project",
  website: "Website",
  profile: "Business profile",
  opportunity: "Opportunity",
};

/** The plural labels of the tabs. */
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

/** Lower-case name of a kind, used inside sentences ("the project …"). */
function kindName(kind: string): string {
  return KIND_LABELS[kind]?.toLowerCase() ?? kind;
}

/** What "Delete forever" destroys for a kind - told plainly, never softened. */
function purgeImpact(kind: string): string {
  switch (kind) {
    case "project":
      return "Its opportunities, its tasks, its settings and its landing pages are deleted with it. The old reports lose this project.";
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

/** What a restore brings back - the promise differs per kind. */
function restoreOutcome(kind: string, title: string): string {
  switch (kind) {
    case "profile":
      return `${title} restored - it is back in the normal lists and re-attached to its projects`;
    case "opportunity":
      return `${title} restored - it is back in the normal lists and its tasks point to it again`;
    default:
      return `${title} restored - it is back in the normal lists with its opportunities, tasks and verification records`;
  }
}

/**
 * An honest message for a failed recycle bin action: a 404 is not reported as
 * a success and not hidden behind a bare "Not Found" either.
 */
function actionError(error: unknown, fallback: string): string {
  if (isNotFoundError(error)) {
    return "The backend answered 404 - the item may be gone already.";
  }
  const message = errorMessage(error);
  return message && message !== "Unknown error" ? message : fallback;
}

interface Busy {
  id: string;
  action: "restore" | "purge";
}

/**
 * The global recycle bin: every deleted project, website, business profile and
 * opportunity waits here until it is restored or deleted forever.
 *
 * Restoring clears the removal mark of a row, so it appears in the normal
 * lists again with its opportunities, tasks and verification records. Deleting
 * a row forever is irreversible and destroys what depends on it - the
 * confirmation names the row and states the impact before anything happens.
 */
export function RecycleBinPanel() {
  const toast = useToast();
  const router = useRouter();
  const searchParams = useSearchParams();

  const requestedKind = searchParams.get("kind") ?? "";
  const kind: "" | RecycleBinKind = isKind(requestedKind) ? requestedKind : "";

  const [page, setPage] = React.useState(1);
  const [busy, setBusy] = React.useState<Busy | null>(null);
  const [purgeTarget, setPurgeTarget] = React.useState<RecycleBinItem | null>(null);

  /* A different tab starts at the first page. */
  React.useEffect(() => {
    setPage(1);
  }, [kind]);

  const list = useResource(
    () =>
      api.recycleBin.list(apiClient, {
        kind: kind || undefined,
        page,
        page_size: PAGE_SIZE,
      }),
    [kind, page],
  );

  const countsResource = useResource(() => api.recycleBin.counts(apiClient), []);

  /* The list response carries the counts too - the dedicated endpoint wins,
   * the list is the fallback so the tabs stay populated if it refuses. */
  const counts: Record<string, number> =
    countsResource.data ?? list.data?.counts ?? {};

  const total = KINDS.reduce((sum, current) => sum + (counts[current] ?? 0), 0);
  const rows = list.data?.items ?? [];

  const refreshAll = React.useCallback(() => {
    list.reload();
    countsResource.reload();
  }, [list, countsResource]);

  const selectKind = (next: string) => {
    setPage(1);
    router.replace(next ? `/recycle-bin?kind=${encodeURIComponent(next)}` : "/recycle-bin");
  };

  /** After a removal the current page can be past the end - step back one. */
  React.useEffect(() => {
    const pages = list.data?.pages ?? 0;
    if (pages > 0 && page > pages) setPage(pages);
  }, [list.data, page]);

  const restore = async (item: RecycleBinItem) => {
    const key = `${item.kind}:${item.id}`;
    setBusy({ id: key, action: "restore" });
    try {
      await api.recycleBin.restore(apiClient, String(item.kind), item.id);
      toast.push(restoreOutcome(String(item.kind), item.title), "success");
      refreshAll();
    } catch (err) {
      toast.push(
        actionError(err, `The ${kindName(String(item.kind))} could not be restored`),
        "error",
      );
    } finally {
      setBusy(null);
    }
  };

  const purge = async () => {
    if (!purgeTarget) return;
    const target = purgeTarget;
    setBusy({ id: `${target.kind}:${target.id}`, action: "purge" });
    try {
      await api.recycleBin.purge(apiClient, String(target.kind), target.id);
      toast.push(`${target.title} deleted forever - this cannot be undone`, "success");
      setPurgeTarget(null);
      refreshAll();
    } catch (err) {
      toast.push(
        actionError(err, `The ${kindName(String(target.kind))} could not be deleted forever`),
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
    busy.id === `${purgeTarget.kind}:${purgeTarget.id}`;

  const tabs = [
    { id: "", label: "All", count: total },
    ...KINDS.map((value) => ({
      id: value,
      label: KIND_TAB_LABELS[value],
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
        <AsyncSection
          loading={list.loading}
          error={list.error}
          data={list.data}
          onRetry={refreshAll}
          isEmpty={rows.length === 0}
          emptyTitle={emptyTitle}
          emptyDescription={emptyDescription}
          skeleton={<TableSkeleton rows={8} columns={5} />}
        >
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
                const isRestoring = busy?.id === key && busy.action === "restore";
                const isPurging = busy?.id === key && busy.action === "purge";
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
                        <p className="max-w-md truncate text-xs text-content-muted" title={item.subtitle}>
                          {item.subtitle}
                        </p>
                      ) : null}
                    </Td>
                    <Td
                      className="whitespace-nowrap text-xs text-content-muted"
                      title={formatDateTime(item.deleted_at)}
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
        </AsyncSection>
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
          <div className="space-y-2 text-xs text-content-muted">
            <p>
              <strong className="font-semibold text-content">{purgeTarget.title}</strong>{" "}
              is deleted forever.
              {purgeTarget.subtitle ? (
                <span className="text-content-subtle"> ({purgeTarget.subtitle})</span>
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
