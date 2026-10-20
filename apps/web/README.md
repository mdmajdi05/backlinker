# Auto Backlinker — Web client

Next.js 15 (App Router) + React 19 + TypeScript + Tailwind CSS 3.4 desktop client for the
Auto Backlinker backend.

## Setup

```bash
cd apps/web
cp .env.example .env.local     # point NEXT_PUBLIC_API_BASE_URL at the backend
npm install
npm run dev                    # http://localhost:3000
```

The shared packages are consumed through `file:` links (no npm workspaces):

```json
"@autobacklinker/ui": "file:../../packages/ui",
"@autobacklinker/shared-types": "file:../../packages/shared-types",
"@autobacklinker/api-client": "file:../../packages/api-client"
```

`next.config.mjs` keeps `resolve.symlinks = false` so that webpack resolves the linked
packages from `apps/web/node_modules` (otherwise `clsx` and `@autobacklinker/shared-types`
cannot be resolved from inside `packages/ui` / `packages/api-client`).
`tsconfig.json` mirrors that with `"preserveSymlinks": true`.

## Scripts

| Script              | Purpose                                   |
| ------------------- | ----------------------------------------- |
| `npm run dev`       | Development server on port 3000           |
| `npm run build`     | Production build                          |
| `npm run start`     | Serve the production build                |
| `npm run typecheck` | `tsc --noEmit`                            |

## Architecture

```
app/
  layout.tsx            root layout: theme + auth + toast providers
  globals.css           imports the shared design system (@autobacklinker/ui/styles.css)
  (auth)/               login + register (public)
  (app)/                authenticated workspace
    layout.tsx          storage provider + route guard + app shell
    page.tsx            Overview (route "/")
    onboarding/         first-run wizard
    projects/           project list + /projects/[id] detail
    discovery/          opportunity discovery
    registry/           website registry (opportunities)
    queue/              backlink queue
    automation/         live automation
    verification/       backlink verification
    reports/            reports & exports
    imports/            import center
    integrations/       adapters, credentials, AI provider
    devices/            devices & agents
    activity/           activity logs
    settings/           global + project settings + database & storage
components/             shared UI built on top of @autobacklinker/ui
lib/                    api client singleton, auth, theme, storage, hooks, formatting
```

### Conventions

- Every list view renders a skeleton while loading, an empty state when there is no data and
  a retryable error state when the request fails.
- Destructive and bulk operations are confirmed with `components/ConfirmDialog.tsx`.
- Metrics always come from the backend. Unknown values are rendered as `—` / `Unknown`,
  never as zero or an invented number.
- Buttons either call a real endpoint or are disabled with a tooltip explaining why.
