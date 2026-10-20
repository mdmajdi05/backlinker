# Architecture

This document describes how the Auto Backlinker backend is put together:
the storage abstraction, the task state machine, the adapter framework, the
discovery pipeline, the verification pipeline and the hybrid / local
execution model.

The guiding principle is **observability**: the platform may only report what
it has really seen.  A metric that would require third-party data is not
guessed - it is listed in `unavailable_metrics`.  A submission is only
successful when a configured success signal is present in the answer.  A
backlink is only `VERIFIED_LIVE` when the link was really found in the
fetched HTML.

---

## 1. Layers

```
routes (app/api/routes)      HTTP shape, validation, authorisation, status codes
services (app/services)      business logic - no HTTP knowledge
repositories (app/db)        portable SQL, pagination, atomic claiming
models (app/db/models.py)    the schema - dialect agnostic
core (app/core)              config, logging, security, network helpers
workers (app/workers)        the execution loop that drives the services
```

Dependencies point in one direction only: `routes → services → repositories →
models`.  A service never imports a router; a repository never imports a
service.

---

## 2. Storage abstraction

### 2.1 One active database, many dialects

`app/core/config.py` resolves the database URL:

```
settings.database_url  →  used as is
otherwise               →  sqlite:///<data_dir>/autobacklinker.db
```

`app/db/session.py` creates the engine and applies dialect specific options:

| Dialect | Options |
| ------- | ------- |
| SQLite | `check_same_thread=False`, `timeout=30`, WAL journal, `synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout=30000` |
| PostgreSQL | `pool_size`, `max_overflow = 2 × pool_size`, `pool_pre_ping`, `pool_recycle=1800` |

The models use portable column types only (`String`, `Text`, `Integer`, `Float`,
`Boolean`, `DateTime`, `JSON`), so the identical schema runs on SQLite and on
PostgreSQL.  JSON columns are used for the free-form configuration blocks
(`project_settings.operating_schedule`, `adapter_configurations.config`,
`website.score_breakdown`, …) instead of JSONB, which keeps SQLite parity.

### 2.2 Repositories

`app/db/repositories.py` contains the generic `Repository` (CRUD),
`paginate()` (offset pagination with a separate count statement) and
`TaskClaimRepository` (atomic claiming).  All of them use portable SQLAlchemy
constructs - no dialect specific SQL is emitted anywhere.

### 2.3 Storage modes

| Mode | Behaviour |
| ---- | --------- |
| `local` | The SQLite file in the data directory.  The desktop default. |
| `cloud` | The PostgreSQL server from `AUTOBL_DATABASE_URL`. |
| `hybrid` | Local SQLite plus a synchronisation queue towards the cloud. |
| `auto` | `cloud` when a PostgreSQL URL is configured, otherwise `local`. |

The mode is stored in the `app_settings` table (key `storage`) and can be
changed at runtime through `/api/v1/storage/connect`.  Switching never
deletes local data: `POST /api/v1/storage/migration/preview` shows what would
be copied, `POST /api/v1/storage/migration/run` copies it.

### 2.4 Backups

`POST /api/v1/storage/backup` writes a `.bak` file into
`<data_dir>/backups`:

* SQLite - a byte copy of the database file;
* PostgreSQL - a JSON dump of every table (works without `pg_dump`).

`POST /api/v1/storage/restore` reverses it.

### 2.5 Schema management

* **Local / desktop** - `AUTOBL_AUTO_CREATE_SCHEMA=true` (default) calls
  `Base.metadata.create_all()` at startup.  A fresh installation therefore
  needs no migration command.
* **Production** - set the variable to `false` and use Alembic
  (`apps/api/scripts/migrate.sh`).  The baseline revision
  `0001_initial_schema` creates the same schema on SQLite and PostgreSQL
  because it delegates to `Base.metadata.create_all(bind=op.get_bind())`.

---

## 3. The task state machine

Every long running unit of work is a row in `tasks`.  A task has a stable
`idempotency_key`, so re-importing a report or queueing the same opportunity
twice never duplicates work.

