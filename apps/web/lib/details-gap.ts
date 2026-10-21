/**
 * The gap report of the submission details.
 *
 * It answers the question "what is missing and can the business profile
 * supply it?".  The backend answers it with
 * `GET /api/v1/opportunities/{id}/details/gaps` - the derivation in this file
 * is only the fallback for a backend that does not have the endpoint yet.
 */

import type { ApiClient } from "@autobacklinker/api-client";
import type { BusinessProfile, Project } from "@autobacklinker/shared-types";
import { isNotFoundError } from "@/lib/api";

/** One field of the report. */
export interface GapField {
  /** The raw name the backend uses ("Address-Region", "phone_number", …). */
  name: string;
  /** The human readable label. */
  label: string;
  /** The fixed field of the form - null for a site specific value. */
  field: string | null;
  /** True when the business profile can supply the value. */
  derivable: boolean;
  /** Why the value can (or can not) be derived. */
  reason: string;
}

export interface DetailsGap {
  /** The fields the site asks for. */
  required: GapField[];
  /** The fields that already hold a value. */
  filled: GapField[];
  /** The fields that are still empty. */
  missing: GapField[];
  /** The missing fields the business profile can supply. */
  derivable: GapField[];
  /** The missing fields only the user can supply. */
  notDerivable: GapField[];
  /** "profile" when a business profile is available, "none" otherwise. */
  source: string;
}

/** The answer of the gap endpoint of the backend. */
interface RawGapReport {
  required?: string[];
  filled?: string[];
  missing?: string[];
  derivable?: string[];
  not_derivable?: Array<{ field?: string; label?: string; reason?: string }>;
  source?: string;
}

/** The registry names that address one of the fixed fields. */
const FIELD_ALIASES: Record<string, string> = {
  name: "company_name",
  company: "company_name",
  company_name: "company_name",
  business_name: "company_name",
  title: "company_name",
  organisation: "company_name",
  organization: "company_name",
  description: "description",
  summary: "description",
  about: "description",
  email: "email",
  contact_email: "email",
  e_mail: "email",
  mail: "email",
  phone: "phone",
  contact_phone: "phone",
  telephone: "phone",
  phone_number: "phone",
  website: "website",
  website_url: "website",
  primary_website: "website",
  homepage: "website",
  url: "website",
  address: "address",
  street: "address",
  street_address: "address",
  address_line1: "address",
  address1: "address",
  city: "city",
  town: "city",
  locality: "city",
  state: "state",
  region: "state",
  province: "state",
  address_region: "state",
  country: "country",
  country_code: "country",
  postal_code: "postal_code",
  postcode: "postal_code",
  zip: "postal_code",
  zip_code: "postal_code",
  postal: "postal_code",
  logo: "logo_path",
  logo_path: "logo_path",
  logo_url: "logo_path",
  categories: "categories",
  category: "categories",
  business_categories: "categories",
  founded_year: "founded_year",
  founded: "founded_year",
  year_founded: "founded_year",
  established: "founded_year",
  employee_count: "employee_count",
  employees: "employee_count",
  employee_number: "employee_count",
  number_of_employees: "employee_count",
  company_size: "employee_count",
  staff_count: "employee_count",
};

/** The labels of the fixed fields. */
const FIELD_LABELS: Record<string, string> = {
  company_name: "Company name",
  description: "Description",
  email: "E-mail address",
  phone: "Phone number",
  website: "Website",
  address: "Street address",
  city: "City",
  state: "State / region",
  country: "Country",
  postal_code: "Postal code",
  logo_path: "Logo",
  categories: "Categories",
  founded_year: "Year founded",
  employee_count: "Number of employees",
};

/** The fixed fields that no business profile can supply. */
const FIXED_FIELDS_WITHOUT_SOURCE = new Set([
  "address",
  "city",
  "postal_code",
  "founded_year",
  "employee_count",
]);

/** How a value of the business profile is read. */
interface ProfileSource {
  /** The label of the source - it is part of the reason. */
  label: string;
  /** The value of the profile (null when it is empty). */
  read: (profile: BusinessProfile) => string | null;
}

