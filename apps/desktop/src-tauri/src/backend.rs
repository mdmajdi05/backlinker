//! Supervision of the bundled Python backend (the "sidecar").
//!
//! The sidecar is a self contained FastAPI application that is shipped next
//! to the desktop binary. It is started with a private configuration:
//!
//! * it only listens on `127.0.0.1` (never on a public interface),
//! * it stores its database inside the OS application data directory,
//! * it runs with a random, per launch API token.

use std::fs::{self, File, OpenOptions};
use std::io::{BufRead, BufReader, Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::thread::{self, JoinHandle};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use rand::RngCore;
use serde::Serialize;
use tauri::{AppHandle, Manager};

/// Maximum number of automatic restarts after a crash.
pub const MAX_RESTARTS: u32 = 3;
/// Default port of the local backend.
pub const DEFAULT_PORT: u16 = 8765;
/// Maximum number of log lines kept in memory / returned to the UI.
const MAX_LOG_LINES: usize = 2000;

/// Serializable snapshot of the sidecar state.
#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BackendStatus {
    pub running: bool,
    pub healthy: bool,
    pub pid: Option<u32>,
    pub port: u16,
    pub base_url: String,
    pub data_dir: String,
    pub log_path: String,
    pub local_token: Option<String>,
    pub restarts: u32,
    pub last_error: Option<String>,
    pub started_at: Option<String>,
    pub version: Option<String>,
    pub sidecar_path: Option<String>,
    pub mode: String,
}

struct Inner {
    port: u16,
    data_dir: PathBuf,
    log_path: PathBuf,
    token: String,
    restarts: u32,
    last_error: Option<String>,
    started_at: Option<String>,
    healthy: bool,
    sidecar_path: Option<PathBuf>,
}

/// Shared state between the Tauri commands and the supervisor thread.
pub struct BackendState {
    inner: Mutex<Inner>,
    child: Arc<Mutex<Option<Child>>>,
    supervisor: Mutex<Option<JoinHandle<()>>>,
    generation: AtomicU64,
    shutdown: AtomicBool,
}

impl BackendState {
    pub fn new() -> Self {
        let data_dir = app_data_dir();
        let logs_dir = data_dir.join("logs");
        let _ = fs::create_dir_all(&logs_dir);
        // The local token is persisted in the application data directory so
        // that every launch of the app - and every sidecar it starts - speaks
        // the same language.  A random token per launch would break the
        // session as soon as the app is restarted while the old backend is
        // still running.
        let token = load_or_create_token(&data_dir);
        Self {
            inner: Mutex::new(Inner {
                port: DEFAULT_PORT,
                log_path: logs_dir.join("backend.log"),
                data_dir,
                token,
                restarts: 0,
                last_error: None,
                started_at: None,
                healthy: false,
                sidecar_path: None,
            }),
            child: Arc::new(Mutex::new(None)),
            supervisor: Mutex::new(None),
            generation: AtomicU64::new(0),
            shutdown: AtomicBool::new(false),
        }
    }

    pub fn status(&self) -> BackendStatus {
        let inner = self.inner.lock().expect("backend state poisoned");
        let pid = self
            .child
            .lock()
            .expect("backend child poisoned")
            .as_ref()
            .map(|child| child.id());
        BackendStatus {
            running: pid.is_some(),
            healthy: inner.healthy,
            pid,
            port: inner.port,
            base_url: format!("http://127.0.0.1:{}", inner.port),
            data_dir: inner.data_dir.to_string_lossy().to_string(),
            log_path: inner.log_path.to_string_lossy().to_string(),
            local_token: Some(inner.token.clone()),
            restarts: inner.restarts,
            last_error: inner.last_error.clone(),
            started_at: inner.started_at.clone(),
            version: None,
            sidecar_path: inner
                .sidecar_path
                .as_ref()
                .map(|path| path.to_string_lossy().to_string()),
            mode: "desktop".to_string(),
        }
    }

    /// Starts (or restarts) the sidecar and (re)arms the supervisor.
    pub fn start(
        self: &Arc<Self>,
        app: &AppHandle,
        port: Option<u16>,
    ) -> Result<BackendStatus, String> {
        self.stop_process();
        self.generation.fetch_add(1, Ordering::SeqCst);

        let requested_port = port.unwrap_or(DEFAULT_PORT);
        let port = if requested_port == 0 {
            DEFAULT_PORT
        } else {
            requested_port
        };

        self.spawn_process(app, port)?;
        self.spawn_supervisor(app.clone());
        Ok(self.status())
    }