```
                       ┌──────────────────────────────┐
                       │  DISCOVERED (paused)         │
                       └──────────────┬───────────────┘
                                      │ resume
                                      ▼
   enqueue()          ┌──────────────────────────────┐
  ─────────►         │  QUEUED                       │
                     └──────────────┬───────────────┘
                                    │ claim (atomic UPDATE)
                                    ▼
                     ┌──────────────────────────────┐
                     │  RUNNING                      │◄──── lease expired
                     └──────────────┬───────────────┘        (reclaim)
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
        ▼                           ▼                           ▼
  SUBMITTED /              WAITING_FOR_USER          RETRY_SCHEDULED
  PUBLISHED_UNVERIFIED     WAITING_FOR_APPROVAL              │
        │                           │                           │
        │                           │ (operator acts)          │ backoff
        │                           ▼                           └──► QUEUED
        ▼                       QUEUED
   COMPLETED
        │
        ▼
   VERIFIED_LIVE  (after the verification task)
```

Terminal states: `VERIFIED_LIVE`, `SKIPPED`, `CANCELLED`, `FAILED` (when the
retry budget is exhausted).

### 3.1 Claiming

`TaskClaimRepository.try_claim()` performs a conditional `UPDATE`:

```sql
UPDATE tasks
   SET status='RUNNING', lease_owner=:worker, lease_expires_at=:until, started_at=…
 WHERE id=:id
   AND status IN ('QUEUED','RETRY_SCHEDULED')
   AND (lease_expires_at IS NULL OR lease_expires_at < :now)
   AND (lease_owner IS NULL OR lease_owner = '')
```

Only the transaction that changes exactly one row wins, therefore two workers
can never own the same task - on SQLite as well as on PostgreSQL.

### 3.2 Leases and recovery

A claimed task carries `lease_expires_at` (`AUTOBL_TASK_LEASE_SECONDS`,
default 300 s).  The worker reclaims expired leases every 30 seconds and
returns the task to `RETRY_SCHEDULED` with the note *"Worker lease expired -
task returned to queue"*.  A crashed worker therefore costs at most one
lease period.

### 3.3 Retries

`fail_task()` increments `attempts` and computes the backoff from the project
settings:

```
delay = backoff_base_seconds × 2^(attempts-1) + random(0, jitter_seconds)
```

Defaults: 30 s base, 15 s jitter.  The task is scheduled with
`next_retry_at` / `scheduled_for`, so it becomes claimable again.

### 3.4 Attempts and events

* `task_attempts` - append-only history: one row per attempt with the outcome,
  the error, the evidence and the worker that executed it.  Attempts are
  never overwritten.
* `task_events` - append-only activity log.  Every entry is also published to
  the in-process event bus and streamed to the browser over SSE.

### 3.5 Concurrency limits

Before claiming, `Worker.within_limits()` checks:

* the global limit (`AUTOBL_WORKER_BATCH_SIZE × 2`),
* the per-project limit (`project_settings.max_concurrency`),
* the per-domain limit (`project_settings.per_domain_concurrency`).

### 3.6 Schedules

`app/services/scheduler.py` implements a portable interval scheduler on top of
the `schedules` table - no cron daemon is needed:

* a schedule stores its `kind` (`discovery` or `verification`), its interval
  and the moment of its next run,
* the worker calls `tick_schedules()` every 30 iterations,
* a due schedule queues the corresponding tasks (verification runs for the
  links that are due, a discovery run for the configured target),
* `last_run_at` is updated and `next_run_at` is moved forward by the
  interval.

---

## 4. The adapter framework

An adapter is the contract between the platform and one way of submitting to
a target.  `app/services/adapters/base.py` defines it:

```python
class BaseAdapter:
    key: str
    supported_categories: tuple[str, ...]
    supported_methods: tuple[str, ...]
    supported_environments: tuple[str, ...]
    required_config: dict
    required_user_fields: tuple[str, ...]
    registration_required: bool
    manual_approval_required: bool
    automatable: bool
    verification_method: str
    retryable_errors: tuple[str, ...]
    success_signals: tuple[str, ...]
    domains: tuple[str, ...]

    def preflight(ctx) -> SubmissionResult | None: ...
    def submit(ctx) -> SubmissionResult: ...
    def verify(ctx, published_page_url) -> dict: ...
```

