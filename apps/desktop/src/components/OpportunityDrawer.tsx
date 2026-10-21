import * as React from "react";
import {
  Alert,
  Badge,
  Button,
  Drawer,
  KeyValue,
  useToast,
} from "@autobacklinker/ui";
import { api, apiClient, isMissingEndpoint } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import { ErrorBlock, LoadingBlock } from "./common";
import { formatDate } from "../lib/format";
import { openPath, sendNativeNotification } from "../lib/backend";
import {
  detailFieldLabel,
  resolveDetailField,
  SubmissionDetailsPanel,
} from "./SubmissionDetailsPanel";
import type {
  BusinessProfile,
  DetailsGapReport,
  Opportunity,
} from "@autobacklinker/shared-types";

/**
 * The drawer of an opportunity.
 *
 * Its heart is the *gap report*: the values a target site asks for and that
 * are still missing - split into the ones the business profile of the project
 * can fill and the ones it can not.  Every value that can not be derived
 * carries the reason, so nobody has to guess why a submission waits.
 *
 * The report is computed by the desktop client from the profile and the
 * details of the backend - the backend itself does not know this endpoint
 * yet.  The values are never invented: a field is only "derivable" when the
 * profile really carries it.
 */

interface ProfileValue {
  derivable: boolean;
  reason: string;
  value?: string;
}

/** The reasons why the profile can not fill a field. */
const NO_PROFILE_REASON =
  "The project has no business profile - nothing can be derived from it.";

function profileValue(
  field: string,
  profile: BusinessProfile | null,
): ProfileValue {
  if (!profile) {
    return { derivable: false, reason: NO_PROFILE_REASON };
  }
  const target = resolveDetailField(field);
  const has = (value: unknown): boolean =>
    Array.isArray(value)
      ? value.length > 0
      : typeof value === "string"
        ? value.trim().length > 0
        : value !== null && value !== undefined;

  switch (target) {
    case "company_name":
      return has(profile.name)
        ? { derivable: true, reason: "", value: profile.name }
        : {
            derivable: false,
            reason: "The business profile has no company name.",
          };
    case "description": {
      const content =
        profile.description ||
        profile.business_descriptions?.[0] ||
        profile.industry ||
        profile.niche;
      return has(content)
        ? { derivable: true, reason: "", value: String(content) }
        : {
            derivable: false,
            reason: "The business profile has no description of the business.",
          };
    }
    case "email":
      return has(profile.contact_email)
        ? { derivable: true, reason: "", value: profile.contact_email ?? "" }
        : {
            derivable: false,
            reason: "The business profile has no e-mail address.",
          };
    case "phone":
      return has(profile.contact_phone)
        ? { derivable: true, reason: "", value: profile.contact_phone ?? "" }
        : {
            derivable: false,
            reason: "The business profile has no phone number.",
          };
    case "website":
      return has(profile.primary_website)
        ? { derivable: true, reason: "", value: profile.primary_website }
        : {
            derivable: false,
            reason: "The business profile has no website.",
          };
    case "logo_path":
      return has(profile.logo_path)
        ? { derivable: true, reason: "", value: profile.logo_path ?? "" }
        : {
            derivable: false,
            reason: "The business profile has no logo.",
          };
    case "categories":
      return has(profile.preferred_categories)
        ? {
            derivable: true,
            reason: "",
            value: profile.preferred_categories.join(", "),
          }
        : {
            derivable: false,
            reason: "The business profile has no categories.",
          };
    case "country":
      return has(profile.target_countries)
        ? {
            derivable: true,
            reason: "",
            value: profile.target_countries.join(", "),
          }
        : {
            derivable: false,
            reason: "The business profile names no target country.",
          };
    case "state":
      return has(profile.target_regions)
        ? {
            derivable: true,
            reason: "",
            value: profile.target_regions.join(", "),
          }
        : {
            derivable: false,
            reason: "The business profile names no target region.",
          };
    case "address":
      return {
        derivable: false,
        reason: "The business profile has no street address.",
      };
    case "city":
      return {
        derivable: false,
        reason: "The business profile has no city.",
      };
    case "postal_code":
      return {
        derivable: false,
        reason: "The business profile has no postal code.",
      };
    case "founded_year":
      return {
        derivable: false,
        reason: "The business profile has no year founded.",
      };
    case "employee_count":
      return {
        derivable: false,
        reason: "The business profile has no number of employees.",
      };
    default:
      return {
        derivable: false,
        reason:
          "The business profile has no data for this field - the value exists only in your business.",
      };
  }
}

/**
 * The gap report of an opportunity.
 *
 * `required` and `missing` come from the backend, the split into "derivable"
 * and "not derivable" is computed from the business profile of the project.
 */
