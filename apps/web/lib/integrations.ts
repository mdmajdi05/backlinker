"use client";

import { apiClient } from "./api";
import type { IntegrationCredential } from "@autobacklinker/shared-types";

/**
 * Credential storage is not part of the typed transport yet. The helpers below
 * probe the backend for the documented REST shape and surface a clear
 * "not available" state instead of pretending that a key was saved.
 */
export const CREDENTIALS_PATH = "/api/v1/integrations/credentials";

export interface CredentialInput {
  provider: string;
  label: string;
  apiKey: string;
  model?: string;
}

export interface CredentialsProbe {
  available: boolean;
  credentials: IntegrationCredential[];
  /** Set when the endpoint responded with something other than 404. */
  error: unknown;
}

function isMissing(error: unknown): boolean {
  const status = (error as { status?: number } | null)?.status;
  return status === 404 || status === 405 || status === 501;
}

export async function probeCredentials(): Promise<CredentialsProbe> {
  try {
    const credentials = await apiClient.get<IntegrationCredential[]>(CREDENTIALS_PATH);
    return { available: true, credentials, error: null };
  } catch (error) {
    if (isMissing(error)) {
      return { available: false, credentials: [], error: null };
    }
    return { available: false, credentials: [], error };
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
