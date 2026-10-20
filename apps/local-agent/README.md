# Auto Backlinker - Local automation agent

The agent runs the *local* part of the platform on a machine that must not be
reachable from the cloud: browser submissions and verifications that need a
real browser or a local network.

It registers itself at a backend, receives a device API key, claims tasks that
are routed to the `LOCAL` execution environment, executes them with the
**adapter framework of the backend** (`apps/api/app/services/adapters`) and
reports the result.

```
┌────────────┐   POST /api/v1/devices/register      ┌──────────────────┐
│   agent    │ ────────────────────────────────────▶ │  backend (cloud) │
│            │ ◀──────────────────────────────────── │                  │
│            │   {device_id, api_key, poll_interval}  └──────────────────┘
│            │
│            │   GET  /api/v1/devices/tasks/claim  ──▶  a task or 204
│            │   POST /api/v1/devices/tasks/{id}/report ──▶ {status, result, error}
└────────────┘
```

---

## 1. Requirements

* Python 3.11 or newer
* The standard library only - **no third party package is required**
* Optional: Playwright (browser tasks) and the backend dependencies (the full
  adapter set)

```bash
cd apps/local-agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # optional extras, see the file
```

## 2. Registration

```bash
python -m agent --register --server-url http://127.0.0.1:8000 --name studio-mac
```

The agent stores the answer in `~/.autobacklinker/agent.json` with mode
`0600`:

```json
{
  "device_id": "33a8935dee8b404c8236ccd6ccd89fd9",
  "api_key": "agent_...",
  "server_url": "http://127.0.0.1:8000",
  "capabilities": ["submit", "verify", "http", "browser"],
  "poll_interval_seconds": 30
}
```

The API key never appears in the log file - the logging filter replaces
tokens, passwords and API keys with `***`.

## 3. Running

```bash
# run continuously (heartbeat + claim + execute + report)
python -m agent --daemon

# claim and execute exactly one task, then exit
python -m agent --once

# show the registration status
python -m agent --status

# forget the registration
python -m agent --reset
```

Useful options:

| Option | Description |
|--------|-------------|
| `--server-url URL` | backend base url (default `http://127.0.0.1:8000`) |
| `--name NAME` | device name shown in the backend |
| `--capabilities a,b` | override the advertised capabilities |
| `--no-browser` | do not advertise the browser capability |
| `--api-dir PATH` | path to `apps/api` (adapter framework) |
| `--log-level DEBUG` | log level of the console and the log file |
| `--status` / `--reset` | inspect / delete the local registration |

The environment variable `AUTOBL_AGENT_HOME` relocates the configuration and
the log file (useful for tests and for portable installations).

## 4. What the agent executes

Only two task types are executed:

| Task type | Behaviour |
|-----------|-----------|
| `SUBMIT` | the adapter of the task performs the submission |
| `VERIFY` | the published page is checked for the expected backlink |

Everything else (`DISCOVER`, `IMPORT`, `EXPORT`, `MANUAL`) is rejected.

### Safety rules

* **Allowlist** - a task whose type is not on the list is never executed.
* **No remote code** - a task whose payload contains an executable field
  (`command`, `cmd`, `exec`, `script`, `shell`, `argv`, `code`, `python`, ...)
  is rejected, including in nested `payload` / `context` / `options` objects.
* **Adapter reuse** - the agent imports the backend adapter framework through
  `sys.path` (the directory of `apps/api`). If the package or one of its
  dependencies is missing, the task is reported as
  *"manual intervention required"* with the exact import error - the agent
  never pretends that it executed something.
* **Browser runtime** - when a task needs a browser and Playwright (or its
  Chromium build) is missing, the agent logs
  *"browser runtime not installed"* and reports the task as
  `WAITING_FOR_USER` instead of failing silently.

### Reported statuses

| Situation | Status |
|-----------|--------|
| Submission succeeded | `SUBMITTED` |
| Publication detected, not verified yet | `PUBLISHED_UNVERIFIED` |
| Link verified | `VERIFIED_LIVE` |
| Link missing | `VERIFICATION_FAILED` |
| A human has to finish the job | `WAITING_FOR_USER` |
| Rejected by the allowlist / an error | `FAILED` |

## 5. Resilience

* a heartbeat is sent every 30 seconds (`POST /api/v1/devices/{id}/heartbeat`),
* when the backend is unreachable the agent keeps its state, logs the error and
  retries with an exponential backoff (1 s → 60 s),
* `SIGINT` / `SIGTERM` stop the loop gracefully, an `OFFLINE` heartbeat is sent
  and the process exits with code `0`.

## 6. Logs

```
~/.autobacklinker/logs/agent.log      (rotating, 2 MB per file, 3 backups)
```

The file contains redacted messages only - API keys, bearer tokens and
passwords are replaced with `***`.

## 7. Tests

The test suite is offline: every HTTP call is served by a mock transport that
asserts the exact request.
```bash
cd apps/local-agent
python -m unittest discover -s tests -v
```

It covers the registration payload, the 0600 permissions of the key file, the
heartbeat, the claim (`204` = idle), the report payload, the allowlist, the
rejection of executable payloads, the "adapter framework missing" error and the
log redaction.

### What was verified on the development machine

| Check | Result |
|-------|--------|
| `python -m compileall apps/local-agent` | no errors |
| `python -m unittest discover -s tests` | 14 tests, all green |
| `python -m agent --help` / `--status` | works |
| `python -m agent --register --server-url http://127.0.0.1:8899` | the backend created the device, the key was written with mode `0600` |
| `python -m agent --once` (empty queue) | "No task was available." (HTTP 204) |
| `python -m agent --daemon` + `SIGTERM` | graceful shutdown, `OFFLINE` heartbeat, exit code 0 |
| claim → execute → report against a live backend with a `LOCAL` task | the task was claimed, executed and reported (`WAITING_FOR_USER` because the task carried no adapter) |
| `TaskExecutor(api_dir=../../apps/api)` | the backend adapter framework is imported and all 5 adapters (`email_outreach`, `generic_manual`, `http_form`, `json_api`, `playwright_form`) are found |

## 8. Running as a service

### macOS (launchd)

```xml
<!-- ~/Library/LaunchAgents/com.autobacklinker.agent.plist -->
<key>ProgramArguments</key>
<array>
  <string>/usr/local/bin/python3</string>
  <string>-m</string>
  <string>agent</string>
  <string>--daemon</string>
</array>
<key>WorkingDirectory</key>
<string>/path/to/auto-backlinker/apps/local-agent</string>
<key>RunAtLoad</key>
<true/>
```

### Windows (Task Scheduler)

```
python -m agent --daemon --server-url https://backlinks.example.com
```

with the trigger "At startup" and the option "Run whether the user is logged
on or not".

### Linux (systemd)

```ini
[Unit]
Description=Auto Backlinker local agent
After=network-online.target

[Service]
WorkingDirectory=/opt/auto-backlinker/apps/local-agent
ExecStart=/usr/bin/python3 -m agent --daemon
Restart=on-failure

[Install]
WantedBy=multi-user.target
```
