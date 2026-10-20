#!/usr/bin/env python3
"""End-to-end integration test of the hybrid execution path.

It starts the real API (uvicorn, SQLite), registers a local agent, queues a
LOCAL task through the REST API, lets the agent claim and execute it and
verifies that the task really moved through the queue and that the activity
log contains the real events.

Usage:  .venv/bin/python scripts/smoke_local_agent.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "bin" / "python"
DATA_DIR = Path(tempfile.mkdtemp(prefix="abk-agent-smoke-"))
PORT = 8766
BASE = f"http://127.0.0.1:{PORT}"

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}" + (f" -> {detail}" if detail else ""))
    if not condition:
        FAILURES.append(label)


def main() -> int:
    env = {
        **os.environ,
        "AUTOBL_DATA_DIR": str(DATA_DIR),
        "AUTOBL_SECRET_KEY": "local-agent-smoke-secret-key-000000000",
        "AUTOBL_WORKER_ENABLED": "false",  # only the local agent executes the task
        "AUTOBL_ALLOW_PRIVATE_NETWORK": "true",
        "PYTHONPATH": str(ROOT / "apps" / "api"),
    }
    server = subprocess.Popen(
        [str(PY), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
        cwd=ROOT / "apps" / "api",
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_for_server()
        token = _register_user()
        headers = {"Authorization": f"Bearer {token}"}
        project_id = _create_project(headers)
        opportunity_id = _create_opportunity(headers, project_id)
        queued = _queue_local_task(headers, opportunity_id, project_id)
        check("LOCAL task queued", queued.get("created") == 1, str(queued))
        task_id = queued["task_ids"][0]

        agent = _run_agent(env)
        check("agent registered", agent.get("device_id") is not None, str(agent)[:120])

        _run_agent_once(env, agent)
        time.sleep(1.0)
        task = _get_task(headers, task_id)
        check(
            "task was claimed by the agent",
            task["status"] in ("SUBMITTED", "PUBLISHED_UNVERIFIED", "WAITING_FOR_USER", "FAILED", "COMPLETED"),
            f"status={task['status']}",
        )
        check("task has an execution environment", task["execution_environment"] == "LOCAL")
        check("task attempt recorded", task["attempts"] >= 1, f"attempts={task['attempts']}")

        events = _activity(headers)
        types = {event["event_type"] for event in events}
        check("task started event emitted", "task.started" in types, str(sorted(types))[:200])
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover
            server.kill()
        shutil.rmtree(DATA_DIR, ignore_errors=True)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
        return 1
    print("local agent smoke test passed")
    return 0


def _wait_for_server() -> None:
    import httpx

    for _ in range(80):
        try:
            response = httpx.get(f"{BASE}/health", timeout=2.0)
            if response.status_code == 200:
                return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("the API did not start in time")


def _api(method: str, path: str, token: str | None = None, payload: dict | None = None) -> dict:
    import httpx

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = httpx.request(method, f"{BASE}{path}", headers=headers, json=payload, timeout=20.0)
    response.raise_for_status()
    return response.json()


def _register_user() -> str:
    payload = {"email": "agent-smoke@example.com", "password": "supersecret123", "name": "Smoke"}
    return _api("POST", "/api/v1/auth/register", payload=payload)["access_token"]


def _create_project(headers: dict) -> str:
    token = headers["Authorization"].split(" ", 1)[1]
    project = _api(
        "POST",
        "/api/v1/projects",
        token=token,
        payload={"name": "Agent smoke project", "target_website": "https://target.example"},
    )
    return project["id"]


def _create_opportunity(headers: dict, project_id: str) -> str:
    token = headers["Authorization"].split(" ", 1)[1]
    opportunity = _api(
        "POST",
        "/api/v1/opportunities",
        token=token,
        payload={
            "opportunity_url": "https://directory.example.org/submit",
            "name": "Directory Example",
            "category": "BUSINESS_DIRECTORY",
            "project_id": project_id,
        },
    )
    return opportunity["id"]


def _queue_local_task(headers: dict, opportunity_id: str, project_id: str) -> dict:
    token = headers["Authorization"].split(" ", 1)[1]
    return _api(
        "POST",
        "/api/v1/queue",
        token=token,
        payload={
            "opportunity_ids": [opportunity_id],
            "type": "SUBMIT",
            "execution_environment": "LOCAL",
        },
    )


def _get_task(headers: dict, task_id: str) -> dict:
    token = headers["Authorization"].split(" ", 1)[1]
    return _api("GET", f"/api/v1/tasks/{task_id}", token=token)


def _activity(headers: dict) -> list[dict]:
    token = headers["Authorization"].split(" ", 1)[1]
    return _api("GET", "/api/v1/activity?page_size=100", token=token)["items"]


def _run_agent(env: dict) -> dict:
    result = subprocess.run(
        [
            str(PY),
            "-m",
            "agent",
            "--register",
            "--server-url",
            BASE,
            "--name",
            "smoke-agent",
            "--api-dir",
            str(ROOT / "apps" / "api"),
            "--no-browser",
        ],
        cwd=ROOT / "apps" / "local-agent",
        env={**env, "PYTHONPATH": str(ROOT / "apps" / "local-agent")},
        capture_output=True,
        text=True,
        timeout=120,
    )
    config_path = Path.home() / ".autobacklinker" / "agent.json"
    if not config_path.exists():
        raise RuntimeError(f"agent registration failed:\n{result.stdout}\n{result.stderr}")
    import json

    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not config.get("device_id") or not config.get("api_key"):
        raise RuntimeError(f"agent configuration is incomplete:\n{config}")
    return config


def _run_agent_once(env: dict, agent: dict) -> str:
    result = subprocess.run(
        [
            str(PY),
            "-m",
            "agent",
            "--once",
            "--server-url",
            BASE,
            "--name",
            "smoke-agent",
            "--api-dir",
            str(ROOT / "apps" / "api"),
            "--no-browser",
        ],
        cwd=ROOT / "apps" / "local-agent",
        env={**env, "PYTHONPATH": str(ROOT / "apps" / "local-agent")},
        capture_output=True,
        text=True,
        timeout=180,
    )
    output = f"{result.stdout}\n{result.stderr}"
    if result.returncode != 0:
        print("--- agent output ---")
        print(output[-3000:])
    return output


if __name__ == "__main__":
    sys.exit(main())