    /// Spawns the sidecar process (without touching the supervisor lifecycle).
    fn spawn_process(self: &Arc<Self>, app: &AppHandle, port: u16) -> Result<(), String> {
        let mut inner = self.inner.lock().expect("backend state poisoned");
        inner.port = port;
        inner.healthy = false;
        inner.last_error = None;

        let data_dir = inner.data_dir.clone();
        let log_path = inner.log_path.clone();
        let token = inner.token.clone();

        if let Err(err) = fs::create_dir_all(&data_dir) {
            let message = format!("Cannot create the data directory: {err}");
            inner.last_error = Some(message.clone());
            return Err(message);
        }
        if let Some(parent) = log_path.parent() {
            let _ = fs::create_dir_all(parent);
        }

        let sidecar = match locate_bundled_backend(app) {
            Some(launcher) => launcher,
            None => {
                let message = "The bundled backend is missing. Build it with \
                              `npm run backend` (scripts/build-backend.sh) before starting \
                              the local backend."
                    .to_string();
                inner.last_error = Some(message.clone());
                return Err(message);
            }
        };
        inner.sidecar_path = Some(match &sidecar {
            BackendLauncher::Python { program, .. } => program.clone(),
            BackendLauncher::Binary { program } => program.clone(),
        });

        // A backend of a previous launch may still be running on the port.
        // Reusing a healthy one is the best case; a stale process that no
        // longer answers is stopped so the new sidecar can bind.
        if http_health(port, &token).unwrap_or(false) {
            inner.healthy = true;
            inner.started_at = Some(now_iso8601());
            inner.last_error = None;
            return Ok(());
        }
        if free_port(port) {
            inner.healthy = false;
        }

        let mut command = match &sidecar {
            BackendLauncher::Python {
                program,
                script,
                python_path,
            } => {
                let mut command = Command::new(program);
                command.arg(script);
                command.env("PYTHONPATH", python_path);
                command.env("PYTHONDONTWRITEBYTECODE", "1");
                command
            }
            BackendLauncher::Binary { program } => Command::new(program),
        };
        command
            .arg("--host")
            .arg("127.0.0.1")
            .arg("--port")
            .arg(port.to_string())
            .env("AUTOBL_DATA_DIR", &data_dir)
            .env("AUTOBL_ENVIRONMENT", "desktop")
            .env("AUTOBL_STORAGE_MODE", "local")
            .env("AUTOBL_WORKER_ENABLED", "true")
            .env("AUTOBL_LOCAL_TOKEN", &token)
            .env("AUTOBL_HOST", "127.0.0.1")
            .env("AUTOBL_PORT", port.to_string())
            .current_dir(&data_dir)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        let mut child = match command.spawn() {
            Ok(child) => child,
            Err(err) => {
                let message = format!("Cannot start the backend sidecar: {err}");
                inner.last_error = Some(message.clone());
                return Err(message);
            }
        };

        inner.started_at = Some(now_iso8601());
        inner.restarts = 0;

        if let Some(stdout) = child.stdout.take() {
            spawn_log_pump(stdout, log_path.clone(), "stdout");
        }
        if let Some(stderr) = child.stderr.take() {
            spawn_log_pump(stderr, log_path.clone(), "stderr");
        }

        append_log(
            &log_path,
            "desktop",
            &format!("Started backend sidecar {sidecar:?} on port {port}"),
        );

        *self.child.lock().expect("backend child poisoned") = Some(child);
        Ok(())
    }

    /// Stops the sidecar (the supervisor thread exits with it).
    pub fn stop(&self) -> Result<BackendStatus, String> {
        self.stop_process();
        self.generation.fetch_add(1, Ordering::SeqCst);
        let mut inner = self.inner.lock().expect("backend state poisoned");
        inner.healthy = false;
        inner.started_at = None;
        Ok(self.status())
    }

    /// Called when the application exits.
    pub fn shutdown(&self) {
        self.shutdown.store(true, Ordering::SeqCst);
        self.generation.fetch_add(1, Ordering::SeqCst);
        self.stop_process();
    }

