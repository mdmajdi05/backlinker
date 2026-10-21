# Multi agent operating model

The repository is built and maintained with a **master agent** that owns the
architecture, the contracts and the final verification, plus a set of
**worker agents** that implement independent pieces in parallel.

```
                    ┌──────────────────────────────┐
                    │        MASTER AGENT           │
                    │  - architecture + contracts   │
                    │  - integration + review       │
                    │  - the verification gate      │
                    └──────────────┬───────────────┘
                                   │  delegates, never blocks
        ┌──────────────────┬───────┴────────┬──────────────────┐
        ▼                  ▼                ▼                  ▼
  ┌───────────┐    ┌──────────────┐   ┌───────────┐    ┌────────────┐
  │ backend   │    │ automation   │   │ dataflow  │    │ clients    │
  │ (API, DB) │    │ (discovery,  │   │ (import / │    │ (web,      │
  │           │    │  adapters,   │   │  export,  │    │  desktop,  │
  │           │    │  verification)│  │  resume)  │    │  agent)    │
  └───────────┘    └──────────────┘   └───────────┘    └────────────┘
```

## The rules that keep it fast

1. **One owner per file.** Every agent receives an explicit list of the files
   it may change. Nobody edits a file another agent owns - that is what caused
   the conflicts during the first build.
2. **The contract is written before the code.** The shared DTOs
   (`packages/shared-types`) and the transport (`packages/api-client`) are the
   interface between the backend and both clients. A change to the contract is
   a coordinated change, never a surprise.
3. **The master keeps working while the workers work.** The master never waits
   for a single agent: it reviews what arrived, runs the verification gate and
   starts the next round.
4. **Every claim is verified.** No agent reports "implemented" without a
   command that proves it. The master repeats the important checks itself.
5. **Bugs found by one agent are fixed by the master**, not by the agent that
   found them - the fix then lands in the shared code and in the regression
   tests.

## The verification gate (the master)

```bash
./scripts/verify_all.sh          # lint, migrations, tests, both clients
make acceptance                  # the complete product loop
make browser-check               # a real browser submits a form
make desktop-check               # the packaged app starts and keeps its session
make ui-check                    # the web client adds a website by hand
make automation-ui-check         # the isolation and the resource controls
```

A change is only finished when the gate is green and the artifacts are
rebuilt.

## The two independent products

| | Web product | Desktop product |
| - | ----------- | --------------- |
| Folder | `apps/web` | `apps/desktop` |
| Backend | `apps/api` started with `make dev-api` | bundled into the app (`src-tauri/Resources/backend/<arch>/`) |
| Database | SQLite by default, PostgreSQL for the cloud | SQLite in the application data directory |
| Start | two commands | one double click |
| Internet | needed for discovery, verification and submissions | not needed - everything except the live checks works offline |

Both talk to **the same API implementation** but run **their own instance** of
it: the desktop never calls the web backend and the web backend never calls
the desktop. A cloud backend is an optional extra that either side may point
at.
