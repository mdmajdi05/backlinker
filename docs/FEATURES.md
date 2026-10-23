# Feature parity: the web product and the desktop product

Both products run the **same** application code, but they are **two separate
products**:

| | Web product | Desktop product |
| - | ----------- | --------------- |
| Folder | `apps/web` | `apps/desktop` |
| Backend | `apps/api`, started separately | bundled into the app |
| Backend instance | its own | **its own** - never the web one |
| Database | SQLite (default) or PostgreSQL | SQLite in the app data directory |
| Start | `make dev-api` + `make dev-web` | one double click |
| Cloud | optional | optional, clearly labelled |

The desktop product **never depends** on the web backend or on a cloud
backend. Everything that needs the network (discovery, verification, form
submissions) is the only part that needs an internet connection - and it needs
it for the *target website*, not for the application itself.

The proof: `apps/desktop/scripts/check-offline.py` drives the packaged
application with a headless browser while every non-loopback request is
blocked - 41 checks, 0 external requests.

---

## The workflow of a backlink campaign

```
1. Project details       one project per website, with its own company facts
2. Assign websites       the category-filtered central list, pasted URLs or
                         Excel/CSV; remove a site without deleting it globally
3. Start / Stop          Start fills the details and queues every ready site;
                         Stop pauses, Start resumes; speed is a simple preset
4. Live report           per website: data ready %, status, last update and the
                         action that makes sense (Fill details, Mark submitted,
                         Verify, Retry, Remove)
5. Export / re-import    Download report (CSV), import an old report and
                         Restart failed for only the unsuccessful websites
```

### The campaign cockpit (the project page)

The project page answers three questions on one screen - *which websites*,
*how far is each* and *what is left*:

| Element | What it does |
| ------- | ------------ |
| Project details | company name, description, e-mail, phone, website, address, city, state, country, postal code, categories, year founded, employees and anchors - saved for this project, editable at any time |
| Add websites | one URL, or many separated by a comma / space / new line; each is added to the central list once and linked to the project |
| Import Excel / CSV | the same spreadsheet columns as the central list; the imported rows are linked to the project in one step |
| Choose websites | the central list with a category filter; tick the sites of this project |
| Assigned websites | category and status filters, missing-field labels and **Remove** (the website stays in the central list) |
| Start backlinks | fills the details from the project details, sets the project to ACTIVE and queues every website with complete details; a row that misses values is reported, never sent half filled |
| Stop / Resume | Stop pauses the queued work (nothing is deleted), Start resumes exactly where it stopped; running tasks stop at the next safe step |
| Speed | Slow / Normal / Fast - one plain choice instead of a wall of execution numbers |
| Live table | website, data ready (%), missing fields, status (`Queued`, `Submitting`, `Stopped`, `Submit by hand`, `Submitted`, `Verified`, `Verification failed`, `Failed`), last update; refreshes every 3 s while a task runs |
| Download report | the live table as CSV |
| Restart failed | queues only the failed submissions and failed verifications again |
| Mark submitted | for directories without an automation: record the published page, complete the waiting task and queue the verification |
| More tools (collapsed) | every website field, auto pilot and the project statistics - ready when needed, out of the way when not |

### Where the work happens

| Step | Web | Desktop | Local agent / cloud |
| ----- | --- | ------- | ------------------- |
| Websites, projects, queue, reports | yes | yes | - |
| Browser submission | yes | yes | yes (the agent on another machine) |
| Verification | yes | yes | yes |
| Cloud workers | optional | optional | yes (Celery) |

Every job shows **where** it runs (`LOCAL` / `CLOUD`) and its state.

### Managing a project

| Action | What happens |
| ------ | ------------ |
| Edit | name, description, target website, status and the landing pages; the company details are saved for this project |
| Delete | the opportunities, tasks, attempts and verification records of the project are removed; **the websites stay in the website list** (they are shared) |
| Settings | speed preset (Slow / Normal / Fast) on the project page; concurrency, request rate, retries, backoff, verification interval and execution environment in More tools |
| Report | CSV download from the project page; the Reports screen generates the full workbook with per-website counters |
| Company details | company name, description, e-mail, phone, website, address, city, state, country, postal code, categories, year founded, employees and the **anchor texts** - asked when the project is created and editable at any time |
| Recycle bin | everything that is deleted (projects, websites, business profiles, opportunities) waits here until it is **restored** or **deleted forever** |

New projects always get their **own** company details - there is no shared
profile to pick. Older projects that still share a profile keep working; the
first time their details are saved the backend copies the profile, so changing
one project can never change another.

## The screens

| Screen | Web | Desktop | Backend endpoint |
| ------ | --- | ------- | ---------------- |
| Dashboard (metrics + live activity) | yes | yes | `/dashboard/metrics`, `/activity` |
| My projects | yes | yes | `/projects` |
| Project detail (campaign cockpit) | yes | yes | `/projects/{id}/campaign`, `/projects/{id}/campaign/start`, `.../stop`, `.../report.csv` |
| Onboarding wizard | yes | yes | `/profiles`, `/projects` |
| Find new websites | yes | yes | `/discovery/providers`, `/discovery/runs` |
| Review websites | yes | yes | `/opportunities`, `/opportunities/bulk` |
| Task queue | yes | yes | `/queue`, `/queue/reorder`, `/queue/{id}/control` |
| Live automation | yes | yes | `/queue`, `/tasks/{id}/attempts`, `/events/stream` |
| Execution control (pause/resume/stop, resources) | yes | yes | `/worker/*`, `/resources` |
| Browser isolation + runtime | yes | yes | `/browser/status`, `/browser/install` |
| Verification | yes | yes | `/verification/records`, `/verification/run` |
| Reports & exports | yes | yes | `/reports`, `/reports/{id}/download` |
| Recycle bin | yes | yes | `/recycle-bin`, `/recycle-bin/{kind}/{id}/restore` |
| Import centre | yes | yes | `/imports/preview`, `/imports/{id}/commit` |
| Integrations (encrypted credentials) | yes | yes | `/integrations/credentials` |
| Devices & agents | yes | yes | `/devices` |
| Activity log | yes | yes | `/activity` |
| Settings (global, project, automation, storage) | yes | yes | `/settings` related endpoints |

The contract test `apps/api/tests/test_contracts.py` compares the endpoints the
two clients use and fails when one of them can do something the other cannot.

## What is deliberately different

| Topic | Web | Desktop | Why |
| ----- | --- | ------- | --- |
| Start | two commands | one double click | the desktop bundles its backend |
| File dialogs | browser file input | native macOS dialog | platform convention |
| Notifications | browser notifications | native notifications | platform convention |
| Cloud switch | available | available but clearly optional | the desktop works without it |
| Browser runtime | installed on demand | installed on demand | 150 MB - it is not bundled |