    fn stop_process(&self) {
        let mut guard = self.child.lock().expect("backend child poisoned");
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }

    /// Returns the last `lines` lines of the backend log file.
    pub fn logs(&self, lines: usize) -> Vec<String> {
        let log_path = {
            let inner = self.inner.lock().expect("backend state poisoned");
            inner.log_path.clone()
        };
        let file = match File::open(&log_path) {
            Ok(file) => file,
            Err(_) => return Vec::new(),
        };
        let reader = BufReader::new(file);
        let mut collected: Vec<String> = Vec::new();
        for line in reader.lines() {
            match line {
                Ok(line) => {
                    collected.push(line);
                    if collected.len() > MAX_LOG_LINES {
                        collected.remove(0);
                    }
                }
                Err(_) => break,
            }
        }
        let take = lines.clamp(1, MAX_LOG_LINES);
        let start = collected.len().saturating_sub(take);
        collected.split_off(start)
    }

    fn spawn_supervisor(self: &Arc<Self>, app: AppHandle) {
        let generation = self.generation.fetch_add(1, Ordering::SeqCst) + 1;
        let state = Arc::clone(self);
        let handle = thread::spawn(move || {
            let mut backoff_secs: u64 = 1;
            let mut ticks: u64 = 0;
            loop {
                if state.is_stale(generation) {
                    break;
                }
                thread::sleep(Duration::from_secs(2));
                if state.is_stale(generation) {
                    break;
                }

                ticks += 1;
                if state.child_exited() {
                    let (log_path, port, token) = {
                        let inner = state.inner.lock().expect("backend state poisoned");
                        (inner.log_path.clone(), inner.port, inner.token.clone())
                    };
                    // A backend that is already running (for example the one
                    // of a previous launch that was adopted) is not a crash -
                    // keep using it instead of restarting in a loop.
                    if http_health(port, &token).unwrap_or(false) {
                        let mut inner = state.inner.lock().expect("backend state poisoned");
                        inner.healthy = true;
                        inner.last_error = None;
                        append_log(
                            &log_path,
                            "desktop",
                            "Using the backend that is already running on this port.",
                        );
                        continue;
                    }
                    append_log(
                        &log_path,
                        "desktop",
                        "The backend sidecar exited unexpectedly.",
                    );

                    let restarts = {
                        let mut inner = state.inner.lock().expect("backend state poisoned");
                        inner.healthy = false;
                        inner.restarts += 1;
                        inner.restarts
                    };
                    if restarts > MAX_RESTARTS {
                        let mut inner = state.inner.lock().expect("backend state poisoned");
                        inner.last_error = Some(format!(
                            "The backend crashed {restarts} times and was not restarted automatically."
                        ));
                        let message = inner.last_error.clone().unwrap_or_default();
                        append_log(&log_path, "desktop", &message);
                        break;
                    }

                    let delay = backoff_secs.min(30);
                    append_log(
                        &log_path,
                        "desktop",
                        &format!(
                            "Restarting the backend in {delay}s (restart {restarts}/{MAX_RESTARTS})."
                        ),
                    );
                    thread::sleep(Duration::from_secs(delay));
                    backoff_secs = (backoff_secs * 2).min(30);

                    let port = {
                        let inner = state.inner.lock().expect("backend state poisoned");
                        inner.port
                    };
                    if let Err(err) = state.spawn_process(&app, port) {
                        let mut inner = state.inner.lock().expect("backend state poisoned");
                        inner.last_error = Some(err);
                    }
                    continue;
                }

                // Health probe (roughly every 10 seconds).
                if ticks % 5 == 0 {
                    let (port, token) = {
                        let inner = state.inner.lock().expect("backend state poisoned");
                        (inner.port, inner.token.clone())
                    };
                    let healthy = http_health(port, &token).unwrap_or(false);
                    let mut inner = state.inner.lock().expect("backend state poisoned");
                    inner.healthy = healthy;
                    if !healthy {
                        inner.last_error =
                            Some("The backend does not answer on the health endpoint yet.".to_string());
                    } else if inner
                        .last_error
                        .as_deref()
                        .map(|message| message.contains("health endpoint"))
                        .unwrap_or(false)
                    {
                        inner.last_error = None;
                    }
                }
            }
        });

        let mut supervisor = self.supervisor.lock().expect("backend supervisor poisoned");
        if let Some(previous) = supervisor.take() {
            let _ = previous.join();
        }
        *supervisor = Some(handle);
    }