### 4.1 Rules the framework enforces

1. **A success signal is mandatory.**  `SubmissionResult.succeeded` is only
   true for `SUBMITTED` and `PUBLISHED_UNVERIFIED`.  An adapter has to prove
   it - a confirmation message, a published page, a documented API answer.
2. **A human stays in control.**  Adapters that need an account, a payment or
   an editor's decision return `WAITING_FOR_USER` or `WAITING_FOR_APPROVAL`.
   The framework then prepares a *submission pack* (URL, anchor text,
   description, contact data) so the operator only has to paste it.
3. **Challenges are never bypassed.**  CAPTCHAs, login walls and cookie
   consent walls are detected (`challenge_kind()`) and the task is paused for
   a human.
4. **The adapter is data.**  Every adapter is also a row in
   `automation_adapters`, so the user can enable / disable it and configure
   it per project (`adapter_configurations`).

### 4.2 Resolution

`adapter_for_website()` picks the adapter:

1. a domain specific adapter (the longest matching domain wins),
2. otherwise the first automatable adapter that supports the category,
3. otherwise the manual pack.

The task can also pin an adapter explicitly (`tasks.adapter_id`).

### 4.3 Shipped adapters

| Key | Kind | What it does |
| --- | ---- | ------------ |
| `generic_manual` | `MANUAL_ASSISTED` | Prepares the submission pack and hands the task to the operator. |
| `http_form` | `BROWSER_AUTOMATION` | Posts a plain HTML form with `httpx` (no JavaScript).  Configured selectors decide the fields and the success signal. |
| `playwright_form` | `BROWSER_AUTOMATION` | Same, but with a real browser.  Pauses on a challenge. |
| `email_outreach` | `EMAIL_OUTREACH` | Prepares a personalised draft.  **Never sends.** |
| `json_api` | `OFFICIAL_API` | Posts a JSON document to a documented endpoint and checks the configured success field. |

All outbound requests travel through `app/core/net.py`:

* `assert_public_url()` rejects non-HTTP schemes, embedded credentials and
  hosts that resolve to private / loopback / link-local addresses (SSRF guard,
  disabled only by `AUTOBL_ALLOW_PRIVATE_NETWORK=true`),
* every redirect hop is validated again,
* `robots.txt` is honoured when `AUTOBL_RESPECT_ROBOTS=true`,
* the response is truncated to 2 MB and a rate limiter caps the requests per
  minute (`AUTOBL_MAX_REQUESTS_PER_MINUTE`).

---

## 5. The discovery pipeline

```
POST /api/v1/discovery/runs
        │
        ├─ validate the provider and its credentials
        ├─ create the DiscoveryRun row (status PENDING)
        └─ enqueue a DISCOVER task (idempotency key DISCOVER:<project>:<run>)
                 │
                 ▼  worker → services/discovery/runner.py
        provider.discover(criteria)
                 │
                 ├─ raw results (name, domain, url, category, …)
                 ├─ fetch the page (SSRF safe, robots aware)
                 ├─ extract the observable title / description / text
                 ├─ classify the category (keyword rules, never guessed)
                 └─ score the opportunity (services/scoring.py)
                 │
                 ▼
        create_website()   → deduplicated by domain + normalised URL
        link_to_project()  → one Opportunity per project
                 │
                 ▼
        Opportunity.status = NEEDS_REVIEW
```

### 5.1 Providers

| Key | Credentials | Notes |
| --- | ----------- | ----- |
| `manual_seed` | none | Uses the URLs the operator supplies. |
| `directory_index` | none | Built-in catalogue of publicly documented submission pages; the reachability is verified live. |
| `brave_search` | `AUTOBL_BRAVE_SEARCH_API_KEY` | Official Brave Search API. |
| `serpapi` | `AUTOBL_SERPAPI_API_KEY` | SerpAPI (Google, Bing, …). |

The key is looked up in the configuration of the run first, then in the
environment, then in the settings.

### 5.2 Deduplication

`canonical_website_key()` normalises the URL (scheme, host, trailing slash,
no fragment) and combines it with the registrable domain.  A website that
already exists is reused, the run counts it as a duplicate and the
opportunity is linked to the project instead.

