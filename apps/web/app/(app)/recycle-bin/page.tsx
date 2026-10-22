"use client";

import * as React from "react";
import { Card, CardBody } from "@autobacklinker/ui";
import { PageHeader } from "@/components/PageHeader";
import { RecycleBinPanel } from "@/components/RecycleBinPanel";
import { TableSkeleton } from "@/components/States";

export default function RecycleBinPage() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="Recycle bin"
        description="Everything you delete waits here until you restore it or delete it forever."
      />

      {/* The panel reads the `kind` search parameter - Next.js needs a
       * Suspense boundary for useSearchParams on a server-rendered page. */}
      <React.Suspense
        fallback={
          <Card>
            <CardBody className="p-0">
              <TableSkeleton rows={8} columns={4} />
            </CardBody>
          </Card>
        }
      >
        <RecycleBinPanel />
      </React.Suspense>
    </div>
  );
}