    fn is_stale(&self, generation: u64) -> bool {
        self.shutdown.load(Ordering::SeqCst)
            || self.generation.load(Ordering::SeqCst) != generation
    }

    fn child_exited(&self) -> bool {
        let mut guard = self.child.lock().expect("backend child poisoned");
        match guard.as_mut() {
            Some(child) => match child.try_wait() {
                Ok(Some(_)) => {
                    *guard = None;
                    true
                }
                Ok(None) => false,
                Err(_) => {
                    *guard = None;
                    true
                }
            },
            None => false,
        }
    }
}

impl Default for BackendState {
    fn default() -> Self {
        Self::new()
    }
}

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */

/// The OS application data directory of the product (not the bundle id).
pub fn app_data_dir() -> PathBuf {
    if cfg!(target_os = "windows") {
        let base = std::env::var("APPDATA").unwrap_or_else(|_| {
            let profile = std::env::var("USERPROFILE").unwrap_or_default();
            PathBuf::from(profile)
                .join("AppData")
                .join("Roaming")
                .to_string_lossy()
                .to_string()
        });
        PathBuf::from(base).join("AutoBacklinker")
    } else if cfg!(target_os = "macos") {
        let home = std::env::var("HOME").unwrap_or_default();
        PathBuf::from(home)
            .join("Library")
            .join("Application Support")
            .join("AutoBacklinker")
    } else {
        let base = std::env::var("XDG_DATA_HOME").unwrap_or_else(|_| {
            let home = std::env::var("HOME").unwrap_or_default();
            PathBuf::from(home)
                .join(".local")
                .join("share")
                .to_string_lossy()
                .to_string()
        });
        PathBuf::from(base).join("auto-backlinker")
    }
}

/// Directory that holds the local agent configuration and logs.
pub fn agent_home_dir() -> PathBuf {
    let home = std::env::var("HOME")
        .or_else(|_| std::env::var("USERPROFILE"))
        .unwrap_or_default();
    PathBuf::from(home).join(".autobacklinker")
}

/// A random, URL safe token used for the local API.
pub fn random_token() -> String {
    let mut bytes = [0u8; 32];
    rand::thread_rng().fill_bytes(&mut bytes);
    bytes
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>()
}

/// The target triple used to name the sidecar binary.
pub fn target_triple() -> String {
    let arch = match std::env::consts::ARCH {
        "aarch64" => "aarch64",
        "x86_64" => "x86_64",
        other => other,
    };
    let os = match std::env::consts::OS {
        "macos" => "apple-darwin",
        "windows" => "pc-windows-msvc",
        "linux" => "unknown-linux-gnu",
        other => other,
    };
    format!("{arch}-{os}")
}

/// Finds the bundled sidecar binary.
pub fn locate_sidecar(app: &AppHandle) -> Option<PathBuf> {
    let suffix = std::env::consts::EXE_SUFFIX;
    let triple = target_triple();
    let names = [
        format!("autobacklinker-api-{triple}{suffix}"),
        format!("autobacklinker-api{suffix}"),
    ];

    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Ok(resource_dir) = app.path().resource_dir() {
        for name in names.iter() {
            candidates.push(resource_dir.join("binaries").join(name));
            candidates.push(resource_dir.join(name));
        }
        // macOS: the sidecar is copied next to the executable
        // (<app>.app/Contents/MacOS/<name>).
        if let Some(macos_dir) = resource_dir.parent().map(|parent| parent.join("MacOS")) {
            for name in names.iter() {
                candidates.push(macos_dir.join(name));
            }
        }
    }
    if let Ok(executable) = std::env::current_exe() {
        if let Some(dir) = executable.parent() {
            for name in names.iter() {
                candidates.push(dir.join("binaries").join(name));
                candidates.push(dir.join(name));
            }
        }
    }
    // Development mode: the sidecar lives in the crate directory.
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("binaries");
    for name in names.iter() {
        candidates.push(manifest.join(name));
    }

    candidates.into_iter().find(|path| path.is_file())
}

