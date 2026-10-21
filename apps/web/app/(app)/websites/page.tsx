"use client";

import * as React from "react";
import { Alert } from "@autobacklinker/ui";
import { PageHeader } from "@/components/PageHeader";
import { WebsiteListPanel } from "@/components/WebsiteListPanel";

export default function WebsitesPage() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="Website list"
        description="The central list of the websites where your projects get backlinks. It is filled by hand or by an Excel import and every project picks the sites it needs from it."
      />

      <Alert tone="neutral" title="How the list is used">
        Add a website once - it stays in this list even when no project uses it. Mark a site
        that stopped working as &quot;not working&quot; instead of deleting it, pick the sites
        you need in the project and read the result (submitted, verified, failed) in the
        report.
      </Alert>

      <WebsiteListPanel />
    </div>
  );
}