const PROFILE_SOURCES: Record<string, ProfileSource> = {
  company_name: { label: "company name", read: (p) => p.name?.trim() || null },
  description: {
    label: "business description",
    read: (p) =>
      p.description?.trim() ||
      p.business_descriptions?.[0]?.trim() ||
      p.keywords?.[0]?.trim() ||
      null,
  },
  email: { label: "contact e-mail", read: (p) => p.contact_email?.trim() || null },
  phone: { label: "contact phone number", read: (p) => p.contact_phone?.trim() || null },
  website: { label: "primary website", read: (p) => p.primary_website?.trim() || null },
  logo_path: { label: "logo", read: (p) => p.logo_path?.trim() || null },
  categories: {
    label: "preferred categories",
    read: (p) => p.preferred_categories?.[0]?.trim() || null,
  },
  country: {
    label: "target countries",
    read: (p) => p.target_countries?.[0]?.trim() || null,
  },
  state: {
    label: "target regions",
    read: (p) => p.target_regions?.[0]?.trim() || null,
  },
};

/** "Address-Region" -> "address_region" */
function normalizeName(name: string): string {
  return name.trim().toLowerCase().replace(/[-\s]+/g, "_");
}

/** The fixed field a registry name addresses (null for site specific values). */
export function fixedFieldOf(name: string): string | null {
  const normalized = normalizeName(name);
  if (normalized in FIELD_ALIASES) return FIELD_ALIASES[normalized];
  if (normalized in FIELD_LABELS) return normalized;
  return null;
}

/** The label of a registry name. */
export function labelOf(name: string): string {
  const field = fixedFieldOf(name);
  if (field) return FIELD_LABELS[field] ?? field.replace(/_/g, " ");
  return name.replace(/_/g, " ").replace(/^./, (char) => char.toUpperCase());
}

/** Describes one field of the gap report. */
function describeField(
  name: string,
  profile: BusinessProfile | null,
): GapField {
  const field = fixedFieldOf(name);
  const label = labelOf(name);

  if (!field) {
    return {
      name,
      label,
      field: null,
      derivable: false,
      reason:
        "This site asks for a value that is not part of the business profile - only you can fill it in.",
    };
  }

  if (!profile) {
    return {
      name,
      label,
      field,
      derivable: false,
      reason:
        "The project has no business profile - there is nothing the value could be derived from.",
    };
  }

  const source = PROFILE_SOURCES[field];
  if (!source || FIXED_FIELDS_WITHOUT_SOURCE.has(field)) {
    return {
      name,
      label,
      field,
      derivable: false,
      reason: `The business profile has no field for the ${label.toLowerCase()}.`,
    };
  }

  const value = source.read(profile);
  if (!value) {
    return {
      name,
      label,
      field,
      derivable: false,
      reason: `The business profile has no ${source.label}.`,
    };
  }

  return {
    name,
    label,
    field,
    derivable: true,
    reason: `Taken from ${source.label} of the business profile.`,
  };
}

/**
 * Builds the gap report of an opportunity.
 *
 * @param details The submission details of the backend (required + missing).
 * @param profile The business profile of the project (null when there is none).
 */
export function buildDetailsGap(
  details: { required?: string[]; missing?: string[] } | null | undefined,
  profile: BusinessProfile | null,
): DetailsGap {
  const required = details?.required ?? [];
  const missing = details?.missing ?? [];

  const requiredFields = required.map((name) => describeField(name, profile));
  const missingFields = requiredFields.filter((field) =>
    missing.some((name) => normalizeName(name) === normalizeName(field.name)),
  );
  const filledFields = requiredFields.filter(
    (field) => !missingFields.some((entry) => entry.name === field.name),
  );

  return {
    required: requiredFields,
    filled: filledFields,
    missing: missingFields,
    derivable: missingFields.filter((field) => field.derivable),
    notDerivable: missingFields.filter((field) => !field.derivable),
    source: profile ? "profile" : "none",
  };
}