/// Serialises the log writes - stdout and stderr are pumped by two threads.
fn log_lock() -> &'static Mutex<()> {
    static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
    LOCK.get_or_init(|| Mutex::new(()))
}

/// Appends a line to the backend log file.
pub fn append_log(log_path: &Path, source: &str, message: &str) {
    let _guard = log_lock().lock().unwrap_or_else(|error| error.into_inner());
    if let Some(parent) = log_path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    if let Ok(mut file) = OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_path)
    {
        let _ = writeln!(file, "[{}] [{}] {}", now_iso8601(), source, message);
    }
}

/// Name of the file that holds the shared local token.
const TOKEN_FILE: &str = "local-token";

/// Load the persisted local token or create it on the first launch.
///
/// The token lives in the application data directory (mode 0600) so that the
/// desktop app and the sidecar it supervises always agree - even after a
/// crash, a reinstall of the app or a second instance of the app.
fn load_or_create_token(data_dir: &Path) -> String {
    let path = data_dir.join(TOKEN_FILE);
    if let Ok(existing) = fs::read_to_string(&path) {
        let trimmed = existing.trim().to_string();
        if !trimmed.is_empty() {
            return trimmed;
        }
    }
    let token = random_token();
    let _ = fs::create_dir_all(data_dir);
    if fs::write(&path, &token).is_ok() {
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let _ = fs::set_permissions(&path, fs::Permissions::from_mode(0o600));
        }
    }
    token
}

/// Stop a stale process that still holds the port.
fn free_port(port: u16) -> bool {
    let output = Command::new("/usr/sbin/lsof")
        .args(["-ti", &format!(":{port}")])
        .output();
    let Ok(output) = output else {
        return false;
    };
    let pids: Vec<u32> = String::from_utf8_lossy(&output.stdout)
        .lines()
        .filter_map(|line| line.trim().parse::<u32>().ok())
        .collect();
    if pids.is_empty() {
        return false;
    }
    for pid in pids {
        let _ = Command::new("/bin/kill")
            .args(["-TERM", &pid.to_string()])
            .status();
    }
    // Give the process a moment to release the socket.
    for _ in 0..20 {
        std::thread::sleep(Duration::from_millis(150));
        if !port_is_open(port) {
            return true;
        }
    }
    false
}

/// Check whether something still listens on the given port.
fn port_is_open(port: u16) -> bool {
    use std::net::TcpStream;
    use std::time::Duration;

    let address = format!("127.0.0.1:{port}");
    match address.parse() {
        Ok(parsed) => TcpStream::connect_timeout(&parsed, Duration::from_millis(400)).is_ok(),
        Err(_) => false,
    }
}

/// How the bundled backend is started.
#[derive(Debug)]
enum BackendLauncher {
    /// The multi architecture backend: a standalone CPython plus the
    /// dependencies.  This is the preferred way because one build works on
    /// Intel and Apple Silicon.
    Python {
        program: PathBuf,
        script: PathBuf,
        python_path: String,
    },
    /// The single file executable built with PyInstaller (fallback).
    Binary { program: PathBuf },
}

/// Locate the backend that is bundled into the application.
///
/// The application ships the backend for both macOS architectures and picks
/// the one that matches the machine it runs on.
fn locate_bundled_backend(app: &AppHandle) -> Option<BackendLauncher> {    if let Ok(resources) = app.path().resource_dir() {
        let arch = match std::env::consts::ARCH {
            "aarch64" => "aarch64",
            "x86_64" => "x86_64",
            other => other,
        };
        let dir = resources.join("backend").join(arch);
        let program = dir.join("runtime").join("bin").join("python3.12");
        let script = dir.join("sidecar_launcher.py");
        if program.is_file() && script.is_file() {
            let python_path = format!(
                "{}:{}",
                dir.join("site-packages").display(),
                dir.display()
            );
            return Some(BackendLauncher::Python {
                program,
                script,
                python_path,
            });
        }
    }
    locate_sidecar(app).map(|program| BackendLauncher::Binary { program })
}

