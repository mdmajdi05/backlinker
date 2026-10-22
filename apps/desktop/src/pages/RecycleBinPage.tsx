import { PageHeader } from "../components/common";
import { RecycleBinPanel } from "../components/RecycleBinPanel";

/**
 * The recycle bin of the desktop client.
 *
 * Everything that was deleted from a normal list waits here until it is
 * restored or deleted forever - the panel below does the whole work.
 */
export function RecycleBinPage() {
  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Recycle bin"
        description="Everything you delete waits here until you restore it or delete it forever."
      />
      <RecycleBinPanel />
    </div>
  );
}
