# Auto Backlinker - Desktop app (Tauri 2)

The desktop client is a thin, native front end for the **same** FastAPI backend
that the web client uses. It adds everything a desktop application needs:

* a **bundled local backend** (Python sidecar) that runs on `127.0.0.1` only,
* **native notifications** for important events,
* a **native file picker** for Excel/CSV imports,
* **native save dialogs** for report downloads,
* **local task controls** (pause / resume / cancel) for tasks whose
  `execution_environment` is `LOCAL`,
* a **local backend status panel** (start / stop / restart, health, data
  directory, log tail).

The UI reuses the shared design system (`packages/ui`) and the shared API
client (`packages/api-client`) - there is no second implementation of the
protocol and no mock data anywhere in this app.

---

## Runs completely on your machine

The desktop application is a **local application**.  Everything it needs is
inside the application bundle, it stores its data on this computer and it
works without an internet connection.  A hosted ("cloud") backend is an
*optional* extra - it is never required and it is never used unless you
select it yourself.

### What is bundled

| Component | Where | Notes |
|-----------|-------|-------|
| The application | `Auto Backlinker.app/Contents/MacOS/autobacklinker-desktop` | Tauri 2 shell + the React frontend |
| The backend | `Auto Backlinker.app/Contents/Resources/backend/<arch>/` | a standalone CPython 3.12 (`runtime/`), the dependencies (`site-packages/`) and the API application (`app/`) |
| The launcher | `.../backend/<arch>/sidecar_launcher.py` | starts uvicorn **on `127.0.0.1` only** and refuses every other address |

The Rust side (`src-tauri/src/backend.rs`) starts that backend when the
window opens, supervises it, restarts it after a crash and stops it when the
application exits.  The backend is the very same FastAPI application the web
client uses - the desktop client is a thin, native view on it.

### No cloud is required

* **Every start begins on the local backend.**  The client is hard-wired to
  `http://127.0.0.1:8765` (or to the port the supervisor reports) and it
  *never* reads a base URL from the browser storage to decide where to go.
* **The machine token stays on this machine.**  The token of the sidecar is
  sent in the `X-Local-Token` header and the transport attaches it **only**
  to loopback addresses - a hosted backend never sees it.
* **The session mode follows the target.**  A loopback base URL is the
  "local" mode, every other URL is the "cloud" mode.  The two can no longer
  get out of sync (the old implementation could point the client at a cloud
  URL while still claiming to be local).
* **The client waits instead of switching.**  If the local backend is not
  reachable yet (it is still booting), the request waits and retries for
  about 20 seconds.  It never falls back to another host.* **The application itself never opens a connection to the internet.**  The
  shipped Content Security Policy allows `connect-src` for the loopback
  interface only (`apps/desktop/index.html` and
  `src-tauri/tauri.conf.json`).

### Where the data lives

| Platform | Location |
|----------|----------|
| macOS | `~/Library/Application Support/AutoBacklinker` |
| Windows | `%APPDATA%\AutoBacklinker` |
| Linux | `$XDG_DATA_HOME/auto-backlinker` (`~/.local/share/auto-backlinker`) |

```
autobacklinker.db     SQLite database (local storage mode)
local-token           the machine token of the local backend (mode 0600)
logs/backend.log      stdout/stderr of the sidecar
backups/              storage backups
files/                managed uploads (imports, exports)
browsers/             the optional browser runtime
browser-profile/      the profile of the isolated browser automation
```

Nothing is uploaded anywhere.  The desktop client owns one local account
(`local-<id>@auto-backlinker.app`) inside that database - it is created on the
first start, it is used for the live event stream and its generated password
lives in the local storage of the web view.

### Without an internet connection

Everything that belongs to the product works offline: projects, the queue,
the registry, the activity log, imports, reports, the local backend itself
and the whole user interface.

Three optional things reach out to the internet - **from the backend, not
from the user interface** - and they are the only ones:

