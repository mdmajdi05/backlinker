# Infrastructure

Docker based stack for the Auto Backlinker backend: PostgreSQL, Redis, the
FastAPI API and the background worker.

```
infrastructure/
├── api.Dockerfile      # image for the API and the worker
├── docker-compose.yml  # postgres + redis + api + worker
└── entrypoint.sh       # applies the migrations before the container starts
```

## Requirements

* Docker Engine 24+ with the Compose V2 plugin (`docker compose ...`).
* ~2 GB of free disk space for the images and the database volume.

## Run the stack

```bash
# from the repository root
docker compose -f infrastructure/docker-compose.yml up -d --build

# follow the logs
docker compose -f infrastructure/docker-compose.yml logs -f api worker

# stop everything (the database volume is kept)
docker compose -f infrastructure/docker-compose.yml down

# stop everything and delete the database volume as well
docker compose -f infrastructure/docker-compose.yml down -v
```

| Service    | URL / port                  | Purpose                                    |
| ---------- | --------------------------- | ------------------------------------------ |
| `api`      | http://localhost:8000       | REST API, interactive docs on `/docs`      |
| `worker`   | -                           | Background worker (discovery, submission)  |
| `postgres` | `localhost:5432`            | Database (`autobacklinker` / `autobacklinker`) |
| `redis`    | `localhost:6379`            | Broker / result backend for Celery         |

The API container applies the migrations (`alembic upgrade head`) before it
starts serving, so a fresh volume is initialised automatically.  The step is
idempotent and can be disabled with `AUTOBL_RUN_MIGRATIONS=0`.

## Configuration

Every setting is an environment variable with the `AUTOBL_` prefix.  The most
relevant ones can be set in a `.env` file next to the compose file or exported
in the shell:

```bash
export AUTOBL_SECRET_KEY="a-long-random-string"
export AUTOBL_CORS_ORIGINS='["http://localhost:3000"]'
export AUTOBL_AI_PROVIDER="openai"
export AUTOBL_AI_API_KEY="sk-..."
export AUTOBL_AI_MODEL="gpt-4o-mini"
docker compose -f infrastructure/docker-compose.yml up -d
```

See `.env.example` in the repository root for the complete list.

## Point the desktop app at this backend

The desktop client (Tauri) and the web client speak the same HTTP protocol as
the API, so they only need the base URL of the API:

1. Start the stack as described above and note the URL of the API
   (for example `http://localhost:8000/api/v1` or
   `https://api.example.com/api/v1`).
2. In the desktop app open *Settings → Cloud synchronisation*, paste the base
   URL into the **Backend URL** field and press **Use this backend**.  The app
   switches from the bundled local backend to the cloud one (the badge next to
   *Cloud synchronisation* shows the active mode).
3. Sign in with the account you created in the web client
   (`POST /api/v1/auth/register` or `/api/v1/auth/login`).  The desktop app
   stores the returned JWT and sends it as `Authorization: Bearer <token>`.
4. Verify the connection - the client calls `GET /api/v1/system/info` and
   `GET /health`; a successful answer means the desktop app is now driving the
   cloud backend.  The *Storage* panel shows the mode, the database type and
   the number of pending synchronisation changes.

For a server that is not reachable over plain HTTP, terminate TLS in front of
the API (for example with a reverse proxy) and use the `https://` URL.  The
API itself never exposes the database: only the REST protocol is used, so the
desktop app needs nothing but the URL and the credentials.

The local agent mode works the same way: a machine registers itself with
`POST /api/v1/devices/register`, receives an API key and then polls
`GET /api/v1/devices/tasks/claim` with that key to pick up the tasks that are
routed to the `LOCAL` execution environment.  The ready to use client lives in
`apps/local-agent`:

```bash
cd apps/local-agent
python3 -m agent --register --server-url https://api.example.com
python3 -m agent --daemon
```

## Local development without Docker

```bash
apps/api/scripts/bootstrap.sh          # create .venv, install deps, migrate
cd apps/api
../../.venv/bin/python -m uvicorn app.main:app --reload --port 8000
../../.venv/bin/python -m app.workers.runner
```

The default configuration uses a SQLite file inside the application data
directory, so PostgreSQL is only required for the cloud deployment.