/* ------------------------------------------------------------------ */
/* The gap endpoint of the backend                                     */
/* ------------------------------------------------------------------ */

/** Reads the answer of the gap endpoint of the backend. */
export async function fetchDetailsGap(
  client: ApiClient,
  opportunityId: string,
): Promise<DetailsGap> {
  const raw = await client.get<RawGapReport>(
    `/api/v1/opportunities/${opportunityId}/details/gaps`,
  );

  const required = raw.required ?? [];
  const filled = raw.filled ?? [];
  const missing = raw.missing ?? [];
  const derivableNames = raw.derivable ?? [];
  const notDerivable = raw.not_derivable ?? [];

  /** The reason the backend gave for a field it cannot derive. */
  const reasonOf = (name: string): string | null => {
    const entry = notDerivable.find(
      (item) => normalizeName(item.field ?? "") === normalizeName(name),
    );
    return entry?.reason ?? null;
  };

  const labelOfEntry = (name: string): string => {
    const entry = notDerivable.find(
      (item) => normalizeName(item.field ?? "") === normalizeName(name),
    );
    return entry?.label ?? labelOf(name);
  };

  const derivableFields: GapField[] = missing
    .filter((name) => derivableNames.some((item) => normalizeName(item) === normalizeName(name)))
    .map((name) => ({
      name,
      label: labelOf(name),
      field: fixedFieldOf(name),
      derivable: true,
      reason: "The business profile of the project can supply this value.",
    }));

  const notDerivableFields: GapField[] = missing
    .filter((name) => !derivableNames.some((item) => normalizeName(item) === normalizeName(name)))
    .map((name) => ({
      name,
      label: labelOfEntry(name),
      field: fixedFieldOf(name),
      derivable: false,
      reason: reasonOf(name) ?? "The business profile of the project can not supply this value.",
    }));

  const missingFields = [
    ...missing
      .filter((name) => derivableNames.some((item) => normalizeName(item) === normalizeName(name)))
      .map((name) => derivableFields.find((field) => field.name === name) as GapField),
    ...missing
      .filter((name) => !derivableNames.some((item) => normalizeName(item) === normalizeName(name)))
      .map((name) => notDerivableFields.find((field) => field.name === name) as GapField),
  ];

  return {
    required: required.map((name) => ({
      name,
      label: labelOf(name),
      field: fixedFieldOf(name),
      derivable: derivableNames.some((item) => normalizeName(item) === normalizeName(name)),
      reason: "",
    })),
    filled: filled.map((name) => ({
      name,
      label: labelOf(name),
      field: fixedFieldOf(name),
      derivable: false,
      reason: "The value is already filled in.",
    })),
    missing: missingFields,
    derivable: derivableFields,
    notDerivable: notDerivableFields,
    source: raw.source ?? "none",
  };
}

/** The business profile of a project (null when the project has none). */
async function loadProfile(
  client: ApiClient,
  projectId: string | null,
): Promise<BusinessProfile | null> {
  if (!projectId) return null;
  const project = await client.get<Project>(`/api/v1/projects/${projectId}`);
  if (!project.business_profile_id) return null;
  const profiles = await client.get<BusinessProfile[]>("/api/v1/profiles");
  return profiles.find((profile) => profile.id === project.business_profile_id) ?? null;
}

/**
 * The gap report of an opportunity.
 *
 * The backend answers it.  When the endpoint does not exist (yet) the report
 * is derived in the client from the details and the business profile - the
 * caller sees which of the two it got.
 */
export async function loadDetailsGap(
  client: ApiClient,
  opportunityId: string,
  projectId: string | null,
): Promise<{ gap: DetailsGap; source: "backend" | "client" }> {
  try {
    return { gap: await fetchDetailsGap(client, opportunityId), source: "backend" };
  } catch (error) {
    if (!isNotFoundError(error)) throw error;
    const details = await client.get<{ required?: string[]; missing?: string[] }>(
      `/api/v1/opportunities/${opportunityId}/details`,
    );
    const profile = await loadProfile(client, projectId);
    return { gap: buildDetailsGap(details, profile), source: "client" };
  }
}
