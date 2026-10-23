# Auto Backlinker

**Autonomous backlink discovery, automation, verification and reporting.**

Auto Backlinker finds places where a business can get a real backlink
(directories, industry listings, local citations, editorial sites, resource
pages, Q&A platforms, ...), lets a human approve every one of them, then
executes the submission with a pluggable adapter, verifies that the link is
actually live and finally exports a report - and can import the same data
back into the system.

The product is built around three rules:

1. **Nothing is simulated.**  Opportunities, tasks, attempts, verifications and
   metrics always reflect the state of the database.
2. **A successful submission requires a success signal.**  Clicking a button is
   not a success - a confirmation message, a published page or a documented API
   answer is.
3. **The human stays in control.**  Adapters that need an account, a payment or
   an editor's decision return `WAITING_FOR_USER` / `WAITING_FOR_APPROVAL`
   instead of pretending to have submitted.

---

## Table of contents

- [Feature status](#feature-status)
- [Architecture](#architecture)
- [Monorepo layout](#monorepo-layout)
- [Quick start](#quick-start)
- [Environment variables](#environment-variables)
- [Database migrations](#database-migrations)
- [Worker](#worker)
- [Testing and linting](#testing-and-linting)
- [Packaging notes](#packaging-notes)
- [End-to-end guide](#end-to-end-guide-discover--approve--queue--run--verify--export--reimport)
- [Known limitations](#known-limitations)

---

## Feature status

### Implemented

| Area | What works |
| ---- | ---------- |
| **Campaign cockpit** | The project page is one screen: paste one or many URLs (comma / new line), import Excel / CSV, assign websites from a category-filtered list, press **Start backlinks** and watch a live table with the data-ready percent, the row status and the last update. **Stop** pauses and Start resumes the same work; **Remove** takes a website out of the project without deleting it; **Download report** exports the table as CSV and **Restart failed** requeues only the failed rows. Manual directories can be marked submitted and verified from the same row. |
| **Review websites** | A secondary review screen for discovery results: approve, exclude, add to a project or queue, merge duplicates and edit website fields. The normal flow does not need it - the project page assigns websites directly. |
| **Discovery** | Pluggable providers: `manual_seed`, `directory_index` (built-in catalogue of publicly documented submission pages), `brave_search`, `serpapi`. Runs are queued as `DISCOVER` tasks, results are stored as websites and linked to the project. |
| **Queue** | Durable, database backed queue with idempotency keys, atomic claiming (conditional `UPDATE`), leases, exponential backoff with jitter, priority reordering, bulk control, cancel / retry / requeue, append-only attempt history. |
| **Adapters** | Five shipped adapters: `generic_manual`, `http_form`, `playwright_form`, `email_outreach`, `json_api`. Each declares the categories, methods, required config, success signals and retryable errors it supports. |
| **Submission** | Adapters resolve automatically (domain specific adapter wins over generic ones), manual packs are generated for non-automatable targets, evidence is stored per attempt. |
| **Verification** | Backlink records are created unverified and are confirmed by the verification engine: link presence, destination match, anchor text, `rel` attribute and HTTP status are recorded per run. |
| **Imports / exports** | XLSX / CSV import with header detection, per-row plan (create / update / skip / retry / verify / conflict / invalid), dry-run preview, commit, CSV error report. XLSX / CSV export with one sheet per report section. |
| **Storage modes** | Local SQLite, cloud PostgreSQL and hybrid (local + synchronisation queue) with backup / restore of the active database. |
| **Sync** | Change queue, push / pull, conflict detection and conflict resolution (`local` / `remote` strategy). |
| **Events** | Every state change is persisted as an activity event and published live over SSE (`GET /api/v1/events/stream`). |
| **AI layer** | Optional provider (OpenAI, OpenRouter, Groq, Ollama, LM Studio, Anthropic) with helpers for classification, relevance explanation, anchor suggestions, outreach drafts, directory descriptions, column mapping, error summaries, next actions, low-value detection and automation planning. Every helper degrades to a deterministic implementation when AI is off. |
| **Devices / local agents** | Devices register themselves, send heartbeats, claim `LOCAL` tasks and report the result.  A ready to use agent lives in `apps/local-agent`. |
| **Schedules** | Periodic discovery and verification schedules; the worker ticks them every 30 iterations and queues the due work. |
| **Celery dispatcher** | Optional: `app/workers/celery_app.py` exposes the same task handlers as Celery tasks for horizontally scaled cloud workers. |
| **Clients** | Next.js web app (`apps/web`) and Tauri 2 desktop app (`apps/desktop`, with the API as a sidecar).  Both speak the same protocol as the API. |
| **Reporting** | XLSX / CSV export with one sheet per section, CSV error report for imports. |

### Needs credentials

| Feature | Missing piece |
| ------- | ------------- |
| Brave Search discovery | `AUTOBL_BRAVE_SEARCH_API_KEY` (or an `api_key` in the run configuration) |
| SerpAPI discovery | `AUTOBL_SERPAPI_API_KEY` (or an `api_key` in the run configuration) |
| AI assistance | `AUTOBL_AI_PROVIDER`, `AUTOBL_AI_API_KEY`, `AUTOBL_AI_MODEL` - the product works without it, the suggestions are then rule based |
| Cloud / hybrid storage | A reachable PostgreSQL server (`AUTOBL_DATABASE_URL`) and the `psycopg[binary]` driver |
| Celery dispatch | A reachable Redis broker (`AUTOBL_CELERY_BROKER_URL`) |
| Automated form submissions | Per-target adapter configuration (form URL, field selectors, success selector) - the targets must allow programmatic submissions |

### Not implemented (yet)

| Feature | Status |
| ------- | ------ |
| Celery is opt-in | The dispatcher exists, but the database worker (`app/workers/runner.py`) is the default and the one used by the compose stack. |
| Email delivery | The outreach adapter creates a *draft*; there is no SMTP transport yet. |
| Per-site adapters with real credentials | Only the generic adapters are shipped; there are no target-specific integrations. |
| Web sockets | The live feed is delivered over Server-Sent Events; no WebSocket endpoint exists. |

---

## Isolated browser automation

The platform never touches the browser a person uses during the day.

| Guarantee | How it is implemented | Where it is verified |
| --------- | --------------------- | -------------------- |
| **Own browser only** | Playwright launches its own Chromium with a throw away profile in `<app data>/browser-profile`. The personal Chrome / Edge / Safari profile is never opened, read or controlled. | `tests/test_browser_isolation.py` + `app/services/browser.py` |
| **Headless by default** | `headless=True` is the default; the headed mode (for workflows that need a human) uses the same isolated profile. | Settings → *Automation & browser* |
| **No extensions, no sync** | The browser is started with `--disable-extensions`, `--disable-sync`, `--no-first-run`, `--password-store=basic`, `--use-mock-keychain` and 17 further arguments. | `tests/test_browser_isolation.py` |
| **Environment cleaned** | Variables that could point the browser at the personal profile (`CHROME_*`, `BROWSER_*`) are removed before the browser starts. | `tests/test_browser_isolation.py` |
| **Own browser build** | Chromium is downloaded into `<app data>/browsers` of this installation - it is never shared with the browser of the operating system. The Playwright package itself is not bundled (it weighs 135 MB per architecture because it contains its own Node runtime) - it is installed on demand into `<app data>/py`. | Settings → *Install browser runtime* |
| **Runs in the background** | The browser is driven by the worker thread, never by an HTTP request, so the user interface never blocks. | `app/workers/runner.py` |
| **Persistent queue** | The job history lives in the database - closing the application loses nothing and finished work is never repeated. | `app/services/queue.py` |
| **Challenges pause the job** | A CAPTCHA, a login or a consent screen stops the job and asks the operator - nothing is bypassed. | `app/services/adapters/impl/playwright_form.py` |
| **Cloud or local** | Every job shows where it runs (`CLOUD` / `LOCAL`); eligible jobs can be moved to a cloud worker. | Live Automation page |

### Resource aware scheduling

The worker measures the machine (CPU, free memory, load) **before** it claims
a browser job and lowers the number of parallel jobs when the machine is busy:

* `max_speed` – use the configured limit
* `balanced` – use about 60 % of it
* `save_resources` – use about 30 % of it
* under heavy load (CPU ≥ 85 % or less than 512 MB free memory) only **one**
  job runs at a time

The limit is really enforced - the worker claims fewer jobs while the machine
is busy. It cannot stop a single browser process from using CPU, so the
interface describes it as a target and not as a guarantee.

### Controls

Settings → *Automation & browser* (and the Live Automation page):

* Pause all / Resume / Stop - `POST /api/v1/worker/pause|resume|stop`
* Maximum parallel browser jobs, jobs per domain, requests per domain per minute
* Job and page timeouts
* Headless or headed (isolated) browser
* Install / reinstall the browser runtime
* A live view of the CPU, the free memory and the effective limit

A running job can be cancelled: the browser is closed at the next checkpoint
instead of being killed.

---

## Two independent products

| | **Web product** (`apps/web`) | **Desktop product** (`apps/desktop`) |
| - | ------------------------ | ------------------------- |
| Start | `make dev-api` + `make dev-web` | one double click |
| Backend | `apps/api` started separately | **bundled into the app** (`src-tauri/Resources/backend/<arch>/`) |
| Backend instance | its own | **its own** - never the web one |
| Database | SQLite (default) or PostgreSQL | SQLite in the application data directory |
| Internet | needed for discovery, verification and submissions | not needed - everything except the live checks works offline |
| Cloud | optional | optional, clearly labelled, the local token never leaves the machine |

Both talk to **the same API implementation** but run **their own instance** of
it. The desktop never calls the web backend and the web backend never calls
the desktop. A cloud backend is an optional extra that either side may point
at.

The proof: `apps/desktop/scripts/check-offline.py` drives the packaged
application with a headless browser while every non-loopback request is
blocked - 41 checks, 0 external requests.

---

## Architecture

```
                       ┌───────────────────────────────────────────┐
                       │            apps/web  (Next.js)            │
                       │   apps/desktop (Tauri 2 + React)         │
                       └───────────────────┬───────────────────────┘
                                           │ HTTP + JWT
                                           ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                          apps/api  ·  FastAPI                           │
│                                                                          │
│  api/routes ──► services ──► db/repositories ──► db/models (SQLAlchemy)  │
│       │             │                                                     │
│       │             ├─► services/discovery  (providers)                  │
│       │             ├─► services/adapters   (submissions)                │
│       │             ├─► services/dataflow   (import / export)            │
│       │             ├─► services/submission, verification, storage      │
│       │             ├─► services/sync       (hybrid mode)               │
│       │             └─► services/ai          (optional AI layer)         │
│       │                                                                  │
│       └──► workers/runner  ──► claims tasks ──► writes attempts          │
└───────────────┬───────────────────────────┬──────────────────────────────┘
                │                           │
                ▼                           ▼
      ┌───────────────────┐     ┌────────────────────────┐
      │  SQLite (local)   │     │  PostgreSQL (cloud)    │
      │  data_dir/*.db    │◄────┤  sync_changes queue    │
      └───────────────────┘     └────────────────────────┘
                │                           │
                │                           └──► apps/local-agent
                │                                (LOCAL tasks, own machine)
                ▼
      ┌───────────────────────────────────────┐
      │  Redis (Celery broker / result store)│
      └───────────────────────────────────────┘
```

Data flow of a single backlink:

```
discovery provider ──► website (registry)
                          │
                          └─► opportunity (per project) ──► approve
                                                              │
                                                    queue (SUBMIT task)
                                                              │
                                                     adapter.submit()
                                                              │
                                     ┌────────────────────────┼───────────────────────┐
                                     │                        │                       │
                              backlink_record          evidence file             task_attempt
                              (unverified)             (screenshot / excerpt)    (append only)
                                                              │
                                                   verification task
                                                              │
                                        verification_runs ──► VERIFIED_LIVE / REMOVED
                                                              │
                                                    export (xlsx / csv)
                                                              │
                                              re-import ──► preview ──► commit
```

---

## Monorepo layout

Two **independent products** live side by side under this root. They share
the code and the design system, but each one runs its **own** backend
instance and its **own** database - the desktop never calls the web backend
and the web backend never calls the desktop.

```
auto-backlinker/
├── apps/
│   ├── api/                  FastAPI backend, workers, migrations (Python)
│   │   ├── alembic/          Alembic environment + versions
│   │   ├── alembic.ini
│   │   ├── app/
│   │   │   ├── api/routes/   REST endpoints (auth, projects, registry, queue, …)
│   │   │   ├── core/         config, logging, security, network helpers
│   │   │   ├── db/           base, models, session, repositories
│   │   │   ├── services/     business logic (discovery, adapters, dataflow, ai, …)
│   │   │   ├── workers/      background worker runtime (+ Celery dispatcher)
│   │   │   ├── main.py       application factory
│   │   │   └── schemas.py    Pydantic request / response models
│   │   ├── scripts/          bootstrap.sh, migrate.sh, smoke_core.py
│   │   ├── tests/            pytest suite
│   │   ├── pyproject.toml    ruff + pytest configuration
│   │   └── requirements.txt
│   ├── web/                  PRODUCT 1 - the browser client (Next.js 15)
│   │   └── app/(app)/        Dashboard, My projects, Backlink websites,
│   │                         Task queue, Reports, Recycle bin, Settings,
│   │                         More tools
│   ├── desktop/              PRODUCT 2 - the desktop software (Tauri 2)
│   │   ├── src/              the same screens, desktop conventions
│   │   ├── src-tauri/        Rust shell, sidecar supervisor, bundler config
│   │   ├── scripts/          build-backend.sh (both architectures),
│   │   │                     build-sidecar.sh, build-dmg.sh, check-*.py
│   │   └── Resources/backend/<arch>/   its OWN backend, bundled into the app
│   └── local-agent/          Standalone agent for the LOCAL execution environment
├── packages/
│   ├── shared-types/         TypeScript DTO contracts (single source of truth)
│   ├── api-client/           typed transport layer used by web + desktop
│   └── ui/                   shared Tailwind components and design tokens
├── infrastructure/
│   ├── api.Dockerfile        image for the API and the worker
│   ├── docker-compose.yml    postgres + redis + api + worker
│   └── README.md
├── scripts/verify_all.sh     runs every check of the monorepo
├── docs/
│   ├── API.md                endpoint reference
│   ├── CAMPAIGN.md           the project page: add, start, watch (guide)
│   ├── FEATURES.md           web / desktop parity and the workflow
│   └── ARCHITECTURE.md       design notes
├── Makefile                  convenience targets (install / dev / test / verify)
├── .env.example
└── README.md
```

The Python API mirrors the TypeScript contracts of `packages/shared-types`:
`app/schemas.py` is the Python counterpart of `packages/shared-types/src/index.ts`.

---

## Quick start

### Prerequisites

* Python 3.11+ (3.12 is used in CI and in the container image)
* Node.js 20+ for the web and desktop clients
* Optional: Docker (for the PostgreSQL / Redis stack)

### 1. API

```bash
# from the repository root
apps/api/scripts/bootstrap.sh

# start the API (from apps/api)
cd apps/api
../../.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

Open <http://localhost:8000/docs> for the interactive API documentation and
<http://localhost:8000/health> for the health check.

`bootstrap.sh` is idempotent: it creates the virtual environment in the
repository root (`.venv`) with a Python 3.11+ interpreter - `python3 -m venv`
or `uv venv` when `uv` is installed - installs `requirements.txt` and applies
the migrations.  Set `AUTOBL_PYTHON` to choose the interpreter and
`AUTOBL_VENV` to use a different environment directory.

### 2. Worker

```bash
cd apps/api
../../.venv/bin/python -m app.workers.runner
```

The API already starts an embedded worker when `AUTOBL_WORKER_ENABLED=true`
(the default), so the standalone worker is only needed for the cloud
deployment - or when you want the API and the worker on separate machines.

### 3. Web client

```bash
cd apps/web
npm install
npm run dev        # http://localhost:3000
```

The client talks to `http://localhost:8000/api/v1` by default; see
`apps/web/lib/api.ts` for the configuration.

### 4. Desktop client

```bash
cd apps/desktop
npm install
npm run tauri:dev
```

The desktop app starts the API as a sidecar (SQLite + embedded worker on
`127.0.0.1`) or points at a remote API - see *Packaging notes*.

### 5. Local agent (optional)

The agent executes the tasks that are routed to the `LOCAL` execution
environment on a machine you control:

```bash
cd apps/local-agent
python3 -m agent --register --server-url http://127.0.0.1:8000
python3 -m agent --daemon
```

The registration (device id + API key) is stored in `~/.autobacklinker/agent.json`
with `0600` permissions.

### 6. Docker stack (cloud mode)

```bash
docker compose -f infrastructure/docker-compose.yml up -d --build
```

PostgreSQL, Redis, the API and the worker are started; the API applies the
migrations automatically.  See `infrastructure/README.md`.

### Everything at once

```bash
make install     # venv + requirements + npm install for web and desktop
make verify      # lint, tests, migrations, typecheck and production builds
```

---

## Environment variables

All variables use the `AUTOBL_` prefix and are read by
`app/core/config.py` (Pydantic settings).  `.env.example` in the repository
root contains the complete, commented list - it is the authoritative
reference.  The most important ones:

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `AUTOBL_ENVIRONMENT` | `local` | `local`, `self_hosted`, `cloud`, `desktop` or `test` |
| `AUTOBL_SECRET_KEY` | `dev-only-insecure-secret-key-change-me-please-000000` | Signs the JWT access tokens - **change it** |
| `AUTOBL_ACCESS_TOKEN_EXPIRE_MINUTES` | `720` | Lifetime of an access token |
| `AUTOBL_CORS_ORIGINS` | `["http://localhost:3000","tauri://localhost"]` | Allowed browser origins (JSON list) |
| `AUTOBL_LOCAL_TOKEN` | *(empty)* | Shared token of the bundled desktop backend |
| `AUTOBL_ALLOW_PRIVATE_NETWORK` | `false` | Allows requests to private addresses (disables the SSRF guard) |
| `AUTOBL_STORAGE_MODE` | `auto` | `auto`, `local`, `cloud` or `hybrid` |
| `AUTOBL_DATABASE_URL` | *(empty)* | PostgreSQL URL; empty means "use the local SQLite file" |
| `AUTOBL_DATA_DIR` | OS specific | Database, uploads, backups and logs |
| `AUTOBL_AUTO_CREATE_SCHEMA` | `true` | Create the schema at startup (local / desktop mode) |
| `AUTOBL_MAX_UPLOAD_MB` | `25` | Maximum size of an imported spreadsheet |
| `AUTOBL_WORKER_ENABLED` | `true` | Run the worker inside the API process |
| `AUTOBL_WORKER_BATCH_SIZE` | `5` | Global concurrency of the worker |
| `AUTOBL_WORKER_POLL_INTERVAL` | `1.0` | Seconds between two claim attempts |
| `AUTOBL_TASK_LEASE_SECONDS` | `300` | After this time an abandoned task returns to the queue |
| `AUTOBL_USE_CELERY` | `false` | Dispatch the tasks through Celery |
| `AUTOBL_CELERY_BROKER_URL` | *(empty)* | Redis broker URL |
| `AUTOBL_RESPECT_ROBOTS` | `true` | Honour `robots.txt` |
| `AUTOBL_MAX_REQUESTS_PER_MINUTE` | `30` | Global rate limit of the automation |
| `AUTOBL_HTTP_TIMEOUT` | `25.0` | Timeout of outbound requests |
| `AUTOBL_ALLOW_BROWSER_AUTOMATION` | `true` | Allow the Playwright adapter |
| `AUTOBL_PLAYWRIGHT_HEADLESS` | `true` | Run the browser without a window |
| `AUTOBL_VERIFICATION_INTERVAL_HOURS` | `168` | Interval between two verifications of a link |
| `AUTOBL_AI_PROVIDER` | *(empty)* | `openai`, `openrouter`, `groq`, `ollama`, `lmstudio`, `anthropic` |
| `AUTOBL_AI_BASE_URL` | *(empty)* | Base URL of the provider (defaults per provider) |
| `AUTOBL_AI_API_KEY` | *(empty)* | API key of the provider |
| `AUTOBL_AI_MODEL` | *(empty)* | Model identifier |
| `AUTOBL_AI_ENABLED` | `true` | Master switch of the AI layer |
| `AUTOBL_BRAVE_SEARCH_API_KEY` | *(empty)* | Brave Search API key |
| `AUTOBL_SERPAPI_API_KEY` | *(empty)* | SerpAPI key |
| `AUTOBL_DEVICE_HEARTBEAT_SECONDS` | `30` | Heartbeat interval of a local agent |
| `AUTOBL_API_PREFIX` | `/api/v1` | Prefix of every REST endpoint |

Two platform variables are read directly (not through the settings): `APPDATA`
on Windows and `XDG_DATA_HOME` on Linux, to derive the default data
directory.

---

## Database migrations

The schema is managed with Alembic.  The URL is never stored in
`alembic.ini` - it is resolved from the settings, so the migrations always
target the same database as the application.

```bash
cd apps/api

# apply every migration
../../.venv/bin/python -m alembic upgrade head

# or with the helper script
scripts/migrate.sh

# inspect the state
../../.venv/bin/python -m alembic current
../../.venv/bin/python -m alembic history

# roll back
../../.venv/bin/python -m alembic downgrade -1
../../.venv/bin/python -m alembic downgrade base

# create a new revision (after changing app/db/models.py)
../../.venv/bin/python -m alembic revision --autogenerate -m "add column to websites"
```

`alembic/versions/0001_initial_schema.py` is the baseline revision.  It uses
`Base.metadata.create_all(bind=op.get_bind())`, so it creates the identical
schema on SQLite **and** PostgreSQL; `downgrade()` drops the tables again.

> **Local / desktop mode:** `AUTOBL_AUTO_CREATE_SCHEMA=true` (the default)
> creates the schema automatically at startup, so a fresh installation needs
> no migration command at all.  Set it to `false` in production and manage the
> schema exclusively with Alembic.

---

## Worker

```bash
# embedded (default, started with the API)
AUTOBL_WORKER_ENABLED=true

# standalone process
cd apps/api && ../../.venv/bin/python -m app.workers.runner

# in the container
docker compose -f infrastructure/docker-compose.yml up -d worker

# optional: dispatch the same handlers through Celery
AUTOBL_USE_CELERY=true
AUTOBL_CELERY_BROKER_URL=redis://localhost:6379/0
cd apps/api && ../../.venv/bin/python -m celery -A app.workers.celery_app.celery_app worker -l info
```

The worker claims tasks with an atomic conditional `UPDATE`, so two workers
can never own the same task.  It honours the per-project and per-domain
concurrency limits, writes an append-only `task_attempts` history, publishes
live events and ticks the schedules (periodic discovery / verification) every
30 iterations.  Tasks whose lease expires (worker crash) are returned to the
queue automatically.

---

## Testing and linting

```bash
cd apps/api

# lint
../../.venv/bin/python -m ruff check app tests scripts

# tests (pytest, asyncio auto mode)
../../.venv/bin/python -m pytest -q

# a single file
../../.venv/bin/python -m pytest tests/test_ai.py -q

# smoke test of the whole stack against a temporary database
../../.venv/bin/python scripts/smoke_core.py
```

The whole monorepo has one entry point:

```bash
make verify              # lint + import check + smoke + migrations + tests + builds
scripts/verify_all.sh    # the same, without the "make" wrapper
scripts/verify_all.sh --fast   # skip the test suite
```

TypeScript:

```bash
make typecheck           # apps/web and apps/desktop
cd packages/shared-types && npx tsc --noEmit
```

---

## Packaging notes

**Desktop (Tauri).**  The desktop bundle ships the API as a *sidecar*: a
Python interpreter plus the application, started on `127.0.0.1` (default port
`8765`) with a random `AUTOBL_LOCAL_TOKEN`.  The client then talks to
`http://127.0.0.1:<port>/api/v1` and authenticates with the local token (or
with a normal JWT after signing in).  `apps/desktop/scripts/build-sidecar.sh`
builds the sidecar binary (PyInstaller) for the current platform, and
`sidecar_launcher.py` starts it.  The data directory is
`~/Library/Application Support/AutoBacklinker` on macOS,
`%APPDATA%\AutoBacklinker` on Windows and `$XDG_DATA_HOME/auto-backlinker` on
Linux, so the SQLite database, the uploads and the backups stay with the user.

**Cloud backend.**  The desktop and web clients are stateless views: they only
need the base URL of the API and the credentials of an account.  In the
desktop app switch the connection mode from *Local* to *Cloud* and enter the
URL of the API (for example `https://api.example.com/api/v1`), then sign in.
See `infrastructure/README.md` for the full walkthrough.

**Container image.**  `infrastructure/api.Dockerfile` builds a
`python:3.12-slim` image that contains the API and the worker.  The
entrypoint applies the migrations before the container starts (idempotent, can
be disabled with `AUTOBL_RUN_MIGRATIONS=0`) and the image runs as a
non-root user.

**Frontend packages.**  `packages/shared-types` holds the DTO contracts,
`packages/api-client` the typed transport layer and `packages/ui` the shared
Tailwind components.  All three are consumed through `file:` references in
`apps/web` and `apps/desktop`.

**Local agent.**  `apps/local-agent` is a standalone program (standard library
only) that registers a device at the backend and then claims the `LOCAL`
tasks.  Its configuration (device id, API key, server URL) lives in
`~/.autobacklinker/agent.json` with `0600` permissions.

---

## End-to-end guide (discover → approve → queue → run → verify → export → reimport)

All examples use `curl` against `http://localhost:8000/api/v1`.

**0. Create an account and a business profile**

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"me@example.com","password":"a-strong-password","name":"Me"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

PROFILE=$(curl -s -X POST http://localhost:8000/api/v1/profiles \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"Acme Analytics","primary_website":"https://acme.example",
       "description":"We build product analytics for SaaS teams.",
       "industry":"Software","niche":"B2B SaaS",
       "keywords":["product analytics","saas analytics"],
       "preferred_anchors":["Acme Analytics"],
       "target_countries":["US"],"preferred_categories":["BUSINESS_DIRECTORY"]}')

PROFILE_ID=$(echo "$PROFILE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
```

**1. Create the project**

```bash
PROJECT=$(curl -s -X POST http://localhost:8000/api/v1/projects \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"name\":\"Acme backlinks\",\"target_website\":\"https://acme.example\",
       \"business_profile_id\":\"$PROFILE_ID\",
       \"settings\":{\"require_approval\":true,\"request_rate_per_minute\":20}}")

PROJECT_ID=$(echo "$PROJECT" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
```

**2. Discover**

```bash
# which providers are available?
curl -s http://localhost:8000/api/v1/discovery/providers \
  -H "Authorization: Bearer $TOKEN"

# start a run (the provider needs credentials - brave_search / serpapi)
curl -s -X POST http://localhost:8000/api/v1/discovery/runs \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"project_id\":\"$PROJECT_ID\",\"provider\":\"directory_index\",
       \"query\":\"saas analytics directory\",\"limit\":25,\"keywords\":[\"product analytics\"]}"
```

The run is queued as a `DISCOVER` task and processed by the worker.  Results
appear as opportunities:

```bash
curl -s "http://localhost:8000/api/v1/opportunities?project_id=$PROJECT_ID" \
  -H "Authorization: Bearer $TOKEN"
```

**3. Review and approve**

```bash
curl -s -X POST http://localhost:8000/api/v1/opportunities/bulk \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"opportunity_ids\":[\"<id-1>\",\"<id-2>\"],\"action\":\"approve\"}"
```

Never approve blindly: check the domain, the category and whether the target
accepts submissions.  Exclude a whole domain with
`POST /api/v1/registry/exclusions`.

**4. Queue the submissions**

```bash
curl -s -X POST http://localhost:8000/api/v1/queue \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"opportunity_ids\":[\"<id-1>\",\"<id-2>\"],\"type\":\"SUBMIT\",\"priority\":5}"
```

The response contains the created task ids.  The queue deduplicates: the same
opportunity cannot be queued twice while a task with the same idempotency key
exists.

**5. Run**

The worker picks the tasks up automatically.  Follow the progress live:

```bash
# server sent events
curl -N http://localhost:8000/api/v1/events/stream

# or the task itself
curl -s http://localhost:8000/api/v1/tasks/<task-id> -H "Authorization: Bearer $TOKEN"
curl -s http://localhost:8000/api/v1/tasks/<task-id>/attempts -H "Authorization: Bearer $TOKEN"
```

A task ends in one of these states:

| State | Meaning |
| ----- | ------- |
| `SUBMITTED` | The adapter saw the configured success signal. |
| `PUBLISHED_UNVERIFIED` | The submission looks published - the link still has to be verified. |
| `WAITING_FOR_USER` | A human has to finish the submission; a *submission pack* was prepared. |
| `WAITING_FOR_APPROVAL` | A draft was prepared (for example an outreach email) and needs approval. |
| `RETRY_SCHEDULED` | A transient error - the task is retried with an exponential backoff. |
| `FAILED` | The error is not retryable (or the retry budget is exhausted). |
| `SKIPPED` | The adapter decided that the target is not suitable (robots.txt, missing fields, ...). |

**6. Verify**

```bash
curl -s -X POST http://localhost:8000/api/v1/verification/run \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"project_id\":\"$PROJECT_ID\",\"force\":true}"

curl -s "http://localhost:8000/api/v1/verification/records?project_id=$PROJECT_ID" \
  -H "Authorization: Bearer $TOKEN"
```

Each record reports `link_present`, `destination_matched`, `observed_anchor_text`,
`link_attribute` and `http_status`, and every check is stored as a
`verification_run`.  A record reaches `VERIFIED_LIVE` only when the link is
present **and** it points to the expected destination.

**7. Export**

```bash
REPORT=$(curl -s -X POST http://localhost:8000/api/v1/reports \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"project_id\":\"$PROJECT_ID\",\"format\":\"xlsx\",\"scope\":\"project:$PROJECT_ID\"}")

REPORT_ID=$(echo "$REPORT" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
curl -s -o report.xlsx "http://localhost:8000/api/v1/reports/$REPORT_ID/download" \
  -H "Authorization: Bearer $TOKEN"
```

The workbook contains one sheet per section: executive summary, all
opportunities, verified backlinks, pending / failed / skipped tasks, the
verification history, the activity log and the import errors.

**8. Re-import**

```bash
# preview first - nothing is written
curl -s -X POST http://localhost:8000/api/v1/imports/preview \
  -H "Authorization: Bearer $TOKEN" -F "file=@report.xlsx" -F "project_id=$PROJECT_ID"

IMPORT_ID=<import_job_id from the response>

# apply it
curl -s -X POST "http://localhost:8000/api/v1/imports/$IMPORT_ID/commit" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"dry_run":false}'

# rows that could not be processed
curl -s "http://localhost:8000/api/v1/imports/$IMPORT_ID/rows" -H "Authorization: Bearer $TOKEN"
curl -s -o errors.csv "http://localhost:8000/api/v1/imports/$IMPORT_ID/error-report" \
  -H "Authorization: Bearer $TOKEN"
```

The importer detects the columns, decides per row whether to create, update,
skip, retry, verify, flag as conflict or reject it, and reuses the existing
opportunities - so a report that is exported and imported again does not
duplicate the registry.

---

## Known limitations

* **No email transport.**  The outreach adapter produces a draft that a human
  sends; nothing is ever sent automatically.
* **Celery is opt-in.**  The dispatcher (`app/workers/celery_app.py`) needs
  `AUTOBL_USE_CELERY=true` and a reachable broker; the compose stack uses the
  database worker instead.
* **Verification is a single fetch.**  The engine checks the published page
  once per run; pages that need JavaScript are reported as `UNKNOWN` and are
  never counted as a success.
* **Only two discovery providers work without credentials.**  `manual_seed`
  and `directory_index`; Brave Search and SerpAPI need an API key.
* **Playwright browsers are not installed by `bootstrap.sh`.**  Run
  `../../.venv/bin/python -m playwright install chromium` before using the
  `playwright_form` adapter.
* **AI output is advisory.**  Everything the AI layer produces can be edited
  by the operator, and the deterministic fallback is used whenever the
  provider is unavailable.
* **`AUTOBL_ALLOW_PRIVATE_NETWORK=true` disables the SSRF protection.**  Never
  enable it on a machine that fetches user supplied URLs.
* **The `POST /api/v1/devices/*` endpoints are not authenticated** with a user
  token; the agent API key is the credential.  Rotate it if it leaks.
* **Project isolation is enforced on the list, read, write and bulk-action
  paths.**  Workspace level rows (tasks without a project) stay visible to
  every authenticated user; everything that belongs to a project is restricted
  to the owner of that project (administrators see everything).

### What was executed while building this repository

The build machine had no Python, Node, Rust, Docker, PostgreSQL or Redis, so
the toolchain was installed locally (uv-managed CPython 3.12, Node 22 from
nodejs.org).  Everything below was actually run:

| Check | Command | Result |
| ----- | ------- | ------ |
| Backend lint | `apps/api: ruff check app scripts tests` | pass |
| Backend test suite | `apps/api: pytest` | 129 passed |
| Backend smoke test | `apps/api: python scripts/smoke_core.py` | 21/21 assertions pass |
| Import / export engine | `apps/api: python scripts/check_dataflow.py` | pass (preview → commit → 9-sheet workbook) |
| Automation engine | `apps/api: python scripts/check_automation.py` | pass (providers, adapters, scoring, statuses) |
| Hybrid local-agent path | `scripts/smoke_local_agent.py` | pass (register → claim → execute → report → attempt + events) |
| **Real browser automation** | `scripts/check_browser_automation.py` | pass - a real Chromium fills the form with the profile facts, submits it, the success signal is detected and the backlink record is created (never simulated) |
| **Packaged desktop app** | `apps/desktop/scripts/check-desktop.py` | pass - first launch, second launch while the backend runs (no port conflict, no restart loop, one backend) and a full restart keep the local session valid (no 401) |
| **Disk image** | mount `release/macos/*.dmg` and start the app from it | pass - the bundled backend starts from the mounted image, `/health` answers, the API accepts the local token and rejects a missing one |
| **Desktop runs offline** | `apps/desktop/scripts/check-offline.py` | pass - 41 checks: every request is served by the local backend, **0 requests leave the machine**, no console error, the local token never travels to a remote host, and the cloud is only used after the operator selects it |
| Full product loop | `scripts/acceptance.py` | pass (profile → project → discovery → approve → queue → worker → activity → metrics → 9-sheet report → re-import preview → commit) |
| Migrations | `alembic upgrade head → downgrade base → upgrade head` | pass (29 tables, both dialects) |
| PostgreSQL dialect | `CreateTable(...).compile(postgresql)` for every table | pass (29/29) |
| Web client | `npm run build` (Next.js) | pass (17 routes) |
| Desktop client | `npm run build` (Vite + `tsc --noEmit`) | pass |
| Desktop sidecar | `scripts/build-sidecar.sh` (PyInstaller) | pass - 69 MB executable (Playwright package included), starts, creates the SQLite database, answers `/health` |
| Native macOS bundle | `npm run tauri:build -- --target universal-apple-darwin` + `scripts/build-dmg.sh` | pass - **universal** app (x86_64 + arm64) with the backend bundled for both architectures; `Auto Backlinker_1.0.0_universal.dmg` (160 MB) mounts, runs and answers `/health` |

Not executed here, and therefore **not claimed as working**:

* **The Windows installer.**  The Tauri configuration declares the `msi` and
  `nsis` targets and the PowerShell sidecar script exists, but the build
  machine is macOS - the Windows artifact has to be produced on Windows (or
  with the `windows-*-msvc` cross toolchain and the NSIS tooling).* **Code signing.**  The `.app` / `.dmg` are unsigned; a distributable build
  needs an Apple Developer ID certificate plus notarization (and an
  Authenticode certificate for Windows).
* **The Docker image and the compose stack**: Docker is not installed here;
  the compose file and Dockerfile are provided but were not built.
* **PostgreSQL and Redis at runtime**: the SQLAlchemy models, migrations and
  the queue all compile for PostgreSQL, but no server was available to run
  the integration path against one.
* **Live submission to a real third-party directory**: no form was submitted
  to a live site during development or testing; the form adapters were
  exercised against a local HTTP fixture.

> Tauri's own `bundle_dmg.sh` step needs AppleScript automation of the
> Finder, which is not permitted on this build machine ("AppleEvent timed
> out").  `apps/desktop/scripts/build-dmg.sh` therefore creates the disk
> image with `hdiutil` only - the same deliverable, without the decorative
> background image.

---

## License

Private project - all rights reserved.
