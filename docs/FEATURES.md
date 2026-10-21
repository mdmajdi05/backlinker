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