export function buildGapReport(
  required: string[],
  missing: string[],
  profile: BusinessProfile | null,
): DetailsGapReport {
  const derivable: string[] = [];
  const notDerivable: DetailsGapReport["not_derivable"] = [];

  missing.forEach((field) => {
    const outcome = profileValue(field, profile);
    if (outcome.derivable) {
      derivable.push(field);
    } else {
      notDerivable.push({
        field,
        label: detailFieldLabel(field),
        reason: outcome.reason,
      });
    }
  });

  return {
    required,
    filled: required.filter((field) => !missing.includes(field)),
    missing,
    derivable,
    not_derivable: notDerivable,
    source: "client",
  };
}

/** The answer of the backend - it is never trusted blindly. */
export function normalizeGapReport(raw: unknown): DetailsGapReport {
  const data = (raw ?? {}) as Record<string, unknown>;
  const list = (value: unknown): string[] =>
    Array.isArray(value)
      ? value.map((item) => String(item ?? "").trim()).filter(Boolean)
      : [];
  const notDerivable = Array.isArray(data.not_derivable)
    ? data.not_derivable.map((item) => {
        const entry = (item ?? {}) as Record<string, unknown>;
        const field = String(entry.field ?? "").trim();
        return {
          field,
          label: String(entry.label ?? "").trim() || detailFieldLabel(field),
          reason: String(entry.reason ?? "").trim(),
        };
      })
    : [];
  const required = list(data.required);
  const missing = list(data.missing);
  return {
    required,
    filled: list(data.filled),
    missing,
    derivable: list(data.derivable),
    not_derivable: notDerivable,
    source: String(data.source ?? "backend"),
  };
}

