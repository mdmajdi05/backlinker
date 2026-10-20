import { EmptyState, Card } from "@autobacklinker/ui";
import { navEntry } from "../lib/nav";

/**
 * Some modules of the web client are not part of the desktop build yet.
 * They render an explicit empty state - never fabricated data.
 */
export function NotImplementedPage({ route }: { route: string }) {
  const entry = navEntry(route);
  return (
    <Card>
      <EmptyState
        title={`${entry?.label ?? "This module"} is not available in the desktop build`}
        description={
          entry?.description ??
          "Use the web client for this module - the desktop build is focused on local execution."
        }
      />
    </Card>
  );
}