/// Path of the browser runtime of the bundled backend (if it is installed).
pub fn browser_runtime(app: &AppHandle) -> Option<String> {
    let launcher = locate_bundled_backend(app)?;
    let (program, script, python_path) = match launcher {
        BackendLauncher::Python {
            program,
            script,
            python_path,
        } => (program, Some(script), Some(python_path)),
        BackendLauncher::Binary { program } => (program, None, None),
    };
    let mut command = Command::new(&program);
    if let Some(script) = script {
        command.arg(script);
    }
    if let Some(python_path) = python_path {
        command.env("PYTHONPATH", python_path);
    }
    let output = command
        .args(["-c", "import playwright, pathlib; print(pathlib.Path(playwright.__file__).parent)"])
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let text = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if text.is_empty() {
        None
    } else {
        Some(text)
    }
}

/// Download the browser runtime that the Playwright adapter needs.
pub fn install_browser_runtime(app: &AppHandle) -> Result<String, String> {
    let launcher = locate_bundled_backend(app)
        .ok_or_else(|| "The bundled backend is missing.".to_string())?;
    let (program, script, python_path) = match launcher {
        BackendLauncher::Python {
            program,
            script,
            python_path,
        } => (program, Some(script), Some(python_path)),
        BackendLauncher::Binary { program } => (program, None, None),
    };
    let mut command = Command::new(&program);
    if let Some(script) = script {
        command.arg(script);
    }
    if let Some(python_path) = python_path {
        command.env("PYTHONPATH", python_path);
    }
    let output = command
        .args(["-m", "playwright", "install", "chromium"])
        .output()
        .map_err(|err| format!("Cannot start the download: {err}"))?;
    let text = String::from_utf8_lossy(&output.stdout).to_string();
    if output.status.success() {
        Ok(format!("The browser runtime was installed.\n{text}"))
    } else {
        let errors = String::from_utf8_lossy(&output.stderr).to_string();
        Err(format!(
            "The browser runtime could not be installed (exit code {}).\n{errors}\n{text}",
            output.status.code().unwrap_or(-1)
        ))
    }
}

fn spawn_log_pump<R: Read + Send + 'static>(
    source: R,
    log_path: PathBuf,
    label: &'static str,
) {
    thread::spawn(move || {
        let reader = BufReader::new(source);
        for line in reader.lines() {
            match line {
                Ok(line) => append_log(&log_path, label, &line),
                Err(_) => break,
            }
        }
    });
}

/// Minimal HTTP health probe (no external dependency).
fn http_health(port: u16, token: &str) -> Result<bool, String> {
    use std::net::TcpStream;
    use std::time::Duration;

    let mut stream = TcpStream::connect(("127.0.0.1", port)).map_err(|err| err.to_string())?;
    let timeout = Some(Duration::from_secs(3));
    let _ = stream.set_read_timeout(timeout);
    let _ = stream.set_write_timeout(timeout);

    let request = format!(
        "GET /health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nAccept: application/json\r\nAuthorization: Bearer {token}\r\nX-Local-Token: {token}\r\nConnection: close\r\n\r\n"
    );
    stream
        .write_all(request.as_bytes())
        .map_err(|err| err.to_string())?;

    let mut buffer = Vec::new();
    let mut chunk = [0u8; 1024];
    loop {
        match stream.read(&mut chunk) {
            Ok(0) => break,
            Ok(size) => {
                buffer.extend_from_slice(&chunk[..size]);
                if buffer.len() > 32 * 1024 {
                    break;
                }
            }
            Err(_) => break,
        }
    }

    let text = String::from_utf8_lossy(&buffer);
    let status_line = text.lines().next().unwrap_or_default();
    let code = status_line
        .split_whitespace()
        .nth(1)
        .and_then(|value| value.parse::<u16>().ok())
        .unwrap_or(0);
    Ok(code >= 200 && code < 400)
}

/// Current UTC time in ISO-8601 (second precision).
pub fn now_iso8601() -> String {
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or(0);
    format_epoch(seconds)
}

/// Formats a unix timestamp as ISO-8601 without pulling in a date library.
pub fn format_epoch(seconds: u64) -> String {
    let days = (seconds / 86_400) as i64;
    let remainder = seconds % 86_400;
    let hour = remainder / 3600;
    let minute = (remainder % 3600) / 60;
    let second = remainder % 60;

    // Days since 1970-01-01 -> civil date (Howard Hinnant's algorithm).
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = if m <= 2 { y + 1 } else { y };

    format!("{year:04}-{m:02}-{d:02}T{hour:02}:{minute:02}:{second:02}Z")
}