| Feature | What it needs | Without an internet connection |
|---------|---------------|-------------------------------|
| Verifying a published backlink | the published page has to be reachable | the verification is reported as *unknown*, never as a success |
| Provider driven discovery (`directory_index`, `brave_search`, `serpapi`) | the public pages of the platforms, plus an API key for Brave/SerpAPI | the provider reports that it cannot reach the catalogue; `manual_seed` works with the URLs you enter |
| The browser runtime (Playwright + Chromium, ~150 MB, once) | the download in **Settings → Browser runtime** | the browser adapter asks for manual completion, every other feature is unaffected |

### The optional hosted backend

A hosted backend is a **feature, not a requirement**.  It is used only when
you switch to it explicitly:

1. open **Settings → Optional hosted backend**,
2. enter the base URL of the deployment (for example
   `https://backlinks.example.com`) - it replaces the local address that is
   shown in the field,
3. press **Use this backend** - the client switches to that backend, the
   badge in the card changes from *Local* to *Hosted* and the sign in screen
   appears,
4. sign in with the account of that deployment (the JWT is sent as
   `Authorization: Bearer ...`),
5. press **Back to local backend** to return - the badge changes back to
   *Local* and the client talks to the sidecar again.

What the switch does **not** do:

* it is never selected automatically - a stored cloud URL is only a
  suggestion, the application always starts on the local backend,
* it does not change the data on this machine - the local database, the
  imports and the backups stay where they are,
* it never leaks the machine token: the `X-Local-Token` header is only sent
  to the loopback interface.

> **Note for the packaged application:** the shipped Content Security Policy
> restricts `connect-src` to the loopback interface, so the *packaged* app
> cannot open a connection to a hosted backend at all.  The switch is
> complete and works in the browser preview (`npm run dev`); to use it in the
> packaged app the policy has to allow the origin of the deployment
> explicitly - it is defined twice and both places have to be changed:
>
> * `apps/desktop/index.html` (the `<meta http-equiv="Content-Security-Policy">`
>   that every build of the frontend carries),
> * `apps/desktop/src-tauri/tauri.conf.json` (`app.security.csp`).
>
> For example, add the origin of the deployment to `connect-src`:
> `connect-src 'self' ipc: http://ipc.localhost http://127.0.0.1:* http://localhost:* https://backlinks.example.com`.
> Until that is done, the browser itself refuses the connection - the request
> never leaves the machine.

### The proof

```bash
cd apps/desktop
../../.venv/bin/python scripts/check-offline.py
```

The script proves the claims above: it starts the packaged application (when
it is built), starts the bundled backend, serves the production frontend
bundle and drives it through a headless browser **while every request that
is not addressed to this machine is blocked**.  It walks through all screens,
checks that the data comes from the local backend (a project that is created
through the local API has to show up in the user interface) and prints a
PASS/FAIL line per check.

---

## 1. Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Node.js | 20+ (22 recommended) | `~/.local/node/bin` on the dev machines |
| Rust | 1.77.2+ | `rustup` - **required for `tauri` commands only** |
| Xcode CLT | macOS only | `xcode-select --install` (needed by the Rust linker) |
| Python | 3.11+ | only to build the backend sidecar |

The frontend (`npm run dev`, `npm run build`) works **without** Rust - the
Tauri shell is only required for the native features.

## 2. Install

```bash
cd apps/desktop
npm install
```

The shared packages are consumed through the file protocol
(`file:../../packages/ui`, ...), therefore `apps/desktop` has its own
`package-lock.json` and does not need an npm workspace at the repository root.

> The `overrides` block in `package.json` rewrites the `workspace:*` dependency
> of `packages/api-client` to a local path so that `npm install` works outside
> of a workspace.

## 3. Development

```bash
# 1. frontend only (browser preview, no native features)
npm run dev            # http://localhost:1420

# 2. full desktop app (Vite + Rust)
npm run tauri:dev      # requires Rust + Xcode CLT
```

`npm run tauri:dev` starts Vite on port 1420 and the Tauri window that loads
`http://localhost:1420`.

