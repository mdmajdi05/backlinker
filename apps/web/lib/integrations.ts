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
  baseUrl?: string;
}

export interface IntegrationProvider {
  key: string;
  name: string;
  purpose: string;
  docs: string;
  configured: boolean;
}

/** The credentials the backend currently stores for this workspace. */
export async function loadCredentials(): Promise<IntegrationCredential[]> {
  return apiClient.get<IntegrationCredential[]>(CREDENTIALS_PATH);
}

/** The providers the backend knows about and whether a secret is stored. */
export async function loadProviders(): Promise<IntegrationProvider[]> {
  return api.integrations.providers(apiClient);
}

export async function saveCredential(input: CredentialInput): Promise<IntegrationCredential> {
  return apiClient.post<IntegrationCredential>(CREDENTIALS_PATH, {
    provider: input.provider,
    label: input.label,
    api_key: input.apiKey,
    ...(input.model ? { model: input.model } : {}),
    ...(input.baseUrl ? { base_url: input.baseUrl } : {}),
  });
}

export async function deleteCredential(id: string): Promise<void> {
  return apiClient.delete<void>(`${CREDENTIALS_PATH}/${id}`);
}

/** Providers that expose a model setting (AI backends). */
export const AI_PROVIDER_KEYS = [
  "openai",
  "anthropic",
  "openrouter",
  "ollama",
  "groq",
  "lmstudio",
  "local",
];

/**
 * Local AI backends (Ollama, LM Studio, a local OpenAI compatible server)
 * run on this machine and need no API key - a model name is enough.
 */
export const KEYLESS_AI_PROVIDERS = ["ollama", "lmstudio", "local"] as const;

export function isKeylessAiProvider(provider: string): boolean {
  return (KEYLESS_AI_PROVIDERS as readonly string[]).includes(
    provider.trim().toLowerCase(),
  );
}