### 5.3 Scoring

`app/services/scoring.py` computes the score from observable input only:
topical relevance (keyword overlap with the profile), editorial relevance,
link allowance, documented submission, effort, business value, relationship
and a spam penalty.  Metrics that would need third-party data
(`domain_authority`, `traffic_estimate`, `publication_status`) are reported
in `unavailable_metrics` instead of being estimated.

---

## 6. The verification pipeline

A successful submission creates a `backlink_records` row with
`verification_status = SUBMITTED` / `PUBLISHED_UNVERIFIED`.  It is **not**
yet a verified backlink.

```
POST /api/v1/verification/run
        └─ enqueue a VERIFY task per record (idempotency key VERIFY:<record>:<scheduled|force>)
                 │
                 ▼  worker → services/verification.py
        safe_get(published_page_url, allow_robots=True)
                 │
                 ├─ extract every anchor (href, text, rel)
                 ├─ match the expected destination (exact, then domain level)
                 ▼
        VerificationRun (append-only) + update of the record
```

| Observation | Resulting status |
| ----------- | ---------------- |
| The link to the expected destination was found | `VERIFIED_LIVE` |
| The page is live but the link was not found | `VERIFICATION_FAILED` |
| The page renders with JavaScript | `UNKNOWN` (never a failure, never a success) |
| HTTP 404 / 410 | `REMOVED` |
| HTTP 5xx, 403, 408, 429 or a network error | `TEMPORARILY_UNAVAILABLE` |
| Blocked by `robots.txt` | `UNKNOWN` |
| The record was verified recently and `force` is not set | `SKIPPED` |

Every run stores the evidence: the requested URL, the final URL, the HTTP
status, the redirects, the number of scanned links, the expected and the
observed destination, the observed anchor text and the `rel` attribute.
`next_verification_at` schedules the next check
(`AUTOBL_VERIFICATION_INTERVAL_HOURS`, default 168 h).

---

## 7. Import and export

### Import

```
POST /api/v1/imports/preview   (multipart, dry run)
        ├─ detect the header row
        ├─ map the columns (aliases + fuzzy match)
        ├─ normalise and validate every row
        ├─ decide per row: CREATE / UPDATE / SKIP / RETRY / VERIFY / CONFLICT / INVALID
        └─ store the plan (import_jobs.detected_mapping, import_rows)
POST /api/v1/imports/{id}/commit
        └─ apply the plan, reuse the existing opportunities, never duplicate
GET  /api/v1/imports/{id}/error-report   → CSV of the invalid rows
```

The column detection lives in `app/services/dataflow/mapping.py` and is
shared with the exporter and the AI layer.

### Export

`POST /api/v1/reports` writes an XLSX (or CSV) workbook with one sheet per
section: executive summary, all opportunities, verified backlinks, pending /
failed / skipped tasks, verification history, activity log and import errors.
The file is stored in the managed files directory and can be downloaded
through `/api/v1/reports/{id}/download`.

---

## 8. The AI layer (optional)

`app/services/ai.py` is a thin, optional layer on top of the deterministic
implementation of every helper.

```
provider = get_provider()          # OpenAI / OpenRouter / Groq / Ollama /
                                    # LM Studio / Anthropic / NullProvider
if not provider.is_available():
    return deterministic_fallback()  # rule based, never fabricated
```

| Helper | Deterministic fallback |
| ------ | ---------------------- |
| `classify_opportunity` | Keyword matching against the registered categories |
| `explain_relevance` | Sentence built from the overlap of profile and page data |
| `suggest_anchors` | Preferred anchors, brand name, keywords, target host |
| `draft_outreach_email` | Template that only repeats facts of the profile |
| `draft_directory_description` | The first business description or a composed fact list |
| `map_columns` | The alias table of the dataflow module |
| `summarize_errors` | Grouping of the errors by code |
| `recommend_next_actions` | Rules over the counters of the workspace |
| `detect_low_value` | Score, nofollow, ugly URL, duplicate, … |
| `plan_automation` | Steps derived from the counters of the project |

