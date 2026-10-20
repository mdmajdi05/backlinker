"use client";

import * as React from "react";
import Link from "next/link";
import { api } from "@autobacklinker/api-client";
import type { Project } from "@autobacklinker/shared-types";
import {
  Button,
  Card,
  CardBody,
  Dialog,
  Pagination,
  StatusBadge,
  Table,
  Td,
  Th,
} from "@autobacklinker/ui";
import { apiClient } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { formatDateTime, formatNumber } from "@/lib/format";
import { PageHeader } from "@/components/PageHeader";
import { AsyncSection, TableSkeleton } from "@/components/States";
import { ProjectWizard } from "@/components/ProjectWizard";

const PAGE_SIZE = 20;

export default function ProjectsPage() {
  const [page, setPage] = React.useState(1);
  const [wizardOpen, setWizardOpen] = React.useState(false);

  const projects = useResource(
    () => api.projects.list(apiClient, { page, page_size: PAGE_SIZE }),
    [page],
  );

  const rows = projects.data?.items ?? [];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Projects"
        description="Every campaign that targets a website and owns its own execution settings."
        actions={
          <Button size="sm" onClick={() => setWizardOpen(true)}>
            New project
          </Button>
        }
      />

      <Card>
        <CardBody className="p-0">
          <AsyncSection
            loading={projects.loading}
            error={projects.error}
            data={projects.data}
            onRetry={projects.reload}
            isEmpty={rows.length === 0}
            emptyTitle="No projects yet"
            emptyDescription="Create your first project to start discovering backlink opportunities."
            emptyAction={
              <Button size="sm" onClick={() => setWizardOpen(true)}>
                New project
              </Button>
            }
            skeleton={<TableSkeleton rows={6} columns={6} />}
          >
            <Table>
              <thead>
                <tr>
                  <Th>Name</Th>
                  <Th>Target website</Th>
                  <Th>Status</Th>
                  <Th className="text-right">Opportunities</Th>
                  <Th className="text-right">Approved</Th>
                  <Th className="text-right">Queued</Th>
                  <Th className="text-right">Verified</Th>
                  <Th className="w-40">Updated</Th>
                </tr>
              </thead>
              <tbody>
                {rows.map((project: Project) => (
                  <tr key={project.id}>
                    <Td>
                      <Link
                        href={`/projects/${project.id}`}
                        className="font-medium text-accent hover:underline"
                      >
                        {project.name}
                      </Link>
                      {project.description ? (
                        <p className="mt-0.5 max-w-md truncate text-xs text-content-muted">
                          {project.description}
                        </p>
                      ) : null}
                    </Td>
                    <Td className="text-xs">
                      <a
                        href={project.target_website}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-accent hover:underline"
                      >
                        {project.target_website}
                      </a>
                    </Td>
                    <Td>
                      <StatusBadge status={project.status} />
                    </Td>
                    <Td className="text-right tabular-nums">
                      {formatNumber(project.counts?.opportunities)}
                    </Td>
                    <Td className="text-right tabular-nums">
                      {formatNumber(project.counts?.approved)}
                    </Td>
                    <Td className="text-right tabular-nums">
                      {formatNumber(project.counts?.queued)}
                    </Td>
                    <Td className="text-right tabular-nums">
                      {formatNumber(project.counts?.verified_live)}
                    </Td>
                    <Td className="text-xs text-content-muted">{formatDateTime(project.updated_at)}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            {projects.data ? (
              <Pagination
                page={projects.data.page}
                pages={projects.data.pages}
                total={projects.data.total}
                onPageChange={setPage}
              />
            ) : null}
          </AsyncSection>
        </CardBody>
      </Card>

      <Dialog
        open={wizardOpen}
        onClose={() => setWizardOpen(false)}
        title="Create project"
        description="Configure the campaign, its landing pages and execution limits."
        width="lg"
      >
        <ProjectWizard
          defaultProfileId={null}
          onCancel={() => setWizardOpen(false)}
          onCreated={(project) => {
            setWizardOpen(false);
            projects.reload();
            void project;
          }}
        />
      </Dialog>
    </div>
  );
}