> **The browser preview talks to the local backend.**  It is served from
> `http://localhost:1420`, and the backend accepts `http://localhost:3000`
> and `tauri://localhost` as origins by default - so a backend that is
> started for the preview needs one more origin:
>
> ```bash
> AUTOBL_CORS_ORIGINS='["http://localhost:3000","tauri://localhost","http://localhost:1420"]' \
>   <start the backend on 127.0.0.1:8765>
> ```
>
> Without it the browser blocks the requests and the screens show an error
> instead of data.  The packaged application is not affected: it is served
> from `tauri://localhost`.  `scripts/check-ui.py` reports the connection
> errors of a backend that is not running - start it first, or use
> `scripts/check-offline.py`, which starts its own backend.

Useful scripts:

| Script | Description |
|--------|-------------|
| `npm run dev` | Vite dev server (browser preview) |
| `npm run build` | `tsc --noEmit` + production build into `dist/` |
| `npm run typecheck` | TypeScript only |
| `npm run tauri` | raw Tauri CLI (`tauri info`, `tauri dev`, ...) |
| `npm run tauri:dev` | desktop app in development mode |
| `npm run tauri:build` | desktop bundle (`.dmg`, `.app`, `.msi`, `.nsis`) |
| `npm run sidecar` | builds the backend sidecar (`scripts/build-sidecar.sh`) |
| `npm run icons` | regenerates the placeholder icons |
| `../../.venv/bin/python scripts/check-offline.py` | proves that the client runs on this machine: the packaged app, the bundled backend and a headless walk through all screens without a single request leaving the computer |
| `../../.venv/bin/python scripts/check-ui.py` | renders the frontend in a headless browser and reports console errors |
| `../../.venv/bin/python scripts/check-desktop.py` | end-to-end check of the packaged application (restart, port conflict, session) |

### The backend sidecar

`npm run tauri:build` requires the sidecar binary, because it is declared in
`src-tauri/tauri.conf.json` as `bundle.externalBin`:

```json
"externalBin": ["binaries/autobacklinker-api"]
```

Tauri looks the file up as
`src-tauri/binaries/autobacklinker-api-<target-triple>` (`.exe` on Windows).
Build it **on every platform you want to ship**:

```bash
# macOS / Linux
npm run sidecar                    # -> src-tauri/binaries/autobacklinker-api-aarch64-apple-darwin
# or with an explicit API checkout
scripts/build-sidecar.sh --api-dir ../../apps/api

# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File scripts\build-sidecar.ps1
```

The script creates a virtual environment, installs the backend requirements,
runs PyInstaller and copies the artefact to `src-tauri/binaries/`.

Requirements for the script: **CPython 3.11+**. It looks for `python3.13`,
`python3.12`, `python3.11` and `python3`; set `PYTHON_BIN` to point at a
specific interpreter:

```bash
PYTHON_BIN=/opt/homebrew/bin/python3.12 scripts/build-sidecar.sh
```

**Playwright browsers** are *not* bundled into the executable (they are
~400 MB). Two options:

1. `PLAYWRIGHT_BROWSERS_PATH=./.playwright-browsers scripts/build-sidecar.sh`
   copies the browsers to `src-tauri/binaries/playwright-browsers` - add
   `"binaries/playwright-browsers"` to `bundle.resources` in
   `src-tauri/tauri.conf.json` to ship them.
2. Install them on the target machine:
   `python -m playwright install chromium`.

Without a browser runtime the agent reports browser tasks as
*"manual intervention required"* - it never fails silently.

### How the backend is started and stopped

The Rust side (`src-tauri/src/backend.rs`) owns the process:

* the app starts the sidecar automatically when the window opens,
* the sidecar receives `AUTOBL_DATA_DIR`, `AUTOBL_ENVIRONMENT=desktop`,
  `AUTOBL_STORAGE_MODE=local`, `AUTOBL_WORKER_ENABLED=true` and a random
  `AUTOBL_LOCAL_TOKEN`,
