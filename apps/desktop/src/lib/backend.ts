/**
 * Bridge to the Rust side of the desktop app.
 *
 * Every helper degrades gracefully: when the UI runs in a plain browser
 * (`npm run dev` without Tauri) the native features are simply reported as
 * unavailable instead of throwing at import time.
 */

import { invoke } from "@tauri-apps/api/core";

export interface BackendStatus {
  running: boolean;
  healthy: boolean;
  pid: number | null;
  port: number;
  baseUrl: string;
  dataDir: string;
  logPath: string;
  localToken: string | null;
  restarts: number;
  lastError: string | null;
  startedAt: string | null;
  version: string | null;
  sidecarPath: string | null;
  mode: string;
}

export interface AgentStatus {
  installed: boolean;
  registered: boolean;
  deviceId: string | null;
  configPath: string;
  logPath: string;
  lastSeen: string | null;
}

export interface FileFilter {
  name: string;
  extensions: string[];
}

export const DEFAULT_BACKEND_PORT = 8765;

/** True when the UI is hosted by the Tauri webview. */
export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export class NativeUnavailableError extends Error {
  constructor(what: string) {
    super(`${what} is only available in the desktop build.`);
    this.name = "NativeUnavailableError";
  }
}

function requireTauri(what: string): void {
  if (!isTauri()) throw new NativeUnavailableError(what);
}

export async function startBackend(port: number): Promise<BackendStatus> {
  requireTauri("Starting the local backend");
  return invoke<BackendStatus>("start_backend", { port });
}

export async function stopBackend(): Promise<BackendStatus> {
  requireTauri("Stopping the local backend");
  return invoke<BackendStatus>("stop_backend");
}

export async function restartBackend(port?: number): Promise<BackendStatus> {
  requireTauri("Restarting the local backend");
  return invoke<BackendStatus>("restart_backend", { port: port ?? null });
}

export async function getBackendStatus(): Promise<BackendStatus> {
  requireTauri("The local backend status");
  return invoke<BackendStatus>("backend_status");
}

export async function getBackendLogs(lines = 200): Promise<string[]> {
  requireTauri("The backend log");
  return invoke<string[]>("backend_logs", { lines });
}

export async function notify(title: string, body: string): Promise<void> {
  requireTauri("Native notifications");
  await invoke<void>("notify", { title, body });
}

export async function pickFile(
  filters?: FileFilter[],
): Promise<string | null> {
  requireTauri("The native file picker");
  return invoke<string | null>("pick_file", { filters: filters ?? null });
}

export async function saveFile(
  suggestedName: string,
  filters?: FileFilter[],
): Promise<string | null> {
  requireTauri("The native save dialog");
  return invoke<string | null>("save_file", {
    suggestedName,
    filters: filters ?? null,
  });
}

export async function openPath(path: string): Promise<void> {
  requireTauri("Opening files");
  await invoke<void>("open_path", { path });
}

export async function readFileBytes(path: string): Promise<Uint8Array> {
  requireTauri("Reading local files");
  return invoke<number[]>("read_file", { path }).then((bytes) =>
    Uint8Array.from(bytes),
  );
}

export async function writeFileBytes(
  path: string,
  contents: Uint8Array,
): Promise<void> {
  requireTauri("Writing local files");
  await invoke<void>("write_file", { path, contents: Array.from(contents) });
}

export async function getAgentStatus(): Promise<AgentStatus> {
  requireTauri("The local agent status");
  return invoke<AgentStatus>("agent_status");
}

/* ------------------------------------------------------------------ */
/* Optional JS plugin helpers (used when the plugin API is present)    */
/* ------------------------------------------------------------------ */

/** Native notification through the official plugin, with a Rust fallback. */
export async function sendNativeNotification(
  title: string,
  body: string,
): Promise<boolean> {
  if (!isTauri()) return false;
  try {
    const plugin = await import("@tauri-apps/plugin-notification");
    let granted = await plugin.isPermissionGranted();
    if (!granted) {
      const permission = await plugin.requestPermission();
      granted = permission === "granted";
    }
    if (!granted) return false;
    plugin.sendNotification({ title, body });
    return true;
  } catch {
    try {
      await notify(title, body);
      return true;
    } catch {
      return false;
    }
  }
}

export interface PickedFile {
  path: string;
  name: string;
  bytes: Uint8Array;
}

/**
 * Opens the native picker and reads the selected file.
 * Falls back to the Rust `read_file` command when the fs plugin scope does
 * not cover the picked path.
 */
export async function pickAndReadFile(
  filters?: FileFilter[],
): Promise<PickedFile | null> {
  const path = await pickFile(filters);
  if (!path) return null;

  let bytes: Uint8Array | null = null;
  try {
    const fs = await import("@tauri-apps/plugin-fs");
    bytes = await fs.readFile(path);
  } catch {
    bytes = null;
  }
  if (!bytes) {
    bytes = await readFileBytes(path);
  }

  const name = path.split(/[\\/]/).pop() ?? path;
  return { path, name, bytes };
}

/** Saves bytes with the native dialog, falling back to a browser download. */
export async function saveBytes(
  suggestedName: string,
  bytes: Uint8Array,
  filters?: FileFilter[],
): Promise<string | null> {
  const path = await saveFile(suggestedName, filters);
  if (!path) return null;

  try {
    const fs = await import("@tauri-apps/plugin-fs");
    await fs.writeFile(path, bytes);
    return path;
  } catch {
    await writeFileBytes(path, bytes);
    return path;
  }
}
