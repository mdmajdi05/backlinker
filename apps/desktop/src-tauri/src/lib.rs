//! Auto Backlinker desktop client (Tauri 2).
//!
//! The Rust side owns the local backend sidecar: it starts it, supervises it,
//! restarts it after a crash and exposes its logs and state to the UI.

pub mod backend;
pub mod commands;

use std::sync::Arc;

use tauri::Manager;

use crate::backend::BackendState;

/// Build and run the desktop application.
pub fn run() {
    let state = Arc::new(BackendState::new());

    tauri::Builder::default()
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_process::init())
        .manage(Arc::clone(&state))
        .invoke_handler(tauri::generate_handler![
            commands::start_backend,
            commands::stop_backend,
            commands::restart_backend,
            commands::backend_status,
            commands::backend_logs,
            commands::notify,
            commands::pick_file,
            commands::save_file,
            commands::open_path,
            commands::read_file,
            commands::write_file,
            commands::agent_status,
        ])
        .setup(move |app| {
            // The desktop app owns its backend: start the sidecar as soon as
            // the window is up. Failures are reported in the UI, they must
            // never abort the application.
            let handle = app.handle().clone();
            let supervisor = Arc::clone(&state);
            std::thread::spawn(move || {
                std::thread::sleep(std::time::Duration::from_millis(400));
                if let Err(error) =
                    supervisor.start(&handle, Some(backend::DEFAULT_PORT))
                {
                    eprintln!("[autobacklinker] cannot start the backend: {error}");
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building the Auto Backlinker application")
        .run(move |app_handle, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                let state = app_handle.state::<Arc<BackendState>>();
                state.shutdown();
            }
            if let tauri::RunEvent::Exit = event {
                let state = app_handle.state::<Arc<BackendState>>();
                state.shutdown();
            }
        });
}