* it is started with `--host 127.0.0.1 --port <port>` - **never** `0.0.0.0`,
* a supervisor thread polls the health endpoint (`GET /health`) every few
  seconds, restarts a crashed backend (exponential backoff, max. 3 restarts)
  and kills the process when the app exits,
* stdout/stderr are captured into `<data dir>/logs/backend.log`,
* the UI can start, stop and restart it from **Settings → Local backend**.

The machine token is sent to the frontend as `localToken` and used in the
`X-Local-Token` header (see `apps/api/app/api/deps.py`).  The transport adds
that header to every request to the loopback interface - and to nothing else.
While the sidecar is still booting, the client waits for it (and retries)
instead of failing or looking somewhere else.

### Where the data is stored

| Platform | Location |
|----------|----------|
| macOS | `~/Library/Application Support/AutoBacklinker` |
| Windows | `%APPDATA%\AutoBacklinker` |
| Linux | `$XDG_DATA_HOME/auto-backlinker` (`~/.local/share/auto-backlinker`) |

Inside that directory:

```
autobacklinker.db     SQLite database (local storage mode)
logs/backend.log      stdout/stderr of the sidecar
backups/              storage backups
files/                managed uploads (imports, exports)
```

The local agent keeps its own state in `~/.autobacklinker/agent.json` (mode
`0600`) and its log in `~/.autobacklinker/logs/agent.log`.

### Optional hosted backend

The desktop app can talk to a hosted backend instead of the local sidecar:

1. open **Settings → Optional hosted backend**,
2. enter the base URL of the deployment (`https://backlinks.example.com`),
3. press **Use this backend** - the client switches to the remote API and
   shows the sign in screen,
4. sign in with the account of that deployment (the JWT is sent as
   `Authorization: Bearer ...`).

**Back to local backend** restores the loopback sidecar.  The hosted URL is
remembered (`autobacklinker.desktop.cloudUrl`), the *connection* is not: the
application always starts on the local backend, so a stale setting can never
take over a start.

