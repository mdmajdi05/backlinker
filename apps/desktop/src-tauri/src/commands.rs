//! Tauri commands exposed to the React frontend.

use std::fs;
use std::path::PathBuf;
use std::sync::Arc;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, State};
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_notification::NotificationExt;
use tauri_plugin_shell::ShellExt;

use crate::backend::{self, BackendState, BackendStatus};

type Shared<'a> = State<'a, Arc<BackendState>>;

/// A file dialog filter (mirrors the shape used by the dialog plugin).
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FileFilter {
    pub name: String,
    pub extensions: Vec<String>,
}

/// Status of the local automation agent.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AgentStatus {
    pub installed: bool,
    pub registered: bool,
    pub device_id: Option<String>,
    pub config_path: String,
    pub log_path: String,
    pub last_seen: Option<String>,
}

/* ------------------------------------------------------------------ */
/* Backend lifecycle                                                   */
/* ------------------------------------------------------------------ */

#[tauri::command]
pub fn start_backend(
    app: AppHandle,
    state: Shared<'_>,
    port: Option<u16>,
) -> Result<BackendStatus, String> {
    state.start(&app, port)
}

#[tauri::command]
pub fn stop_backend(state: Shared<'_>) -> Result<BackendStatus, String> {
    state.stop()
}

#[tauri::command]
pub fn restart_backend(app: AppHandle, state: Shared<'_>) -> Result<BackendStatus, String> {
    state.stop()?;
    state.start(&app, None)
}

#[tauri::command]
pub fn backend_status(state: Shared<'_>) -> Result<BackendStatus, String> {
    Ok(state.status())
}

#[tauri::command]
pub fn backend_logs(state: Shared<'_>, lines: Option<u32>) -> Result<Vec<String>, String> {
    Ok(state.logs(lines.unwrap_or(200) as usize))
}

/* ------------------------------------------------------------------ */
/* Native integrations                                                 */
/* ------------------------------------------------------------------ */

#[tauri::command]
pub fn notify(app: AppHandle, title: String, body: String) -> Result<(), String> {
    app.notification()
        .builder()
        .title(title)
        .body(body)
        .show()
        .map_err(|error| error.to_string())
}

#[tauri::command]
pub async fn pick_file(
    app: AppHandle,
    filters: Option<Vec<FileFilter>>,
) -> Result<Option<String>, String> {
    // `blocking_pick_file` must not run on the main thread - an async command
    // is executed on the async runtime (see the plugin documentation).
    let mut dialog = app.dialog().file();
    if let Some(filters) = filters {
        for filter in filters {
            let extensions: Vec<&str> =
                filter.extensions.iter().map(|value| value.as_str()).collect();
            dialog = dialog.add_filter(&filter.name, &extensions);
        }
    }
    let picked = dialog.blocking_pick_file();
    Ok(picked
        .and_then(|path| path.into_path().ok())
        .map(|path: PathBuf| path.to_string_lossy().to_string()))
}

#[tauri::command]
pub async fn save_file(
    app: AppHandle,
    suggested_name: String,
    filters: Option<Vec<FileFilter>>,
) -> Result<Option<String>, String> {
    let mut dialog = app.dialog().file().set_file_name(&suggested_name);
    if let Some(filters) = filters {
        for filter in filters {
            let extensions: Vec<&str> =
                filter.extensions.iter().map(|value| value.as_str()).collect();
            dialog = dialog.add_filter(&filter.name, &extensions);
        }
    }
    let picked = dialog.blocking_save_file();
    Ok(picked
        .and_then(|path| path.into_path().ok())
        .map(|path: PathBuf| path.to_string_lossy().to_string()))
}

#[tauri::command]
// The shell plugin is still a hard requirement of this build (it is listed in
// Cargo.toml); its `open` helper is deprecated in favour of tauri-plugin-opener
// but works on every supported platform.
#[allow(deprecated)]
pub fn open_path(app: AppHandle, path: String) -> Result<(), String> {
    app.shell()
        .open(path, None)
        .map_err(|error| error.to_string())
}

/// Reads a file (fallback for the fs plugin when the path is out of scope).
#[tauri::command]
pub fn read_file(path: String) -> Result<Vec<u8>, String> {
    fs::read(&path).map_err(|error| format!("Cannot read {path}: {error}"))
}

/// Writes a file (fallback for the fs plugin when the path is out of scope).
#[tauri::command]
pub fn write_file(path: String, contents: Vec<u8>) -> Result<(), String> {
    if let Some(parent) = PathBuf::from(&path).parent() {
        let _ = fs::create_dir_all(parent);
    }
    fs::write(&path, contents).map_err(|error| format!("Cannot write {path}: {error}"))
}

/* ------------------------------------------------------------------ */
/* Local agent                                                         */
/* ------------------------------------------------------------------ */

#[tauri::command]
pub fn agent_status() -> Result<AgentStatus, String> {
    let home = backend::agent_home_dir();
    let config_path = home.join("agent.json");
    let log_path = home.join("logs").join("agent.log");

    let mut device_id: Option<String> = None;
    let mut last_seen: Option<String> = None;
    let mut registered = false;

    if let Ok(text) = fs::read_to_string(&config_path) {
        if let Ok(value) = serde_json::from_str::<serde_json::Value>(&text) {
            registered = true;
            device_id = value
                .get("device_id")
                .and_then(|item| item.as_str())
                .map(|item| item.to_string());
            last_seen = value
                .get("last_seen")
                .and_then(|item| item.as_str())
                .map(|item| item.to_string());
        }
    }

    Ok(AgentStatus {
        installed: config_path.exists(),
        registered,
        device_id,
        config_path: config_path.to_string_lossy().to_string(),
        log_path: log_path.to_string_lossy().to_string(),
        last_seen,
    })
}
