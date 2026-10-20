"use client";

import * as React from "react";
import { Badge, Button, EmptyState, ErrorState, Skeleton } from "@autobacklinker/ui";
import { errorMessage } from "@/lib/api";

/** Generic skeleton block used while a list view is loading. */
export function TableSkeleton({ rows = 6, columns = 5 }: { rows?: number; columns?: number }) {
  return (
    <div className="space-y-2 p-3" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading…</span>
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <div key={rowIndex} className="flex gap-3">
          {Array.from({ length: columns }).map((__, colIndex) => (
            <Skeleton key={colIndex} className="h-4 flex-1" />
          ))}
        </div>
      ))}
    </div>
  );
}

export function CardSkeleton({ count = 3 }: { count?: number }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" aria-busy="true">
      {Array.from({ length: count }).map((_, index) => (
        <div key={index} className="abk-card space-y-2 p-4">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-7 w-16" />
        </div>
      ))}
    </div>
  );
}

export function ErrorPanel({
  error,
  onRetry,
  title = "Could not load data",
}: {
  error: unknown;
  onRetry?: () => void;
  title?: string;
}) {
  return (
    <ErrorState
      title={title}
      message={errorMessage(error)}
      action={
        onRetry ? (
          <Button variant="outline" size="sm" onClick={onRetry}>
            Retry
          </Button>
        ) : undefined
      }
    />
  );
}

export function EmptyPanel({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="abk-card">
      <EmptyState title={title} description={description} action={action} />
    </div>
  );
}

/**
 * Renders the correct feedback for a remote resource: skeleton while loading,
 * retryable error state on failure, empty state when there is nothing to show.
 */
export function AsyncSection<T>({
  loading,
  error,
  data,
  onRetry,
  isEmpty,
  emptyTitle = "Nothing here yet",
  emptyDescription,
  emptyAction,
  skeleton,
  children,
}: {
  loading: boolean;
  error: unknown;
  data: T | null | undefined;
  onRetry?: () => void;
  isEmpty?: boolean;
  emptyTitle?: string;
  emptyDescription?: string;
  emptyAction?: React.ReactNode;
  skeleton?: React.ReactNode;
  children: React.ReactNode;
}) {
  if (loading && data === null) {
    return <>{skeleton ?? <TableSkeleton />}</>;
  }
  if (error && data === null) {
    return <ErrorPanel error={error} onRetry={onRetry} />;
  }
  if (isEmpty) {
    return <EmptyPanel title={emptyTitle} description={emptyDescription} action={emptyAction} />;
  }
  return <>{children}</>;
}

export function InlineError({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <Badge tone="danger" className="whitespace-normal text-left">
      {errorMessage(error)}
    </Badge>
  );
}