This switch only changes where the client sends requests.  It does **not**
copy or synchronise data between the local database and the hosted backend.
The full rules - and the limits of the packaged build - are described in
[Runs completely on your machine](#runs-completely-on-your-machine).

## 4. Production builds

### macOS

```bash
npm run sidecar                 # on an Apple Silicon / Intel machine
npm run tauri:build             # -> Auto Backlinker.app
bash scripts/build-dmg.sh       # -> Auto Backlinker_1.0.0_<arch>.dmg
# -> src-tauri/target/release/bundle/dmg/Auto Backlinker_1.0.0_x64.dmg
# -> src-tauri/target/release/bundle/macos/Auto Backlinker.app
```

> **What was actually built on the development machine:** the PyInstaller
> sidecar (`autobacklinker-api-x86_64-apple-darwin`, 27 MB), the native
> application bundle (`Auto Backlinker.app`, 32 MB, containing the desktop
> binary, the sidecar and the icon) and the disk image
> (`Auto Backlinker_1.0.0_x64.dmg`, 30 MB).  The DMG was verified to mount and
> to contain the application plus the `/Applications` symlink, and the bundled
> backend was started from inside the bundle - it created its SQLite database
> and answered `/health`.
>
> Tauri's own DMG step needs AppleScript automation of the Finder, which the
> build machine does not permit ("AppleEvent timed out").  `build-dmg.sh`
> creates the same disk image with `hdiutil` only, so the packaging works in
> CI and on headless build agents as well.

Signing and notarisation are **not** part of the open source build. To ship a
signed build you need:

* an **Apple Developer Program** membership (paid),
* a *Developer ID Application* certificate installed in the keychain,
* a **Developer ID Installer** certificate for the `.dmg`,
* a notarisation ticket:

```bash
codesign --deep --force --options runtime --timestamp \
  --sign "Developer ID Application: <TEAM> (<TEAMID>)" \
  "src-tauri/target/release/bundle/macos/Auto Backlinker.app"

xcrun notarytool submit "Auto Backlinker_1.0.0_aarch64.dmg" \
  --keychain-profile "AC_PASSWORD" --wait
xcrun stapler staple "Auto Backlinker_1.0.0_aarch64.dmg"
```

Without notarisation macOS Gatekeeper will block the application on other
machines.

### Windows

```bash
powershell -ExecutionPolicy Bypass -File scripts\build-sidecar.ps1
npm run tauri:build
# -> src-tauri\target\release\bundle\nsis\Auto Backlinker_1.0.0_x64-setup.exe
# -> src-tauri\target\release\bundle\msi\Auto Backlinker_1.0.0_x64_en-US.msi
```

Signing requires an **Authenticode** code signing certificate
(Sectigo / DigiCert / Azure Code Signing) in a PFX file and the environment
variables `TAURI_SIGNING_PRIVATE_KEY` (base64 PKCS#12) and
`TAURI_SIGNING_PRIVATE_KEY_PASSWORD`. The MSI additionally needs
`TAURI_BUNDLE_MSI_WIX_FILE` or the WiX toolset v3.14 installed.

Unsigned builds trigger the "Windows protected your PC" dialog - that is
expected for an internal build.

### What a developer needs for `npm run tauri build`

1. **Rust toolchain**: `rustup toolchain install stable`
   (`rustc 1.77.2` or newer).
2. **Xcode Command Line Tools** on macOS (`xcode-select --install`) - the Rust
   linker needs them.
3. **A sidecar binary** for the target triple:
   `npm run sidecar` (see above). Without it the bundler fails with
   *"external binary autobacklinker-api not found"*.
4. **The frontend build**: `npm run build` (the Tauri `beforeBuildCommand`
   runs it automatically).
5. Optional: signing certificates / notarisation credentials.

### What was verified on the development machine

| Command | Result |
|---------|--------|
| `npm install` | 148 packages, own lockfile |
| `npx tsc --noEmit` | no errors |
| `npm run build` | `dist/` built (253 kB JS / 20 kB CSS) |
| `cargo check` (src-tauri) | no errors, no warnings |
| `npm run tauri build` | `Auto Backlinker.app` (75 MB) + `Auto Backlinker_1.0.0_x64.dmg` (80 MB), **unsigned** |
| `apps/desktop/src-tauri/target/release/bundle/macos/Auto Backlinker.app/Contents/MacOS/autobacklinker-desktop` | starts, spawns the sidecar, `GET http://127.0.0.1:8765/health` answers, SQLite database is created in `~/Library/Application Support/AutoBacklinker` |
| `scripts/check-ui.py` (headless Chromium) | the UI renders, no console errors |
| `scripts/check-offline.py` (headless Chromium) | the packaged app starts its bundled backend, the client starts on the local sidecar, all 14 screens render, a project created in the local backend shows up in the UI, **no request leaves the machine**, no console error |

The bundles are **not signed and not notarised** - see the macOS section
above for what a release build needs.

## 5. Security model

* the sidecar binds to `127.0.0.1` only and uses a random per-launch token,
* the token is only handed to the local web view,
* the transport attaches the `X-Local-Token` header to loopback addresses
  only - it is never sent to a hosted backend,
* the Tauri capabilities (`src-tauri/capabilities/default.json`) grant exactly
  the permissions the app uses (dialog, notification, shell open, process
  restart/exit, scoped file access),
* the local agent only executes an allowlist of task types and rejects any
  payload that contains an executable/command field,
* the agent log is redacted (API keys, bearer tokens and passwords are
  replaced with `***`).

## 6. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| "The backend sidecar binary is missing" | run `npm run sidecar` |
| Backend does not become healthy | check **Settings → Local backend → log tail** |
| Port already in use | change the port in **Settings → Local backend** |
| Browser tasks need manual help | install Playwright + Chromium on the machine |
| `npm install` fails on `workspace:*` | the `overrides` block rewrites it - do not remove it |