export function OpportunityDrawer({
  opportunity,
  onClose,
  onChanged,
}: {
  opportunity: Opportunity;
  onClose: () => void;
  onChanged?: () => void;
}) {
  const toast = useToast();
  const [rawError, setRawError] = React.useState<unknown>(null);
  const [generating, setGenerating] = React.useState(false);
  const [editing, setEditing] = React.useState(false);

  const details = useAsync(async () => {
    try {
      return await api.submissionDetails.get(apiClient, opportunity.id);
    } catch (err) {
      setRawError(err);
      throw err;
    }
  }, [opportunity.id]);

  const project = useAsync(
    () => api.projects.get(apiClient, opportunity.project_id),
    [opportunity.project_id],
  );

  const profile = useAsync(
    () => {
      const id = project.data?.business_profile_id;
      return id
        ? api.profiles.get(apiClient, id)
        : Promise.resolve(null as BusinessProfile | null);
    },
    [project.data?.business_profile_id],
  );

  const data = details.data;
  const unsupported =
    Boolean(details.error) && isMissingEndpoint(rawError ?? details.error);

  // The backend knows the gap report - an older one does not, then the
  // desktop client computes it from the details and the profile.
  const backendGap = useAsync(async () => {
    try {
      const raw = await apiClient.get<unknown>(
        `/api/v1/opportunities/${opportunity.id}/details/gaps`,
      );
      return normalizeGapReport(raw);
    } catch (err) {
      if (isMissingEndpoint(err)) return null;
      throw err;
    }
  }, [opportunity.id]);

  const gap = React.useMemo(() => {
    if (backendGap.data) return backendGap.data;
    if (!data) return null;
    return buildGapReport(
      data.required.map((entry) => entry.field),
      data.missing.map((entry) => entry.field),
      profile.data ?? null,
    );
  }, [backendGap.data, data, profile.data]);

  const gapSource = backendGap.data ? "backend" : "client";

  async function generate() {
    setGenerating(true);
    try {
      const result = await api.submissionDetails.generate(
        apiClient,
        opportunity.id,
      );
      const names = result.generated.map(detailFieldLabel);
      const message = names.length
        ? `${names.join(", ")} were filled from your business profile`
        : "The business profile does not carry the missing values - nothing was filled";
      toast.push(message, names.length ? "success" : "info");
      void sendNativeNotification(
        "Auto Backlinker",
        `${message} (${opportunity.name}).`,
      );
      details.reload();
      onChanged?.();
    } catch (err) {
      toast.push(
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : "Could not fill the missing details",
        "error",
      );
    } finally {
      setGenerating(false);
    }
  }

  async function openOpportunity() {
    if (!opportunity.opportunity_url) return;
    try {
      await openPath(opportunity.opportunity_url);
    } catch {
      window.open(opportunity.opportunity_url, "_blank", "noopener,noreferrer");
    }
  }

  return (
    <>
      <Drawer
        open
        onClose={onClose}
        title={opportunity.name || opportunity.domain || "Opportunity"}
        width="lg"
        footer={
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Button variant="outline" onClick={onClose}>
              Close
            </Button>
            <Button
              variant="outline"
              onClick={() => setEditing(true)}
              disabled={unsupported}
            >
              Edit the submission details
            </Button>
            <Button
              loading={generating}
              disabled={unsupported || !gap || gap.derivable.length === 0}
              onClick={() => void generate()}
            >
              Generate the derivable ones
            </Button>
          </div>
        }
      >
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="accent">{opportunity.category.replace(/_/g, " ")}</Badge>
            <Badge tone="neutral">
              Score {Math.round(opportunity.score || 0)}
            </Badge>
            <Badge tone="neutral">{opportunity.domain}</Badge>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => void openOpportunity()}
            >
              Open the site ↗
            </Button>
          </div>

          {details.loading && !data ? <LoadingBlock rows={4} /> : null}

          {details.error ? (
            unsupported ? (
              <Alert
                tone="warning"
                title="The backend does not provide submission details yet"
              >
                The details of a target site are read and written by the
                backend. An older local backend can not show the gap report -
                update the backend and reload this view.
              </Alert>
            ) : (
              <ErrorBlock message={details.error} onRetry={details.reload} />
            )
          ) : null}

          {gap ? (
            <section className="rounded-lg border border-line">
              <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
                <div>
                  <h3 className="text-xs font-semibold text-content">
                    Gap report
                  </h3>
                  <p className="text-[11px] text-content-muted">
                    {gap.missing.length === 0
                      ? "Every value this site asks for is filled."
                      : `${gap.missing.length} value${
                          gap.missing.length === 1 ? " is" : "s are"
                        } still missing - ${gap.derivable.length} of them come from your business profile.`}
                  </p>
                </div>
                <Badge tone="neutral">
                  {gap.derivable.length} derivable ·{" "}
                  {gap.not_derivable.length} not derivable
                </Badge>
              </header>

              <div className="p-3">
                {gap.missing.length === 0 ? (
                  <Alert tone="success" title="Nothing is missing">
                    The submission can run without asking for anything.
                  </Alert>
                ) : (
                  <ul className="flex flex-col gap-2">
                    {gap.missing.map((field) => {
                      const derivable = gap.derivable.includes(field);
                      const entry = gap.not_derivable.find(
                        (item) => item.field === field,
                      );
                      return (
                        <li
                          key={field}
                          className="rounded-md border border-line px-3 py-2"
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <span className="text-xs font-medium text-content">
                              {detailFieldLabel(field)}
                            </span>
                            <Badge tone={derivable ? "success" : "warning"}>
                              {derivable
                                ? "Derivable from the profile"
                                : "Not derivable"}
                            </Badge>
                          </div>
                          <p className="mt-1 text-[11px] text-content-muted">
                            {derivable
                              ? "The business profile of the project carries this value - the generator fills it."
                              : (entry?.reason ??
                                "The business profile has no data for this field.")}
                          </p>
                        </li>
                      );
                    })}
                  </ul>
                )}

                <p className="mt-3 text-[11px] text-content-subtle">
                  {gapSource === "backend"
                    ? "The report comes from your local backend - it knows which values the business profile carries."
                    : "The report is computed by the desktop client from the details of the backend and from the business profile of the project. A value is only filled when the profile really carries it."}
                </p>
              </div>
            </section>
          ) : null}

          {data ? (
            <section className="rounded-lg border border-line">
              <header className="border-b border-line px-3 py-2">
                <h3 className="text-xs font-semibold text-content">
                  Stored details
                </h3>
              </header>
              <div className="p-3">
                <KeyValue
                  items={[
                    ["Company name", data.company_name ?? "-"],
                    ["E-mail address", data.email ?? "-"],
                    ["Phone number", data.phone ?? "-"],
                    ["Website", data.website ?? "-"],
                    ["Street address", data.address ?? "-"],
                    ["City", data.city ?? "-"],
                    ["State / region", data.state ?? "-"],
                    ["Country", data.country ?? "-"],
                    ["Postal code", data.postal_code ?? "-"],
                    ["Categories", data.categories.join(", ") || "-"],
                    ["Updated", formatDate(data.updated_at)],
                  ]}
                />
              </div>
            </section>
          ) : null}
        </div>
      </Drawer>

      {editing ? (
        <SubmissionDetailsPanel
          opportunityId={opportunity.id}
          opportunityName={opportunity.name}
          onClose={() => {
            setEditing(false);
            details.reload();
            onChanged?.();
          }}
          onChanged={() => {
            details.reload();
            onChanged?.();
          }}
        />
      ) : null}
    </>
  );
}