Every answer carries `ai_generated`, so the UI can label machine generated
content.

**Safety rules**

* The system prompt states that every content that comes from a third-party
  page, spreadsheet or website is *untrusted data* and that instructions
  inside it must never be followed.
* The model never produces configuration, credentials or security settings -
  its output is only text or structured suggestions that a human can edit.
* The prompts and the answers are length limited (12 000 / 8 000 characters)
  and the JSON answers are parsed defensively.
* No provider configured, a network error or an unusable answer all lead to
  the same deterministic fallback - the product never depends on the AI.

---

## 9. Hybrid and local execution

### 9.1 Execution environments

Every task carries `execution_environment`:

| Value | Executed by |
| ----- | ----------- |
| `CLOUD` | The worker of the cloud deployment (the API process or the standalone worker container). |
| `LOCAL` | A registered local agent (`/api/v1/devices/*`) on the machine of the operator. |

A local agent registers itself, receives an API key, sends heartbeats and
claims the `LOCAL` tasks:

```
POST /api/v1/devices/register            → device_id + api_key
GET  /api/v1/devices/tasks/claim          → one task (Authorization: Bearer <api key>)
POST /api/v1/devices/tasks/{id}/report    → {"status": "SUCCEEDED"|"FAILED", "result": {...}}
```

This is how a target that only accepts a real browser (a local session, a
captcha the operator solves, an internal submission portal) is handled: the
task is routed to the `LOCAL` environment and executed on a machine that the
operator controls.

### 9.2 Hybrid storage

```
   local SQLite                          cloud PostgreSQL
   ┌──────────────────┐                  ┌──────────────────┐
   │ projects         │◄──── push ─────►│ projects         │
   │ opportunities    │                  │ opportunities    │
   │ tasks            │◄──── pull ─────►│ tasks            │
   └────────┬─────────┘                  └──────────────────┘
            │
            │ sync_changes (entity_type, entity_id, operation, version, payload, conflict)
            ▼
      change queue + conflict list
```

* Every local write is recorded in `sync_changes`.
* `POST /api/v1/sync/push` sends the pending changes to the cloud.
* `POST /api/v1/sync/pull` imports the remote changes.
* The version is compared on both sides: a newer cloud version wins, an older
  local version is queued for the next push, and a real conflict is flagged
  for the operator (`POST /api/v1/sync/conflicts/{id}/resolve` with the
  strategy `local` or `remote`).

The cloud is the source of truth for the synchronised entities; the local
database stays usable when the cloud is unreachable.

### 9.3 Desktop mode

The desktop bundle starts the API as a sidecar on `127.0.0.1` with a random
port and a shared `AUTOBL_LOCAL_TOKEN`.  The client authenticates with the
local token (or with a normal JWT) and everything - database, uploads,
backups, the embedded worker - lives in the data directory of the operating
system.  The same client can be switched to a cloud backend by changing the
base URL; the protocol does not change.

---

## 10. Security summary

| Concern | Measure |
| ------- | ------- |
| Passwords | PBKDF2-HMAC-SHA256 with 240 000 rounds and a random salt (`app/core/security.py`) - no native dependency. |
| Sessions | JWT (HS256) signed with `AUTOBL_SECRET_KEY`, 12 h lifetime. |
| Password / token leakage in the logs | `app/core/logging.py` redacts `password`, `token`, `api_key`, `secret`, `authorization` and `cookie`. |
| SSRF | `app/core/net.py` validates the scheme, the host and every redirect hop; private addresses are rejected. |
| Robots | Honoured by default (`AUTOBL_RESPECT_ROBOTS=true`). |
| Rate limit | `AUTOBL_MAX_REQUESTS_PER_MINUTE` plus the per-domain concurrency limit. |
| Uploads | Extension and magic byte check, `AUTOBL_MAX_UPLOAD_MB` limit, files stored in the managed files directory. |
| Prompt injection | Third-party content is passed to the AI as untrusted data; the system prompt forbids following instructions inside it. |
| Secrets in the API | The AI status endpoint only reports whether a provider is configured - never the key. |
| Audit | `audit_logs` records the create / update / delete / bulk actions with the actor. |
