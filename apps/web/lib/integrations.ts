"use client";

import { apiClient } from "./api";
import { api } from "@autobacklinker/api-client";
import type { IntegrationCredential } from "@autobacklinker/shared-types";

/**
 * Integration credentials live on the backend (`/api/v1/integrations/*`).
 * Secrets are encrypted at rest and are never returned - the API only reports
 * whether a credential exists and shows a masked hint.
 */
export const CREDENTIALS_PATH = "/api/v1/integrations/credentials";

export interface CredentialInput {
  provider: string;
  label: string;
  apiKey: string;
  model?: string;
}

export interface IntegrationProvider {
  key: string;
  name: string;
  purpose: string;
  docs: string;
  configured: boolean;
}

export interface CredentialsProbe {
  available: boolean;
  credentials: IntegrationCredential[];
  providers: IntegrationProvider[];
  /** Set when the endpoint responded with something other than 404. */
  error: unknown;
}

function isMissing(error: unknown): boolean {
  const status = (error as { status?: number } | null)?.status;
  return status === 404 || status === 405 || status === 501;
}

export async function probeCredentials(): Promise<CredentialsProbe> {
  try {
    const [credentials, providers] = await Promise.all([
      apiClient.get<IntegrationCredential[]>(CREDENTIALS_PATH),
      api.integrations
        .providers(apiClient)
        .catch(() => [] as IntegrationProvider[]),
    ]);
    return { available: true, credentials, providers, error: null };
  } catch (error) {
    if (isMissing(error)) {
      return { available: false, credentials: [], providers: [], error: null };
    }
    return { available: false, credentials: [], providers: [], error };
  }
}

export async function saveCredential(input: CredentialInput): Promise<IntegrationCredential> {
  return apiClient.post<IntegrationCredential>(CREDENTIALS_PATH, {
    provider: input.provider,
    label: input.label,
    api_key: input.apiKey,
    ...(input.model ? { model: input.model } : {}),
  });
}

export async function deleteCredential(id: string): Promise<void> {
  return apiClient.delete<void>(`${CREDENTIALS_PATH}/${id}`);
}

/** Providers that expose a model setting (AI backends). */
export const AI_PROVIDER_KEYS = ["openai", "anthropic", "gemini", "ollama", "azure-openai"];
