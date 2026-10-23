# API reference

Base URL of a local installation: `http://localhost:8000`
API prefix: `/api/v1` (configurable with `AUTOBL_API_PREFIX`)

Interactive documentation: <http://localhost:8000/docs> (Swagger UI),
<http://localhost:8000/redoc>, <http://localhost:8000/openapi.json>

---

## Authentication

| Mechanism | Header | Used by |
| --------- | ------ | ------- |
| JWT access token | `Authorization: Bearer <token>` | Every endpoint marked **yes** below |
| Local token (desktop sidecar) | `X-Local-Token: <token>` | The bundled desktop backend; requires `AUTOBL_LOCAL_TOKEN` to be set |
| Device API key | `Authorization: Bearer <agent key>` or `?authorization=<agent key>` | The local agent endpoints (`/devices/register`, `/devices/tasks/claim`, `/devices/tasks/{id}/report`, `/devices/{id}/heartbeat`) |

Obtain a token:

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"me@example.com","password":"a-strong-password","name":"Me"}'
```

The response contains `access_token`, `token_type` and `expires_in`
(`AUTOBL_ACCESS_TOKEN_EXPIRE_MINUTES`, default 720).

### Errors

Every error uses the same envelope:

```json
{
  "error": {
    "code": "not_found",
    "message": "Opportunity not found",
    "details": null,
    "request_id": null
  }
}
```

| Status | Typical code |
| ------ | ------------ |
| `400` | `invalid`, `unknown_action`, `invalid_request`, `provider_unavailable` |
| `401` | `not_authenticated`, `invalid_token`, `invalid_credentials`, `unauthorized` |
| `403` | `forbidden` |
| `404` | `not_found` |
| `409` | `already_committed`, `conflict`, `email_taken` |
| `413` | `file_too_large` |
| `422` | `validation_error`, `invalid_request` |
| `500` | `internal_error` |

### Pagination

List endpoints accept `page` (default `1`), `page_size` (default `25`, max
`500`), `sort` and `order` (`asc` / `desc`) and return:

```json
{ "items": [], "total": 0, "page": 1, "page_size": 25, "pages": 1 }
```

---

## System

| Method | Path | Purpose | Auth |
| ------ | ---- | ------- | ---- |
| GET | `/health` | Liveness probe: version, database check, worker status, storage mode. | no |
| GET | `/api/v1/system/info` | Name, version, environment, storage mode, database type, data directory, AI / Celery flags. | no |
| GET | `/docs`, `/redoc`, `/openapi.json` | Generated documentation. | no |

---

## Auth — `/api/v1/auth`

| Method | Path | Purpose | Auth |
| ------ | ---- | ------- | ---- |
| POST | `/api/v1/auth/register` | Create an account and return an access token. `409` when the email is taken. | no |
| POST | `/api/v1/auth/login` | Exchange email + password for an access token. | no |
| GET | `/api/v1/auth/me` | The profile of the authenticated user. | yes |

---

## Business profiles — `/api/v1/profiles`

A profile holds everything the automation needs to describe the business:
descriptions, author bios, keywords, landing pages, preferred anchors, target
countries, excluded domains, monthly target and campaign goals.

| Method | Path | Purpose | Auth |
| ------ | ---- | ------- | ---- |
| GET | `/api/v1/profiles` | List all profiles. | yes |
| POST | `/api/v1/profiles` | Create a profile. | yes |
| GET | `/api/v1/profiles/{profile_id}` | Read one profile. | yes |
| PUT | `/api/v1/profiles/{profile_id}` | Replace a profile. | yes |
| DELETE | `/api/v1/profiles/{profile_id}` | Delete a profile. | yes |

---

## Projects — `/api/v1/projects`

| Method | Path | Purpose | Auth |
| ------ | ---- | ------- | ---- |
| GET | `/api/v1/projects` | Paginated list of the projects of the user. | yes |
| POST | `/api/v1/projects` | Create a project with its settings and landing pages. | yes |
| GET | `/api/v1/projects/{project_id}` | One project including its settings and counts. | yes |
| PATCH | `/api/v1/projects/{project_id}` | Update name, description, target website, … | yes |
| DELETE | `/api/v1/projects/{project_id}` | Move a project to the recycle bin (its opportunities, tasks and records stay). | yes |
| GET | `/api/v1/projects/{project_id}/settings` | Concurrency, rate limits, retries, verification interval, approval policy, execution environment. | yes |
| PUT | `/api/v1/projects/{project_id}/settings` | Replace the settings. | yes |
| GET | `/api/v1/projects/{project_id}/campaigns` | Campaigns of the project. | yes |
| POST | `/api/v1/projects/{project_id}/campaigns` | Create a campaign. | yes |

---

## Campaign cockpit — `/api/v1/projects/{project_id}/campaign`

The one screen of a project. A campaign is a **view** over the existing
websites, opportunities, tasks and backlink records - it is not a second source
of truth.

| Method | Path | Purpose | Auth |
| ------ | ---- | ------- | ---- |
| GET | `/api/v1/projects/{project_id}/campaign` | Every website of the project with `details_percent`, `status`, `last_update` and the counters (`done`, `verified`, `submitted`, `in_progress`, `waiting_manual`, `needs_details`, `failed`, `remaining`, `percent`). | yes |
| POST | `/api/v1/projects/{project_id}/campaign/websites` | Body `{"text": "a.example/x, b.example/y"}` (or `{"urls": [...]}`). Adds every URL to the central list once and links it to the project. Answers every URL with `added`, `linked`, `existing`, `deleted` or `invalid`. | yes |
| POST | `/api/v1/projects/{project_id}/campaign/import` | Multipart `file` (XLSX/CSV). Imports into the central list and links the imported rows to the project. | yes |
| POST | `/api/v1/projects/{project_id}/campaign/start` | Fills the details from the business profile, sets the project `ACTIVE` and queues every website with complete details. Returns `queued`, `already_queued`, `needs_details` (with the missing labels), `done`, `excluded`. Never queues a half filled row and never duplicates a finished task. | yes |
| POST | `/api/v1/projects/{project_id}/campaign/{opportunity_id}/submit` | Body `{"published_url"?, "anchor_text"?, "verify"?}`. Records a manual submission, completes the waiting task, writes the backlink record and (by default) queues the verification. The record stays `SUBMITTED` - never `VERIFIED` without a real check. | yes |
| POST | `/api/v1/projects/{project_id}/campaign/{opportunity_id}/verify` | Queue a verification of the backlink of one row. | yes |

Row statuses: `NEEDS_DETAILS`, `READY`, `QUEUED`, `SUBMITTING`,
`WAITING_MANUAL`, `SUBMITTED`, `VERIFIED`, `FAILED`, `VERIFICATION_FAILED`,
`EXCLUDED`.

---

## Campaigns and schedules

| Method | Path | Purpose | Auth |
| ------ | ---- | ------- | ---- |
| DELETE | `/api/v1/campaigns/{campaign_id}` | Delete a campaign. | yes |
| GET | `/api/v1/schedules` | List the schedules. | yes |
| POST | `/api/v1/schedules` | Create a schedule (`kind` is `discovery` or `verification`). | yes |
| PATCH | `/api/v1/schedules/{schedule_id}` | Update a schedule. | yes |
| DELETE | `/api/v1/schedules/{schedule_id}` | Delete a schedule. | yes |

> The schedules are ticked by the background worker (every 30 iterations).
> A due schedule queues the corresponding discovery or verification work.

---

## The website list — `/api/v1/websites`

The central list of websites where the backlinks are made. It is independent
of the projects: a project picks the sites it wants from it.

| Method | Path | Purpose | Auth |
| ------ | ---- | ------- | ---- |
| GET | `/api/v1/websites` | Paginated list with the per website statistics. Filters: `search`, `category`, `niche`, `status`, `project_id`, `sort`, `order`. Rows with `status=DELETED` are hidden unless they are asked for. | yes |
| POST | `/api/v1/websites` | Add a website to the list by hand (`opportunity_url`, `name`, `category`, `niche`, `notes`, `submission_method`). A duplicate domain + URL answers `409 duplicate`. | yes |
| PATCH | `/api/v1/websites/{id}` | Edit name, category, niche, notes, status (`ACTIVE`, `NEEDS_REVIEW`, `APPROVED`, `NOT_WORKING`, `EXCLUDED`, `REJECTED`, `DELETED`, …) or the exclusion date. | yes |
| DELETE | `/api/v1/websites/{id}` | Soft delete: the status becomes `DELETED`, the opportunities, the tasks and the history stay. | yes |
| POST | `/api/v1/websites/import` | Import Excel/CSV into the list. Answers how many rows were created, updated, skipped (a deleted site is never resurrected) or invalid - always with a reason. | yes |
| GET | `/api/v1/websites/stats` | One row per domain: opportunities, submitted, verified, failed, pending, waiting for details, last attempt. Computed, never stored. | yes |
| POST | `/api/v1/projects/{id}/websites/choose` | Pick websites from the list into a project (`website_ids`, optional `category`, `niche`, `anchor_text`, `target_landing_page`). Creates the opportunity and the submission task; a second run changes nothing. | yes |

## Submission details — `/api/v1/opportunities/{id}/details`

| Method | Path | Purpose | Auth |
| ------ | ---- | ------- | ---- |
| GET | `/api/v1/opportunities/{id}/details` | The values the target site asks for, plus `required`, `missing` and `complete`. | yes |
| PUT | `/api/v1/opportunities/{id}/details` | Save the fields that were sent. | yes |
| DELETE | `/api/v1/opportunities/{id}/details` | Clear the details of this opportunity. | yes |
| GET | `/api/v1/opportunities/{id}/details/required` | Only the required, the missing and the complete flag. | yes |
| GET | `/api/v1/opportunities/{id}/details/gaps` | Which details are missing, which of them can be derived from the business profile and which cannot - with a plain reason. | yes |
| POST | `/api/v1/opportunities/{id}/details/generate` | Fill the empty fields from the business profile (AI when it is configured, the deterministic profile facts otherwise). Never invents facts. | yes |

## Automatic submission — `/api/v1/projects/{id}/autopilot`

| Method | Path | Purpose | Auth |
| ------ | ---- | ------- | ---- |
| GET | `/api/v1/projects/{id}/autopilot` | The state: `enabled`, `categories`, `waiting`, `submitted`, `pending`, `queued`. | yes |
| POST | `/api/v1/projects/{id}/autopilot` | Switch it on or off (`enabled`, `categories`). When it is on, approving an opportunity queues it automatically. | yes |

---

## Registry / opportunities

| Method | Path | Purpose | Auth |
| ------ | ---- | ------- | ---- |
| GET | `/api/v1/opportunities` | Paginated list. Filters: `project_id`, `status`, `category`, `domain`, `source`, `backlink_status`, `search`, `min_score`, `execution_environment`. | yes |
| POST | `/api/v1/opportunities` | Add a website manually and link it to one or all projects of the user. | yes |
| GET | `/api/v1/opportunities/{opportunity_id}` | One opportunity including the website data. | yes |
| PATCH | `/api/v1/opportunities/{opportunity_id}` | Edit name, category, status, anchor text, description, adapter, … | yes |
| POST | `/api/v1/opportunities/bulk` | Bulk action: `approve`, `reject`, `exclude`, `delete`, `queue`, `add_to_project`. | yes |
| POST | `/api/v1/registry/exclusions` | Exclude a whole domain (`domain`, optional `until`, `reason`). | yes |
| POST | `/api/v1/registry/merge` | Merge duplicate websites (`primary_id`, `duplicate_ids`). | yes |

---

## Discovery — `/api/v1/discovery`

| Method | Path | Purpose | Auth |
| ------ | ---- | ------- | ---- |
| GET | `/api/v1/discovery/providers` | Available providers with `available` flag and the reason when a credential is missing. | yes |
| POST | `/api/v1/discovery/runs` | Queue a discovery run. Returns `202` with the run. | yes |
| GET | `/api/v1/discovery/runs` | Paginated list of runs (`project_id`). | yes |
| GET | `/api/v1/discovery/runs/{run_id}` | One run with its counters. | yes |

Request body of `POST /api/v1/discovery/runs`:

```json
{
  "project_id": "…",
  "provider": "directory_index",
  "query": "saas analytics directory",
  "keywords": ["product analytics"],
  "countries": ["US"],
  "language": "en",
  "category": "BUSINESS_DIRECTORY",
  "limit": 25,
  "seeds": [],
  "config": { "api_key": "…" }
}
```

`config.api_key` overrides the environment variable of the provider for this
run.

---

## Queue and tasks

| Method | Path | Purpose | Auth |
| ------ | ---- | ------- | ---- |
| GET | `/api/v1/queue` | Paginated list of tasks. Filters: `project_id`, `type`, `status`, `environment`, `search`. | yes |
| GET | `/api/v1/queue/stats` | Number of tasks per status (optionally for one `project_id`). | yes |
| POST | `/api/v1/queue` | Queue tasks for opportunities or whole projects. | yes |
| POST | `/api/v1/queue/reorder` | Re-prioritise the queue (`task_ids` in the desired order). | yes |
| POST | `/api/v1/queue/bulk-control` | Apply one control action to many tasks. | yes |
| POST | `/api/v1/queue/{task_id}/control` | `pause`, `resume`, `cancel`, `retry` or `requeue` a task. | yes |
| GET | `/api/v1/tasks/{task_id}` | One task. | yes |
| GET | `/api/v1/tasks/{task_id}/attempts` | Append-only attempt history. | yes |
| GET | `/api/v1/tasks/{task_id}/events` | Events of the task (max. 200). | yes |
| POST | `/api/v1/tasks/{task_id}/cancel` | Cancel a task. | yes |
| POST | `/api/v1/tasks/{task_id}/retry` | Requeue a task for another attempt. | yes |

`POST /api/v1/queue` body:

```json
{
  "project_ids": [],
  "opportunity_ids": ["…"],
  "type": "SUBMIT",
  "priority": 5,
  "scheduled_for": null,
  "execution_environment": "CLOUD",
  "adapter_id": null,
  "payload": {}
}
```

`type` is one of `DISCOVER`, `SUBMIT`, `VERIFY`, `IMPORT`, `EXPORT`, `MANUAL`.
`execution_environment` is `CLOUD` or `LOCAL` (`LOCAL` tasks are picked up by
a registered local agent).

---

## Verification — `/api/v1/verification`

| Method | Path | Purpose | Auth |
| ------ | ---- | ------- | ---- |
| GET | `/api/v1/verification/records` | Paginated list of backlink records. Filters: `project_id`, `status`, `search`. | yes |
| POST | `/api/v1/verification/run` | Queue verification tasks (`backlink_ids` or `project_id`, optional `force`). | yes |
| GET | `/api/v1/verification/records/{record_id}` | One backlink record. | yes |
| GET | `/api/v1/verification/records/{record_id}/history` | All verification runs of the record. | yes |

---

## Imports — `/api/v1/imports`

| Method | Path | Purpose | Auth |
| ------ | ---- | ------- | ---- |
| POST | `/api/v1/imports/preview` | Upload an `.xlsx` / `.xlsm` / `.xls` / `.csv` file and get the detected mapping plus a per-row plan. Nothing is written. | yes |
| POST | `/api/v1/imports/{import_id}/commit` | Apply the plan (`apply_actions`, `dry_run`). | yes |
| GET | `/api/v1/imports` | Paginated list of import jobs. | yes |
| GET | `/api/v1/imports/{import_id}` | One import job. | yes |
| GET | `/api/v1/imports/{import_id}/rows` | The row plan of the import. | yes |
| GET | `/api/v1/imports/{import_id}/error-report` | CSV download of the invalid rows. | yes |

The preview is a multipart request with the file in the `file` field and the
optional `project_id` field.

---

## Reports — `/api/v1/reports`

| Method | Path | Purpose | Auth |
| ------ | ---- | ------- | ---- |
| POST | `/api/v1/reports` | Generate a report. Body: `project_id`, `scope`, `format` (`xlsx` / `csv`). | yes |
| GET | `/api/v1/reports` | Paginated list of export jobs. | yes |
| GET | `/api/v1/reports/{export_id}/download` | Download the generated file. | yes |
| DELETE | `/api/v1/reports/{export_id}` | Delete an export job (the file stays on disk). | yes |

---

## Adapters — `/api/v1/adapters`

| Method | Path | Purpose | Auth |
| ------ | ---- | ------- | ---- |
| GET | `/api/v1/adapters` | All adapters with their capabilities and restrictions. | yes |
| PATCH | `/api/v1/adapters/{adapter_id}` | Enable / disable an adapter or change its metadata. | yes |
| GET | `/api/v1/adapters/{adapter_id}/configuration` | Per-project configuration of the adapter. | yes |
| PUT | `/api/v1/adapters/{adapter_id}/configuration` | Store the configuration (`project_id` optional = global). | yes |

---

## Browser automation and the worker — `/api/v1`

| Method | Path | Purpose | Auth |
| ------ | ---- | ------- | ---- |
| GET | `/api/v1/browser/status` | Is the isolated browser runtime ready? Includes the isolation guarantees (own profile, headless default, extensions and sync disabled). | yes |
| POST | `/api/v1/browser/install` | Download the browser runtime into the data directory of this installation. | yes |
| GET | `/api/v1/worker/status` | The execution state, the running jobs, the machine load and the effective limit. | yes |
| PUT | `/api/v1/worker/settings` | `max_browser_jobs`, `resource_preference`, `headless`, `per_domain_limit`, `per_domain_requests_per_minute`, `task_timeout_seconds`, `page_timeout_seconds`. | yes |
| POST | `/api/v1/worker/pause` | Stop claiming new jobs - the running ones finish. | yes |
| POST | `/api/v1/worker/resume` | Claim jobs again. | yes |
| POST | `/api/v1/worker/stop` | Stop claiming and cancel the running jobs. | yes |
| GET | `/api/v1/resources` | The current CPU, memory and disk measurement with the effective concurrency. | yes |

---

## Devices / local agents — `/api/v1/devices`

| Method | Path | Purpose | Auth |
| ------ | ---- | ------- | ---- |
| POST | `/api/v1/devices/register` | Register an agent, returns `device_id` and a one-time `api_key`. | no (device key) |
| GET | `/api/v1/devices` | List the registered devices. | yes |
| DELETE | `/api/v1/devices/{device_id}` | Revoke a device. | yes |
| POST | `/api/v1/devices/{device_id}/heartbeat` | Report the status of a device. | no (device key) |
| GET | `/api/v1/devices/tasks/claim` | Claim one task that is routed to the `LOCAL` environment. | no (device key) |
| POST | `/api/v1/devices/tasks/{task_id}/report` | Report the result of a claimed task. | no (device key) |

---

## Activity, dashboard and events

| Method | Path | Purpose | Auth |
| ------ | ---- | ------- | ---- |
| GET | `/api/v1/activity` | Paginated activity feed. Filters: `project_id`, `level`, `event_type`, `since`. | yes |
| GET | `/api/v1/dashboard/metrics` | Aggregated counters (`project_id` optional). | yes |
| GET | `/api/v1/events/recent` | The last events (`limit`, max. 200). | yes |
| GET | `/api/v1/events/stream` | Server-Sent Events stream of the live activity. | no |

The SSE stream sends `connected`, `ping` and one event per activity entry:

```
event: task.completed
data: {"event_type":"task.completed","message":"Task submitted","level":"SUCCESS", …}
```

---

## Storage and database — `/api/v1/storage`

| Method | Path | Purpose | Auth |
| ------ | ---- | ------- | ---- |
| GET | `/api/v1/storage/status` | Mode, database type, masked URL, pending sync changes, conflicts, schema version. | yes |
| POST | `/api/v1/storage/test` | Test a candidate database URL without changing anything. | yes |
| POST | `/api/v1/storage/connect` | Store the cloud connection and switch to hybrid mode. | yes |
| POST | `/api/v1/storage/disconnect` | Remove the cloud connection (local data is kept). | yes |
| GET | `/api/v1/storage/migration/preview` | Number of records that would be transferred to the cloud. | yes |
| POST | `/api/v1/storage/migration/run` | Copy the local dataset into the configured cloud database. | yes |
| POST | `/api/v1/storage/backup` | Create a backup of the active database. | yes |
| POST | `/api/v1/storage/restore` | Restore a backup (`path` optional = newest). | yes |
| GET | `/api/v1/storage/history` | List the available backups. | yes |

---

## Synchronisation (hybrid mode) — `/api/v1/sync`

| Method | Path | Purpose | Auth |
| ------ | ---- | ------- | ---- |
| GET | `/api/v1/sync/status` | Sync state, pending changes and conflicts. | yes |
| POST | `/api/v1/sync/push` | Push the local changes to the cloud. | yes |
| POST | `/api/v1/sync/pull` | Pull the cloud changes (`since` optional). | yes |
| GET | `/api/v1/sync/changes` | The changes a local workspace should pull (`since`, `limit`). | yes |
| POST | `/api/v1/sync/conflicts/{change_id}/resolve` | Resolve a conflict with the strategy `local` or `remote`. | yes |
| POST | `/api/v1/sync/{entity_type}` | Cloud side of the protocol: accept a pushed change (`projects`, `opportunities`). | yes |

---

## AI assistance — `/api/v1/ai`

The AI layer is optional.  When no provider is configured every helper falls
back to a deterministic implementation and the answer carries
`"ai_generated": false`.

| Method | Path | Purpose | Auth |
| ------ | ---- | ------- | ---- |
| GET | `/api/v1/ai/status` | `{"configured": bool, "provider": str \| null, "model": str \| null}`. | yes |
| POST | `/api/v1/ai/{action}` | Run one helper (see below). | yes |

Supported `action` values and their request bodies:

| Action | Body | Answer |
| ------ | ---- | ------ |
| `classify` | `{"text": "...", "url": "...", "categories": ["BUSINESS_DIRECTORY"]}` | `{"category", "confidence", "reasons", "ai_generated"}` |
| `explain` | `{"website": {...}, "profile": {...}}` | `{"text", "ai_generated"}` |
| `anchors` | `{"profile": {...}, "target_url": "...", "count": 5}` | `{"anchors": [...], "ai_generated"}` |
| `outreach` | `{"website": {...}, "profile": {...}, "anchor_text": "..."}` | `{"subject", "body", "ai_generated"}` |
| `description` | `{"profile": {...}, "category": "BUSINESS_DIRECTORY"}` | `{"description", "ai_generated"}` |
| `map-columns` | `{"headers": ["Business Name", "Target URL"]}` | `{"mapping": [{"source_column", "target_field", "confidence", "required", "ai_generated"}], "ai_generated"}` |
| `summarize` | `{"errors": [{"code": "...", "message": "..."}]}` | `{"summary", "ai_generated"}` |
| `recommend` | `{"context": {"pending_review": 5, "failed_tasks": 2}}` | `{"actions": [...], "ai_generated"}` |
| `plan` | `{"project_summary": {...}}` | `{"summary", "steps", "ai_generated"}` |

An unknown action returns `400` with the code `unknown_action` and the list of
supported actions in `details.supported`.

> The AI never changes configuration, credentials or security settings.  Text
> that was fetched from third-party pages is passed to the model as untrusted
> data and instructions inside it are ignored.

---

## Recycle bin — `/api/v1/recycle-bin`

Deleting a project, a business profile, a website or an opportunity does not
throw the row away.  It gets a `deleted_at` timestamp, disappears from the
normal endpoints and waits in the recycle bin - this keeps the old reports
truthful, because the submissions and the verification records are still there.

| Method | Path | Purpose | Auth |
| ------ | ---- | ------- | ---- |
| GET | `/api/v1/recycle-bin?kind=&page=&page_size=` | The removed rows, newest first, plus the count of every kind. | yes |
| GET | `/api/v1/recycle-bin/counts` | `{"project": n, "website": n, "profile": n, "opportunity": n}`. | yes |
| POST | `/api/v1/recycle-bin/{kind}/{id}/restore` | Bring the row back into the normal lists. | yes |
| DELETE | `/api/v1/recycle-bin/{kind}/{id}` | Delete it **forever**, with everything that depends on it. | yes |

`kind` is `project`, `website`, `profile` or `opportunity`.  An item looks like
`{"kind", "id", "title", "subtitle", "deleted_at", "meta"}`.

What "delete forever" removes:

* **project** - its opportunities, tasks, settings and landing pages,
* **website** - its opportunities and the tasks of those opportunities,
* **profile** - nothing else; the projects are only detached,
* **opportunity** - nothing else; its tasks stay in the history without the link.

Deleting also cancels the **open tasks** of the removed rows, so the worker
cannot submit work for something that is gone.

## Backlink details of a project — `/api/v1/projects/{id}/backlink-details`

The facts a directory asks for (company name, description, e-mail, phone,
website, address, categories, year founded, employees, anchors) live in the
**business profile** of the project - one place, shared by every website of the
project and by every project that uses the same profile.

| Method | Path | Purpose | Auth |
| ------ | ---- | ------- | ---- |
| GET | `/api/v1/projects/{id}/backlink-details` | The values, the target website, the landing pages, and `required` / `filled` / `missing`. | yes |
| PUT | `/api/v1/projects/{id}/backlink-details` | Write the values (only the fields that are sent).  Creates and links a profile when the project has none. | yes |

`POST /api/v1/projects` and `PATCH /api/v1/projects/{id}` accept a `details`
block with the same fields, so a project can be created complete in one call.
The answer also carries `shared_with_projects` and plain `notes` (for example
"these details are shared with 2 other projects") so the interface can tell the
truth instead of duplicating the data.

---

## Status codes

| Code | Meaning |
| ---- | ------- |
| `200` | Success |
| `201` | Created (register, profile, project, opportunity, campaign, schedule, device) |
| `202` | Accepted (discovery run, report generation) |
| `204` | No content (deletes) |
| `400` / `401` / `403` / `404` / `409` / `413` / `422` / `500` | See *Errors* above |
