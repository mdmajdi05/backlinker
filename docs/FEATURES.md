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
1. Business profile      what the business is, once, reused by every project
2. Project               the target website + the landing page that gets the link
3. Websites              ONE place with every site where a backlink can go
                         (manual entry or Excel import, editable, deletable,
                          status: ACTIVE / NOT_WORKING / … - deleting moves a
                          site to the recycle bin, where it can be restored)
4. Choose                the project picks the sites it wants from that list
                         (filterable by category and niche)
5. Auto pilot            approving a site queues it automatically - the worker
                          submits in the background, retries, and never
                          duplicates finished work
6. Details               the site asks for a name, a description, an address…
                          the operator fills what is missing, the assistant
                          derives what it can from the profile and says what
                          it cannot derive
7. Verify                link present? anchor right? destination right? rel?
8. Report                per website: how many submissions worked, how many not
9. Re-import             verified → skip, failed → retry, pending → queue
```

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
| Edit | name, description, target website, business profile, status and the landing pages - only the fields that were sent are changed |
| Delete | the opportunities, tasks, attempts and verification records of the project are removed; **the websites stay in the website list** (they are shared) and the business profile is untouched |
| Settings | concurrency, request rate, retries, backoff, verification interval, execution environment |
| Report | project scoped workbook with the **per website** counters (submitted / verified / failed / pending) and a *Retry failed* action |
| Backlink details | company name, description, e-mail, phone, website, address, city, state, country, postal code, categories, year founded, employees and the **anchor texts** - asked when the project is created and editable at any time; they are stored in the business profile, so nothing is duplicated |
| Recycle bin | everything that is deleted (projects, websites, business profiles, opportunities) waits here until it is **restored** or **deleted forever** |

## The screens

| Screen | Web | Desktop | Backend endpoint |
| ------ | --- | ------- | ---------------- |
| Overview (metrics + live activity) | yes | yes | `/dashboard/metrics`, `/activity` |
| Projects | yes | yes | `/projects` |
| Project detail | yes | yes | `/projects/{id}`, `/projects/{id}/settings` |
| Onboarding wizard | yes | yes | `/profiles`, `/projects` |
| Opportunity discovery | yes | yes | `/discovery/providers`, `/discovery/runs` |
| Website registry | yes | yes | `/opportunities`, `/opportunities/bulk` |
| Backlink queue | yes | yes | `/queue`, `/queue/reorder`, `/queue/{id}/control` |
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
